# Model-Search Loop Spec — requisites & recommendation (2026-06-12)

Companion to `baseline_registry.md` (the gate), `variable_inventory.md` (the
material), `data_validation_2026-06-12.md` (the caveats). Nothing in this
document has been fit yet; the candidate queue below is a **pre-registration**.

---

## 1. Frozen evaluation protocol — created BEFORE any candidate is fit

### 1.1 The split (temporal, with a route holdout on top)

| Set | Definition |
|---|---|
| **TRAIN** | service_date 2026-05-30 → 2026-06-07, minus anomaly days (rule in `fit_m3.R`), minus excluded routes (12940, 6700, 30055, 6702, 6718, 6619), minus held-out routes 6641 & 6705, standard row filters (`route_id != ''`, non-NULL model columns, `|delay| ≤ 3600`, `|prev| ≤ 3600`) |
| **TEST (frozen)** | service_date **2026-06-08 → 2026-06-12**, same row filters, ALL routes except the six excluded (i.e. 6641/6705 are present in TEST but never in TRAIN) |

**Why by date, not by route:** deployment is forecasting *future* days, and a
date split also keeps within-trip rows (which share a trip and are serially
dependent) on one side of the fence — a random row split would leak through
`previous_stop_delay`'s within-trip structure. The route holdout (6641, 6705)
already exists in `fit_m3.R` and is kept as a *secondary* readout
(unseen-route generalization), reported per-route on the same TEST window.

**Why this boundary:** Jun 8 is TransLink's summer-signup service-period
boundary (`static_sync_gap_check.md` §2) — train and test sit on different
schedules, which is a *deliberately honest* (slightly hard) deployment
scenario; the test window contains a dense Monday (Jun 8), repairing the
biggest dow blind spot; and it contains **zero FIFA match days** (first match
Jun 13), so the loop measures regular-service skill and match-day regime
shifts can't masquerade as wins or losses.

**Known asymmetry, accepted:** TRAIN has thin Mon/Tue coverage (Jun 1–2
collapsed). A candidate that improves dow handling will be partly handicapped;
that is preferable to a test set contaminated by selection.

### 1.2 Freezing mechanics (iteration 0, before any fit)

1. `venv/bin/python3 pipeline/process_delays.py --since 2026-06-08`
   (incremental — see `static_sync_gap_check.md` §4; do NOT full-rebuild).
2. Export one parquet, then materialize `exports/loop_train.parquet` and
   `exports/loop_test.parquet` by the definitions above (deterministic
   script, seed 42 for the per-route subsampling of TRAIN if subsampling is
   retained).
3. Record both files' SHA-256 + row counts in `exports/run_log.csv`'s
   companion `exports/loop_split_manifest.txt` and commit the manifest
   (parquets stay gitignored). **The TEST parquet is never regenerated**, even
   as collection continues. New data accruing after Jun 12 is not used by
   this loop at all — neither side of the split moves.
4. Re-evaluate baseline m3 ONCE on the frozen TEST set (ELPD, RMSE, MAE,
   coverage) — this row is the reference value for gate G4/G5.

### 1.3 Subsampling policy

`fit_m3.R` currently trains on top-25-routes × 500 rows (~12.5K) to keep NUTS
tractable. The loop keeps this policy **fixed for all candidates** (same
routes, same seed, same n) so model structure is the only thing varying.
Scaling up training data is itself a legitimate candidate (C8) — but it is a
*candidate*, not a free change.

### 1.4 Held-out scoring details

- ELPD on TEST via `log_lik(fit, newdata = test_df, allow_new_levels = TRUE,
  sample_new_levels = "gaussian")` — TEST contains trip_ids/stop_ids (and two
  routes) unseen in training; scoring them through the hierarchical prior is
  the point, not a bug. Pointwise log-lik matrices are saved so ΔELPD ± SE
  between any two candidates is computable without refitting
  (`loo::elpd()` / paired pointwise differences).
- RMSE/MAE/coverage from `posterior_predict` means and 90% intervals — the
  existing `run_tracker.R` machinery.

## 2. Is an autonomous loop viable here? — Recommendation

