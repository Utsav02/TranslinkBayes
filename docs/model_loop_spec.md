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
| **TEST (frozen)** | service_date **2026-06-08 → 2026-06-11** (four complete dense days; 06-12 excluded — see below), same row filters, ALL routes except the six excluded (i.e. 6641/6705 are present in TEST but never in TRAIN) |

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
biggest dow blind spot.

**Why TEST ends 2026-06-11, not 06-12 (FIFA contamination guard):** the first
FIFA match at BC Place is **2026-06-13 21:00 PT**, and TransLink's FIFA service
changes (route 130 detour, extra service on 14/19/23/28/222) are active from
**2026-06-08**. So even the test window already sits inside the FIFA *service*
regime — that is tolerable (it is a single consistent regime across all four
test days, and the same routes' shape_dist caveats apply uniformly). What is
**not** tolerable is letting match-eve effects or an incomplete day leak in:
06-12 (Fri) is match-eve with BC Place setup / downtown closures beginning, and
as of the freeze it is also a *partial* collection day (~117K rows vs 400–640K
for complete days). Ending at 06-11 (Thu) gives four complete, pre-match,
single-regime days and a full buffer before any match-day signal. Match-day
regime modelling is deferred to the v2 queue with its own split (§4).

**Standing caveat — thin TRAIN window (applies to every conclusion the loop
draws):** TRAIN is only **~9 dense days** (2026-05-30 → 06-07), and Mondays are
effectively absent (Jun 1 collapsed; the only clean dense Monday, Jun 8, is in
TEST not TRAIN). Tuesdays are similarly thin. This is acceptable for a
*reference baseline* and for relative ΔELPD comparisons between candidates
(every candidate shares the same handicap), but it caps external validity:
any accepted effect — especially day-of-week, weather, or anything seasonal —
is established on barely over a week of data spanning one weekly cycle, and
must be reported as provisional pending a wider window. A candidate that
improves dow handling is also partly handicapped by the train gap; that is
preferable to contaminating the test set by selection. **Every PASS in the
closing summary must carry this caveat explicitly.**

### 1.2 Freezing mechanics (iteration 0)

> **Steps 1–2 are run MANUALLY BY THE OWNER, not by the loop session.** They
> are the only steps that write to a database or regenerate parquets — i.e.
> the only destructive surface — and the incremental-vs-full-rebuild nuance
> (`static_sync_gap_check.md` §4) is exactly the kind of thing a loop agent
> could fat-finger into a full rebuild that silently degrades pre-Jun-8 joins.
> The loop session begins at step 4, with the frozen parquets already on disk
> and recorded in the manifest. See §3 "out of scope" and §5.3.

**Owner-run, exact commands (do not improvise; do not substitute `--since
2026-05-09`):**

```bash
cd /Users/utsavsingh/Desktop/Post-Uni/Projects/TranslinkBayes
# 1. Incremental reprocess of new-schedule dates ONLY (safe; correct static join)
venv/bin/python3 pipeline/process_delays.py --since 2026-06-08
# 2. Export the all-routes parquet covering both train and test windows
venv/bin/python3 pipeline/export_route.py --route all --since 2026-05-30
```

3. **(Owner or a one-shot setup script, not the loop):** from that parquet,
   materialize `exports/loop_train.parquet` (≤ 2026-06-07, filters/exclusions
   per §1.1, seed-42 per-route subsample) and `exports/loop_test.parquet`
   (2026-06-08 → 2026-06-11, filters per §1.1). Record both files' SHA-256 +
   row counts in `exports/loop_split_manifest.txt` and commit the manifest
   (parquets stay gitignored). **The TEST parquet is never regenerated**, even
   as collection continues. New data accruing after Jun 11 (including all FIFA
   match days, from Jun 13) is not used by this loop at all — neither side of
   the split moves.
4. **(Loop iteration 0):** re-evaluate baseline m3 ONCE on the frozen TEST set
   (ELPD, RMSE, MAE, coverage) — read-only on the parquets; this row is the
   reference value for gate G4/G5.

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

**Out of scope for the loop (hard rules):** no collector/launchd changes; **no
running of `process_delays.py` or `export_route.py`, and no database writes of
any kind** — the owner runs §1.2 steps 1–2 manually before the loop starts, and
the loop only ever reads the already-frozen `loop_train.parquet` /
`loop_test.parquet`. A loop that finds those parquets missing must STOP and ask
the owner, never regenerate them (the full-vs-incremental rebuild nuance is too
easy to get wrong — see `static_sync_gap_check.md` §4). No new external data
acquisition unless the candidate explicitly lists it (C7 weather, and only from
the already-materialized `exports/weather_hourly.parquet`); no prior tightening
to chase convergence without logging it as a deviation.

### 3.1 Running it — sleep-proof launcher (built 2026-06-13)

The fit died twice from system sleep; every long run must hold a system-sleep
assertion and be detached from the terminal. Two committed scripts do this:

- `scripts/sleepproof_run.sh <logfile> <cmd...>` — wraps any command in
  `caffeinate -s` (system-sleep assertion, survives a closed lid on AC) +
  `nohup … & disown` (immune to SIGHUP). Prints the detached PID. Warns if not
  on AC (where `caffeinate -s` is a no-op).
- `scripts/run_loop_iteration.sh [--dry-run]` — runs ONE iteration: (1) verifies
  `loop_train/test.parquet` against `loop_split_manifest.txt` and ABORTS on
  drift; (2) resolves the lowest-numbered candidate in
  `analysis/loop_candidates.tsv` with no `run_log.csv` row; (3) requires
  `analysis/fit_candidate_<ID>.R`; (4) launches it sleep-proof + detached;
  (5) verifies liveness (process alive, assertion held, log past iter 50 — the
  point earlier fits died). `--dry-run` resolves the next candidate and proves
  the plumbing without fitting.

**Authoring a candidate (the loop agent's per-iteration job):** copy
`analysis/fit_candidate_TEMPLATE.R` to `analysis/fit_candidate_<ID>.R` and edit
only the three marked blocks (id, optional data prep, formula + adapt_delta).
The template already reads the frozen parquets, applies shared priors/sampler
settings, evaluates held-out ELPD (saving pointwise log-lik for ΔELPD±SE),
RMSE, and coverage, and appends the `run_log.csv` row via `run_tracker.R`. It
sets `file_refit="always"` so a cached `.rds` is never silently reloaded
(baseline_registry caveat #1).

**Starting the Ralph /loop:** point the loop at the per-iteration prompt below;
each iteration the agent (a) authors the next `fit_candidate_<ID>.R` from the
template, then (b) runs `scripts/run_loop_iteration.sh`. Cadence generous
(one fit per session / ~hours). The launcher's hash check + the
"never regenerate parquets" rule (§3) are the guardrails.

## 4. Pre-registered candidate queue (v2, reconciled 2026-06-16)

v1 (2026-06-12) presumed an m3 base. After four laptop fits, m3 cannot
converge on this 9-dense-day split (registry §2.1). The reconciled queue
modifies the **C_m2nu4 base** instead:

```r
delay_seconds ~ previous_stop_delay + shape_dist_traveled +
                s(hour, bs="cc", k=8) + s(dow, bs="cc", k=5) +
                (1 | route_id)
family   = student()                         # nu = constant(4)
priors   = base_priors with prior(exponential(0.5), class = sd)
knots    = list(hour = c(0, 24), dow = c(0.5, 7.5))
iter=2000, warmup=1000, chains=4, seed=42, adapt_delta=0.95
```

Each candidate is a **hypothesis, not a foregone conclusion**. Candidates face
the STRICT gate (R-hat<1.01, 0 div, ESS≥400, ΔELPD>2×SE on the frozen test
set). Only the REFERENCE gets the relaxed gate (registry §2.1).

| Order | ID | Change vs C_m2nu4 base | Hypothesis | Convergence risk | Data prep |
|---|---|---|---|---|---|
| 1 | **C7** | + `precip_mm + temp_c` | weather adds signal beyond schedule features | low (2 continuous FE) | join `weather_hourly.parquet` on Pacific (date, hour) — fetcher in `pipeline/fetch_weather_eccc.py` |
| 2 | **C2** | + `log(headway_obs / headway_sched)` | bunching amplifies delay beyond carry-forward | low (1 continuous FE) | derive headway via SQL window over `stop_delays`, persist in TRAIN/TEST |
| 3 | **C5** | `(1|route_id)` → `(1 + previous_stop_delay | route_id)` | propagation strength varies by route (express vs local) | **acceptable** — 25 route groups, NOT high-cardinality; this is the "structure without funneling" template that replaces the dropped trip/stop REs | none |
| 4 | **C3** | + `timepoint * previous_stop_delay` | propagation resets at scheduled timepoints (slope < off-timepoint) | low (1 interaction) | join `timepoint` from static `stop_times` |
| 5 | **C4** | `shape_dist_traveled` → `s(shape_dist_traveled, bs="tp", k=8)` | non-linear delay accumulation along route (recovery padding) | low (smooth, no RE) | none |
| 6 | **C1** | TRAIN filtered to settled rows (`actual_arrival ≤ timestamp`) | **VALIDITY PROBE** — does b_prev fall well below 1 once the response is observation-grade not predicted? | low (no formula change) | settled flag (tier-b); subset shrinks TRAIN to ~5.9% — note in run_log |
| 7 | **C9** | `bf(..., sigma ~ is_rush_hour + s(hour, bs="cc", k=8))` | residual scale is time-varying — gains in cov90/ELPD, not RMSE | medium (smooth on σ scale) | none |
| 8 | **C8** | scale-up: top-50 routes × 1,500 rows (~75k TRAIN) | does more data identify what 25×500 cannot (tighter posteriors)? | structure unchanged; **expensive** (~6–8 h cloud) | none |

The machine-readable order is `analysis/loop_candidates.tsv`. Order is
deliberate: **front-load** the cheapest and highest-hypothesis-value
candidates (weather, bunching, route slopes) so a preemptible cloud instance
that doesn't finish all eight still answers the headline questions.

**Dropped from v1** (the queue records the reason inline; the launcher skips
commented rows):

- **C0** (m3 at `adapt_delta=0.99`) — C0_nu4 at `adapt_delta=0.95` with nu
  off the lb=2 floor (already better geometry than C0's plan) still produced
  25 divergences and R-hat 1.0114. Sampler-tuning alone is insufficient
  against the full m3 RE stack on 9 dense days. Superseded by C_m2nu4.
- **C6** (`ar(stop_sequence, gr=trip_serv_id, p=1)`) — within-trip AR(1)
  requires sequential observations inside each ~5,500 trip-day group, but the
  frozen TRAIN is a random 500-rows-per-route subsample (~2 obs/trip-day on
  average); the AR coefficient is not identifiable on this split. Not a
  funneling problem; a sampling-policy problem. Defer to a v2 split with
  by-trip stratification once the dataset fattens.

**FIFA regime candidates remain explicitly deferred to a v2 queue** with a
new frozen split once match days exist in both train and test (earliest
~mid-July).

**Note on C1 and the snapshot log:** an append-only `stop_delays_snapshots`
table now captures the full prediction trajectory, but only **from 2026-06-12**
— it does *not* cover this loop's frozen window (06-08…06-11). So C1 here still
uses the settled-row heuristic (`final fetch ≥ predicted arrival`) computed on
`stop_delays`. The snapshot log's true fixed-horizon evaluation becomes
available to the **v2 / FIFA-phase** loop, whose window post-dates 06-12.

## 5. Owner decisions — RESOLVED 2026-06-12

1. **Frozen split — APPROVED**, with the FIFA correction applied: train ≤
   2026-06-07, **test 2026-06-08 → 06-11** (06-12 dropped as match-eve +
   partial), route holdout 6641/6705 kept. Standing thin-train caveat (§1.1)
   attaches to every conclusion. Alternative considered and rejected:
   route-only holdout (leaves temporal generalization untested; date split
   subsumes it).
2. **Weather acquisition (C7) — APPROVED.** ECCC hourly, free/no-key, fetched
   by `pipeline/fetch_weather_eccc.py`; joined into the loop parquets on
   Pacific (date, hour). C7 stays in the queue.
3. **Reprocess/export — owner runs manually** (the two commands in §1.2). The
   loop has no DB-write or processing surface (§3 out-of-scope). Resolved: the
   loop does NOT run these.
