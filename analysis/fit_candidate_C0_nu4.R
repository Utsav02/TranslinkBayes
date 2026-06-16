# C0_nu4 — TARGETED CONVERGENCE EXPERIMENT (2026-06-14).
# Divergence localization (diagnose_divergences.R) showed nu pinned at its lb=2
# floor in 100% of draws for BOTH m3 and C0_notrip — the near-Cauchy likelihood,
# not the RE structure, is the suspected cause of the non-convergence. This is
# the single falsifiable test: FIX nu at 4 (a moderate, well-behaved tail) and
# change NOTHING else (full m3 formula incl. trip RE, adapt_delta=0.95).
#
#   clean convergence  -> near-Cauchy tails were the problem; C0_nu4 is the
#                         converging reference and the loop can proceed.
#   still not clean    -> HARD STOP (see docs/baseline_registry.md): m3 is too
#                         ambitious for 9 days of data; go strategic, no fit #4.
suppressMessages({ library(brms); library(arrow); library(dplyr); library(lubridate); library(loo) })
options(mc.cores = parallel::detectCores())

CANDIDATE_ID <- "C0_nu4"

prep <- function(p) arrow::read_parquet(p) |>
  mutate(trip_id = as.character(trip_id), stop_id = as.character(stop_id),
         route_id = as.character(route_id), hour = as.integer(hour), dow = as.integer(dow))
train <- prep("../exports/loop_train.parquet")
test  <- prep("../exports/loop_test.parquet")
stopifnot(nrow(test) >= 100)

# Full m3 formula — UNCHANGED from the baseline.
f_cand <- bf(
  delay_seconds ~ previous_stop_delay + shape_dist_traveled +
    s(hour, bs = "cc", k = 8) + s(dow, bs = "cc", k = 5) +
    (1 | route_id) + (1 | trip_id) + (1 | stop_id)
)

# Shared priors, EXCEPT nu is FIXED at 4 via constant() (was gamma(2,0.1) lb=2).
# This is the one and only change under test.
priors <- c(
  prior(normal(0, 2),    class = b),
  prior(normal(0, 10),   class = Intercept),
  prior(exponential(1),  class = sigma),
  prior(exponential(1),  class = sd),
  prior(constant(4),     class = nu)
)

cat(sprintf("Fitting %s (nu FIXED at 4) — train=%d test=%d\n", CANDIDATE_ID, nrow(train), nrow(test)))
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
clean <- rhat_max < 1.01 && n_div == 0
cat(sprintf("%s convergence-gate (R-hat<1.01 & 0 div): %s\n", CANDIDATE_ID,
            if (clean) "PASS" else "FAIL -> HARD STOP, go strategic"))

source("loop_eval.R")
eval_and_log(fit, CANDIDATE_ID, train, test,
             model_file = sprintf("models/brms_%s.rds (nu fixed=4 experiment, frozen test)", CANDIDATE_ID))
cat(sprintf("%s COMPLETE\n", CANDIDATE_ID))
