# TransLink Bayesian Delay Model — Known Baseline

**Last updated:** 2026-05-25
**Status:** Data pipeline documented. Model baseline pending study period.

## How to use this document

If you are a Claude Code agent running the Ralph loop, read Part 1 before proposing
any feature engineering changes — it defines what data is available and what every
column means. Read Part 2 before proposing any model changes — it lists what has
already been tried and what not to re-propose. Append to Part 3 after each
iteration using the format specified there.

If you are the project owner, this document tracks the current state of data
quality and modelling progress. Update Part 1 after any significant pipeline change
and Part 2 after each new model family is established.

---

## Part 1: Data Pipeline and Health

### 1.1 Collection Architecture

Two launchd jobs run continuously. Both are defined in
`~/Library/LaunchAgents/com.translink.collect.plist` and
`~/Library/LaunchAgents/com.translink.sync-static.plist`.

#### `com.translink.collect` — RT trip-update collector

- **Frequency:** every 5 minutes
- **Script:** `pipeline/collect_realtime_v2.py`
- **URL:** `https://gtfsapi.translink.ca/v3/gtfsrealtime?apikey={API_KEY}`
  (defined as `TRIP_UPDATES_URL` in `pipeline/config.py`)
- **Protocol:** HTTP GET → binary protobuf, decoded with
  `google.transit.gtfs_realtime_pb2.FeedMessage`
- **What is fetched:** `TripUpdate` entities only. For every active trip in
  the feed, and for every `StopTimeUpdate` inside that trip, one row is prepared
  with `trip_id`, `route_id`, `stop_id`, `stop_sequence`, predicted
  `arrival.time` (UTC), `arrival.delay` (seconds), and the fetch timestamp.
- **Where it is written:** `database/gtfs_realtime_v2.db`, table `stop_delays`.
- **ON CONFLICT strategy:** `ON CONFLICT(trip_id, stop_id) DO UPDATE SET` —
  all five mutable fields (`actual_arrival`, `actual_arrival_pacific`,
  `delay_seconds`, `bus_id`, `timestamp`) are overwritten with the newer
  prediction. This means each row always holds the **most recent prediction**
  for that (trip, stop) pair, not the first or an average.
- **`bus_id` is always NULL.** The code comment reads: *"bus_id: populated only
  if vehicle-position collection is added later. realtime_vehicle_positions is
  currently unpopulated — skip the query."* The `realtime_vehicle_positions`
  table exists in the schema but holds no data. Do not treat 100 % NULL on
  `bus_id` as a data quality problem; it is a known architectural choice.
- **Audit log:** every invocation inserts a row into `collection_runs` with
  `started`, `finished`, `rows_inserted`, and `status` (`'ok'` or `'error'`).
  This table is the primary source for detecting collection gaps.

#### `com.translink.sync-static` — static GTFS refresher

- **Frequency:** every Saturday at 10:00 AM Pacific time
- **Script:** `pipeline/sync_static_gtfs.py`
- **Smart-skip logic (two-stage):**
  1. HTTP HEAD with `If-Modified-Since: <last_modified from meta>`. If the
     server returns 304, the job exits immediately — no download.
  2. If a download does occur, SHA-256 hashes of the four key files
     (`stop_times.txt`, `trips.txt`, `routes.txt`, `stops.txt`) are compared
     against the previous hashes stored in `database/gtfs_static_meta.json`.
     If all four are identical, the DB update is skipped even though the zip
     was downloaded.
- **What it extracts:** the full `google_transit.zip` (~39 MB) from
  `https://gtfs-static.translink.ca/gtfs/google_transit.zip`. All files are
  extracted to `data/static/YYYY-MM-DD/` (dated snapshot) and then copied to
  `data/gtfs_static/` (active directory).
- **Where it writes:** after promotion, it calls `pipeline/process_static.py`,
  which drops and rebuilds all four tables in `database/gtfs_static.db` from
  the active directory CSVs.
- **Meta file:** `database/gtfs_static_meta.json` stores `last_modified`
  (from HTTP header), `last_downloaded` (UTC ISO8601), `hashes` (SHA-256 of
  the four key files), and `changed_files` (list of which files differed).
  The current meta file (as of 2026-05-25) records `last_modified: "Fri,
  22 May 2026 21:35:35 GMT"`.

**Data collection history:**
- Collection started: **2026-05-09**
- Dense, reliable collection (Mac running 24/7): **2026-05-16** onwards
- Validation pipeline added: **2026-05-25**
- Data prior to 2026-05-25 has been retroactively validated but the
  pre-validator period (no real-time gate) carries slightly lower confidence
  than post-validator data. Use with normal confidence for training.

---

### 1.2 Database Schema

#### `database/gtfs_realtime_v2.db`

This is the primary working database. Opened with `PRAGMA journal_mode=WAL`
for concurrent reads during collection.

##### Table: `stop_delays`

The raw RT store. One row per (trip, stop) pair — the most recent prediction
received before that stop was served.

