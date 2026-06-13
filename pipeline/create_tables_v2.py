"""
Creates the v2 realtime database schema.
Run once before starting new data collection, or re-run on an existing DB
to apply schema migrations (all DDL is idempotent or guarded).
Old gtfs_realtime.db is never touched.
"""
import sqlite3
from config import DB_REALTIME, LOG_DIR

LOG_DIR.mkdir(exist_ok=True)

conn = sqlite3.connect(DB_REALTIME)
conn.execute("PRAGMA journal_mode=WAL")

conn.executescript("""
CREATE TABLE IF NOT EXISTS stop_delays (
    trip_id                TEXT,
    route_id               TEXT,
    stop_id                TEXT,
    stop_sequence          INTEGER,
    actual_arrival         TEXT,
    actual_arrival_pacific TEXT,
    delay_seconds          INTEGER,
    bus_id                 TEXT,
    timestamp              TEXT DEFAULT CURRENT_TIMESTAMP,
    service_date           TEXT,
    PRIMARY KEY (trip_id, stop_id, service_date)
);

CREATE INDEX IF NOT EXISTS idx_sd_route    ON stop_delays (route_id);
CREATE INDEX IF NOT EXISTS idx_sd_trip     ON stop_delays (trip_id);
CREATE INDEX IF NOT EXISTS idx_sd_ts       ON stop_delays (timestamp);

-- Append-only prediction-snapshot log (added 2026-06-12, pre-FIFA).
-- stop_delays UPSERTS — it keeps only the LAST snapshot per (trip,stop,date),
-- so the prediction trajectory (and the post-arrival "settled" value vs an
-- early forecast) is overwritten and unrecoverable. This table keeps EVERY
-- 5-minute snapshot, so fixed-horizon evaluation and the C1 validity probe
-- (docs/model_loop_spec.md) are possible on FIFA-window data.
--   * Purely additive: no existing table or consumer is touched.
--   * timestamp is in the PK, so each fetch appends rather than overwrites.
--   * Growth ≈ 4.6× stop_delays (~3M rows/dense day, ~100M over the FIFA
--     window). See docs note on retention if disk becomes a concern.
CREATE TABLE IF NOT EXISTS stop_delays_snapshots (
    trip_id                TEXT,
    route_id               TEXT,
    stop_id                TEXT,
    stop_sequence          INTEGER,
    actual_arrival         TEXT,
    actual_arrival_pacific TEXT,
    delay_seconds          INTEGER,
    bus_id                 TEXT,
    timestamp              TEXT,
    service_date           TEXT,
    PRIMARY KEY (trip_id, stop_id, service_date, timestamp)
);

CREATE INDEX IF NOT EXISTS idx_snap_traj  ON stop_delays_snapshots (trip_id, stop_id, service_date);
CREATE INDEX IF NOT EXISTS idx_snap_route ON stop_delays_snapshots (route_id);
CREATE INDEX IF NOT EXISTS idx_snap_svc   ON stop_delays_snapshots (service_date);

CREATE TABLE IF NOT EXISTS realtime_vehicle_positions (
    timestamp     TEXT,
    route_id      TEXT,
    trip_id       TEXT,
    stop_id       TEXT,
    latitude      REAL,
    longitude     REAL,
    bus_id        TEXT,
    vehicle_label TEXT,
    PRIMARY KEY (bus_id, timestamp)
);

CREATE TABLE IF NOT EXISTS collection_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started       TEXT    NOT NULL,
    finished      TEXT,
    rows_inserted INTEGER,  -- total rows passed to executemany (inserts + updates)
    net_new_rows  INTEGER,  -- net increase in stop_delays row count (new trips only)
    status        TEXT      -- 'ok' | 'error'
);

CREATE TABLE IF NOT EXISTS processed_stops (
    trip_id             TEXT,
    route_id            TEXT,
    direction_id        INTEGER,
    stop_id             TEXT,
    stop_sequence       INTEGER,
    stop_lat            REAL,
    stop_lon            REAL,
    delay_seconds       REAL,
    previous_stop_delay REAL,
    shape_dist_traveled REAL,
    hour                INTEGER,
    dow                 INTEGER,
    is_rush_hour        INTEGER,
    is_weekend          INTEGER,
    timestamp           TEXT,
    service_date        TEXT,
    PRIMARY KEY (trip_id, stop_id, service_date)
);

CREATE INDEX IF NOT EXISTS idx_ps_route ON processed_stops (route_id);
CREATE INDEX IF NOT EXISTS idx_ps_dir   ON processed_stops (route_id, direction_id);
CREATE INDEX IF NOT EXISTS idx_ps_ts    ON processed_stops (timestamp);
""")

