"""Tab 1 — Collection Health."""
from datetime import date

import plotly.express as px
import streamlit as st

from dashboard.charts import add_fifa
from dashboard.data import collection_runs, daily_counts, hourly_heatmap


def render(DF, DT, TMPL):
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
