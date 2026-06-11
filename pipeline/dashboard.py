"""
TransLink Data Health Dashboard
Run: venv/bin/python3 -m streamlit run pipeline/dashboard.py
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import sqlite3
import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
RT_DB        = str(PROJECT_ROOT / "database" / "gtfs_realtime_v2.db")
STATIC_DB    = str(PROJECT_ROOT / "database" / "gtfs_static.db")

# ── Constants ─────────────────────────────────────────────────────────────────
# 12940/6700/30055/6702/6718 — stop-sequence tie artifacts (LAG corruption)
# 6619 — structural GTFS join failure: Lougheed Hwy extension + termini have
#         no shape_dist_traveled in gtfs_static.db; NULL pattern is geographic,
#         not random — remaining sample is biased to central Broadway corridor
ANOMALY_ROUTES = ["12940", "6700", "30055", "6702", "6718", "6619"]
HOLDOUT_ROUTES = ["6641", "6705"]
FIFA_MATCH_DATES = [
    "2026-06-13", "2026-06-18", "2026-06-21",
    "2026-06-24", "2026-06-26", "2026-07-02", "2026-07-07",
]
DATA_START = "2026-05-23"
DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# BC Data Catalogue WFS — official provincial government source
MV_WFS_URL = (
    "https://openmaps.gov.bc.ca/geo/pub/wfs"
    "?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
    "&typeName=WHSE_LEGAL_ADMIN_BOUNDARIES.ABMS_MUNICIPALITIES_SP"
    "&outputFormat=application/json"
    "&CQL_FILTER=ADMIN_AREA_GROUP_NAME%3D%27Metro+Vancouver+Regional+District%27"
    "&srsName=EPSG:4326"
)

# Broader region groupings (municipality → region label)
REGION_GROUPS = {
    "City of Vancouver":                              "Vancouver",
    "City of Burnaby":                                "Burnaby / New West",
    "City of New Westminster":                        "Burnaby / New West",
    "City of Richmond":                               "Richmond / Delta",
    "City of Delta":                                  "Richmond / Delta",
    "City of Surrey":                                 "Surrey / Langley",
    "City of Langley":                                "Surrey / Langley",
    "The Corporation of the Township of Langley":     "Surrey / Langley",
    "City of White Rock":                             "Surrey / Langley",
    "City of Coquitlam":                              "Tri-Cities",
    "City of Port Coquitlam":                         "Tri-Cities",
    "City of Port Moody":                             "Tri-Cities",
    "Village of Anmore":                              "Tri-Cities",
    "Village of Belcarra":                            "Tri-Cities",
    "City of North Vancouver":                        "North Shore",
    "The Corporation of the District of North Vancouver": "North Shore",
    "District Municipality of West Vancouver":        "North Shore",
    "Bowen Island Municipality":                      "North Shore",
    "Village of Lions Bay":                           "North Shore",
    "City of Maple Ridge":                            "East Valley",
    "City of Pitt Meadows":                           "East Valley",
}

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TransLink Health",
    page_icon="🚌",
    layout="wide",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🚌 TransLink Health")

    theme = st.radio("Theme", ["Light", "Dark"], horizontal=True)
    TMPL  = "plotly_dark" if theme == "Dark" else "plotly_white"

    if theme == "Dark":
        st.markdown(
            "<style>.stApp{background-color:#0e1117;color:#fafafa;}</style>",
            unsafe_allow_html=True,
        )

    st.divider()
    date_from = st.date_input("From", value=date.fromisoformat(DATA_START))
    date_to   = st.date_input("To",   value=date.today())

    if st.button("↺  Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    try:
        _conn = sqlite3.connect(RT_DB)
        _last = _conn.execute(
            "SELECT started, status, net_new_rows FROM collection_runs "
            "ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        _conn.close()
        if _last:
            _dt  = datetime.fromisoformat(_last[0])
            _age = (datetime.now(timezone.utc) - _dt).total_seconds() / 60
            _ico = "✅" if _last[1] == "ok" else "❌"
            st.caption("Last collection")
            st.write(f"{_ico} **{_last[1]}** — {_age:.0f} min ago")
            if _last[2]:
                st.write(f"+{_last[2]:,} rows")
    except Exception:
        st.caption("Collection status unavailable")

DF  = date_from.isoformat()
DT  = date_to.isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────
def _where(df=DF, dt=DT, prefix="WHERE"):
    return (
        f"{prefix} timestamp >= '{df}' "
        f"AND timestamp <= '{dt} 23:59:59'"
    )

def _and(df=DF, dt=DT):
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

def add_fifa(fig):
    for d in FIFA_MATCH_DATES:
        fig.add_vline(x=d, line_dash="dot", line_color="gold", line_width=1)
        fig.add_annotation(
            x=d, y=1, yref="paper", text="FIFA", showarrow=False,
            font=dict(size=9, color="gold"), xanchor="left",
        )
    return fig

def route_label(rid, lmap):
    short = lmap.get(rid, "")
    tag   = " ⚠" if rid in ANOMALY_ROUTES else (" [holdout]" if rid in HOLDOUT_ROUTES else "")
    return f"{rid} — {short}{tag}" if short else f"{rid}{tag}"

ANOMALY_EXCL = "','".join(ANOMALY_ROUTES)


# ── Cached queries ────────────────────────────────────────────────────────────
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


# ── Tabs ──────────────────────────────────────────────────────────────────────
t1, t2, t3, t4, t5, t6 = st.tabs([
    "📡 Collection Health",
    "📊 Delay Distributions",
    "🔍 Route Explorer",
    "🧹 Data Quality",
    "🗺️ Geographic",
    "🔬 Ralph Loop",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — COLLECTION HEALTH
# ══════════════════════════════════════════════════════════════════════════════
with t1:
    try:
        dc = daily_counts(DF, DT)
        if dc.empty:
            st.warning("No data in selected date range.")
            st.stop()

        med     = dc["n"].median()
        today_s = date.today().isoformat()
        today_n = dc.loc[dc["day"] == today_s, "n"].sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total rows",       f"{dc['n'].sum():,}")
        c2.metric("Days with data",   f"{len(dc)}")
        c3.metric("Median rows/day",  f"{med:,.0f}")
        delta = f"{100*(today_n-med)/med:+.0f}% vs median" if med and today_n else "—"
        c4.metric("Today's rows", f"{today_n:,}", delta)

        dc["status"] = dc["n"].apply(
            lambda n: "Low (<50% median)" if n < 0.5 * med else "Normal"
        )
        fig = px.bar(
            dc, x="day", y="n", color="status",
            color_discrete_map={"Normal": "steelblue", "Low (<50% median)": "crimson"},
            labels={"day": "Date", "n": "Rows", "status": ""},
            title="Rows collected per day",
            template=TMPL,
        )
        fig.update_layout(legend=dict(orientation="h", y=1.08))
        fig = add_fifa(fig)
        st.plotly_chart(fig, use_container_width=True)

        hm = hourly_heatmap(DF, DT)
        if not hm.empty:
            pivot = hm.pivot(index="day", columns="hour", values="n").fillna(0)
            fig2  = px.imshow(
                pivot,
                labels=dict(x="Hour (Pacific)", y="Date", color="Rows"),
                title="Data density — date × hour of day",
                color_continuous_scale="Blues",
                template=TMPL,
                aspect="auto",
            )
            st.plotly_chart(fig2, use_container_width=True)

        runs = collection_runs()
        if not runs.empty:
            st.subheader("Last 50 collection runs")
            def _style_status(val):
                return "background-color:#ff4b4b;color:white" if val != "ok" else ""
            st.dataframe(
                runs.style.map(_style_status, subset=["status"]),
                use_container_width=True, hide_index=True,
            )

    except Exception as e:
        st.error(f"Collection Health error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DELAY DISTRIBUTIONS
# ══════════════════════════════════════════════════════════════════════════════
with t2:
    try:
        st.info(
            "**`actual_arrival`** in the raw feed is the GTFS-RT *predicted* arrival "
            "time — not an observed ground-truth. **`delay_seconds`** is the "
            "GPS-derived signal broadcast by TransLink."
        )

        h = delay_histogram(DF, DT)
        s = delay_stats(DF, DT)

        if not h.empty and not s.empty:
            sv = s.iloc[0]
            total = sv["total"] or 1
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Mean delay",      f"{sv['mean_d']:.1f}s")
            c2.metric("% early",         f"{100*sv['n_early']/total:.1f}%")
            c3.metric("% >5 min late",   f"{100*sv['n_late5']/total:.1f}%")
            c4.metric("Outliers (>1hr)", f"{int(sv['n_outlier']):,}")

            fig = px.bar(
                h, x="bucket", y="n",
                labels={"bucket": "Delay (seconds)", "n": "Count"},
                title="Delay distribution  (|delay| ≤ 1800 s, 30 s bins)",
                template=TMPL,
            )
            fig.add_vline(x=0, line_dash="dash", line_color="tomato")
            fig.add_annotation(x=0, y=1, yref="paper", text="On time",
                               showarrow=False, font=dict(size=9, color="tomato"),
                               xanchor="left")
            st.plotly_chart(fig, use_container_width=True)

        hd = delay_by_hour(DF, DT)
        if not hd.empty:
            fig_h = px.bar(
                hd, x="hour", y="mean_d",
                labels={"hour": "Hour (Pacific)", "mean_d": "Mean delay (s)"},
                title="Mean delay by hour of day",
                template=TMPL,
            )
            fig_h.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig_h, use_container_width=True)

        dd = delay_by_dow(DF, DT)
        if not dd.empty:
            dd["day_name"] = dd["dow"].map(dict(enumerate(DOW_LABELS)))
            fig_d = px.bar(
                dd, x="day_name", y="mean_d",
                labels={"day_name": "Day of week", "mean_d": "Mean delay (s)"},
                title="Mean delay by day of week",
                template=TMPL,
            )
            fig_d.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig_d, use_container_width=True)

        rs = route_summary(DF, DT)
        rl = route_labels()
        lmap = dict(zip(rl["route_id"], rl["route_short_name"]))

        if not rs.empty:
            st.subheader("Mean delay by route")
            show_all = st.toggle("Show all routes", value=False)

            agg = (
                rs[~rs["route_id"].isin(ANOMALY_ROUTES)]
                .groupby("route_id")
                .agg(mean_delay=("mean_delay", "mean"), n_rows=("n_rows", "sum"))
                .reset_index()
            )
            if not show_all:
                top30 = agg.nlargest(30, "n_rows")["route_id"]
                agg   = agg[agg["route_id"].isin(top30)]

            agg = agg.sort_values("mean_delay", ascending=False)
            agg["label"] = agg["route_id"].apply(lambda r: route_label(r, lmap))

            fig_r = px.bar(
                agg, x="mean_delay", y="label", orientation="h",
                labels={"mean_delay": "Mean delay (s)", "label": "Route"},
                title="Per-route mean delay (excl. anomaly routes)",
                template=TMPL,
                height=max(400, 22 * len(agg)),
            )
            fig_r.add_vline(x=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig_r, use_container_width=True)

    except Exception as e:
        st.error(f"Delay Distributions error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — ROUTE EXPLORER
# ══════════════════════════════════════════════════════════════════════════════
with t3:
    try:
        rs   = route_summary(DF, DT)
        rl   = route_labels()
        lmap = dict(zip(rl["route_id"], rl["route_short_name"]))

        if rs.empty:
            st.warning("No route data in selected date range.")
        else:
            all_routes = sorted(rs["route_id"].unique())

            col_r, col_d = st.columns([3, 1])
            with col_r:
                sel = st.selectbox(
                    "Route",
                    options=all_routes,
                    format_func=lambda r: route_label(r, lmap),
                )
            with col_d:
                avail_dirs = sorted(
                    rs.loc[rs["route_id"] == sel, "direction_id"]
                    .dropna().astype(int).unique().tolist()
                )
                dir_opts = ["Both"] + [str(d) for d in avail_dirs]
                sel_dir  = st.selectbox("Direction", dir_opts)

            dir_val = sel_dir if sel_dir == "Both" else int(sel_dir)

            if sel in HOLDOUT_ROUTES:
                st.info(
                    f"Route **{sel}** ({lmap.get(sel, '')}) is a **holdout route** — "
                    "excluded from all model training. Used for out-of-distribution "
                    "evaluation after fitting."
                )
            if sel in ANOMALY_ROUTES:
                st.warning(
                    f"Route **{sel}** is an **anomaly route** with structural "
                    "duplicate `stop_sequence` entries. `previous_stop_delay` "
                    "(LAG-based) is unreliable for this route."
                )

            rm = rs[rs["route_id"] == sel]
            if sel_dir != "Both":
                rm = rm[rm["direction_id"] == int(sel_dir)]

            if not rm.empty:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Rows",            f"{rm['n_rows'].sum():,}")
                c2.metric("Trips",           f"{rm['n_trips'].sum():,}")
                c3.metric("Mean delay",      f"{rm['mean_delay'].mean():.1f}s")
                c4.metric("Outliers (>1hr)", f"{rm['n_outliers'].sum():,}")

            # Daily mean delay
            rd = route_daily(sel, dir_val, DF, DT)
            if not rd.empty:
                rd["Direction"] = rd["direction_id"].apply(lambda d: f"Direction {int(d)}")
                fig = px.line(
                    rd, x="day", y="mean_delay", color="Direction",
                    labels={"day": "Date", "mean_delay": "Mean delay (s)"},
                    title=f"Route {sel} — daily mean delay by direction",
                    template=TMPL,
                )
                fig.add_hline(y=0, line_dash="dash", line_color="gray")
                fig = add_fifa(fig)
                st.plotly_chart(fig, use_container_width=True)

            # Delay distribution vs overall
            rh      = route_hist(sel, dir_val, DF, DT)
            hall    = delay_histogram(DF, DT)
            if not rh.empty:
                rh["Direction"] = rh["direction_id"].apply(lambda d: f"Dir {int(d)}")
                total_r   = rh["n"].sum()
                total_all = hall["n"].sum()
                scale = total_r / total_all if total_all else 1

                fig2 = px.line(
                    rh, x="bucket", y="n", color="Direction",
                    labels={"bucket": "Delay (s)", "n": "Count", "Direction": ""},
                    title=f"Delay distribution — route {sel} vs overall (scaled)",
                    template=TMPL,
                )
                fig2.add_scatter(
                    x=hall["bucket"], y=hall["n"] * scale,
                    mode="lines", name="Overall (scaled)",
                    line=dict(dash="dot", color="gray"),
                )
                fig2.add_vline(x=0, line_dash="dash", line_color="tomato")
                st.plotly_chart(fig2, use_container_width=True)

            # By hour
            rhr = route_by_hour(sel, dir_val, DF, DT)
            if not rhr.empty:
                rhr["Direction"] = rhr["direction_id"].apply(lambda d: f"Direction {int(d)}")
                fig3 = px.line(
                    rhr, x="hour", y="mean_delay", color="Direction",
                    labels={"hour": "Hour (Pacific)", "mean_delay": "Mean delay (s)"},
                    title=f"Route {sel} — mean delay by hour",
                    template=TMPL,
                )
                fig3.add_hline(y=0, line_dash="dash", line_color="gray")
                st.plotly_chart(fig3, use_container_width=True)

    except Exception as e:
        st.error(f"Route Explorer error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — DATA QUALITY
# ══════════════════════════════════════════════════════════════════════════════
with t4:
    try:
        # NULL rates
        st.subheader("NULL rates — model variables")
        nr = null_rates(DF, DT)

        PREV_THRESH = 7.0

        def _rag(row):
            pct   = row["null_pct"]
            thresh = PREV_THRESH if row["column"] == "previous_stop_delay" else 1.0
            if pct == 0:
                return "✅ OK"
            if pct <= thresh:
                return "🟡 WARN"
            return "🔴 FAIL"

        nr["status"] = nr.apply(_rag, axis=1)
        st.dataframe(nr, use_container_width=True, hide_index=True)

        st.divider()

        # Stop-sequence integrity
        st.subheader("Stop-sequence tie rates by route")
        st.caption(
            "A 'bad trip' has duplicate `stop_sequence` numbers in the RT feed. "
            "The LAG-based `previous_stop_delay` is unreliable at those tie points."
        )
        si = seq_integrity(DF, DT)
        if not si.empty:
            def _cat(row):
                if row["route_id"] in ANOMALY_ROUTES:
                    return "Anomaly route (excluded)"
                p = row["pct_bad"] or 0
                if p > 50:
                    return "High (>50%)"
                if p >= 5:
                    return "Medium (5–50%)"
                return "Low (<5%)"

            si["category"] = si.apply(_cat, axis=1)
            cmap = {
                "Anomaly route (excluded)": "crimson",
                "High (>50%)":              "orangered",
                "Medium (5–50%)":           "gold",
                "Low (<5%)":                "mediumseagreen",
            }
            fig_si = px.bar(
                si, x="route_id", y="pct_bad", color="category",
                color_discrete_map=cmap,
                labels={"route_id": "Route", "pct_bad": "% bad trips", "category": ""},
                title="Stop-sequence tie rate by route (≥10 trips)",
                template=TMPL,
            )
            st.plotly_chart(fig_si, use_container_width=True)
            st.dataframe(si[["route_id","total_trips","bad_trips","pct_bad","category"]],
                         use_container_width=True, hide_index=True)

        st.divider()

        # Stale predictions
        st.subheader("Stale predictions")
        stale_n, total_sd = stale_pct(DF, DT)
        if total_sd:
            sp = 100 * stale_n / total_sd
            st.metric(
                "Rows where predicted arrival < fetch timestamp",
                f"{stale_n:,} / {total_sd:,}",
                f"{sp:.2f}%  {'🔴' if sp > 5 else '✅'}",
            )
        else:
            st.warning("No stop_delays rows with actual_arrival in range.")

        st.divider()

        # Completeness calendar
        st.subheader("Collection completeness by day")
        dc2 = daily_counts(DF, DT)
        if not dc2.empty:
            med2 = dc2["n"].median()
            dc2["pct_complete"] = (dc2["n"] / med2 * 100).clip(upper=110)
            fig_c = px.bar(
                dc2, x="day", y="pct_complete",
                labels={"day": "Date", "pct_complete": "% of median rows"},
                title="Completeness relative to median daily row count",
                template=TMPL,
            )
            fig_c.add_hline(y=20, line_dash="dot", line_color="crimson")
            fig_c.add_annotation(x=0, y=20, yref="y", text="Sparse (20%)",
                                 showarrow=False, font=dict(size=9, color="crimson"),
                                 xanchor="left", xref="paper")
            fig_c.add_hline(y=100, line_dash="dot", line_color="mediumseagreen")
            fig_c.add_annotation(x=0, y=100, yref="y", text="Median",
                                 showarrow=False, font=dict(size=9, color="mediumseagreen"),
                                 xanchor="left", xref="paper")
            fig_c = add_fifa(fig_c)
            st.plotly_chart(fig_c, use_container_width=True)

        st.divider()

        st.subheader("Known data issues")
        st.warning(
            "**`actual_arrival` is misnamed** — it holds the GTFS-RT *predicted* "
            "arrival, not an observed arrival. The name is an artefact of the "
            "protobuf field `StopTimeEvent.arrival`."
        )
        st.warning("**`bus_id` is always NULL** — vehicle position collection not implemented.")
        st.info(
            f"**Data before {DATA_START} is sparse** — the collector was not running "
            "24/7 before that date. Always use `--since {DATA_START}` for analysis."
        )

    except Exception as e:
        st.error(f"Data Quality error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — GEOGRAPHIC
# ══════════════════════════════════════════════════════════════════════════════
with t5:
    try:
        with st.spinner("Loading Metro Vancouver boundaries (BC Data Catalogue WFS)…"):
            muni_map, geo_err = stop_municipality_map()

        if muni_map is None:
            st.error(
                f"Could not load Metro Vancouver GeoJSON from BC openmaps.gov.bc.ca.\n\n"
                f"Error: {geo_err}\n\nCheck network connectivity and refresh."
            )
        else:
            geo_df = geo_stop_delay(DF, DT)
            if geo_df.empty:
                st.warning("No geographic data in selected date range.")
            else:
                geo_df = geo_df.merge(muni_map, on="stop_id", how="left")
                geo_df["municipality"] = geo_df["municipality"].fillna("Unknown")
                geo_df["region"] = geo_df["municipality"].map(REGION_GROUPS).fillna("Other")

                # Plurality municipality and region per route
                route_muni = (
                    geo_df.groupby(["route_id", "municipality"])["n_rows"]
                    .sum().reset_index()
                    .sort_values("n_rows", ascending=False)
                    .drop_duplicates("route_id")
                    .rename(columns={"municipality": "primary_municipality"})
                )
                route_muni["region"] = route_muni["primary_municipality"].map(
                    REGION_GROUPS
                ).fillna("Other")

                rl   = route_labels()
                lmap = dict(zip(rl["route_id"], rl["route_short_name"]))

                rs_summary = route_summary(DF, DT)

                geo5a, geo5b, geo5c = st.tabs([
                    "📊 Overview",
                    "🔍 Region Explorer",
                    "🗺️ Map",
                ])

                # ── GEO SUB-TAB A: OVERVIEW ──────────────────────────────────
                with geo5a:
                    # Region-level summary
                    region_agg = (
                        geo_df[geo_df["municipality"] != "Unknown"]
                        .groupby("region")
                        .agg(
                            n_municipalities=("municipality", "nunique"),
                            n_routes=("route_id", "nunique"),
                            n_rows=("n_rows", "sum"),
                            mean_delay=("mean_delay", "mean"),
                        )
                        .reset_index()
                        .sort_values("mean_delay", ascending=False)
                    )
                    region_agg["mean_delay"] = region_agg["mean_delay"].round(1)

                    st.subheader("Delay by broad region")
                    fig_reg = px.bar(
                        region_agg, x="region", y="mean_delay",
                        color="mean_delay", color_continuous_scale="RdYlGn_r",
                        labels={"region": "Region", "mean_delay": "Mean delay (s)"},
                        title="Mean delay by Metro Vancouver region",
                        template=TMPL,
                    )
                    fig_reg.add_hline(y=0, line_dash="dash", line_color="gray")
                    st.plotly_chart(fig_reg, use_container_width=True)
                    st.dataframe(region_agg, use_container_width=True, hide_index=True)

                    st.divider()

                    # Municipality-level summary
                    muni_agg = (
                        geo_df[geo_df["municipality"] != "Unknown"]
                        .groupby(["region", "municipality"])
                        .agg(
                            n_routes=("route_id", "nunique"),
                            n_rows=("n_rows", "sum"),
                            mean_delay=("mean_delay", "mean"),
                        )
                        .reset_index()
                        .sort_values(["region", "mean_delay"], ascending=[True, False])
                    )
                    muni_agg["mean_delay"] = muni_agg["mean_delay"].round(1)

                    st.subheader("Delay by municipality")
                    fig_muni = px.bar(
                        muni_agg, x="municipality", y="mean_delay",
                        color="region",
                        labels={"municipality": "Municipality",
                                "mean_delay": "Mean delay (s)", "region": "Region"},
                        title="Mean delay by municipality (coloured by region)",
                        template=TMPL,
                    )
                    fig_muni.add_hline(y=0, line_dash="dash", line_color="gray")
                    fig_muni.update_xaxes(tickangle=35)
                    st.plotly_chart(fig_muni, use_container_width=True)
                    st.dataframe(muni_agg, use_container_width=True, hide_index=True)

                # ── GEO SUB-TAB B: REGION EXPLORER ──────────────────────────
                with geo5b:
                    regions   = sorted(route_muni["region"].dropna().unique())
                    sel_reg   = st.selectbox("Region", regions, key="geo_region")

                    reg_munis = sorted(
                        route_muni[route_muni["region"] == sel_reg]
                        ["primary_municipality"].unique()
                    )
                    sel_muni  = st.selectbox(
                        "Municipality (within region)", ["All"] + reg_munis,
                        key="geo_muni"
                    )

                    if sel_muni == "All":
                        sel_rids = route_muni[route_muni["region"] == sel_reg]["route_id"]
                    else:
                        sel_rids = route_muni[
                            route_muni["primary_municipality"] == sel_muni
                        ]["route_id"]

                    # Route-level delay for selection (per direction)
                    sel_routes_df = (
                        rs_summary[rs_summary["route_id"].isin(sel_rids)]
                        .copy()
                    )
                    sel_routes_df["label"] = sel_routes_df["route_id"].apply(
                        lambda r: route_label(r, lmap)
                    )
                    sel_routes_df["dir_label"] = sel_routes_df["direction_id"].apply(
                        lambda d: f"Dir {int(d)}"
                    )

                    if not sel_routes_df.empty:
                        title = (
                            f"Routes in {sel_muni}" if sel_muni != "All"
                            else f"Routes in {sel_reg} region"
                        )
                        fig_re = px.bar(
                            sel_routes_df.sort_values("mean_delay", ascending=False),
                            x="mean_delay", y="label",
                            color="dir_label",
                            barmode="group",
                            orientation="h",
                            labels={"mean_delay": "Mean delay (s)",
                                    "label": "Route", "dir_label": "Direction"},
                            title=title,
                            template=TMPL,
                            height=max(350, 28 * len(sel_routes_df)),
                        )
                        fig_re.add_vline(x=0, line_dash="dash", line_color="gray")
                        st.plotly_chart(fig_re, use_container_width=True)

                        # Summary metrics
                        c1, c2, c3 = st.columns(3)
                        c1.metric("Routes", sel_routes_df["route_id"].nunique())
                        c2.metric("Total rows", f"{sel_routes_df['n_rows'].sum():,}")
                        c3.metric("Mean delay", f"{sel_routes_df['mean_delay'].mean():.1f}s")

                        st.dataframe(
                            sel_routes_df[["route_id","dir_label","n_rows","n_trips",
                                          "mean_delay","n_outliers"]]
                            .rename(columns={"dir_label": "direction"})
                            .sort_values("mean_delay", ascending=False),
                            use_container_width=True, hide_index=True,
                        )
                    else:
                        st.info("No routes found for this selection.")

                # ── GEO SUB-TAB C: MAP ───────────────────────────────────────
                with geo5c:
                    map_regions = ["All regions"] + sorted(
                        geo_df[geo_df["region"] != "Other"]["region"].unique()
                    )
                    map_filter = st.selectbox("Filter map by region", map_regions,
                                              key="map_region_filter")

                    map_df = geo_df[
                        (geo_df["municipality"] != "Unknown") &
                        (geo_df["municipality"] != "Outside Metro Van")
                    ].copy()

                    if map_filter != "All regions":
                        map_df = map_df[map_df["region"] == map_filter]

                    sample = map_df.sample(min(5000, len(map_df)), random_state=42)

                    fig_map = px.scatter_mapbox(
                        sample,
                        lat="stop_lat", lon="stop_lon",
                        color="mean_delay",
                        color_continuous_scale="RdYlGn_r",
                        hover_data={
                            "route_id": True,
                            "municipality": True,
                            "region": True,
                            "mean_delay": ":.1f",
                            "stop_lat": False, "stop_lon": False,
                        },
                        mapbox_style="open-street-map",
                        zoom=9,
                        center={"lat": 49.25, "lon": -123.0},
                        opacity=0.65,
                        title=f"Mean delay by stop — {map_filter} (≤5,000 sampled points)",
                        template=TMPL,
                    )
                    fig_map.update_layout(height=600)
                    st.plotly_chart(fig_map, use_container_width=True)

    except Exception as e:
        st.error(f"Geographic error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — RALPH LOOP (stub)
# ══════════════════════════════════════════════════════════════════════════════
with t6:
    st.info(
        "**Model diagnostics — available after the first Ralph loop iteration.**\n\n"
        "This tab will show:\n"
        "- Posterior predictive check (PPC) overlays\n"
        "- Route-level random effects with 95% credible intervals\n"
        "- Temporal holdout metrics: MAE, RMSE, 90% CI coverage\n"
        "- Route holdout evaluation (6641 vs hand-built M0–M3, 6705 suburban)\n"
        "- Rhat / ESS convergence flags\n"
        "- Run history from `exports/run_log.csv`"
    )
