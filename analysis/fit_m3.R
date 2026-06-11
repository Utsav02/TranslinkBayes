library(brms)
library(arrow)
library(dplyr)
library(lubridate)

options(mc.cores = parallel::detectCores())

# Auto-discover latest all-routes parquet
pq_path <- tail(
  sort(list.files(
    "../exports",
    pattern   = "all_routes_.*\\.parquet",
    full.names = TRUE
  )),
  1
)
if (length(pq_path) == 0) stop("No all_routes_*.parquet found in exports/")
cat(sprintf("Loading: %s\n", pq_path))

raw <- arrow::read_parquet(pq_path) |>
  filter(
    route_id != "",
    !is.na(delay_seconds), !is.na(previous_stop_delay),
    !is.na(shape_dist_traveled), !is.na(hour),
    !is.na(stop_id), !is.na(trip_id),
    abs(delay_seconds)       <= 3600,
    abs(previous_stop_delay) <= 3600
  ) |>
  mutate(
    timestamp = as.POSIXct(timestamp, tz = "UTC"),
    date      = as.Date(timestamp),
    hour      = as.integer(hour),
    dow       = as.integer(wday(timestamp, week_start = 1L)),
    trip_id   = as.character(trip_id),
    stop_id   = as.character(stop_id),
    route_id  = as.character(route_id)
  )

# Data-driven anomaly day exclusion (mirrors multi_route_analysis.Rmd)
daily_stats <- raw |>
  group_by(date) |>
  summarise(
    n          = n(),
    mean_delay = mean(delay_seconds, na.rm = TRUE),
    .groups    = "drop"
  )
overall_mean <- mean(daily_stats$mean_delay)
overall_sd   <- sd(daily_stats$mean_delay)
anomaly_days <- daily_stats |>
  filter(
    n < 0.20 * median(daily_stats$n) |
      abs(mean_delay - overall_mean) > 2 * overall_sd
  ) |>
  pull(date)
if (length(anomaly_days) > 0) {
  cat(sprintf(
    "Excluding anomaly days: %s\n",
    paste(anomaly_days, collapse = ", ")
  ))
  raw <- raw |> filter(!date %in% anomaly_days)
}

set.seed(42)

# Curated exclusion list.  Two distinct failure modes — do not conflate:
#
# (A) Stop-sequence tie artifacts: RT feed broadcasts multiple stops at the
#     same stop_sequence number (branching/loop topology).  LAG()-based
#     previous_stop_delay is incorrect at tie points.  Do NOT replace with
#     a threshold-based auto-exclusion — the bad-trip distribution is
#     continuous (0–98%), not bimodal.  Update when the diagnostic below
#     flags a new route above ~60% with >= 50 trips.
#     Identified via stop-sequence integrity analysis (2026-05-29):
#       12940  98.5%   6700  88.1%   30055  63.6%   6702  60.6%
#     6718 stays despite 27.3% in recent processed_stops: only 11 trips in
#     the May-16+ window — historically 100% bad.  Coverage artifact.
#
# (B) Structural GTFS join failure (different root cause from A):
#     6619 (Route 009 Broadway/Lougheed): 65.5% of stops lack
#     shape_dist_traveled because whole route sections — the Lougheed Hwy
#     extension eastbound (stops 901–908) and both termini — have no shape
#     entry in gtfs_static.db.  The NULL pattern is geographic, not random.
#     After pre-filtering on shape_dist, only the central Broadway corridor
#     remains — a structurally biased, non-representative sample.  Excluded
#     here so a future data-volume increase cannot silently re-admit it.
anomaly_routes <- c("12940", "6700", "30055", "6702", "6718", "6619")

# Held-out routes — excluded from training entirely.
#   6641 (099 Broadway B-Line): used in all single-route hand-tuning; holdout
#     enables direct Ralph loop vs hand-built model comparison.
#   6705 (321 King George Blvd): suburban Surrey — geographic contrast.
holdout_routes <- c("6641", "6705")

# Diagnostic: prints tied-sequence rates so new candidates are visible.
report_seq_integrity <- function(df, min_trips = 10) {
  trip_flags <- df |>
    group_by(.data$route_id, .data$trip_id) |>
    summarise(
      has_tie = any(duplicated(.data$stop_sequence)),
      .groups = "drop"
    )

  route_flags <- trip_flags |>
    group_by(.data$route_id) |>
    summarise(
      total_trips = n(),
      bad_trips   = sum(.data$has_tie),
      pct_bad     = round(100 * mean(.data$has_tie), 1),
      .groups     = "drop"
    ) |>
    filter(.data$total_trips >= min_trips) |>
    arrange(desc(.data$pct_bad))

  cat("Stop-sequence tie rates (routes >= 10 trips):\n")
  for (i in seq_len(nrow(route_flags))) {
    r    <- route_flags[i, ]
    excl <- if (r$route_id %in% anomaly_routes) " <-- EXCLUDED" else ""
    cat(sprintf(
      "  %-10s  %5d trips  %5.1f%% bad%s\n",
      r$route_id, r$total_trips, r$pct_bad, excl
    ))
  }
  invisible(route_flags)
}

report_seq_integrity(raw)
cat(sprintf(
  "Excluding %d route(s): %s\n",
  length(anomaly_routes), paste(anomaly_routes, collapse = ", ")
))

route_counts <- raw |>
  filter(!route_id %in% anomaly_routes, !route_id %in% holdout_routes) |>
  count(route_id, name = "n_rows") |>
  filter(n_rows >= 500) |>
  arrange(desc(n_rows))
top_routes <- route_counts |> slice_max(n_rows, n = 25)

df <- raw |>
  filter(route_id %in% top_routes$route_id) |>
  group_by(route_id) |>
  slice_sample(n = 500) |>
  ungroup()

dates    <- sort(unique(df$date))
cutoff   <- dates[floor(0.75 * length(dates))]
train_df <- filter(df, date <= cutoff)

cat(sprintf(
  "Train: %d rows, %d routes\n",
  nrow(train_df), n_distinct(train_df$route_id)
))

f_m3 <- bf(
  delay_seconds ~ previous_stop_delay + shape_dist_traveled +
    s(hour, bs = "cc", k = 8) +
    s(dow,  bs = "cc", k = 5) +
    (1 | route_id) +
    (1 | trip_id) +
    (1 | stop_id)
)

base_priors <- c(
  prior(normal(0, 2),   class = b),
  prior(normal(0, 10),  class = Intercept),
  prior(exponential(1), class = sigma),
  prior(exponential(1), class = sd),
  prior(gamma(2, 0.1),  class = nu, lb = 2)
)

cat("Fitting M3 — chain progress will print below.\n")
m3 <- brm(
  f_m3,
  data    = train_df,
  family  = student(),
  prior   = base_priors,
  knots   = list(hour = c(0, 24), dow = c(0.5, 7.5)),
  iter    = 2000, warmup = 1000, chains = 4, seed = 42,
  control = list(adapt_delta = 0.95),
  file    = "models/brms_m3_multiRoute",
  refresh = 50
)

cat("\n=== M3 Summary ===\n")
print(summary(m3, pars = c(
  "b_Intercept", "b_previous_stop_delay",
  "b_shape_dist_traveled", "sigma", "nu"
)))
cat("\nModel saved to models/brms_m3_multiRoute.rds\n")
cat("Now render:\n")
cat("  Rscript -e \"rmarkdown::render('multi_route_analysis.Rmd')\"\n")
