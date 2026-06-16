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
| **2026-06-13** | **m3 (genuine refit)** | 7,842 (25 rt) | 1.0007 [0.9993, 1.002] | **9.68** | 2.00 | **1.0356** | **315** | **9** | 24.87 | 67.78 | 0.827 |
| 2026-06-14 | C0_notrip (m3 − trip RE) | 12,500 (25 rt) | 1.0008 [0.9999, 1.0017] | 8.68 | 2.00 | 1.0280 | 147 | 42 | 35.48 | 91.33 | 0.803 |
| 2026-06-16 | C0_nu4 (m3, nu fixed=4) | 12,500 (25 rt) | 1.0001 [0.9987, 1.0015] | 15.45 | 4.0 | 1.0114 | 418 | 25 | 35.44 | 91.07 | 0.830 |
| **2026-06-16** | **C_m2nu4 (REFERENCE — see §2.1)** | 12,500 (25 rt) | 0.9987 [0.9966, 1.0008] | 26.07 | 4.0 | **1.0043** | **703** | **29** | 36.69 | 91.85 | **0.8465** |

### §2.1 — REFERENCE selected (relaxed gate, documented): **C_m2nu4** (2026-06-16)

`C_m2nu4` = m3 minus `(1|trip_id)` minus `(1|stop_id)`; one hierarchy only,
`(1|route_id)`; **`nu` fixed at 4** via `constant(4)` (not freely estimated;
diagnostic showed nu pinned at the `lb=2` floor in 100% of m3/C0_notrip draws);
**`sd` prior tightened** to `exponential(0.5)`. This is the **m2-class single
hierarchy** the spec's Step-2 rule names. The full formula:

```r
delay_seconds ~ previous_stop_delay + shape_dist_traveled +
                s(hour, bs="cc", k=8) + s(dow, bs="cc", k=5) +
                (1 | route_id)
family = student()  # nu = constant(4)
prior(exponential(0.5), class = sd)
iter = 2000, warmup = 1000, chains = 4, seed = 42, adapt_delta = 0.95
```

**It does NOT pass the strict §4 gate (R-hat < 1.01 AND zero divergences).**
It passes the **RELAXED reference gate** explicitly enacted here:

| | C_m2nu4 | strict | RELAXED bar | pass? |
|---|---|---|---|---|
| R-hat max | **1.0043** | < 1.01 | < 1.02 | ✓ (relaxed) |
| Divergences | **29 / 4000 = 0.73%** | 0 | < 1.0% of draws | ✓ (relaxed) |
| ESS min | **703** | ≥ 400 | ≥ 400 | ✓ (**strict**) |

**The relaxed bar is for the REFERENCE only.** Loop CANDIDATES are still
evaluated against the strict §4 gate; the relaxation is so that *relative*
ΔELPD comparisons against a near-clean reference can proceed at all (waiting
for a strictly-clean m3-class reference on 9 dense days of data is the path to
no progress — diagnose_divergences localized the 29 div as DIFFUSE; this is
the floor on this dataset, not a tunable parameter).

**Acknowledged biases of this choice** (must be carried in every loop conclusion):

1. **C_m2nu4's own ELPD is mildly biased** because of the 29 divergent
   transitions (which over-explore high-curvature pockets of the posterior
   and slightly distort the tails of the predictive distribution). ΔELPD
   *differences* against C_m2nu4 are more reliable than its absolute value —
   the bias largely cancels for paired pointwise comparisons.
2. **The trip and stop hierarchies are dropped, not relegated.** Loop
   candidates that re-introduce them (e.g. C5's `(1+prev|route_id)` is
   different in spirit but related; a stop-level term would need a separate
   candidate) will be compared against a reference that lacks them. If such a
   candidate passes the strict G1–G3 *and* its ΔELPD vs C_m2nu4 is large and
   positive, that is a finding *despite* C_m2nu4's simpler structure — not
   undermined by it.
3. **`sigma` jumped to 26.07 from m3's 9.68.** This is correct: with the
   stop-level RE absorbed into the residual (stops were partially absorbing
   what the model called "noise"), the residual scale has to grow. Predictive
   metrics held essentially unchanged (RMSE 91.9 ≈ C0_nu4's 91.1; cov90
   0.847 *better* than C0_nu4's 0.830). The model wasn't gaining accuracy
   from those REs on this data — it was overfitting them.

**The strict gate remains the eventual target.** When the dataset fattens
(FIFA + the snapshot collector add daily data, with clean Mondays returning
post-Jun 8) the cloud loop's v2 may revisit C0 (`m3 at adapt_delta=0.99`) on
the richer split and replace C_m2nu4 as reference. Until then, **C_m2nu4 is
the reference of record** and the loop runs against it.

— Decision recorded 2026-06-16; row 7 of `exports/run_log.csv`;
  pointwise ELPD at `exports/elpd_pointwise_C_m2nu4.rds`;
  saved fit at `analysis/models/brms_C_m2nu4.rds` (6.7 MB — yes, 100× smaller
  than the m3-class fits because we dropped the dense REs).

### ⚠ 2026-06-13 genuine refit — FAILS the convergence gate (loop NO-GO)

The 2026-06-13 row is the **first genuinely independent m3 fit** (`fit_refit="always"`
path, cache cleared, parquet `all_routes_2026-06-07.parquet`, seed 42; ~5 h wall,
sleep-proofed). It is the honest current baseline and it does **not** pass §4:

- **R-hat max 1.0356** (> 1.01) — G1 fail.
- **9 divergent transitions** (> 0) — G2 fail. The 56-divergence problem from
  the stale rows reproduces in milder but still-failing form.
- **bulk-ESS proxy 315** (< 400) — G3 fail.

It also shows the stale rows were optimistic: genuine `sigma` is **9.68** (not
20.18), `route_sd` jumped 0.74 → **3.47**, ESS fell 1,011 → 315. The likely
cause is the near-saturated `(1 | trip_id)` term (~5,500 levels on 7,842 rows ≈
1.4 obs/level → funnel geometry). PSIS-LOO flagged 31/7,842 obs with Pareto-k >
0.7 (0.4%) — minor, not the blocker.

**Decision: do NOT start the open C1–C9 loop.** First get a clean-converging
reference. Run **C0** (m3 at `adapt_delta = 0.99`) on the frozen split; if
divergences/R-hat persist, escalate to a non-centred parameterization of the
trip-level RE or reconsider `(1 | trip_id)` itself. Only once a reference
passes G1–G3 should the structural candidates (which all inherit this geometry)
be fit — otherwise every candidate starts from an unconverged baseline and
ΔELPD comparisons are unreliable.

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
4. The reproducibility re-fit (launched 2026-06-12, completed 2026-06-13) is
   now logged as the **2026-06-13 row above** and analysed in the box above it.
   Result: it does not reproduce the stale numbers and fails the convergence
   gate (R-hat 1.0356, 9 divergences, ESS 315) → loop is NO-GO until C0 yields
   a clean reference.

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
