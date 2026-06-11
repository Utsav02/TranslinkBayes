"""
Exports processed_stops to parquet or CSV for use in R / reproducibility.

Usage examples:
    python export_route.py --route 6641
    python export_route.py --route 6641 --direction 0
    python export_route.py --route 6641 --since 2025-03-01 --until 2025-04-01
    python export_route.py --route all  --format csv
    python export_route.py --route 6641 --output exports/my_snapshot.parquet
"""
import argparse
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from config import DB_REALTIME, EXPORT_DIR

EXPORT_DIR.mkdir(exist_ok=True)

_COLS = [
    "trip_id", "route_id", "direction_id", "stop_id", "stop_sequence",
    "stop_lat", "stop_lon", "delay_seconds", "previous_stop_delay",
    "shape_dist_traveled", "hour", "dow", "is_rush_hour", "is_weekend",
    "timestamp",
]


def _build_query(route: str, direction: int | None, since: str | None, until: str | None) -> tuple[str, list]:
    clauses, params = [], []
    if route != "all":
        clauses.append("route_id = ?")
        params.append(route)
    if direction is not None:
        clauses.append("direction_id = ?")
        params.append(direction)
    if since:
        clauses.append("timestamp >= ?")
        params.append(since)
    if until:
        clauses.append("timestamp < ?")
        params.append(until)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    query = f"SELECT {', '.join(_COLS)} FROM processed_stops {where} ORDER BY trip_id, stop_sequence"
    return query, params


def _default_name(route: str, direction: int | None, fmt: str) -> Path:
    tag = f"route{route}" if route != "all" else "all_routes"
    if direction is not None:
        tag += f"_dir{direction}"
    stamp = date.today().isoformat()
    return EXPORT_DIR / f"{tag}_{stamp}.{fmt}"


def _write(df: pd.DataFrame, path: Path, fmt: str) -> None:
    if fmt == "parquet":
        try:
            df.to_parquet(path, index=False)
        except ImportError:
            print("pyarrow not installed — falling back to CSV. Run: python3 -m pip install pyarrow")
            path = path.with_suffix(".csv")
            df.to_csv(path, index=False)
    else:
        df.to_csv(path, index=False)


def export(
    route: str,
    direction: int | None = None,
    since: str | None = None,
    until: str | None = None,
    fmt: str = "parquet",
    output: Path | None = None,
) -> Path:
    conn = sqlite3.connect(DB_REALTIME)
    query, params = _build_query(route, direction, since, until)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        print("No rows matched — check route/direction/date filters.")
        sys.exit(1)

    out_path = output or _default_name(route, direction, fmt)
    _write(df, out_path, fmt)

    print(f"Exported {len(df):,} rows → {out_path}")
    print(f"  routes:     {sorted(df['route_id'].unique())}")
    print(f"  date range: {df['timestamp'].min()[:10]} → {df['timestamp'].max()[:10]}")
    print(f"  delay (s):  mean={df['delay_seconds'].mean():.1f}  "
          f"std={df['delay_seconds'].std():.1f}  "
          f"NaN={df['delay_seconds'].isna().sum()}")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export processed stops to parquet/CSV")
    parser.add_argument("--route",     required=True, help="Route ID or 'all'")
    parser.add_argument("--direction", type=int,       help="0 or 1")
    parser.add_argument("--since",                     help="ISO date, e.g. 2025-03-01")
    parser.add_argument("--until",                     help="ISO date, exclusive")
    parser.add_argument("--format",    default="parquet", choices=["parquet", "csv"])
    parser.add_argument("--output",    type=Path,      help="Override output path")
    args = parser.parse_args()

    export(
        route=args.route,
        direction=args.direction,
        since=args.since,
        until=args.until,
        fmt=args.format,
        output=args.output,
    )
