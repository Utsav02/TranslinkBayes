# Data Validation Report — 2026-06-12

Read-only validation of `database/gtfs_realtime_v2.db` (`stop_delays`,
`processed_stops`) and `database/gtfs_static.db`, ahead of the model-search
loop. Companion documents: `static_sync_gap_check.md` (June-6 sync question),
`baseline_registry.md`, `variable_inventory.md`, `model_loop_spec.md`.

All queries were run against the live databases on 2026-06-12 (read-only
connections). `processed_stops` was last rebuilt **2026-06-07 22:12** with
`--since 2026-05-09`, so it lags `stop_delays` by five service days.

---

## 1. Volume & coverage

### Totals

| Table | Rows | Service-date range |
|---|---|---|
| `stop_delays` | 4,702,896 | 2026-04-26 → 2026-06-12 |
| `processed_stops` | 3,040,231 | 2026-05-09 → 2026-06-07 (stale — see §6) |

### The dense/sparse boundary is 2026-05-30, not 2026-05-16

CLAUDE.md says dense collection started 2026-05-16. The per-service-date counts
say otherwise — there are **two distinct regime changes**:

| Era | Rows/day | Stops captured per trip | Interpretation |
|---|---|---|---|
| 2026-04-26 → 05-15 | 18 – 3,000 | ~1–2 | collector intermittent (Mac sleep) |
| 2026-05-16 → 05-29 | 0.8K – 18K | ~4 | collector mostly up, but few stop-updates per trip retained |
| 2026-05-30 → present | 117K – 641K (good days) | ~27 | full-feed dense capture |

The jump on 05-30 is a ~50× volume change: e.g. 05-29 has 6,768 rows / 2,436
trips, 05-30 has 404,295 rows / 14,838 trips. **97.8% of all model-ready rows
come from 2026-05-30 onward** (2,643,193 of 2,702,949). The pre-05-30 era
contributes ~60K rows and, more importantly, is *structurally different data*
(sparse per-trip stop coverage changes what `previous_stop_delay` means — the
"previous" observed stop may be many stops upstream).

**Recommendation: treat 2026-05-30 as the effective start of the modeling
dataset.** Keeping `--since 2026-05-09` for processing is harmless, but model
fits and the held-out split should use 2026-05-30+.

### Bad days inside the dense era

Even after 05-30, collector uptime varies (`collection_runs`, 288 runs = full
24h day):

| Day | ok runs | Note |
|---|---|---|
| 2026-06-01 (Mon) | 130 | partial — only 6,776 rows |
| 2026-06-02 (Tue) | 69 | collapsed — 3,466 rows |
| 2026-06-04 (Thu) | 97 ok / **89 error** | DB locked or API errors — 128K rows |
| 2026-06-09 (Tue) | 89 | partial — 128K rows |
| 2026-06-10 (Wed) | 41 | partial — 163K rows |

### Coverage by dimension (dense era, `processed_stops` ≥ 2026-05-30)

- **route_id**: 227 routes observed; 215 have ≥ 500 rows; 152 have ≥ 5,000;
  only 7 routes below 100 rows. Route-level hierarchical terms are well fed.
- **direction_id**: balanced — 1.46M (dir 0) vs 1.48M (dir 1), 0% NULL.
- **hour**: all 24 hours covered; hours 02–05 are thin (1.8K–20K rows,
  vs 60–120K for daytime hours) — a cyclic-spline on hour is fine, but
  hour-level random effects or interactions would starve overnight cells.
- **dow — the one genuinely starved dimension** in the current
  `processed_stops`:

  | dow | rows | distinct days |
  |---|---|---|
  | Mon | 4,556 | 2 |
  | Tue | 3,505 | 3 |
  | Wed | 524,324 | 3 |
  | Thu | 120,568 | 3 |
  | Fri | 553,677 | 4 |
  | Sat | 904,195 | 5 |
  | Sun | 829,089 | 5 |

  The collapsed days (Jun 1, Jun 2) were precisely Monday and Tuesday, so
  Mon/Tue carry **< 0.3%** of dense-era rows. Any dow term fit on the current
  table is effectively interpolating Mondays and Tuesdays from weekend
  behaviour. **Mitigation already in hand**: `stop_delays` holds an
  unprocessed dense Monday (Jun 8: 560,585 rows) and a partial Tuesday
  (Jun 9: 128,275) — reprocessing (§6) materially repairs the dow imbalance.
  This will remain the weakest cell; one good Monday is still only one Monday.

---

## 2. Missingness per column

`stop_delays` since 2026-05-30 (4,575,114 rows):