```
trip_id                TEXT    -- GTFS trip_id from the RT feed
route_id               TEXT    -- GTFS route_id from the RT feed
stop_id                TEXT    -- GTFS stop_id from the StopTimeUpdate
stop_sequence          INTEGER -- Position of this stop within the trip
actual_arrival         TEXT    -- Predicted arrival time, ISO8601 UTC
                               --   e.g. "2026-05-20T14:32:00+00:00"
actual_arrival_pacific TEXT    -- Same time in Pacific, formatted
                               --   "YYYY-MM-DD HH:MM:SS"
delay_seconds          INTEGER -- Seconds late relative to the static
                               --   schedule (negative = early). Sourced
                               --   directly from GTFS-RT arrival.delay.
bus_id                 TEXT    -- Always NULL. Vehicle-position feed not
                               --   implemented. Do not flag as a quality issue.
timestamp              TEXT    -- UTC ISO8601 datetime of the fetch that
                               --   produced this prediction. Updated on
                               --   every upsert — reflects when the most
                               --   recent prediction was written.
PRIMARY KEY (trip_id, stop_id)
```

Indexes: `idx_sd_route (route_id)`, `idx_sd_trip (trip_id)`,
`idx_sd_ts (timestamp)`.

**Semantics of `delay_seconds`:** The TransLink RT feed publishes `arrival.delay`
as the number of seconds by which the predicted arrival deviates from the
scheduled arrival in the static GTFS. Positive = bus is late; negative = bus is
running early. Zero means on schedule.

**Semantics of the primary key:** because `(trip_id, stop_id)` is the PK, and
each 5-minute fetch upserts (never inserts a second row), this table retains
only the **last prediction** emitted for each (trip, stop) pair — i.e.,
the freshest estimate just before the bus physically passes that stop. Earlier
predictions for the same stop on the same trip are silently overwritten.

##### Table: `realtime_vehicle_positions`

Defined in the schema but **currently empty**. Intended for vehicle GPS
positions from the `https://gtfsapi.translink.ca/v3/gtfsposition` endpoint
(defined as `VEHICLE_URL` in config.py). Collection not yet implemented.

```
timestamp     TEXT
route_id      TEXT
trip_id       TEXT
stop_id       TEXT
latitude      REAL
longitude     REAL
bus_id        TEXT
vehicle_label TEXT
PRIMARY KEY (bus_id, timestamp)
```

##### Table: `collection_runs`

One row per invocation of `collect_realtime_v2.py`. Use this to detect
collection gaps.

```
run_id        INTEGER  PRIMARY KEY AUTOINCREMENT
started       TEXT     NOT NULL — UTC ISO8601, set at job start
finished      TEXT     — UTC ISO8601, set at job end (NULL if crashed)
rows_inserted INTEGER  — total rows passed to executemany (includes updates)
status        TEXT     — 'ok' or 'error'
```

##### Table: `processed_stops`

The analysis-ready table, rebuilt by `pipeline/process_delays.py`. Contains
every column from `stop_delays` plus static-join columns and derived features.
One row per (trip, stop) pair — same PK as `stop_delays`, same upsert
semantics (only the last prediction per stop is represented).

```
trip_id             TEXT    -- GTFS trip_id (date-specific; see §1.3)
route_id            TEXT    -- GTFS route_id
direction_id        INTEGER -- 0 or 1; from static trips table
stop_id             TEXT    -- GTFS stop_id
stop_sequence       INTEGER -- Stop position within the trip
stop_lat            REAL    -- WGS-84 latitude; from static stops table
stop_lon            REAL    -- WGS-84 longitude; from static stops table
delay_seconds       REAL    -- Same as stop_delays.delay_seconds (promoted
                            --   to REAL for modelling)
previous_stop_delay REAL    -- delay_seconds at the preceding stop on the
                            --   same trip (see §1.7 for exact definition)
shape_dist_traveled REAL    -- Distance along the trip shape at this stop,
                            --   normalized per trip (see §1.7)
hour                INTEGER -- Hour of day (0–23) in Pacific time
dow                 INTEGER -- Day of week: 0=Monday … 6=Sunday (pandas
                            --   convention; NOTE: R models recompute this
                            --   as 1–7 using wday(week_start=1) — see §1.7)
is_rush_hour        INTEGER -- 1 if hour ∈ {7,8,9,16,17,18}; else 0
is_weekend          INTEGER -- 1 if dow ∈ {5,6} (Sat, Sun); else 0
timestamp           TEXT    -- UTC ISO8601 from stop_delays.timestamp
PRIMARY KEY (trip_id, stop_id)
```

Indexes: `idx_ps_route (route_id)`, `idx_ps_dir (route_id, direction_id)`.

**Note on rebuilding:** `process_delays.py` with no date filter runs
`DELETE FROM processed_stops` before writing. With `--since` / `--until`
it appends (insert-or-replace via pandas `to_sql`). The standard refresh
workflow (`refresh_analysis.sh`) always runs a full delete-then-rebuild
from 2026-05-09.

