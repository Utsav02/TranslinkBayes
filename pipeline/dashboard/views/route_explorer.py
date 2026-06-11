"""Tab 3 — Route Explorer."""
import plotly.express as px
import streamlit as st

from dashboard.charts import add_fifa, route_label
from dashboard.constants import ANOMALY_ROUTES, HOLDOUT_ROUTES
from dashboard.data import (
    delay_histogram,
    route_by_hour,
    route_daily,
    route_hist,
    route_labels,
    route_summary,
)


def render(DF, DT, TMPL):
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
