# Baseline Registry — what any new model must beat

Status date: 2026-06-12. This is the acceptance gate for the model-search
loop (`model_loop_spec.md`). A candidate model is only "better" if it clears
**all** convergence criteria *and* beats M3 on the frozen held-out set.

---

## 1. The baselines (m0–m3)

All Student-t likelihood, shared priors, `iter=2000, warmup=1000, chains=4,
seed=42, adapt_delta=0.95`. Full provenance: `docs/known_baseline.md` Part 2;
fit code: `analysis/brms_analysis.Rmd` (m0–m2), `analysis/fit_m3.R` +
`analysis/multi_route_analysis.Rmd` (m3).

| Model | Formula (delay_seconds ~ …) | Scope |
|---|---|---|
| m0 | `prev_stop_delay + shape_dist + factor(hour) + s(dow,cc,5) + (1|trip_id)` | single route 6641 |
| m1 | m0 with `s(hour,cc,8)` replacing `factor(hour)` | single route 6641 |
| m2 | m1 + `(1|stop_id)` | single route 6641 |
| m3 | `prev + shape_dist + s(hour,cc,8) + s(dow,cc,5) + (1|route_id) + (1|trip_id) + (1|stop_id)` | multi-route (top 25 × 500 rows, per current `fit_m3.R`) |

Shared priors:

```r
c(prior(normal(0, 2),   class = b),
  prior(normal(0, 10),  class = Intercept),
  prior(exponential(1), class = sigma),
  prior(exponential(1), class = sd),
  prior(gamma(2, 0.1),  class = nu, lb = 2))
```

`fit_m3.R` additionally hardcodes: anomaly-route exclusions
(12940, 6700, 30055, 6702, 6718, 6619 — see comments there for the two failure
modes) and **held-out routes 6641, 6705** (never trained on; used for
unseen-route evaluation).

## 2. Current recorded values (`exports/run_log.csv`)

| run_date | model | n_train | b_prev [95% CI] | sigma | nu | rhat_max | ess_min | div | MAE | RMSE | cov90 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-05-20 | m3 | 3,608 (50 rt) | 0.9969 [0.9944, 0.9996] | 20.18 | 2.01 | 1.0065 | 1,011 | 56 | 37.81 | 89.59 | 0.858 |
| 2026-05-20 | m2 | 2,532 | 0.9988 [0.9955, 1.0021] | 31.64 | 2.06 | 1.0096 | 620 | 34 | 63.88 | 105.13 | 0.783 |
| 2026-06-07 | m3 | 7,842 (25 rt) | 0.9969 | 20.18 | 2.01 | 1.0068 | 1,011 | 56 | 32.72 | 72.65 | 0.864 |

### ⚠ Known integrity caveats on this table

1. **The 2026-06-07 m3 row is not an independent fit.** Its posterior columns
   are bit-identical to the 2026-05-20 row despite a different training set.
   Cause: `brm(file = "models/brms_m3_multiRoute")` silently *loads* the
   cached .rds instead of refitting when the file exists. The 06-07 row is a
   re-*evaluation* of the May-20 posterior on newer test data. Any loop
   iteration that reuses the `file=` idiom must delete/rename the target
   first, or use `file_refit = "always"`.
2. A 463MB m3 .rds was written 2026-06-08 22:02 with **no corresponding
   run_log row** (preserved as
   `analysis/models/brms_m3_multiRoute_pre_refit_2026-06-12.rds.bak`). The
   run_log and the on-disk model had diverged — rule for the loop: **no fit
   without a log row, no log row without a fit.**
3. MAE/RMSE/coverage in different rows are computed on *different* test sets
   (whatever the 25%-of-dates tail was on the day of the run). They are not
   comparable across rows. This is exactly what the frozen split in
   `model_loop_spec.md` fixes.
4. A reproducibility re-fit of m3 via `fit_m3.R` (cache cleared, parquet
   vintage 2026-06-07, seed 42) was launched 2026-06-12; its row is appended
   to `run_log.csv` and this section should be updated with the result.

## 3. The metric

- **Primary: held-out ELPD** on the frozen test set (sum of pointwise log
  predictive densities, `brms::log_lik(fit, newdata = test_df,
  allow_new_levels = TRUE, sample_new_levels = "gaussian")`). ELPD evaluates
  the full predictive distribution — calibration and tails, which RMSE is
  blind to and which matter for a ν≈2 likelihood. Report **ΔELPD ± SE** vs m3
  on the identical test set.
- **Secondary: held-out RMSE and MAE** (posterior-mean point predictions) and
  **90% interval coverage** — the existing `run_tracker.R` columns, kept for
  continuity and interpretability.
- **Diagnostic (not a gate): PSIS-LOO on the training set** via the `loo`
  package (`add_criterion(fit, "loo")`). Cheap relative-comparison among
  candidates and a Pareto-k early-warning for influential observations, but
  the frozen test set is the arbiter — LOO shares the training data and can
  be gamed by overfitting the training window.

## 4. The acceptance gate

A candidate **passes** only if ALL of:

| # | Criterion | Bar |
|---|---|---|
| G1 | Convergence | R-hat < 1.01 for every parameter |
| G2 | Divergences | 0 divergent transitions (one retry allowed at `adapt_delta = 0.99`; if still > 0, reject and log) |
| G3 | Effective sample size | bulk-ESS and tail-ESS ≥ 400 for every reported parameter |
| G4 | Primary metric | ΔELPD(candidate − m3) > 2 × SE(ΔELPD) on the frozen test set |
| G5 | Sanity | held-out RMSE not worse than m3 by > 5%, and 90% coverage in [0.85, 0.95] |

Failing any of G1–G3 means the *fit* is invalid — the candidate may be retried
once with adjusted sampler settings, then rejected. Failing G4/G5 means the
*hypothesis* is rejected on this data. **Both outcomes get a run_log row.**

Honest note on G2: the current m3 baseline itself recorded **56 divergences**
— it would not pass its own gate. The 2026-06-12 re-fit determines whether
that is reproducible; if it is, the first loop iteration should be "make the
baseline pass the gate" (e.g. `adapt_delta = 0.99`) before any new structure
is tried, so candidates are compared against a clean reference.

## 5. Context the loop must not "rediscover"

- `b_previous_stop_delay ≈ 0.997–0.999` is substantially the RT feed's own
  prediction-propagation rule, not bus physics: 78% of consecutive-stop pairs
  get their final values from the same 5-minute feed snapshot
  (`data_validation_2026-06-12.md` §4.2). Candidates should be framed as
  "what explains delay *beyond* the feed's carry-forward," and the
  settled-response robustness candidate (C1 in the loop spec) quantifies the
  artifact.
- ν ≈ 2.01 sits at the prior's hard floor (`lb = 2`) — the likelihood wants
  tails at least this heavy. Treat ν at the boundary as a flag, not a fact of
  nature; a candidate may probe `lb = 1`.
- `route_sd ≈ 0.74s` is tiny against σ ≈ 20s: route identity explains almost
  nothing *once previous-stop delay is conditioned on*. Hierarchical
  elaboration on intercepts is unlikely to pay; slope heterogeneity might.