---

#### `database/gtfs_static.db`

Rebuilt from scratch each time `process_static.py` runs (all four tables
are replaced via `to_sql(..., if_exists="replace")`). Contains the
TransLink schedule as of the most recent Saturday sync.

| Table | Source file | Primary key (inferred) | Columns used in cross-DB join |
|---|---|---|---|
| `stops` | stops.txt | `stop_id` | `stop_id`, `stop_lat`, `stop_lon` |
| `routes` | routes.txt | `route_id` | not joined in process_delays.py |
| `stop_times` | stop_times.txt | `(trip_id, stop_sequence)` | `trip_id`, `stop_id`, `stop_sequence`, `shape_dist_traveled` |
| `trips` | trips.txt | `trip_id` | `trip_id`, `direction_id` |

**Important:** `gtfs_static.db` has **no `shapes` table**. Spatial work must
use stop coordinates from the `stops` table, not route geometry from shapes.
This is a known limitation noted in CLAUDE.md.

The cross-DB join in `process_delays.py` attaches `gtfs_static.db` as
`static_db` and performs three LEFT JOINs: `stop_times` for
`shape_dist_traveled`, `trips` for `direction_id`, and `stops` for
coordinates. All are LEFT JOINs, so rows that fail to match (e.g., orphan
trip_ids during Saturday rollover) are retained with NULL in static-derived
columns, and will not appear in `processed_stops` after the join produces
NULL for the PK-constraining columns. See §1.5 for the rollover window.

---

### 1.3 GTFS Concepts for This Project

A **trip** in GTFS is a single complete run of a vehicle along a route on a
specific service date. It is not the route itself. The route "Bus 99 B-Line"
may run hundreds of trips per day; each has its own `trip_id`. Because
`trip_id` values encode the service date (TransLink follows the GTFS convention
of date-prefixed identifiers), the same physical route on different days
produces different `trip_ids`. This means historical data accumulates correctly
across days even though the `(trip_id, stop_id)` primary key is fixed — there
is no collision between yesterday's trip and today's.

A **TripUpdate** is a real-time prediction message published by TransLink at a
specific moment in time. It says: *"for trip X, which is currently active, here
are my best estimates of when the bus will arrive at each remaining stop."*
Because the bus is moving, each 5-minute fetch produces a fresh TripUpdate for
the same trip with updated predictions. The ON CONFLICT upsert therefore
overwrites older predictions; only the most recent one is kept per stop.

The consequence for analysis: **`stop_delays` does not store historical
prediction snapshots** — it stores only the final prediction for each
(trip, stop) pair. If a stop was published in 20 consecutive fetches as the bus
approached, only the 20th prediction survives. This is appropriate for a delay
propagation model (we want the prediction just before arrival) but means
time-series-of-predictions analysis is not possible from `stop_delays` alone.

---

### 1.4 Validation Rules

`pipeline/quality_report.py` queries `processed_stops` and produces a
structured text report saved to `exports/quality_report_YYYY-MM-DD.txt`.
It exits with code 1 on any hard failure. `refresh_analysis.sh` runs it
under `set -e`, so a hard failure halts the entire refresh before R sees bad data.

#### Section 1 — Collection Completeness

- Daily row counts are computed from `processed_stops`.
- **Sparse day definition:** a day where `n < 0.20 × median(daily counts)`.
  The 20 % threshold is `SPARSE_PCTILE = 0.20`.
- **Hard failure:** `processed_stops` is completely empty.
- **Warning (not hard failure):** total rows < 500,000 over a ≥ 7-day window
  (expected volume is ~1M+ rows for a full week of dense collection).
- Sparse days are flagged inline and collected into a summary warning.

#### Section 2 — Timestamp Gap Detection

- For each day, the maximum gap between consecutive `timestamp` values in
  `processed_stops` is computed using `LEAD()` within a per-day window.
- **Threshold:** gaps > **2 hours** (`MAX_GAP_HOURS = 2.0`) are flagged as
  possible Mac sleep events.
- **Note:** the quality report only flags the daily maximum gap, not every
  individual gap. A day can have multiple short gaps summing to significant
  missing time, yet report clean if no single gap exceeds 2 hours.

#### Section 3 — Field Integrity (NULL Rates)

Checked model columns: `delay_seconds`, `previous_stop_delay`,
`shape_dist_traveled`, `hour`, `dow`, `trip_id`, `stop_id`, `route_id`.

- **Warn threshold:** NULL rate > **1 %** (`NULL_RATE_WARN = 0.01`) for any
  checked column.
- `bus_id` is **not checked** — it is 100 % NULL by design (see §1.1).
- Additionally checks for **blank (empty string) `route_id`** — a separate
  issue from NULL, caused by API responses with missing route data.
- **GTFS join failure check:** `shape_dist_traveled` NULL rate > **10 %**
  (`GTFS_FAIL_WARN = 0.10`) triggers a specific GTFS-join warning, separate
  from the general NULL-rate check. This threshold reflects that some NULL is
  expected during the Saturday rollover orphan window.

