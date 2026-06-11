"""
Loads TransLink static GTFS files into gtfs_static.db.
Called automatically by sync_static_gtfs.py after a schedule update,
or run directly from the repo root:
    python pipeline/process_static.py
"""
import sqlite3

import pandas as pd

from config import DB_STATIC, ROOT

ACTIVE_DIR = ROOT / "data" / "gtfs_static"

# ── Minimum row counts — guard against corrupt/empty downloads ───────────────
# Calibrated against TransLink's actual schedule size. If these fire on a
# legitimate update, raise the constants — don't lower them without investigation.
_MIN_STOPS      = 10_000
_MIN_STOP_TIMES = 500_000
_MIN_TRIPS      =  5_000
_MIN_ROUTES     =    100


def get_latest_gtfs_folder():
    """Returns ACTIVE_DIR, or its most-recent dated subfolder if one exists."""
    subfolders = [f for f in ACTIVE_DIR.iterdir() if f.is_dir()]
    if not subfolders:
        return ACTIVE_DIR
    return max(subfolders)


def main():
    gtfs_dir = get_latest_gtfs_folder()
    print(f"Using latest GTFS static data from: {gtfs_dir}")

    conn = sqlite3.connect(DB_STATIC)
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        stops      = pd.read_csv(gtfs_dir / "stops.txt")
        routes     = pd.read_csv(gtfs_dir / "routes.txt")
        stop_times = pd.read_csv(gtfs_dir / "stop_times.txt")
        trips      = pd.read_csv(gtfs_dir / "trips.txt", low_memory=False)

        # ── Integrity check before touching the DB ────────────────────────────
        # A corrupted download or partial extraction would silently load empty
        # tables and break every downstream join. Fail loudly before writing.
        checks = [
            (len(stops),      _MIN_STOPS,      "stops"),
            (len(routes),     _MIN_ROUTES,     "routes"),
            (len(stop_times), _MIN_STOP_TIMES, "stop_times"),
            (len(trips),      _MIN_TRIPS,      "trips"),
        ]
        failures = [
            f"{name}: {count:,} rows (minimum {minimum:,})"
            for count, minimum, name in checks
            if count < minimum
        ]
        if failures:
            raise ValueError(
                "Static GTFS integrity check failed — refusing to overwrite DB:\n  "
                + "\n  ".join(failures)
            )

        stops.to_sql("stops", conn, if_exists="replace", index=False)
        routes.to_sql("routes", conn, if_exists="replace", index=False)
        stop_times.to_sql("stop_times", conn, if_exists="replace", index=False)
        trips.to_sql("trips", conn, if_exists="replace", index=False)

        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_st_trip_stop_seq
                ON stop_times (trip_id, stop_id, stop_sequence);
            CREATE INDEX IF NOT EXISTS idx_trips_trip ON trips (trip_id);
            CREATE INDEX IF NOT EXISTS idx_stops_stop ON stops (stop_id);
        """)
        conn.commit()
        print(f"Static GTFS loaded: {len(stops):,} stops  {len(routes):,} routes  "
              f"{len(trips):,} trips  {len(stop_times):,} stop_times")

    except Exception as e:
        print(f"Error loading GTFS static data: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
