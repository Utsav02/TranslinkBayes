# Post-fit evaluation for the C0 / m3 reproducibility run (launched 2026-06-13).
# Reconstructs the EXACT split fit_m3.R used (same seed, same filters, and the
# SAME parquet vintage — pinned to all_routes_2026-06-07.parquet, which is what
# fit_m3.R auto-discovered at launch; the newer 06-13 parquet must NOT be used
# or the split won't match the fitted model), evaluates the held-out test set,
# appends a run_log.csv row via run_tracker.R, and records PSIS-LOO.
#
# Run from analysis/:  Rscript eval_m3_repro.R
suppressMessages({ library(brms); library(arrow); library(dplyr); library(lubridate); library(loo) })

PARQUET <- "../exports/all_routes_2026-06-07.parquet"   # PINNED to the fit's vintage
stopifnot(file.exists(PARQUET))
cat(sprintf("Eval using pinned parquet: %s\n", PARQUET))

raw <- arrow::read_parquet(PARQUET) |>
  filter(route_id != "", !is.na(delay_seconds), !is.na(previous_stop_delay),
         !is.na(shape_dist_traveled), !is.na(hour), !is.na(stop_id), !is.na(trip_id),
         abs(delay_seconds) <= 3600, abs(previous_stop_delay) <= 3600) |>
  mutate(timestamp = as.POSIXct(timestamp, tz = "UTC"),
         # `date` in Vancouver TZ to match Python pipeline's service_date (audit 2026-07-08)
         date = as.Date(format(timestamp, "%Y-%m-%d", tz = "America/Vancouver")),
         hour = as.integer(hour), dow = as.integer(wday(timestamp, week_start = 1L)),
         trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id))

# Anomaly-day exclusion — identical rule to fit_m3.R
ds <- raw |> group_by(date) |> summarise(n = n(), mean_delay = mean(delay_seconds), .groups = "drop")
om <- mean(ds$mean_delay); osd <- sd(ds$mean_delay)
anom <- ds |> filter(n < 0.20 * median(ds$n) | abs(mean_delay - om) > 2 * osd) |> pull(date)
if (length(anom) > 0) { cat("Excluding anomaly days:", paste(anom, collapse = ", "), "\n"); raw <- raw |> filter(!date %in% anom) }

set.seed(42)   # identical seed → identical subsample + split as fit_m3.R
anomaly_routes <- c("12940", "6700", "30055", "6702", "6718", "6619")
holdout_routes <- c("6641", "6705")
route_counts <- raw |> filter(!route_id %in% anomaly_routes, !route_id %in% holdout_routes) |>
  count(route_id, name = "n_rows") |> filter(n_rows >= 500) |> arrange(desc(n_rows))
top_routes <- route_counts |> slice_max(n_rows, n = 25)
df <- raw |> filter(route_id %in% top_routes$route_id) |>
  group_by(route_id) |> slice_sample(n = 500) |> ungroup()
dates  <- sort(unique(df$date)); cutoff <- dates[floor(0.75 * length(dates))]
train_df <- filter(df, date <= cutoff); test_df <- filter(df, date > cutoff)
cat(sprintf("Reconstructed split: train=%d test=%d cutoff=%s\n", nrow(train_df), nrow(test_df), cutoff))

m3 <- readRDS("models/brms_m3_multiRoute.rds")
if (nrow(m3$data) != nrow(train_df))
  stop(sprintf("Split mismatch: model trained on %d rows, reconstructed train has %d — wrong parquet vintage?",
               nrow(m3$data), nrow(train_df)))
cat("[ok] model training-row count matches reconstructed train split\n")

# Convergence diagnostics (does the 56-divergence problem reproduce?)
ps <- posterior_summary(m3)
for (p in c("b_previous_stop_delay", "b_shape_dist_traveled", "sigma", "nu"))
  cat(sprintf("  %s: %.4f [%.4f, %.4f]\n", p, ps[p, "Estimate"], ps[p, "Q2.5"], ps[p, "Q97.5"]))
rhat_max <- max(brms::rhat(m3), na.rm = TRUE)
np <- bayesplot::nuts_params(m3); n_div <- sum(np$Value[np$Parameter == "divergent__"])
cat(sprintf("  rhat_max=%.4f  divergences=%d / 4000 draws\n", rhat_max, n_div))

# Held-out evaluation (fit_m3.R's own temporal holdout)
pred <- posterior_predict(m3, newdata = test_df, allow_new_levels = TRUE, sample_new_levels = "gaussian")
mu <- colMeans(pred); lo <- apply(pred, 2, quantile, 0.05); hi <- apply(pred, 2, quantile, 0.95)
results <- test_df |> mutate(pred = mu, residual = delay_seconds - mu,
                             covered = delay_seconds >= lo & delay_seconds <= hi)
cat(sprintf("  holdout MAE=%.2f RMSE=%.2f cov90=%.4f\n",
            mean(abs(results$residual)), sqrt(mean(results$residual^2)), mean(results$covered)))

source("run_tracker.R")
track_run(model = m3, train_df = train_df, test_df = test_df, results = results,
          model_file = "models/brms_m3_multiRoute.rds (C0 repro refit 2026-06-13)",
          n_routes = n_distinct(train_df$route_id))

cat("Computing PSIS-LOO (training fit)...\n")
print(loo(m3))
cat("\nEVAL COMPLETE — run_log.csv row appended.\n")