**Qualified GO.** The disciplined form below is viable and worth running;
open-ended pattern discovery is not, and would be actively harmful here.

Honest framing of the ceiling: the baseline already sits at b_prev ≈ 0.998
with σ ≈ 20s because, for ~78% of pairs, response and predictor are the same
feed snapshot and the model is recovering TransLink's carry-forward rule
(`data_validation_2026-06-12.md` §4.2). **Large RMSE gains over m3 are
unlikely and should not be the loop's promise.** What the loop *can* honestly
deliver:

1. quantified answers to specific transit hypotheses (bunching, timepoint
   resets, inter-trip block propagation, weather) — each a clean
   accept/reject on held-out ELPD;
2. a validity-stress-tested baseline (settled-response subset, C1);
3. a clean, convergent reference model for the FIFA phase-2 analysis, which
   is where this dataset's genuinely novel scientific value lies.

If after the queue runs the result is "nothing beats m3," that is a
*publishable negative result* about feed-derived delay data, not a failure of
the loop. Conversely, the reason not to skip the loop: candidates C2/C5/C7
attack exactly the part of the variance (residual σ ≈ 20s, heavy tails) that
the carry-forward cannot explain, and nobody has tested them.

### Garden of forking paths — named and mitigated

The risk: fit many models, report the winner, overstate its evidence. With ~9
candidates and a 2×SE gate, the family-wise chance of a spurious "pass" is
non-trivial (~roughly 9 × ~2.5% ≈ 20% if all nulls were true). Mitigations,
all mandatory:

- **Pre-registered finite queue** (§4): candidates, formulas, and hypotheses
  are written down *here, before any fit*. No mid-loop additions; amending
  the queue requires a new versioned section in this file and restarts the
  non-improvement counter disclosure.
- **One frozen test set** for every candidate; no candidate is tuned against
  it (no second fit of the same candidate "to see if it passes now", except
  the single permitted `adapt_delta` retry, which targets convergence, not
  the metric).
- **All attempts logged** — pass AND fail rows in `run_log.csv`. The final
  report states "k of N pre-registered candidates passed," never just the
  winners.
- **Effect-size honesty**: a pass is reported with ΔELPD ± SE and the
  multiple-comparison count alongside, and the headline claim for any single
  winner should survive a Bonferroni-style mental discount (ΔELPD > 2×SE with
  9 looks is suggestive; > 4×SE is solid).

## 3. Iteration contract (hand this to a Ralph /loop session)

**State the loop reads:** `docs/model_loop_spec.md` (this file, §4 queue) +
`exports/run_log.csv` (memory of attempts: a candidate is "done" iff a row
with its `model_file` exists) + `exports/loop_split_manifest.txt`.

**Per-iteration prompt (verbatim):**

> Read docs/model_loop_spec.md §4 and exports/run_log.csv. Identify the
> lowest-numbered candidate with no run_log row. If none remain, or if the
> last 3 candidate rows are all non-passes on gate G4, STOP and write the
> closing summary. Otherwise: (1) write `analysis/fit_candidate_<ID>.R` by
> copying the fixed scaffold (load `exports/loop_train.parquet`, the §4
> formula for this candidate, shared priors, student(), iter=2000 warmup=1000
> chains=4 seed=42 adapt_delta=0.95, file_refit="always"); (2) run it —
> expect 1–3 h; (3) compute diagnostics (rhat, divergences, bulk/tail ESS).
> If divergences > 0, retry ONCE with adapt_delta=0.99. (4) Evaluate on
> `exports/loop_test.parquet`: ELPD (allow_new_levels=TRUE,
> sample_new_levels="gaussian", save pointwise to
> `exports/loglik_<ID>.rds`), RMSE, MAE, coverage_90; compute ΔELPD ± SE vs
> the baseline pointwise log-lik. (5) Append a run_log.csv row via
> track_run() plus the ΔELPD columns; mark PASS only if gates G1–G5
> (docs/baseline_registry.md §4) all hold. (6) Commit the script + a 5-line
> verdict appended to docs/loop_journal.md: hypothesis, ΔELPD±SE, RMSE,
> diagnostics, PASS/FAIL. Never refit a candidate that has a row; never touch
> loop_test.parquet; never modify the queue.

