# C_m2nu4 — DECISIVELY-SIMPLER REFERENCE (2026-06-16). Last brms fit on this laptop.
#
# Step 1 localization on saved C0_nu4 (analysis/diagnose_divergences.R):
# divergences are DIFFUSE — sd_stop_id shows the largest shift (p68, +0.27 ≈ 1%)
# but there is no clean funnel signal on any single hyperparameter. Per the
# user's rule, that means stop shaving m3 one RE at a time. Fit a decisively
# simpler model we're confident converges, accept it as the reference, and let
# the loop's candidates climb complexity back up from there (this is what C5's
# random-slopes etc. exist for).
#
# Changes from m3 (one block of related simplifications, not whack-a-mole):
#   - DROP both (1|trip_id) and (1|stop_id). Keep only (1|route_id), the one
#     hierarchy that has been well-identified across all three failed m3 fits
#     (route_sd 3.3-3.9, stable, no MC noise). This is "m2-class" per docs.
#   - nu FIXED at 4 (Step 1's C0_nu4 result: pinning nu off the lb=2 floor was
#     necessary, just not sufficient; we keep it).
#   - Tighten the RE-SD prior: exponential(0.5) instead of exponential(1).
#     Belt-and-suspenders regularization on the single remaining group SD.
#   - adapt_delta = 0.95 (default; we've shown 0.95 is plenty when geometry
#     isn't pathological).
suppressMessages({ library(brms); library(arrow); library(dplyr); library(lubridate); library(loo) })
options(mc.cores = parallel::detectCores())

CANDIDATE_ID <- "C_m2nu4"

prep <- function(p) arrow::read_parquet(p) |>
  mutate(trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id), hour = as.integer(hour), dow = as.integer(dow))
train <- prep("../exports/loop_train.parquet")
test  <- prep("../exports/loop_test.parquet")
stopifnot(nrow(test) >= 100)

f_cand <- bf(
  delay_seconds ~ previous_stop_delay + shape_dist_traveled +
    s(hour, bs = "cc", k = 8) + s(dow, bs = "cc", k = 5) +
    (1 | route_id)                                # single hierarchy only
)

priors <- c(
  prior(normal(0, 2),     class = b),
  prior(normal(0, 10),    class = Intercept),
  prior(exponential(1),   class = sigma),
  prior(exponential(0.5), class = sd),            # tighter than default exp(1)
  prior(constant(4),      class = nu)
)

cat(sprintf("Fitting %s (m2-class, nu=4, tight sd prior) — train=%d test=%d\n",
            CANDIDATE_ID, nrow(train), nrow(test)))
fit <- brm(
  f_cand, data = train, family = student(), prior = priors,
  knots = list(hour = c(0, 24), dow = c(0.5, 7.5)),
  iter = 2000, warmup = 1000, chains = 4, seed = 42,
  control = list(adapt_delta = 0.95),
  file = sprintf("models/brms_%s", CANDIDATE_ID), file_refit = "always",
  refresh = 50
)

rhat_max <- max(brms::rhat(fit), na.rm = TRUE)
np <- bayesplot::nuts_params(fit); n_div <- sum(np$Value[np$Parameter == "divergent__"])
cat(sprintf("%s rhat_max=%.4f  divergences=%d\n", CANDIDATE_ID, rhat_max, n_div))
clean   <- rhat_max < 1.01  && n_div == 0
near    <- rhat_max < 1.02  && n_div < 40                 # 40 = 1% of 4000 draws
cat(sprintf("%s gate: clean=%s  near-clean(<1%%div & R-hat<1.02)=%s\n",
            CANDIDATE_ID, clean, near))

source("loop_eval.R")
eval_and_log(fit, CANDIDATE_ID, train, test,
             model_file = sprintf("models/brms_%s.rds (m2-class nu=4, frozen test)", CANDIDATE_ID))
cat(sprintf("%s COMPLETE\n", CANDIDATE_ID))