As of the 2026-05-21 quality report (representative of the current data):

| Column | NULL rate |
|---|---|
| `delay_seconds` | 1.30 % |
| `previous_stop_delay` | 4.72 % (expected — first stop of each trip has no previous) |
| `shape_dist_traveled` | 5.65 % (GTFS join misses; within 10 % threshold) |
| `hour`, `dow`, `trip_id`, `stop_id`, `route_id` | 0.000 % |

#### Section 4 — Delay Distribution and Anomaly Detection

- **Outlier definition:** `|delay_seconds| > 3600` (one hour).
  This matches the filter applied in both R analysis scripts
  (`abs(delay_seconds) <= 3600`).
- **Anomaly day definition:** a day where the daily mean delay satisfies
  `|daily_mean − window_mean| > 2 × window_SD`, where `window_mean` and
  `window_SD` are computed across **all days in the query window** (not a
  rolling subwindow). The constant is `ANOMALY_SD = 2.0`.
- The R Rmd scripts apply the same dual criterion for exclusion: a day is
  anomalous if `n < 0.20 × median(daily_n)` OR
  `|mean_delay − overall_mean| > 2 × overall_sd`. Both Python and R use the
  same logic; the Python report is diagnostic, the R exclusion is applied
  during model fitting.

#### Section 5 — Route Coverage

- Reports total number of routes with any rows in `processed_stops`.
- Reports number of routes with **≥ 500 rows** — the minimum required for M3
  route-level random effects.
- Flags routes where `|mean filtered delay| > 300s` (after the 1-hour outlier
  filter). As of 2026-05-21: routes `39305` (mean 386s) and `29039` (mean 424s)
  exceeded this threshold and warrant investigation before including in M3 fits.

#### Section 6 — Stale Predictions

Queries `stop_delays` for rows where `actual_arrival < timestamp` — i.e.,
predictions that were still being broadcast after the predicted arrival time
had passed. These represent the RT feed continuing to include stale stop-time
entries for trips that have already served the stop.

- **Threshold:** > 5 % of rows with non-NULL `actual_arrival` (`STALE_WARN_PCT = 0.05`).
- **As of 2026-05-25:** 6.31 % (98,514 / 1,562,472 rows) — above threshold.
  This is a newly discovered baseline characteristic of the TransLink RT feed,
  not a pipeline bug. These rows are included in `processed_stops` and survive
  into model training unless explicitly filtered. The R Rmds do not currently
  filter on staleness. **Consider adding** `actual_arrival >= timestamp` as a
  filter in `export_route.py` before modelling, or treating `stale` as a
  covariate.

#### Section 7 — Stop-Sequence Integrity

Checks `stop_delays` for trips where `stop_sequence` is not strictly
increasing (non-monotone). The `previous_stop_delay` LAG computation in
`process_delays.py` partitions by `trip_id` and orders by `stop_sequence`,
so non-monotone sequences produce incorrect LAG values silently.

- **As of 2026-05-25:** 2,283 / 55,291 trips (4.1 %) have non-monotone
  `stop_sequence`. This means `previous_stop_delay` is wrong for ~4 % of the
  data. The cause is likely the RT feed re-sequencing stops when a vehicle
  changes its service pattern mid-run (e.g., short-turn, diversion). These
  trips should ideally be excluded from training. **Consider adding** a
  sequence-integrity filter in `process_delays.py`:
  ```sql
  -- Exclude trips with any repeated or reversed stop_sequence
  WHERE trip_id NOT IN (
      SELECT DISTINCT trip_id FROM stop_delays
      WHERE ... [non-monotone check] ...
  )
  ```

#### Known Gaps in Current Validation (not yet implemented)

The following are planned additions; their absence is not a data quality
problem, just a known gap in coverage:

- **No per-fetch pipeline gate:** validation is post-hoc (run manually or via
  `refresh_analysis.sh`), not real-time. Bad fetches are not rejected
  automatically.
- **No trip_id cross-reference at fetch time:** the collector does not check
  whether a `trip_id` exists in the current static schedule when inserting.
  Orphan rows (trip_ids not in the static DB) are inserted silently and only
  detected as NULL-valued rows after `process_delays.py` runs the join.
- **No static referential integrity check:** `quality_report.py` does not
  verify that `stop_id` values in `processed_stops` exist in `gtfs_static.db`.

---

### 1.5 Known Data Quality Windows

#### 1. Pre-validator period: 2026-05-09 to 2026-05-25

No real-time gate was active. Data has been retroactively validated by running
`quality_report.py --since 2026-05-09`. **Use with normal confidence for
training.** The known sparse days (2026-05-11 through 2026-05-14) are
automatically excluded by anomaly detection in both the quality report and R
analysis scripts.

Specific gap log for this period (from `exports/quality_report_2026-05-21.txt`):