**STOP conditions:** queue exhausted, OR 3 consecutive G4 non-improvements,
OR any iteration finds the frozen parquets' hashes changed (abort — split
integrity broken).

**Cadence:** generous — these are MCMC fits with ~10⁴ random-effect levels;
one iteration per **4 hours** (or one per session). This is not a tight poll
loop; the wakeup interval exists only to resume after a fit finishes.

**Out of scope for the loop (hard rules):** no collector/launchd changes, no
database writes outside `processed_stops`-derived parquets, no new external
data acquisition unless the candidate explicitly lists it (C7 weather), no
prior tightening to chase convergence without logging it as a deviation.

## 4. Pre-registered candidate queue (v1, 2026-06-12)

Each entry is a **hypothesis, not a foregone conclusion**. Formulas modify the
m3 base: `delay_seconds ~ previous_stop_delay + shape_dist_traveled +
s(hour, bs="cc", k=8) + s(dow, bs="cc", k=5) + (1|route_id) + (1|trip_id) +
(1|stop_id)`, student(), shared priors, knots as in `fit_m3.R`.

| ID | Change vs m3 | Hypothesis being tested | New data prep |
|---|---|---|---|
| **C0** | none; `adapt_delta = 0.99` | the baseline's 56 divergences are a sampler artifact; a clean-converging m3 is the true reference | none |
| **C1** | same formula; TRAIN restricted to settled rows (final fetch ≥ predicted arrival) | b_prev ≪ 1 on observation-grade responses ⇒ the near-unit slope is feed carry-forward (validity probe; G4 not expected to pass — judged on what it reveals, reported regardless) | settled flag (tier-b) |
| **C2** | + `bunching` term: `+ log(headway_obs / headway_sched)` | short headways (bunching) amplify delay beyond per-trip carry-forward | headway derivation (tier-b, SQL window) |
| **C3** | + `timepoint * previous_stop_delay` interaction | drivers hold at timepoints ⇒ delay propagation resets there (slope < off-timepoint slope) | timepoint join (tier-b) |
| **C4** | `s(shape_dist_traveled)` replaces linear term | delay accumulation along the route is non-linear (recovery padding at route ends) | none |
| **C5** | + `(1 + previous_stop_delay | route_id)` random slopes | propagation strength differs by route type (express vs local) | none |
| **C6** | + `ar(time = stop_sequence, gr = trip_serv_id, p = 1)` | residual serial correlation along the trip persists beyond the LAG term | trip×date grouping var |
| **C7** | + `precip_mm + temp_c` (ECCC hourly, station 1108446) | rain increases delays and delay variance beyond all schedule features | **external fetch — needs owner sign-off** |
| **C8** | same formula; TRAIN scaled to top-50 routes × 2,000 rows | the subsampling policy, not model structure, is the binding constraint (posterior SDs shrink, held-out ELPD improves) | none (longer fit, expect ≫ 3 h) |
| **C9** | distributional: `bf(…, sigma ~ is_rush_hour + s(hour, bs="cc", k=8))` | residual scale is time-varying (heteroscedastic); ELPD gains come from calibration, not point accuracy | none |

Queue order is deliberate: C0 first (clean reference), validity probe second,
then tier-b covariates (cheap, high-prior), then structure, then the two
expensive ones. **FIFA regime candidates are explicitly deferred to a v2
queue** with a new frozen split once match days exist in both train and test
(earliest ~mid-July).

## 5. Decisions needed from the owner before iteration 0

1. **Approve the frozen split** (train ≤ Jun 7 / test Jun 8–12, route holdout
   kept). Alternative considered and rejected: route-only holdout (leaves
   temporal generalization untested; date split subsumes it).
2. **Weather acquisition (C7)** — yes/no on adding the ECCC fetch script.
   Without it C7 is skipped and logged as "not run — data not acquired."
3. Whether the loop may run `process_delays.py --since 2026-06-08` and the
   export itself (iteration 0), or you run those two commands manually first.
