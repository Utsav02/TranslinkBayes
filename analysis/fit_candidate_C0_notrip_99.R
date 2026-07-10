# ─────────────────────────────────────────────────────────────────────────────
# C0_notrip_99 — reference-tension resolver (2026-07-10).
#
# WHY: The original C0_notrip fit (adapt_delta=0.95) beat the accepted reference
# C_m2nu4 by ΔELPD +3201 (SE 214, z=+15) on the frozen test set — dramatic
# predictive-quality dominance — but failed convergence with 42 divergences,
# R-hat 1.028, ESS 147. This refit changes ONLY adapt_delta (0.95 → 0.99).
# Same formula, same priors, same seed, same train/test data. Tests whether
# more careful HMC step-size adaptation alone rescues the fit that would
# otherwise become the reference.
#
# OUTCOME BRANCHES:
#   Clean (R-hat<1.01, 0 div, ESS≥400) → this becomes the new reference; update
#     baseline_registry §2.1, retarget loop_eval to elpd_pointwise_C0_notrip_99,
#     regenerate reference pointwise ELPD, refresh ΔELPD comparisons.
#   Near-clean under relaxed gate (R-hat<1.02, <1% div, ESS≥400) → same as
#     above with the relaxed-gate caveat documented.
#   Still failing → C_m2nu4 stays the reference; the ELPD-underestimation caveat
#     gets a full paragraph in baseline_registry acknowledging that a
#     predictively-superior fit exists but its convergence prevents adoption.
# ─────────────────────────────────────────────────────────────────────────────
suppressMessages({
  library(brms); library(arrow); library(dplyr); library(lubridate); library(loo)
})
options(mc.cores = parallel::detectCores())

CANDIDATE_ID <- "C0_notrip_99"

train <- arrow::read_parquet("../exports/loop_train.parquet") |>
  mutate(trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id), hour = as.integer(hour), dow = as.integer(dow))
test  <- arrow::read_parquet("../exports/loop_test.parquet") |>
  mutate(trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id), hour = as.integer(hour), dow = as.integer(dow))
stopifnot(nrow(test) >= 100)

# ── Formula: EXACTLY C0_notrip (m3 base with (1|trip_id) removed).
#    Priors: EXACTLY C0_notrip (gamma(2,0.1) nu, exp(1) sd). No change from the
#    fit that produced the winning ELPD.
f_cand <- bf(
  delay_seconds ~ previous_stop_delay + shape_dist_traveled +
    s(hour, bs = "cc", k = 8) + s(dow, bs = "cc", k = 5) +
    (1 | route_id) + (1 | stop_id)
)
# THE ONE CHANGE — everything else is byte-for-byte identical to C0_notrip.
ADAPT_DELTA <- 0.99

base_priors <- c(
  prior(normal(0, 2),   class = b),
  prior(normal(0, 10),  class = Intercept),
  prior(exponential(1), class = sigma),
  prior(exponential(1), class = sd),
  prior(gamma(2, 0.1),  class = nu, lb = 2)
)

cat(sprintf("Fitting %s — train=%d test=%d  adapt_delta=%.2f\n",
            CANDIDATE_ID, nrow(train), nrow(test), ADAPT_DELTA))
fit <- brm(
  f_cand, data = train, family = student(), prior = base_priors,
  knots = list(hour = c(0, 24), dow = c(0.5, 7.5)),
  iter = 2000, warmup = 1000, chains = 4, seed = 42,
  control = list(adapt_delta = ADAPT_DELTA),
  file = sprintf("models/brms_%s", CANDIDATE_ID),
  file_refit = "always",
  refresh = 50
)

# ── Convergence gate ───────────────────────────────────────────────────────
rhat_max <- max(brms::rhat(fit), na.rm = TRUE)
np       <- bayesplot::nuts_params(fit)
n_div    <- sum(np$Value[np$Parameter == "divergent__"])
cat(sprintf("%s rhat_max=%.4f  divergences=%d\n", CANDIDATE_ID, rhat_max, n_div))
clean_strict  <- rhat_max < 1.01  && n_div == 0
clean_relaxed <- rhat_max < 1.02  && n_div < 40    # <1% of 4000 draws
cat(sprintf("%s gate: strict=%s  relaxed=%s\n", CANDIDATE_ID,
            if (clean_strict) "PASS" else "FAIL",
            if (clean_relaxed) "PASS" else "FAIL"))

# ── Held-out eval + run_log (memory-safe, chunked; matches loop_eval semantics)
source("loop_eval.R")
eval_and_log(fit, CANDIDATE_ID, train, test,
             model_file = sprintf("models/brms_%s.rds (reference-tension resolver, adapt_delta=0.99, frozen test)",
                                  CANDIDATE_ID))
cat(sprintf("%s complete.\n", CANDIDATE_ID))
