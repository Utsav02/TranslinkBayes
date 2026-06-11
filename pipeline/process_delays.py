"""
Post-processing layer: joins raw stop_delays with static GTFS, computes
previous_stop_delay via SQL window function, adds temporal features,
and writes to processed_stops.

Safe to re-run — fully overwrites processed_stops from raw data.

Usage:
    python process_delays.py
    python process_delays.py --since 2025-03-01
    python process_delays.py --since 2025-03-01 --until 2025-04-01
"""
import argparse
import logging
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from config import DB_REALTIME, DB_STATIC, LOG_DIR, PACIFIC_TZ

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "process_delays.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# SQLite syntax: LAG over trip ordered by stop_sequence gives previous stop's delay.
# ATTACH lets us join across the two databases in a single query.
_QUERY = """
SELECT
    sd.trip_id,
    sd.route_id,
    sd.stop_id,
    sd.stop_sequence,
    sd.delay_seconds,
    sd.bus_id,
    sd.timestamp,
    sd.service_date,
    LAG(sd.delay_seconds) OVER (
        PARTITION BY sd.trip_id, sd.service_date
        ORDER BY sd.stop_sequence, sd.actual_arrival
    )                              AS previous_stop_delay,
    st.shape_dist_traveled,
    t.direction_id,
    s.stop_lat,
    s.stop_lon
FROM main.stop_delays sd
LEFT JOIN static_db.stop_times st
       ON sd.trip_id       = st.trip_id
      AND sd.stop_id        = st.stop_id
      AND sd.stop_sequence  = st.stop_sequence
LEFT JOIN static_db.trips t  ON sd.trip_id = t.trip_id
LEFT JOIN static_db.stops s  ON sd.stop_id  = s.stop_id
{where}
ORDER BY sd.trip_id, sd.service_date, sd.stop_sequence
"""

_RUSH_HOURS = set(range(7, 10)) | set(range(16, 19))  # 7-9, 16-18 inclusive


def _add_temporal(df: pd.DataFrame) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp"], format="ISO8601", utc=True).dt.tz_convert(PACIFIC_TZ)
    df["hour"]        = ts.dt.hour
    df["dow"]         = ts.dt.dayofweek          # 0=Mon, 6=Sun
    df["is_rush_hour"] = ts.dt.hour.isin(_RUSH_HOURS).astype(int)
    df["is_weekend"]   = (ts.dt.dayofweek >= 5).astype(int)
    return df


def _normalize_dist(df: pd.DataFrame) -> pd.DataFrame:
    df["shape_dist_traveled"] = df.groupby("trip_id")["shape_dist_traveled"].transform(
        lambda x: x - x.min()
    )
    return df


def process(since: str | None = None, until: str | None = None) -> int:
    clauses = []
    if since:
        clauses.append(f"sd.service_date >= '{since}'")
    if until:
        clauses.append(f"sd.service_date < '{until}'")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    conn = sqlite3.connect(DB_REALTIME)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"ATTACH DATABASE '{DB_STATIC}' AS static_db")

    logging.info("Running extraction query (since=%s, until=%s)", since, until)
    df = pd.read_sql_query(_QUERY.format(where=where), conn)
    logging.info("Extracted %d raw rows", len(df))

    df = _add_temporal(df)
    df = _normalize_dist(df)

    out = df[[
        "trip_id", "route_id", "direction_id", "stop_id", "stop_sequence",
        "stop_lat", "stop_lon", "delay_seconds", "previous_stop_delay",
        "shape_dist_traveled", "hour", "dow", "is_rush_hour", "is_weekend",
        "timestamp", "service_date",
    ]]

    # Deduplicate: stop_times JOIN can produce multiple rows per
    # (trip_id, stop_id, service_date) for branching/loop routes.
    # Sort so rows with shape_dist_traveled come first, then keep first.
    before_dedup = len(out)
    out = (out
           .sort_values("shape_dist_traveled", na_position="last")
           .drop_duplicates(subset=["trip_id", "stop_id", "service_date"], keep="first"))
    if len(out) < before_dedup:
        logging.info("Deduped %d → %d rows", before_dedup, len(out))

    # Clear the date window being (re)processed, then insert fresh.
    # Always-clear is safe: processed_stops is rebuilt from stop_delays.
    clauses_del = []
    if since:
        clauses_del.append(f"service_date >= '{since}'")
    if until:
        clauses_del.append(f"service_date < '{until}'")
    if clauses_del:
        conn.execute("DELETE FROM processed_stops WHERE " + " AND ".join(clauses_del))
    else:
        conn.execute("DELETE FROM processed_stops")
    conn.commit()
    logging.info("Cleared processed_stops window before insert")

    # SQLite caps variables per statement at 32766; with 16 cols max chunk = 2048
    out.to_sql("processed_stops", conn, if_exists="append", index=False,
               method="multi", chunksize=2_000)
    conn.commit()

    logging.info("Wrote %d rows to processed_stops", len(out))
    conn.execute("DETACH DATABASE static_db")
    conn.close()
    return len(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process raw delays into analysis-ready table")
    parser.add_argument("--since", help="ISO date lower bound, e.g. 2025-03-01")
    parser.add_argument("--until", help="ISO date upper bound (exclusive)")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    n = process(since=args.since, until=args.until)
    elapsed = (datetime.now(timezone.utc) - started).seconds
    print(f"Processed {n:,} rows in {elapsed}s → processed_stops")