| Column | NULL rate | Handling today |
|---|---|---|
| `delay_seconds` | 1.47% (67,466) | kept in `processed_stops`; dropped by R model filters (`!is.na`) |
| `actual_arrival` | 1.47% — **exactly the same rows** as `delay_seconds` (stop_time_updates broadcast without an arrival block) | same |
| `bus_id` | **100%** (known — vehicle-positions feed not collected; collector hardcodes `NULL`) | unused everywhere |
| `route_id = ''` | 0.31% (14,191) | kept; dropped by R filter `route_id != ""` |

`processed_stops` (full window, from quality_report 2026-06-11):

| Column | NULL rate | Source of NULLs |
|---|---|---|
| `shape_dist_traveled` | 6.91% (5.8–8.2% on dense days) | static `stop_times` join miss (orphan trip/stop/seq); R drops |
| `previous_stop_delay` | 6.30% | structural — first stop of each trip has no LAG; R drops |
| `direction_id` | 0.00% | trips join is complete (verified per-day, see gap check doc) |
| `stop_lat` / `stop_lon` | ≈ stop join miss, small | R models don't currently use them |

No imputation happens anywhere — every model so far is complete-case. That is
defensible given the rates, but it means the modeled population is "stops that
join cleanly to the static schedule," which under-represents detoured/changed
routes (see route 130 / FIFA note in `known_baseline.md` §1.6).

---

## 3. Anomaly days

Rule (implemented twice, near-identically: `fit_m3.R` and
`multi_route_analysis.Rmd`): after the row filters, compute daily counts and
daily mean delay; exclude days with
`n < 0.20 × median(daily n)` **or** `|mean − overall mean| > 2 × SD(daily means)`.
A MAD-based variant of the same idea runs in `quality_report.py` (2.5×MAD flag,
warn-only).

Applied to the current table (since 2026-05-09, model filters applied —
median daily n = 2,890, mean delay 44.6s, SD of daily means 44.0s), the rule
excludes **7 days, all by sparseness, totalling 656 rows (0.02%)**:
05-10, 05-11, 05-12, 05-13, 05-14, 05-20, 05-21.

No day is currently excluded on the mean-delay criterion;
`quality_report.py`'s MAD variant flags 2026-06-04 (mean 122s) as anomalous —
worth watching but it survives the Rmd rule.

Two caveats:

1. The rule is **window-relative**: once the dense era dominates, every
   pre-05-30 day will fall under the 20%-of-median bar and be auto-excluded.
   That is the right outcome, but it makes the `--since 2026-05-09` cutoff
   cosmetic — the rule is already enforcing ≥ 05-30 de facto.
2. The thresholds are computed on the data being filtered (mildly circular).
   Acceptable for sparse-day removal; do not extend it to mean-delay-based
   exclusion of real high-delay days (e.g. FIFA match days, starting
   2026-06-13) — those are signal, not anomaly. The FIFA service window
   (Jun 8 – Jul 19) makes this a live concern **now**.

---

## 4. Leakage & validity checks

### 4.1 `previous_stop_delay` construction is causally ordered…

`process_delays.py` computes it as
`LAG(delay_seconds) OVER (PARTITION BY trip_id, service_date ORDER BY stop_sequence, actual_arrival)` —
strictly the prior stop in sequence order, never a future stop. Partitioning
includes `service_date`, so trip_id reuse across days cannot leak. Duplicate
`(trip_id, stop_id, service_date)` keys post-dedup: **0** (verified by direct
GROUP BY/HAVING count). Non-monotone `stop_sequence` (ties from branching/loop
topology) affects 2,183 / 185,399 dense-era trip-days (**1.18%**) — these
produce wrong LAG values silently and are the reason for the curated route
exclusion list in `fit_m3.R` (12940, 6700, 30055, 6702, 6718; plus 6619 for
structural join failure).

### 4.2 …but predictor and response are usually the *same feed snapshot*

This is the most important validity finding of this review.

`delay_seconds` is not an observed arrival time — it is TransLink's
**predicted** delay from the trip-updates feed, upserted on every 5-minute
fetch; the stored value is whatever the *last* fetch said. Lead-time
distribution (final fetch vs predicted arrival, dense era):

- 5.9% "settled" — final value fetched at/after the predicted arrival
  (closest to an observation);
- 84.4% fetched 0–5 min before arrival (short-horizon prediction);
- 1.0% fetched > 30 min before arrival (pure forecast — trip dropped out of
  the feed or collector slept).

