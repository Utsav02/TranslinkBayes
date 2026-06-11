"""Tab 5 — Geographic (region/municipality breakdowns + stop map)."""
import plotly.express as px
import streamlit as st

from dashboard.charts import route_label
from dashboard.constants import REGION_GROUPS
from dashboard.data import (
    geo_stop_delay,
    route_labels,
    route_summary,
    stop_municipality_map,
)


def render(DF, DT, TMPL):
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

                with geo5a:
                    _render_overview(geo_df, TMPL)
                with geo5b:
                    _render_region_explorer(route_muni, rs_summary, lmap, TMPL)
                with geo5c:
                    _render_map(geo_df, TMPL)

    except Exception as e:
        st.error(f"Geographic error: {e}")


def _render_overview(geo_df, TMPL):
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


def _render_region_explorer(route_muni, rs_summary, lmap, TMPL):
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


def _render_map(geo_df, TMPL):
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