| Day | Max gap | Note |
|---|---|---|
| 2026-05-09 | 10.4h | Intermittent collection, Mac sleep |
| 2026-05-10 | 2.3h | Mac sleep |
| 2026-05-11 | 3.1h | Sparse (1,467 rows) |
| 2026-05-12 | 5.1h | Sparse (375 rows) |
| 2026-05-13 | 3.8h | Sparse (1,161 rows) |
| 2026-05-14 | 4.0h | Sparse (1,646 rows) |
| 2026-05-15 | 0.25h | Clean |
| 2026-05-16 | 7.7h | One gap — collector not yet running at startup |
| 2026-05-17 onwards | < 1.1h | Dense, reliable |

From 2026-05-16 onwards the collector runs 24/7. 2026-05-09 to 2026-05-15 are
pre-dense and should be treated with lower per-day confidence, but their
anomaly days will be auto-excluded.

#### 2. Static rollover orphan window

Every Saturday ~10:00 AM Pacific, `sync_static_gtfs.py` downloads a new static
GTFS and rebuilds `gtfs_static.db`. For approximately 12–24 hours after
rollover, the RT feed may reference `trip_ids` from the *previous* week's
schedule that no longer exist in the updated static DB.

**Effect on the pipeline:** these orphan rows are inserted into `stop_delays`
by the collector (it does not check the static DB). When `process_delays.py`
runs the LEFT JOIN against `static_db.trips`, orphan trips produce NULL for
`direction_id`, `shape_dist_traveled`, `stop_lat`, and `stop_lon`. They are
included in `processed_stops` as NULL-padded rows but excluded from R
modelling by the `!is.na(shape_dist_traveled)` filter.

**How to identify a rollover date:** check `database/gtfs_static_meta.json`
for `last_modified` and `last_downloaded`. Current snapshot: `last_modified`
Friday 22 May 2026 21:35:35 GMT.

#### 3. Mac sleep gaps

See current gap log: `[see exports/quality_report_*.txt for current gap log]`.
New gaps appear whenever the Mac sleeps. Check `collection_runs` for any runs
where `finished` is NULL (crashed) or where consecutive `started` timestamps
are more than 10 minutes apart.

#### 4. 2026-05-23 sync crash

The launchd `com.translink.sync-static` job exited with code 1 on 2026-05-23.
The failure was caused by a stale error state from the previous week and
cleared automatically. The static DB was not corrupted. The snapshot at
`data/static/2026-05-23/` is valid. The `gtfs_static_meta.json` correctly
reflects the 22 May 2026 schedule.

---

### 1.6 FIFA 2026 Natural Experiment

BC Place, Vancouver hosts seven FIFA World Cup 2026 matches. These matches
constitute a planned **regime analysis window**: do TransLink bus delays spike
on match days, and if so, by how much and on which routes?

**Match schedule (all times Pacific):**

| Date | Day | Time PT | Match | Group |
|---|---|---|---|---|
| 2026-06-13 | Sat | 21:00 | Australia vs Türkiye | D |
| 2026-06-18 | Thu | 15:00 | Canada vs Qatar | B |
| 2026-06-21 | Sun | 18:00 | New Zealand vs Egypt | D |
| 2026-06-24 | Wed | 12:00 | Switzerland vs Canada | B |
| 2026-06-26 | Fri | 20:00 | New Zealand vs Belgium | D |
| 2026-07-02 | Thu | 20:00 | Round of 32 | — |
| 2026-07-07 | Tue | 13:00 | Round of 16 | — |

**TransLink service changes active June 8 – July 19:**

- **Route 130:** Detoured via McGill / Renfrew / East Hastings during the FIFA
  window. Treat `shape_dist_traveled` for Route 130 as **unreliable during
  this window** — the changed route geometry means the static-derived distances
  no longer describe the actual path. Either exclude Route 130 from FIFA-window
  fits or model it without `shape_dist_traveled`.
- **Routes 14, 19, 23, 28, 222:** Extra service frequency. Higher row counts
  on these routes during the FIFA window are expected and must **not** be
  flagged as anomalies by the row-count anomaly detector.

**Modelling note:** the FIFA window should be encoded as a **regime variable**,
not excluded from training. Two planned covariates (not yet in the pipeline):

- `match_day` (boolean): 1 on any of the seven match dates above, 0 otherwise.
- `hours_to_kickoff` (float): hours until the next kickoff on the same day;
  set to a large sentinel (e.g. 99.0) on non-match days.

These should be computed from the match dates above and joined at query time
in `export_route.py`. The join key is the date component of `timestamp`
(Pacific time). **These covariates do not yet exist in the pipeline** — they
are a planned addition before the Ralph loop begins fitting FIFA-window data.

---

### 1.7 Feature Definitions

All features below are columns in `processed_stops` that serve as model inputs.
All values are derived from the Python pipeline; the R Rmds may recompute some
(noted below).

---

#### `delay_seconds`

**Source:** `stop_delays.delay_seconds`, sourced from `stu.arrival.delay` in
the GTFS-RT protobuf (`StopTimeUpdate.StopTimeEvent.delay`).

