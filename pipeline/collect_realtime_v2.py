"""
Collects GTFS Realtime trip updates from TransLink API into gtfs_realtime_v2.db.
Designed to be run every 5 minutes via launchd or cron.
"""
import logging
import sqlite3
import warnings
from datetime import datetime, timezone

import pytz
import requests
from google.transit import gtfs_realtime_pb2

from config import API_KEY, DB_REALTIME, LOG_DIR, PACIFIC_TZ, TRIP_UPDATES_URL, VEHICLE_URL

warnings.filterwarnings("ignore", category=DeprecationWarning)

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "collect_realtime_v2.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_pacific = pytz.timezone(PACIFIC_TZ)


def _to_pacific(utc_dt: datetime) -> str:
    return utc_dt.astimezone(_pacific).strftime("%Y-%m-%d %H:%M:%S")


# Append-only snapshot log. CREATE IF NOT EXISTS here too (not only in
# create_tables_v2.py) so deploying the new collector needs no separate
# migration step — the first run materializes the table on an existing DB.
_SNAPSHOT_DDL = """
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
"""


def _ensure_snapshot_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_SNAPSHOT_DDL)
    conn.commit()


def _start_run(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO collection_runs (started, status) VALUES (?, 'running')",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    return cur.lastrowid


def _finish_run(conn: sqlite3.Connection, run_id: int, rows: int, net_new: int, status: str) -> None:
    conn.execute(
        "UPDATE collection_runs SET finished=?, rows_inserted=?, net_new_rows=?, status=? WHERE run_id=?",
        (datetime.now(timezone.utc).isoformat(), rows, net_new, status, run_id),
    )
    conn.commit()


def _fetch(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.content
    except requests.RequestException as e:
        logging.error("Fetch failed: %s", e)
        return None


def collect(conn: sqlite3.Connection) -> int:
    data = _fetch(TRIP_UPDATES_URL)
    if not data:
        return 0, 0

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(data)

    rows = []
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        tu       = entity.trip_update
        trip_id  = tu.trip.trip_id
        route_id = tu.trip.route_id
        # bus_id: TransLink's trip-updates feed carries a VehicleDescriptor for
        # ~84% of trip-updates entities (verified 2026-07-09). Extract it here;
        # 100%-NULL bus_id was blocking per-vehicle random effects, bunching,
        # block-continuity features, etc. Empty-string → None so the SQLite
        # column reads as NULL for the ~16% of trips without vehicle info.
        # (The separate gtfsposition endpoint is currently returning an empty
        # feed — TransLink hasn't been publishing GPS positions during the
        # setup of this project; if/when they do, `collect_vehicle_positions`
        # picks that up independently.)
        bus_id = tu.vehicle.id if tu.HasField("vehicle") and tu.vehicle.id else None

        for stu in tu.stop_time_update:
            arr_utc = (
                datetime.fromtimestamp(stu.arrival.time, timezone.utc)
                if stu.arrival.time
                else None
            )
            # service_date: Pacific calendar date the trip is running.
            # Using the predicted arrival time keeps the date correct for
            # overnight trips; falls back to current Pacific date if no arrival.
            svc_dt = arr_utc if arr_utc else datetime.now(timezone.utc)
            service_date = _to_pacific(svc_dt)[:10]
            rows.append((
                trip_id,
                route_id,
                stu.stop_id,
                stu.stop_sequence,
                arr_utc.isoformat() if arr_utc else None,
                _to_pacific(arr_utc) if arr_utc else None,
                stu.arrival.delay if stu.arrival.HasField("delay") else None,
                bus_id,
                datetime.now(timezone.utc).isoformat(),
                service_date,
            ))

    before = conn.execute("SELECT COUNT(*) FROM stop_delays").fetchone()[0]
    conn.executemany(
        """
        INSERT INTO stop_delays (
            trip_id, route_id, stop_id, stop_sequence,
            actual_arrival, actual_arrival_pacific, delay_seconds, bus_id,
            timestamp, service_date
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(trip_id, stop_id, service_date) DO UPDATE SET
            actual_arrival         = excluded.actual_arrival,
            actual_arrival_pacific = excluded.actual_arrival_pacific,
            delay_seconds          = excluded.delay_seconds,
            bus_id                 = excluded.bus_id,
            timestamp              = excluded.timestamp
        """,
        rows,
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM stop_delays").fetchone()[0]

    # Append every snapshot to the immutable log (best-effort: a failure here
    # must NEVER break the primary upsert above, which already committed).
    # timestamp is per-row and carries microseconds, so each fetch appends new
    # rows rather than colliding with a prior fetch; OR IGNORE guards the rare
    # within-fetch duplicate (branching topology, identical microsecond stamp).
    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO stop_delays_snapshots (
                trip_id, route_id, stop_id, stop_sequence,
                actual_arrival, actual_arrival_pacific, delay_seconds, bus_id,
                timestamp, service_date
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
    except sqlite3.Error as exc:
        logging.error("Snapshot log insert failed (non-fatal, upsert succeeded): %s", exc)

    return len(rows), after - before  # (total_processed, net_new_trips)


# ── VehiclePositions collection ──────────────────────────────────────────────
# Added 2026-07-09. TransLink's gtfsposition feed publishes bus GPS positions
# every ~5 min, keyed by bus_id + timestamp. Populates realtime_vehicle_positions
# (schema in create_tables_v2.py) so downstream analysis can (a) recover TRUE
# arrival times by spatial-joining bus positions to stop coordinates, breaking
# the "prediction = observation" tautology, and (b) get bus_id (currently 100%
# NULL in stop_delays), unlocking per-vehicle random effects and bunching /
# headway derivations. Kept in a SEPARATE function so its failure NEVER kills
# the trip-updates collection above — the two feeds are independent and the
# trip-updates path is the more critical of the two.

def parse_vehicle_positions(pb_bytes: bytes, now_utc: datetime | None = None) -> list[tuple]:
    """Parse a GTFS-RT VehiclePositions payload into a list of rows for
    realtime_vehicle_positions. Pure function — no I/O — for testability.

    now_utc: injected so tests can fix the fallback timestamp deterministically.

    Row shape: (timestamp, route_id, trip_id, stop_id, latitude, longitude,
                bus_id, vehicle_label). Rows missing bus_id are DROPPED because
    the table's primary key is (bus_id, timestamp) and there is no meaningful
    identifier to fall back on.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(pb_bytes)

    rows: list[tuple] = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        bus_id = v.vehicle.id if v.HasField("vehicle") else ""
        if not bus_id:
            # No PK → cannot store. Skip.
            continue

        # Prefer the feed's own timestamp (bus reported time); fall back to
        # collector time so the row always has SOMETHING to key on.
        if v.timestamp:
            ts = datetime.fromtimestamp(v.timestamp, timezone.utc).isoformat()
        else:
            ts = now_utc.isoformat()

        rows.append((
            ts,
            v.trip.route_id if v.HasField("trip") else None,
            v.trip.trip_id  if v.HasField("trip") else None,
            v.stop_id       if v.stop_id         else None,
            v.position.latitude  if v.HasField("position") else None,
            v.position.longitude if v.HasField("position") else None,
            bus_id,
            v.vehicle.label if v.vehicle.label else None,
        ))
    return rows


def collect_vehicle_positions(conn: sqlite3.Connection) -> int:
    """Fetch the vehicle-positions feed and INSERT OR IGNORE into
    realtime_vehicle_positions. Returns rows inserted (best-effort — a fetch
    failure returns 0 rather than raising, so the trip-updates run still
    reports 'ok' in collection_runs).
    """
    data = _fetch(VEHICLE_URL)
    if not data:
        logging.warning("Vehicle-positions fetch returned no data; skipping insert")
        return 0
    try:
        rows = parse_vehicle_positions(data)
    except Exception as exc:
        logging.exception("Vehicle-positions parse failed: %s", exc)
        return 0
    if not rows:
        logging.info("Vehicle-positions parse yielded 0 rows (unusual — check feed)")
        return 0
    try:
        conn.executemany(
            """
            INSERT OR IGNORE INTO realtime_vehicle_positions
                (timestamp, route_id, trip_id, stop_id, latitude, longitude,
                 bus_id, vehicle_label)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            rows,
        )
        conn.commit()
    except sqlite3.Error as exc:
        logging.error("Vehicle-positions insert failed (non-fatal): %s", exc)
        return 0
    logging.info("Vehicle-positions: inserted/ignored %d rows", len(rows))
    return len(rows)


if __name__ == "__main__":
    logging.info("collect_realtime_v2 started")
    conn = sqlite3.connect(DB_REALTIME)
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_snapshot_table(conn)
    run_id = _start_run(conn)
    try:
        n, net_new = collect(conn)
        _finish_run(conn, run_id, n, net_new, "ok")
        logging.info("Inserted/updated %d rows, %d net-new (run_id=%d)", n, net_new, run_id)
    except Exception as exc:
        _finish_run(conn, run_id, 0, 0, "error")
        logging.exception("Run failed: %s", exc)
        raise

    # Vehicle-positions collection is INDEPENDENT of the trip-updates path above.
    # It runs after the primary run has been committed and marked 'ok', and its
    # exceptions are swallowed at the function boundary — so a broken vehicle
    # feed can never mark the whole collection run as errored. The tradeoff:
    # vehicle-position failures are silent to `collection_runs.status` but
    # visible in logs.
    try:
        collect_vehicle_positions(conn)
    except Exception as exc:
        logging.exception("Vehicle-positions collection swallowed exception: %s", exc)
    finally:
        conn.close()
    logging.info("collect_realtime_v2 finished")
