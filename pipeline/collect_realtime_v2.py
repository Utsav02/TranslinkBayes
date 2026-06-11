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

from config import API_KEY, DB_REALTIME, LOG_DIR, PACIFIC_TZ, TRIP_UPDATES_URL

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
        # bus_id: populated only if vehicle-position collection is added later.
        # realtime_vehicle_positions is currently unpopulated — skip the query.
        bus_id   = None

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
    return len(rows), after - before  # (total_processed, net_new_trips)


if __name__ == "__main__":
    logging.info("collect_realtime_v2 started")
    conn = sqlite3.connect(DB_REALTIME)
    conn.execute("PRAGMA journal_mode=WAL")
    run_id = _start_run(conn)
    try:
        n, net_new = collect(conn)
        _finish_run(conn, run_id, n, net_new, "ok")
        logging.info("Inserted/updated %d rows, %d net-new (run_id=%d)", n, net_new, run_id)
    except Exception as exc:
        _finish_run(conn, run_id, 0, 0, "error")
        logging.exception("Run failed: %s", exc)
        raise
    finally:
        conn.close()
    logging.info("collect_realtime_v2 finished")
