"""Tab 2 — Delay Distributions."""
import plotly.express as px
import streamlit as st

from dashboard.charts import route_label
from dashboard.constants import ANOMALY_ROUTES, DOW_LABELS
from dashboard.data import (
    delay_by_dow,
    delay_by_hour,
    delay_histogram,
    delay_stats,
    route_labels,
    route_summary,
)


def render(DF, DT, TMPL):
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