**Definition:** the number of seconds by which the predicted arrival at this
stop deviates from the static scheduled arrival time. Positive = late; negative
= early; 0 = on schedule.

**Type in pipeline:** stored as `INTEGER` in `stop_delays`; promoted to `REAL`
in `processed_stops`.

**NULL meaning:** the RT feed did not include an `arrival.delay` field for this
stop (i.e., `stu.arrival.HasField("delay")` returned False). The R models
filter these out with `!is.na(delay_seconds)`.

---

#### `previous_stop_delay`

**Source:** computed in `process_delays.py` using a SQL window function:

```sql
LAG(sd.delay_seconds) OVER (
    PARTITION BY sd.trip_id ORDER BY sd.stop_sequence
) AS previous_stop_delay
```

**Definition:** the `delay_seconds` value at the stop immediately preceding
this stop on the same trip, ordered by `stop_sequence`. Represents how late
the bus was predicted to arrive at the stop just before the current one — the
key autoregressive input for delay propagation modelling.

**NULL meaning:** this is the first stop of the trip as seen in `stop_delays`
(i.e., there is no earlier stop with a lower `stop_sequence` for this
`trip_id`). This is expected for all first stops; ~4–5 % NULL rate is normal.

**Important caveat:** because `stop_delays` only retains the last prediction
per (trip, stop), and predictions are written at different fetch times, the
`previous_stop_delay` is the final prediction for the previous stop, not the
prediction that was current when the current stop's prediction was made. This
is a mild form of look-ahead that is acceptable for delay propagation modelling
but should be noted if computing causal counterfactuals.

---

#### `shape_dist_traveled`

**Source:** `static_db.stop_times.shape_dist_traveled` (the raw static GTFS
value), then **normalized per trip** in `_normalize_dist()`:

```python
df["shape_dist_traveled"] = df.groupby("trip_id")["shape_dist_traveled"].transform(
    lambda x: x - x.min()
)
```

**Definition after normalization:** distance along the trip's route shape from
the *first stop that appears in the RT feed for this trip* to the current stop.
The unit is whatever the TransLink static GTFS uses (meters, based on typical
GTFS convention). **This is not normalized to [0, 1]** — it is zero-shifted per
trip. The value 0.0 is the first-fetched stop; the maximum value is the total
distance from that stop to the last stop in the trip's RT feed.

**Why zero-shifted instead of [0, 1]?** `x - x.min()` anchors each trip at
zero regardless of where in the static schedule the trip started being reported.
It does not rescale to [0, 1] because the denominator would vary by trip length,
making the coefficient less interpretable across routes.

**NULL meaning:** the LEFT JOIN between `stop_delays` and `static_db.stop_times`
failed — this `(trip_id, stop_id, stop_sequence)` combination does not exist in
the current static schedule. Causes include: static rollover orphan window (see
§1.5), or a genuine mismatch between the RT and static feeds. Rows with NULL
`shape_dist_traveled` are excluded by the R models' `!is.na(shape_dist_traveled)`
filter. Currently ~5.65 % of rows are NULL (within the 10 % quality threshold).

**Route 130 caveat during FIFA window:** the detour changes the physical path
but may not update the static `shape_dist_traveled` values mid-week. Do not
use `shape_dist_traveled` for Route 130 between 2026-06-08 and 2026-07-19.

---

#### `hour`

**Source:** `_add_temporal()` in `process_delays.py`:

```python
ts = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True).dt.tz_convert(PACIFIC_TZ)
df["hour"] = ts.dt.hour
```

**Definition:** hour of day (0–23) in **America/Vancouver (Pacific) time**.
The conversion uses `pytz.timezone("America/Vancouver")` from `config.PACIFIC_TZ`,
which handles daylight saving time correctly.

**R behaviour:** `brms_analysis.Rmd` and `multi_route_analysis.Rmd` do **not**
recompute `hour` from `timestamp` — they use the value from the parquet directly.
The spline `s(hour, bs = "cc", k = 8)` is fitted with
`knots = list(hour = c(0, 24))` to enforce periodicity across midnight.

---

#### `dow`

**Source (Python):** `_add_temporal()`:

```python
df["dow"] = ts.dt.dayofweek   # 0=Monday … 6=Sunday  (pandas convention)
```

**Source (R — OVERWRITES the parquet value):** both Rmds recompute:

```r
dow = as.integer(wday(timestamp, week_start = 1L))
# Result: 1=Monday … 7=Sunday  (lubridate convention)
```

**⚠ Encoding mismatch:** the `dow` column in `processed_stops` / parquet files
is **0=Monday, 6=Sunday**. The `dow` used by the fitted brms models is
**1=Monday, 7=Sunday**, because the R code overwrites the Python value during
loading. Always refer to the R code's encoding when interpreting model
coefficients. The cyclic spline knots `list(dow = c(0.5, 7.5))` are set to
match the R 1–7 encoding.

---

#### `is_rush_hour`

**Source:**

