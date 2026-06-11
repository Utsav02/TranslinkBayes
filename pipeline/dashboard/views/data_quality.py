"""Tab 4 — Data Quality."""
import plotly.express as px
import streamlit as st

from dashboard.charts import add_fifa
from dashboard.constants import ANOMALY_ROUTES, DATA_START
from dashboard.data import daily_counts, null_rates, seq_integrity, stale_pct


def render(DF, DT, TMPL):
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
