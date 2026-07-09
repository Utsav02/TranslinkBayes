"""
Derive per-row settledness quality label from stop_delays_snapshots.

For each (trip_id, stop_id, service_date), compute:
  - settledness_gap_seconds: (last_snapshot.timestamp - actual_arrival) in seconds.
    NEGATIVE = last snapshot was BEFORE arrival (prediction).
    POSITIVE = last snapshot was AFTER arrival (observation).
  - n_snapshots: total snapshots captured for this key.
  - min_horizon_seconds: min |predicted_arr - fetch_ts| across all snapshots (how
    close did any single fetch get to true arrival — a "best trajectory point").

Writes exports/stop_delays_settledness.parquet with those quality columns
alongside the raw (trip_id, stop_id, service_date) key. Downstream consumers
join on that key to attach quality to stop_delays / processed_stops rows.

Coverage: only service_date >= 2026-06-12 (when the snapshot collector started).
Rows before that have no snapshot history and get NULL settledness.

Usage:
    python pipeline/derive_settledness.py                    # all snapshots
    python pipeline/derive_settledness.py --since 2026-06-12
"""
import argparse, sqlite3, logging, time
from datetime import datetime, timezone
from pathlib import Path

from config import DB_REALTIME, EXPORT_DIR, LOG_DIR

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "derive_settledness.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_QUERY = """
WITH per_key AS (
    SELECT trip_id, stop_id, service_date, actual_arrival,
           MAX(timestamp) AS last_ts,
           COUNT(*)       AS n_snapshots,
           MIN(ABS((julianday(timestamp) - julianday(actual_arrival)) * 86400.0))
                          AS min_horizon_seconds
    FROM stop_delays_snapshots
    WHERE actual_arrival IS NOT NULL {where}
    GROUP BY trip_id, stop_id, service_date, actual_arrival
)
SELECT
    trip_id,
    stop_id,
    service_date,
    n_snapshots,
    min_horizon_seconds,
    (julianday(last_ts) - julianday(actual_arrival)) * 86400.0
        AS settledness_gap_seconds
FROM per_key
"""


def derive(since: str | None = None) -> Path:
    import pandas as pd
    where = f"AND service_date >= '{since}'" if since else ""
    sql = _QUERY.format(where=where)

    conn = sqlite3.connect(DB_REALTIME)
    conn.execute("PRAGMA journal_mode=WAL")

    logging.info("Deriving settledness (since=%s)", since or "ALL")
    t0 = time.time()
    df = pd.read_sql_query(sql, conn)
    logging.info("Derived %d rows in %.1fs", len(df), time.time() - t0)
    conn.close()

    # Bucket for quick filtering — matches the analysis buckets in the design doc
    def bucket(g):
        if g > 300:  return "F_stale_after"       # >5 min after arr — feed lag
        if g >= 0:   return "A_settled"           # 0-5 min after arr — true observation
        if g > -120: return "B_near_settled"      # 0-2 min before arr — very close
        if g > -300: return "C_short_horizon"     # 2-5 min before
        if g > -600: return "D_medium_forecast"   # 5-10 min before
        return "E_forecast"                       # >10 min before

    df["settledness_bucket"] = df["settledness_gap_seconds"].apply(bucket)

    out_path = EXPORT_DIR / "stop_delays_settledness.parquet"
    df.to_parquet(out_path, index=False)
    logging.info("Wrote %s (%d rows)", out_path, len(df))
    print(f"Wrote {len(df):,} rows → {out_path}")

    print("\n=== bucket distribution ===")
    dist = df["settledness_bucket"].value_counts().sort_index()
    tot = dist.sum()
    for b, n in dist.items():
        print(f"  {b:<25}  {n:>9,}  ({100*n/tot:5.2f}%)")
    return out_path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--since", help="ISO date lower bound (default: all snapshots)")
    args = p.parse_args()
    derive(args.since)