And crucially: **78.3% of consecutive-stop pairs got their final values from
the same fetch** (timestamps within 10s; 98.1% within one 5-min cycle). When
stop k−1 and stop k are written by the same feed snapshot, regressing
`delay_seconds(k)` on `previous_stop_delay(k−1)` largely recovers TransLink's
*own prediction-propagation rule* — their engine carries an observed delay
forward along the remaining stops. This, together with `b_previous_stop_delay
≈ 0.997–0.999` and a residual σ of ~20s, strongly suggests the headline
coefficient is substantially a **measurement artifact of the feed**, not a
clean estimate of physical delay propagation between stops.

This is not classic future-leakage — the LAG is causally ordered, and in a
*deployment* setting (predict downstream delay from the live feed) the model
is still answering a fair question. But it must be reported honestly: the
near-unit slope is the feed's autocorrelation, and model improvements should
be judged on what they add *beyond* it (which is exactly what held-out ELPD /
RMSE comparison does).

Mitigation options (none retroactive — the upsert overwrites history, so
earlier snapshots are unrecoverable):

- **Settled-response subset**: restrict the *response* to settled rows
  (final fetch ≥ arrival). ~267K dense-era rows — still ample. A candidate in
  the loop queue tests whether conclusions survive on this subset.
- Going forward, an append-only prediction log would allow true
  fixed-horizon evaluation; that is a collector change and out of scope here.

### 4.3 `hour`/`dow` are computed from the fetch timestamp, not the arrival

`_add_temporal()` uses `timestamp` (last fetch, UTC→Pacific), not
`actual_arrival_pacific`. The two disagree on `hour` for **6.5%** of dense-era
rows (boundary effects + stale rows). Not fatal — but the cleaner definition
is the arrival time, and rows where the final fetch is long before arrival get
systematically mis-binned. Worth a small `process_delays.py` fix at some
point; flagged here so the loop doesn't "discover" hour effects that are
partly binning noise.

### 4.4 Delay distribution & outliers (don't clip silently)

Dense-era `delay_seconds` (4.51M non-null rows):

| min | p1 | p5 | p25 | p50 | p75 | p95 | p99 | p99.9 | max |
|---|---|---|---|---|---|---|---|---|---|
| −5,117s | −503 | −227 | −53 | 20 | 135 | 465 | 1,017 | 2,713 | **71,977s** |

- `|delay| > 3600s`: 2,471 rows (0.055%) — these are excluded by the existing
  `abs(delay_seconds) <= 3600` filter in all fits, and that filter should stay
  **explicit and reported** in every loop iteration (it removes 1 row in
  ~1,800, not a meaningful truncation of the t-tail).
- `|delay| > 1800s`: 0.27%. The heavy tail the Student-t (ν ≈ 2.01) is
  modeling is real and persists after the 1-hour clip: p99.9 ≈ 45 min.
- The max (71,977s ≈ 20h) and similar extremes are feed pathologies (wrong
  service_date attribution or stuck predictions), not buses 20 hours late —
  the 3600s filter handles them.
- Early-running buses are common: 25% of stops are ≥ 53s *early*. Any
  asymmetric treatment of delay would be wrong.

---

## 5. Static-join integrity

Covered in depth in `static_sync_gap_check.md`. Summary: the static DB was
frozen on the May-22 schedule from 2026-05-30 to 2026-06-11 00:03 (integrity
floor blocked two legitimate updates), but **no corrupted rows resulted** —
`processed_stops` (rebuilt Jun 7) used the schedule that was actually in
effect through Jun 7 (old service period ended exactly 2026-06-07), and
service dates ≥ Jun 8 have never been processed. Where both schedules match a
row, `shape_dist_traveled` agrees to ~0.3m mean — no silent drift.

---

## 6. Verdict

**Modeling-ready: YES, from service_date 2026-05-30, after one incremental
reprocess.**

Required before the first loop iteration (both are existing, routine commands —
no code changes):

1. `venv/bin/python3 pipeline/process_delays.py --since 2026-06-08` —
   brings Jun 8–12 into `processed_stops` against the correct (new) schedule
   and repairs the Mon/Tue starvation. Do **not** run a full rebuild from
   05-09: pre-Jun-8 dates would re-join against the wrong schedule
   (match rate drops ~93% → ~85%; see gap-check doc).
2. Re-export the all-routes parquet (`make export` /
   `export_route.py --route all --since 2026-05-30`).

Standing caveats for every model fit (to be restated in the loop spec):

- `previous_stop_delay` ≈ same-snapshot feed propagation (§4.2) — report
  coefficients accordingly; include the settled-subset robustness candidate.
- Mon/Tue remain the thinnest dow cells even after reprocessing.
- FIFA service window is active **now** (Jun 8 – Jul 19; first match Jun 13):
  route 130's `shape_dist_traveled` is unreliable; match-day regime covariates
  don't exist yet (`known_baseline.md` §1.6).
- bus_id is 100% NULL; vehicle-position-derived features are unavailable.
