# Database schema

Two SQLite databases live in `database/` (gitignored). Schemas below were introspected
from the live files on 2026-06-10. All paths come from `pipeline/config.py`
(`DB_STATIC`, `DB_REALTIME`).

| Database | File | Written by |
|---|---|---|
| Static GTFS | `database/gtfs_static.db` | `pipeline/process_static.py` (refreshed weekly by `sync_static_gtfs.py`) |
| Realtime v2 | `database/gtfs_realtime_v2.db` | `pipeline/create_tables_v2.py` (DDL), `collect_realtime_v2.py`, `process_delays.py` |

A legacy `gtfs_realtime.db` (v1, `DB_REALTIME_LEGACY` in config) may exist on older
machines; it is read-only historical data and is not used by any current script.

---

## gtfs_static.db

Loaded from the TransLink static GTFS feed by `process_static.py` (pandas `to_sql`,
hence the TEXT/INTEGER/REAL affinity quirks — empty GTFS columns import as REAL NaN).
**There is no `shapes` table** — use `stops.stop_lat`/`stop_lon` for spatial work.

### routes (246 rows)

| Column | Type | Notes |
|---|---|---|
| route_id | TEXT | PK in GTFS terms (no SQLite constraint) |
| route_short_name | TEXT | e.g. "99" |
| route_long_name | TEXT | |
| route_type | INTEGER | GTFS route type (3 = bus) |
| route_color / route_text_color | TEXT | |
| agency_id | TEXT | |
| route_url | TEXT | |
| route_desc | REAL | empty in feed (NaN) |

### stops (8,952 rows)

| Column | Type | Notes |
|---|---|---|
| stop_id | TEXT | join key; indexed (`idx_stops_stop`) |
| stop_code | REAL | public-facing 5-digit code |
| stop_name | TEXT | |
| stop_lat / stop_lon | REAL | only spatial coordinates available |
| zone_id | TEXT | |
| location_type | INTEGER | |
| wheelchair_boarding | INTEGER | |
| parent_station, stop_desc, stop_url | REAL/TEXT | mostly empty |

### trips (134,661 rows)

| Column | Type | Notes |
|---|---|---|
| trip_id | INTEGER | join key; indexed (`idx_trips_trip`) |
| route_id | TEXT | |
| service_id | TEXT | calendar key |
| direction_id | INTEGER | 0/1 |
| trip_headsign | TEXT | |
| block_id | TEXT | |
| shape_id | INTEGER | shape geometry NOT imported |
| wheelchair_accessible, bikes_allowed | INTEGER | |
| trip_short_name | REAL | empty |

### stop_times (3,762,067 rows)

| Column | Type | Notes |
|---|---|---|
| trip_id | INTEGER | composite index (`idx_st_trip_stop_seq` on trip_id, stop_id, stop_sequence) |
| stop_id | INTEGER | note: INTEGER here vs TEXT in `stops` — cast when joining |
| stop_sequence | INTEGER | |
| arrival_time / departure_time | TEXT | "HH:MM:SS", can exceed 24:00 per GTFS spec |
| shape_dist_traveled | REAL | distance along route; used as spatial covariate in m1+ |
| timepoint | INTEGER | |
| pickup_type, drop_off_type, stop_headsign | REAL | mostly empty |

---

## gtfs_realtime_v2.db

DDL owned by `create_tables_v2.py`. The collector (`collect_realtime_v2.py`, launchd
every 5 min) appends to `stop_delays` and logs to `collection_runs`;
`process_delays.py` rebuilds `processed_stops` (safe to truncate and reprocess).
Row counts below are as of 2026-06-10 and grow continuously.

### collection_runs (~8,000 rows)

One row per collector invocation — the health log for the launchd job.

| Column | Type | Notes |
|---|---|---|
| run_id | INTEGER | PK AUTOINCREMENT |
| started / finished | TEXT | UTC ISO timestamps |
| rows_inserted | INTEGER | rows written this run |
| net_new_rows | INTEGER | after PK dedup (added later via ALTER) |
| status | TEXT | 'ok' \| 'error' |

### stop_delays (~3.9M rows, 2026-04-26 → present)

Raw arrival observations from the GTFS-RT trip updates feed.

| Column | Type | Notes |
|---|---|---|
| trip_id | TEXT | PK part; indexed (`idx_sd_trip`) |
| stop_id | TEXT | PK part |
| service_date | TEXT | PK part; indexed (`idx_sd_svcdate`) |
| route_id | TEXT | indexed (`idx_sd_route`) |
| stop_sequence | INTEGER | |
| actual_arrival | TEXT | UTC |
| actual_arrival_pacific | TEXT | America/Vancouver |
| delay_seconds | INTEGER | observed − scheduled |
| bus_id | TEXT | vehicle identifier |
| timestamp | TEXT | DEFAULT CURRENT_TIMESTAMP; indexed (`idx_sd_ts`) |

PK `(trip_id, stop_id, service_date)` makes re-collection idempotent — the same
trip/stop/day observation upserts rather than duplicates.

### processed_stops (~3.0M rows)

Model-ready feature table built by `process_delays.py` by joining `stop_delays`
against the static DB. Rebuilt, not appended — truncate-and-reprocess is safe.

| Column | Type | Notes |
|---|---|---|
| trip_id, stop_id, service_date | TEXT | PK (same idempotency as stop_delays) |
| route_id | TEXT | indexed (`idx_ps_route`) |
| direction_id | INTEGER | composite index (`idx_ps_dir` on route_id, direction_id) |
| stop_sequence | INTEGER | |
| stop_lat / stop_lon | REAL | joined from static `stops` |
| delay_seconds | REAL | response variable |
| previous_stop_delay | REAL | key predictor (delay propagation) |
| shape_dist_traveled | REAL | joined from static `stop_times` |
| hour, dow | INTEGER | local-time features |
| is_rush_hour, is_weekend | INTEGER | 0/1 flags |
| timestamp | TEXT | indexed (`idx_ps_ts`) |

### realtime_vehicle_positions (0 rows)

Created by the v2 DDL for the vehicle-positions feed but **currently unpopulated** —
the v2 collector only consumes the trip-updates feed.

| Column | Type | Notes |
|---|---|---|
| bus_id, timestamp | TEXT | composite PK |
| route_id, trip_id, stop_id | TEXT | |
| latitude / longitude | REAL | |
| vehicle_label | TEXT | |
