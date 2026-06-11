"""Sidebar: theme toggle, date range, refresh, last-collection status."""
import sqlite3
from datetime import date, datetime, timezone

import streamlit as st

from dashboard.constants import DATA_START
from dashboard.data import RT_DB


def render():
    """Render the sidebar; return (date_from_iso, date_to_iso, plotly_template)."""
    with st.sidebar:
        st.title("🚌 TransLink Health")

        theme = st.radio("Theme", ["Light", "Dark"], horizontal=True)
        tmpl  = "plotly_dark" if theme == "Dark" else "plotly_white"

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

    return date_from.isoformat(), date_to.isoformat(), tmpl
