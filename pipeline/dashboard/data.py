"""Data access: SQLite query helpers and all cached queries.

DB paths come from pipeline/config.py (single source of truth for paths).
"""
import sqlite3

import pandas as pd
import streamlit as st

from config import DB_REALTIME as RT_DB, DB_STATIC as STATIC_DB
from dashboard.constants import ANOMALY_EXCL, MV_WFS_URL


def _where(df, dt, prefix="WHERE"):
    return (
        f"{prefix} timestamp >= '{df}' "
        f"AND timestamp <= '{dt} 23:59:59'"
    )

def _and(df, dt):
    return _where(df, dt, prefix="AND")

def qrt(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(RT_DB)
    out  = pd.read_sql_query(sql, conn)
    conn.close()
    return out

def qstatic(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(STATIC_DB)
    out  = pd.read_sql_query(sql, conn)
    conn.close()
    return out


@st.cache_data(ttl=300)
def daily_counts(df, dt):
    return qrt(f"""
        SELECT date(timestamp) AS day, COUNT(*) AS n
        FROM processed_stops {_where(df,dt)}
        GROUP BY day ORDER BY day
    """)

@st.cache_data(ttl=300)
def hourly_heatmap(df, dt):
    return qrt(f"""
        SELECT date(timestamp) AS day, hour, COUNT(*) AS n
        FROM processed_stops {_where(df,dt)}
        GROUP BY day, hour
    """)

@st.cache_data(ttl=300)
def collection_runs():
    return qrt(
        "SELECT run_id, started, finished, status, rows_inserted, net_new_rows "
        "FROM collection_runs ORDER BY run_id DESC LIMIT 50"
    )

@st.cache_data(ttl=300)
def delay_histogram(df, dt):
    return qrt(f"""
        SELECT ROUND(delay_seconds / 30.0) * 30 AS bucket, COUNT(*) AS n
        FROM processed_stops {_where(df,dt)}
        AND abs(delay_seconds) <= 1800
        GROUP BY bucket ORDER BY bucket
    """)

@st.cache_data(ttl=300)
def delay_stats(df, dt):
    return qrt(f"""
        SELECT
            AVG(delay_seconds)                                          AS mean_d,
            COUNT(*)                                                    AS total,
            SUM(CASE WHEN delay_seconds < 0 THEN 1 ELSE 0 END)         AS n_early,
            SUM(CASE WHEN delay_seconds > 300 THEN 1 ELSE 0 END)       AS n_late5,
            SUM(CASE WHEN abs(delay_seconds) > 3600 THEN 1 ELSE 0 END) AS n_outlier
        FROM processed_stops {_where(df,dt)}
    """)

@st.cache_data(ttl=300)
def delay_by_hour(df, dt):
    return qrt(f"""
        SELECT hour, AVG(delay_seconds) AS mean_d, COUNT(*) AS n
        FROM processed_stops {_where(df,dt)}
        AND abs(delay_seconds) <= 3600
        GROUP BY hour ORDER BY hour
    """)

@st.cache_data(ttl=300)
def delay_by_dow(df, dt):
    return qrt(f"""
        SELECT dow, AVG(delay_seconds) AS mean_d, COUNT(*) AS n
        FROM processed_stops {_where(df,dt)}
        AND abs(delay_seconds) <= 3600
        GROUP BY dow ORDER BY dow
    """)

@st.cache_data(ttl=300)
def route_summary(df, dt):
    return qrt(f"""
        SELECT route_id, direction_id,
            COUNT(*)              AS n_rows,
            COUNT(DISTINCT trip_id) AS n_trips,
            AVG(delay_seconds)    AS mean_delay,
            SUM(CASE WHEN abs(delay_seconds) > 3600 THEN 1 ELSE 0 END) AS n_outliers
        FROM processed_stops {_where(df,dt)}
        AND route_id != ''
        GROUP BY route_id, direction_id
        ORDER BY n_rows DESC
    """)

@st.cache_data(ttl=300)
def route_daily(route_id, direction, df, dt):
    dir_clause = f"AND direction_id = {int(direction)}" if direction != "Both" else ""
    return qrt(f"""
        SELECT date(timestamp) AS day, direction_id,
            AVG(delay_seconds) AS mean_delay, COUNT(*) AS n
        FROM processed_stops
        WHERE route_id = '{route_id}' {dir_clause}
        {_and(df,dt)}
        GROUP BY day, direction_id ORDER BY day
    """)

@st.cache_data(ttl=300)
def route_hist(route_id, direction, df, dt):
    dir_clause = f"AND direction_id = {int(direction)}" if direction != "Both" else ""
    return qrt(f"""
        SELECT ROUND(delay_seconds/30.0)*30 AS bucket, direction_id, COUNT(*) AS n
        FROM processed_stops
        WHERE route_id = '{route_id}' {dir_clause}
        {_and(df,dt)}
        AND abs(delay_seconds) <= 1800
        GROUP BY bucket, direction_id ORDER BY bucket
    """)

@st.cache_data(ttl=300)
def route_by_hour(route_id, direction, df, dt):
    dir_clause = f"AND direction_id = {int(direction)}" if direction != "Both" else ""
    return qrt(f"""
        SELECT hour, direction_id, AVG(delay_seconds) AS mean_delay, COUNT(*) AS n
        FROM processed_stops
        WHERE route_id = '{route_id}' {dir_clause}
        {_and(df,dt)}
        AND abs(delay_seconds) <= 3600
        GROUP BY hour, direction_id ORDER BY hour
    """)

@st.cache_data(ttl=300)
def null_rates(df, dt):
    cols = [
        "delay_seconds", "previous_stop_delay", "shape_dist_traveled",
        "stop_lat", "stop_lon", "hour", "dow",
    ]
    conn  = sqlite3.connect(RT_DB)
    total = conn.execute(
        f"SELECT COUNT(*) FROM processed_stops {_where(df,dt)}"
    ).fetchone()[0]
    rows  = []
    for col in cols:
        n = conn.execute(
            f"SELECT COUNT(*) FROM processed_stops {_where(df,dt)} AND {col} IS NULL"
        ).fetchone()[0]
        rows.append({"column": col, "null_count": n,
                     "null_pct": round(100 * n / total, 3) if total else 0})
    conn.close()
    return pd.DataFrame(rows)

@st.cache_data(ttl=300)
def seq_integrity(df, dt):
    return qrt(f"""
        SELECT route_id,
            COUNT(DISTINCT trip_id) AS total_trips,
            SUM(is_bad)             AS bad_trips,
            ROUND(100.0 * SUM(is_bad) / COUNT(DISTINCT trip_id), 1) AS pct_bad
        FROM (
            SELECT trip_id, route_id,
                MAX(CASE WHEN gap <= 0 THEN 1 ELSE 0 END) AS is_bad
            FROM (
                SELECT trip_id, route_id,
                    stop_sequence - LAG(stop_sequence) OVER (
                        PARTITION BY trip_id ORDER BY stop_sequence
                    ) AS gap
                FROM stop_delays {_where(df,dt)}
            )
            GROUP BY trip_id, route_id
        )
        GROUP BY route_id
        HAVING total_trips >= 10
        ORDER BY pct_bad DESC
    """)

@st.cache_data(ttl=300)
def stale_pct(df, dt):
    conn  = sqlite3.connect(RT_DB)
    total = conn.execute(
        f"SELECT COUNT(*) FROM stop_delays "
        f"WHERE actual_arrival IS NOT NULL {_and(df,dt)}"
    ).fetchone()[0]
    stale = conn.execute(
        f"SELECT COUNT(*) FROM stop_delays "
        f"WHERE actual_arrival IS NOT NULL AND actual_arrival < timestamp {_and(df,dt)}"
    ).fetchone()[0]
    conn.close()
    return stale, total

@st.cache_data(ttl=3600)
def route_labels():
    return qstatic("SELECT route_id, route_short_name, route_long_name FROM routes")

# Stop municipality classification — no date dependency, cache 24h
@st.cache_data(ttl=86400)
def metro_van_geojson():
    import requests as _req
    try:
        r = _req.get(MV_WFS_URL, timeout=30,
                     headers={"User-Agent": "TranslinkBayes/1.0"})
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=86400)
def stop_municipality_map():
    from shapely.geometry import Point, shape

    result, err = metro_van_geojson()
    if result is None:
        return None, err

    stops = qstatic("SELECT stop_id, stop_lat, stop_lon FROM stops WHERE stop_lat IS NOT NULL")

    polys = []
    for feat in result.get("features", []):
        name = feat["properties"].get("ADMIN_AREA_NAME", "Unknown")
        try:
            polys.append((name, shape(feat["geometry"])))
        except Exception:
            pass

    def classify(lat, lon):
        pt = Point(lon, lat)
        for name, poly in polys:
            try:
                if poly.contains(pt):
                    return name
            except Exception:
                pass
        return "Outside Metro Van"

    stops["municipality"] = stops.apply(
        lambda r: classify(r["stop_lat"], r["stop_lon"]), axis=1
    )
    return stops[["stop_id", "municipality"]], None

@st.cache_data(ttl=300)
def geo_stop_delay(df, dt):
    return qrt(f"""
        SELECT route_id, stop_id, stop_lat, stop_lon,
            AVG(delay_seconds) AS mean_delay,
            COUNT(*)           AS n_rows
        FROM processed_stops {_where(df,dt)}
        AND stop_lat IS NOT NULL AND stop_lon IS NOT NULL
        AND route_id NOT IN ('{ANOMALY_EXCL}') AND route_id != ''
        GROUP BY route_id, stop_id, stop_lat, stop_lon
    """)