conn.commit()

# ── Migrations for existing databases ────────────────────────────────────────
applied = 0

# Migration 1: net_new_rows column
try:
    conn.execute("ALTER TABLE collection_runs ADD COLUMN net_new_rows INTEGER")
    conn.commit()
    applied += 1
except sqlite3.OperationalError:
    pass

# Migration 2: add service_date to stop_delays PRIMARY KEY.
# SQLite cannot ALTER a PRIMARY KEY, so recreate the table.
# The new key (trip_id, stop_id, service_date) preserves one row per stop per
# service day; the old key (trip_id, stop_id) was silently overwriting history
# when the same trip_id recurred on a later date.
sd_cols = {r[1] for r in conn.execute("PRAGMA table_info(stop_delays)")}
if "service_date" not in sd_cols:
    conn.executescript("""
        CREATE TABLE stop_delays_new (
            trip_id                TEXT,
            route_id               TEXT,
            stop_id                TEXT,
            stop_sequence          INTEGER,
            actual_arrival         TEXT,
            actual_arrival_pacific TEXT,
            delay_seconds          INTEGER,
            bus_id                 TEXT,
            timestamp              TEXT DEFAULT CURRENT_TIMESTAMP,
            service_date           TEXT,
            PRIMARY KEY (trip_id, stop_id, service_date)
        );
        INSERT OR IGNORE INTO stop_delays_new
            SELECT trip_id, route_id, stop_id, stop_sequence,
                   actual_arrival, actual_arrival_pacific, delay_seconds,
                   bus_id, timestamp,
                   COALESCE(date(actual_arrival_pacific), date(timestamp)) AS service_date
            FROM stop_delays;
        DROP TABLE stop_delays;
        ALTER TABLE stop_delays_new RENAME TO stop_delays;
        CREATE INDEX IF NOT EXISTS idx_sd_route   ON stop_delays (route_id);
        CREATE INDEX IF NOT EXISTS idx_sd_trip    ON stop_delays (trip_id);
        CREATE INDEX IF NOT EXISTS idx_sd_ts      ON stop_delays (timestamp);
        CREATE INDEX IF NOT EXISTS idx_sd_svcdate ON stop_delays (service_date);
    """)
    conn.commit()
    applied += 1
    print("  Migrated stop_delays → PRIMARY KEY (trip_id, stop_id, service_date)")

# Migration 3: add service_date to processed_stops PRIMARY KEY.
# processed_stops is always rebuilt by process_delays.py so data loss is fine —
# just drop and recreate with the new schema.
ps_cols = {r[1] for r in conn.execute("PRAGMA table_info(processed_stops)")}
if "service_date" not in ps_cols:
    conn.executescript("""
        DROP TABLE IF EXISTS processed_stops;
        CREATE TABLE processed_stops (
            trip_id             TEXT,
            route_id            TEXT,
            direction_id        INTEGER,
            stop_id             TEXT,
            stop_sequence       INTEGER,
            stop_lat            REAL,
            stop_lon            REAL,
            delay_seconds       REAL,
            previous_stop_delay REAL,
            shape_dist_traveled REAL,
            hour                INTEGER,
            dow                 INTEGER,
            is_rush_hour        INTEGER,
            is_weekend          INTEGER,
            timestamp           TEXT,
            service_date        TEXT,
            PRIMARY KEY (trip_id, stop_id, service_date)
        );
        CREATE INDEX IF NOT EXISTS idx_ps_route   ON processed_stops (route_id);
        CREATE INDEX IF NOT EXISTS idx_ps_dir     ON processed_stops (route_id, direction_id);
        CREATE INDEX IF NOT EXISTS idx_ps_ts      ON processed_stops (timestamp);
        CREATE INDEX IF NOT EXISTS idx_ps_svcdate ON processed_stops (service_date);
    """)
    conn.commit()
    applied += 1
    print("  Recreated processed_stops → PRIMARY KEY (trip_id, stop_id, service_date)")

conn.close()
print(f"Schema created/verified: {DB_REALTIME}  ({applied} migration(s) applied)")
