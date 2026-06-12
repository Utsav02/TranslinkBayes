# Variable Inventory — 2026-06-12

Every variable available to the model-search loop, in three tiers:
(a) in the data now, (b) derivable from what is already collected,
(c) acquirable external covariates. For each: readiness, risks, and an honest
prior on whether it plausibly explains held-out delay variance *beyond the
feed's own delay carry-forward* (see `data_validation_2026-06-12.md` §4.2 —
the bar every candidate must clear).

---

## Tier (a) — in `processed_stops` now

| Variable | Readiness | Risks / caveats | Plausibly adds signal? |
|---|---|---|---|
| `delay_seconds` (response) | ready | is the feed's *predicted* delay, last-upsert wins; 1.47% NULL; heavy tails (p99.9 ≈ 45 min) | — |
| `previous_stop_delay` | ready | same-snapshot artifact (78% of pairs); wrong for 1.18% tied-sequence trip-days (curated route exclusions) | already in baseline; dominates |
| `shape_dist_traveled` | ready | ~6.5% NULL (join misses); per-trip normalized; route 130 unreliable during FIFA detour (Jun 8–Jul 19) | weak alone (m1 ≈ m0); nonlinear form untested |
| `hour`, `dow` | ready | computed from *fetch* timestamp, not arrival — 6.5% hour mis-binning; Mon/Tue cells thin until Jun-8+ reprocess | in baseline as cyclic splines |
| `is_rush_hour`, `is_weekend` | ready | redundant with hour/dow splines | only as cheap interaction terms |
| `stop_lat`, `stop_lon` | ready | unused so far | yes — spatial field candidate (corridor effects) |
| `direction_id` | ready | 0% NULL | cheap; inbound/outbound asymmetry plausible |
| `stop_sequence` | ready | route-length confounded (seq 40 means different things on different routes) | yes, as trip-progress proxy |
| `route_id`, `trip_id`, `stop_id` | ready | grouping factors; trip_id RE blows up parameter count (≈ 1 level per few rows) | in baseline |
| `service_date`, `timestamp` | ready | bookkeeping / split keys | — |
| `bus_id` | **dead — 100% NULL** | vehicle-positions feed never collected | no (see block_id below for a substitute) |

## Tier (b) — derivable from already-collected data (no new collection)

| Variable | How to derive | Readiness | Risks | Plausibly adds signal? |
|---|---|---|---|---|
| **Headway / bunching** | gap between consecutive `actual_arrival` at same (route_id, stop_id, direction_id); bunching = headway ≪ scheduled | SQL window function on `stop_delays`; medium effort | needs dense capture (OK since 05-30); arrival times are predictions too; scheduled headway requires `stop_times` join | **high** — bunching is the classic delay-amplification mechanism and is *not* in the feed's per-trip carry-forward |
| **Cumulative upstream delay** | mean/max of `delay_seconds` over stops 1..k−1 within trip | trivial window function | collinear with `previous_stop_delay` | medium — tests memory beyond one stop |
| **Time-since-trip-start** | current minus first `actual_arrival` in trip | trivial | first stop often missing (6.3% structural) | medium — schedule-recovery behaviour |
| **Trip progress fraction** | `stop_sequence / max(stop_sequence)` per trip | trivial | end-of-trip truncation on partial captures | medium; cleaner than raw stop_sequence |
| **Stop spacing** | Δ`shape_dist_traveled` between consecutive stops | trivial | NULL propagation | low-medium — long gaps accumulate more delay |
| **Settled flag / lead time** | `actual_arrival − timestamp` per row | trivial | — | **high for validity** (response-quality stratification, candidate C1), not as a covariate |
| **Scheduled time-of-day** | `stop_times.arrival_time` join | join exists | >24:00 HH:MM:SS parsing | low — `hour` already proxies |
| **Timepoint flag** | `stop_times.timepoint` | join exists | meaning varies by agency | medium — drivers hold at timepoints → delay resets (interacts with prev_delay) |
| **`block_id` (vehicle linkage)** | `trips.block_id` from static | join exists | block ≠ vehicle guarantee, but same block = same bus across consecutive trips | medium-high — enables *inter-trip* delay propagation (late inbound trip delays the next outbound), invisible to per-trip models; partial bus_id substitute |
| **Route type / short name** | `routes` join | trivial | — | low — B-line/express vs local contrast only |
| **True route geometry** | `data/static/*/shapes.txt` **exists on disk** — never imported (`schema.md` says "no shapes table", which is true of the DB only) | one-time import script | DB write (out of scope this session); shape_id ↔ trip join needed | medium — exact inter-stop distance & curvature; better than stop coords |
| **FIFA `match_day` / `hours_to_kickoff`** | static table of 7 match datetimes, `known_baseline.md` §1.6 | trivial derivation | **zero training data before Jun 13** — first match is tomorrow; not evaluable on the frozen test split (ends Jun 12) | high *for June–July data*, phase-2 only |

## Tier (c) — acquirable external covariates

| Variable | Source | Join key + cadence | Readiness | Risks | Plausibly adds signal? |
|---|---|---|---|---|---|
| **Weather (precip, temp, wind)** | ECCC historical hourly CSV (free, no key: `climate.weather.gc.ca` bulk endpoint), station Vancouver Harbour CS (climate ID 1108446) or YVR (1108395) | Pacific `date` + `hour`; hourly | one fetch script + cached CSV; **easiest external add** | station ≠ whole-network weather; ECCC data lags a few days (fine for backtests, not nowcasts); June has limited rain variance — may need weeks of accumulation to test | **high** — rain is the best-documented exogenous delay driver in the transit literature, and is genuinely outside the feed's carry-forward |
| BC stat holidays / school calendar | static lists (BC gov, VSB) | `service_date`; daily | trivial | almost no holidays in the Jun–Jul window (Canada Day Jul 1) | low in this window |
| Road incidents / closures | DriveBC events API (free) | geo + time matching to routes | moderate scripting | matching incidents to routes is fiddly; sparse | medium but high effort |
| Traffic congestion index | TomTom/Google (paid) | — | not free | cost; licensing | not recommended |
| Ridership / pass-ups | TransLink open data (periodic), not real-time | route + period | low | coarse cadence | low for this design |

## Recommended acquisition order

1. **Nothing new before the loop starts** — tier (b) headway/bunching,
   upstream-delay, timepoint, and block_id candidates are all computable from
   existing tables and cover the highest-value hypotheses.
2. **Weather (ECCC)** is the one tier-(c) acquisition worth doing during the
   loop: free, one script, clean hourly join. Decision needed from the owner
   (it adds a fetch dependency to the pipeline).
3. FIFA covariates become testable only when match days exist in *both*
   training data and a (new, second) frozen test split — schedule for July.