```python
_RUSH_HOURS = set(range(7, 10)) | set(range(16, 19))  # {7,8,9,16,17,18}
df["is_rush_hour"] = ts.dt.hour.isin(_RUSH_HOURS).astype(int)
```

**Definition:** 1 if `hour` (Pacific) is in {7, 8, 9, 16, 17, 18}; 0 otherwise.
This covers the AM peak (07:00–09:59) and PM peak (16:00–18:59).
This binary feature is not currently used in any fitted model (M0–M3 use the
cyclic spline on `hour` instead), but it is available in `processed_stops`
as a potential future predictor or stratification variable.

---

#### `is_weekend`

**Source:**

```python
df["is_weekend"] = (ts.dt.dayofweek >= 5).astype(int)
```

**Definition:** 1 if `dow` (Python, 0=Monday) is 5 (Saturday) or 6 (Sunday);
0 otherwise. Like `is_rush_hour`, this binary feature is available in
`processed_stops` but not used in any fitted model — the cyclic spline on
`dow` captures within-week variation continuously.

---

#### Features NOT currently available

| Feature | Why absent | Path to availability |
|---|---|---|
| Bus speed between stops | Requires `VehiclePositions` feed — `gtfsposition` endpoint not collected | Implement `collect_realtime_v2.py` vehicle position collection; populate `realtime_vehicle_positions` |
| Headway to next/previous bus on same route | Not computed; would require grouping by route + time | Computable from existing `collection_runs` + `stop_delays` data as a future derived feature |
| Weather | Not collected | External data source required (e.g. Environment Canada hourly) |
| Passenger occupancy | Not in TransLink's GTFS-RT feed | Not available |
| `match_day` / `hours_to_kickoff` | FIFA regime covariates not yet implemented | Planned addition before Ralph loop; derive from §1.6 match schedule |

---

## Part 2: Model Baseline

> **Status: To be completed during the study period (June–July 2026) before
> the Ralph loop begins. The Ralph loop agent must read this section before
> proposing any model changes.**

### 2.1 Iteration 0 — Starting Model

The current baseline is **M3**, as defined in `analysis/multi_route_analysis.Rmd`.
This is distinct from the M3 preview sketched in `brms_analysis.Rmd` (which uses
a nested `(1 | route_id / trip_id) + (1 | stop_id)` structure). The **actual
fitted M3** uses only route-level random intercepts, fitted on a subsampled
multi-route dataset.

**brms formula (exact R syntax):**

```r
f_m3 <- bf(
  delay_seconds ~ previous_stop_delay + shape_dist_traveled +
    s(hour, bs = "cc", k = 8) +
    s(dow,  bs = "cc", k = 5) +
    (1 | route_id)
)
```

**Family:** `student()` — Student-t likelihood with estimated degrees of
freedom `nu`. Link function: identity.

**Priors (all four models share this block):**

```r
base_priors <- c(
  prior(normal(0, 2),    class = b),         # all fixed-effect slopes
  prior(normal(0, 10),   class = Intercept), # global intercept
  prior(exponential(1),  class = sigma),     # residual scale (seconds)
  prior(exponential(1),  class = sd),        # random-effect scale(s)
  prior(gamma(2, 0.1),   class = nu, lb = 2) # Student-t df; hard floor at 2
)
```

**Sampler settings:** `iter = 2000`, `warmup = 1000`, `chains = 4`, `seed = 42`,
`adapt_delta = 0.95`.

**Data subsampling for M3:** top 50 routes by observation count (≥ 500 rows
each), then 150 rows sampled per route. Total training input: ~7,500 rows.
Rationale: keeps NUTS feasible (~50 route random effects instead of ~6,700
trip-level effects).

**What the random effect represents in transit terms:** `(1 | route_id)` allows
each route to have a different baseline delay level after accounting for the
fixed effects. A large positive route intercept means that route is
systematically later than average (controlling for delay propagation, distance,
hour, and day of week). A near-zero route SD would mean all routes behave
similarly in their baseline delay.

**Most recent run (2026-05-20, from `exports/run_log.csv`):**

| Metric | Value |
|---|---|
| `b_previous_stop_delay` | 0.9969 [0.9944, 0.9996] |
| `sigma` (residual scale) | 20.18 s |
| `nu` (Student-t df) | 2.01 — near-Cauchy tails |
| `route_sd` (SD of route intercepts) | 0.74 s |
| R-hat max | 1.0065 |
| ESS min | 1,011 |
| Divergences | 56 / 4,000 draws (1.4 %) |
| MAE (temporal holdout) | 37.81 s |
| RMSE (temporal holdout) | 89.59 s |
| 90 % coverage | 85.84 % |
| Training rows | 3,608 (from 2026-05-09 to 2026-05-18) |
| Test rows | 3,892 |
| Routes in training | 50 |

**ELPD-LOO:** not yet recorded in `run_log.csv` — LOO is computed via
`add_criterion(m3, "loo")` inside the Rmd but not currently extracted into the
log. See `analysis/models/brms_m3_multiRoute.rds` for the stored model object;
run `loo(m3)` to retrieve the current LOO estimate.

