# ─────────────────────────────────────────────────────────────────────────────
# C_fifa — quantifies the FIFA match-day delay premium on affected routes.
#
# Pre-registered 2026-07-09 from the dow-hour-matched raw-stop_delays analysis
# (see docs/fifa_effect_2026.md when written). Empirical benchmark: +87 s to
# +276 s mean delay premium per match kickoff window (±3 h) on 6 affected
# Vancouver routes (short_names 014, 019, 023, 028, 130, 222 — id map below).
#
# HYPOTHESIS: the model recovers the observed effect with a tight CI.
# NOT expected to shift RMSE much (the effect is concentrated in narrow time
# × route slices); IS expected to improve ELPD by tightening the tail
# density on match-day rush hours.
#
# Base: C_m2nu4 (registry §2.1). Formula adds interaction terms only —
# no new REs.
# ─────────────────────────────────────────────────────────────────────────────
suppressMessages({
  library(brms); library(arrow); library(dplyr); library(lubridate); library(loo)
})
options(mc.cores = parallel::detectCores())

CANDIDATE_ID <- "C_fifa"

# ── FIFA constants (from docs/known_baseline.md §1.6 + web-confirmed 2026-06-19)
FIFA_MATCH_DAYS <- c(
  "2026-06-13", "2026-06-18", "2026-06-21",
  "2026-06-24", "2026-06-26", "2026-07-02", "2026-07-07"
)
FIFA_KICKOFF_PT_HOUR <- c(  # local Pacific hour of kickoff, one per match date
  "2026-06-13" = 21, "2026-06-18" = 15, "2026-06-21" = 18,
  "2026-06-24" = 12, "2026-06-26" = 20, "2026-07-02" = 20, "2026-07-07" = 13
)
# Affected route_ids (short_names 014, 019, 023, 028, 130, 222):
AFFECTED_ROUTE_IDS <- c("16718", "6624", "30055", "6630", "6651", "39305")

# ── Load frozen train/test ──────────────────────────────────────────────────
train <- arrow::read_parquet("../exports/loop_train.parquet") |>
  mutate(trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id), hour = as.integer(hour), dow = as.integer(dow))
test  <- arrow::read_parquet("../exports/loop_test.parquet") |>
  mutate(trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id), hour = as.integer(hour), dow = as.integer(dow))
stopifnot(nrow(test) >= 100)

# ── Data prep: derive is_match_day, is_affected_route, hour_from_kickoff ────
# hour_from_kickoff = signed hours between the row's local hour and the day's
# kickoff hour, on match days only. NA on non-match days — filled with a
# neutral sentinel (0) since the interaction below multiplies by is_match_day
# and thus zeros out on non-match days, so the sentinel value doesn't matter
# for the effect estimate — but must be numeric or the spline throws.
attach_fifa <- function(df) {
  df$is_match_day       <- as.integer(df$service_date %in% FIFA_MATCH_DAYS)
  df$is_affected_route  <- as.integer(df$route_id %in% AFFECTED_ROUTE_IDS)
  # kickoff hour per row (0 outside match days — masked by is_match_day)
  df$kickoff_hr <- ifelse(
    df$is_match_day == 1,
    FIFA_KICKOFF_PT_HOUR[df$service_date],
    0L
  )
  df$hour_from_kickoff <- as.numeric(df$hour) - as.numeric(df$kickoff_hr)
  # For the spline to be identifiable, non-match rows must have a consistent
  # sentinel value. We already mask via is_match_day in the formula.
  df$hour_from_kickoff[df$is_match_day == 0] <- 0
  df
}
train <- attach_fifa(train)
test  <- attach_fifa(test)

cat(sprintf("TRAIN: match-day rows=%d (%.1f%%), affected-route rows=%d (%.1f%%), both=%d (%.1f%%)\n",
    sum(train$is_match_day),        100 * mean(train$is_match_day),
    sum(train$is_affected_route),   100 * mean(train$is_affected_route),
    sum(train$is_match_day * train$is_affected_route),
    100 * mean(train$is_match_day * train$is_affected_route)))
cat(sprintf("TEST:  match-day rows=%d (%.1f%%), affected-route rows=%d (%.1f%%), both=%d (%.1f%%)\n",
    sum(test$is_match_day),         100 * mean(test$is_match_day),
    sum(test$is_affected_route),    100 * mean(test$is_affected_route),
    sum(test$is_match_day * test$is_affected_route),
    100 * mean(test$is_match_day * test$is_affected_route)))

# ── Formula: C_m2nu4 base + FIFA interaction ────────────────────────────────
# The interaction structure:
#   is_match_day * is_affected_route                          → main match×route effect
#   is_match_day * is_affected_route * s(hour_from_kickoff)   → hour-shaped premium
# Cubic-shrinkage spline (bs="cs") lets non-match / non-affected rows contribute
# no shape info (their hour_from_kickoff=0 sentinels are masked by the product).
f_cand <- bf(
  delay_seconds ~ previous_stop_delay + shape_dist_traveled +
    s(hour, bs = "cc", k = 8) + s(dow, bs = "cc", k = 5) +
    is_match_day + is_affected_route +
    is_match_day:is_affected_route +
    s(hour_from_kickoff, by = interaction(is_match_day, is_affected_route),
      bs = "cs", k = 6) +
    (1 | route_id)
)
ADAPT_DELTA <- 0.95

base_priors <- c(
  prior(normal(0, 2),     class = b),
  prior(normal(0, 10),    class = Intercept),
  prior(exponential(1),   class = sigma),
  prior(exponential(0.5), class = sd),    # C_m2nu4-tight prior on group SD
  prior(constant(4),      class = nu)     # nu fixed at 4 (registry §2.1)
)

cat(sprintf("Fitting %s — train=%d test=%d\n", CANDIDATE_ID, nrow(train), nrow(test)))
fit <- brm(
  f_cand, data = train, family = student(), prior = base_priors,
  knots = list(hour = c(0, 24), dow = c(0.5, 7.5)),
  iter = 2000, warmup = 1000, chains = 4, seed = 42,
  control = list(adapt_delta = ADAPT_DELTA),
  file = sprintf("models/brms_%s", CANDIDATE_ID),
  file_refit = "always",
  refresh = 50
)

# ── Convergence gate inputs ─────────────────────────────────────────────────
rhat_max <- max(brms::rhat(fit), na.rm = TRUE)
np       <- bayesplot::nuts_params(fit)
n_div    <- sum(np$Value[np$Parameter == "divergent__"])
cat(sprintf("%s rhat_max=%.4f  divergences=%d\n", CANDIDATE_ID, rhat_max, n_div))

# ── Held-out eval + run_log row (memory-safe, chunked) ──────────────────────
source("loop_eval.R")
eval_and_log(fit, CANDIDATE_ID, train, test,
             model_file = sprintf("models/brms_%s.rds (loop %s, frozen test)",
                                  CANDIDATE_ID, CANDIDATE_ID))

# ── Reporting the key effect for the writeup ────────────────────────────────
# Extract the match×affected interaction and its CI. These are what the loop
# journal entry and the FIFA descriptive report will quote as the model's
# recovered estimate of the empirical +87..+276s benchmark.
ps <- brms::posterior_summary(fit, variable = "b_is_match_day:is_affected_route")
cat(sprintf("\n%s recovered match×affected coefficient: %.1f s [%.1f, %.1f] (95%% CrI)\n",
            CANDIDATE_ID, ps[1, "Estimate"], ps[1, "Q2.5"], ps[1, "Q97.5"]))
cat(sprintf("%s complete.\n", CANDIDATE_ID))