This is the **baseline** all Ralph loop iterations are measured against.

---

### 2.2 Model Progression So Far — DO NOT RE-PROPOSE AS NOVEL

> The Ralph loop agent must not propose models from this list as if they were
> novel. These are already implemented and evaluated starting points.

All models use the Student-t family, the shared `base_priors` block above,
`iter = 2000 / warmup = 1000 / chains = 4 / seed = 42 / adapt_delta = 0.95`.

| Model | File | Formula summary | Key distinction |
|---|---|---|---|
| M0 | `brms_m0.rds` | `delay ~ prev + dist + factor(hour) + s(dow, cc, k=5) + (1\|trip_id)` | Baseline; 24 independent hour parameters |
| M1 | `brms_m1.rds` | same + `s(hour, cc, k=8)` replaces `factor(hour)` | Cyclic cubic spline for hour; forces smoothness and midnight periodicity |
| M2 | `brms_m2.rds` | M1 formula + `(1\|stop_id)` | Adds stop-level random intercepts; single route (6641 dir 0) |
| M3 | `brms_m3_multiRoute.rds` | M1 formula + `(1\|route_id)` | Route-level random intercepts; multi-route subsampled dataset |

**Why Student-t, not Gaussian:** delay distributions are heavy-tailed —
occasional extreme delays (incidents, traffic) are real and must not excessively
influence the fit. `nu ≈ 2.01` (near-Cauchy) confirms the tails are very heavy
and that the Gaussian would severely underfit the extremes. The Student-t
likelihood is well-motivated by the empirical distribution and the transit
operations literature.

**M2 (from run_log.csv, single-route run 2026-05-20):**
`b_prev ≈ 0.999`, `sigma ≈ 31.64 s`, `nu ≈ 2.06`, R-hat max 1.0096,
ESS min 620, divergences 34, MAE 63.88 s, RMSE 105.13 s, 90 % coverage 78.27 %.

---

### 2.3 Open Research Directions

> [PLACEHOLDER — to be filled during the June–July 2026 study period, before
> the Ralph loop begins. Each entry should record: hypothesis, what data it
> requires, and why it has not been tried yet.]

Candidate directions (not yet attempted; add detail during study period):

- **Headway to next/previous bus on same route:** computable from existing
  `stop_delays` data; requires grouping by `(route_id, stop_id)` and computing
  time between consecutive `timestamp` values. Hypothesis: bunching (short
  headway to the bus ahead) amplifies delay propagation.
- **`match_day` / `hours_to_kickoff` regime variable:** FIFA window natural
  experiment; see §1.6. Requires implementing the covariate in `export_route.py`
  before fitting.
- **Network upstream delay term:** average delay across all trips on the same
  route in the previous 30 minutes. Requires graph construction over `stop_delays`.
  Hypothesis: captures network-wide congestion signals beyond what a single
  trip's previous stop delay provides.
- **Varying slopes on `hour` by route:** `s(hour, bs="cc") + (hour | route_id)`
  or a route-specific smooth. Hypothesis: peak-hour delay profiles differ
  substantially by route (e.g., express vs local).
- **Bimodal / mixture likelihood:** Gaussian mixture separating "on-time"
  and "bunched" regimes. Hypothesis: the heavy `nu` reflects genuine bimodality
  rather than a single heavy-tailed distribution.
- **Trip-level random effects in M3:** the current M3 drops trip-level
  grouping. Adding `(1 | route_id / trip_id)` nests trips within routes.
  This was the M3 design previewed in `brms_analysis.Rmd` but not implemented
  in `multi_route_analysis.Rmd`. Requires careful assessment of the added
  random-effect dimensions vs. NUTS feasibility.

---

## Part 3: Ralph Loop Iteration Log

> **Instructions for the Ralph loop agent:**
> After each iteration, append one entry to this section using exactly the
> format below. Do not modify previous entries. Do not summarise or abbreviate
> — write the full entry.
>
> The ELPD value to record is the `elpd_loo` estimate from `loo(model)$estimates`.
> Report it as the point estimate ± SE (e.g. "-12345.6 ± 23.1").
> If LOO fails (Pareto-k > 0.7 on > 10 % of observations), record that and
> use WAIC as a fallback, noting the substitution.

Format for each entry:

```
### Iteration N — YYYY-MM-DD

**Change from previous:** [one sentence describing what was modified]
**Hypothesis:** [why this change was expected to help]
**ELPD:** [previous value] → [new value] ([delta])
**R-hat max:** [value]  **Divergences:** [value]
**ESS bulk min:** [value]  **ESS tail min:** [value]
**Pareto-k >0.7:** [count] observations
**Decision:** KEPT / REVERTED
**If reverted:** [one sentence on why — sampler issue, ELPD degraded, etc.]
**Next hypothesis:** [what this result suggests to try next]
```

---

[No entries yet — Ralph loop not started]
