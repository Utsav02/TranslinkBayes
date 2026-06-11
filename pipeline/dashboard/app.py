"""
TransLink Data Health Dashboard
Run: venv/bin/python3 -m streamlit run pipeline/dashboard/app.py
"""
import sys
from pathlib import Path

# Streamlit runs this file as a script: put pipeline/ on sys.path so the
# `dashboard` package and `config` import the same way as sibling scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

st.set_page_config(
    page_title="TransLink Health",
    page_icon="🚌",
    layout="wide",
)

from dashboard import sidebar
from dashboard.views import (
    collection_health,
    data_quality,
    delay_distributions,
    geographic,
    ralph_loop,
    route_explorer,
)

DF, DT, TMPL = sidebar.render()

t1, t2, t3, t4, t5, t6 = st.tabs([
    "📡 Collection Health",
    "📊 Delay Distributions",
    "🔍 Route Explorer",
    "🧹 Data Quality",
    "🗺️ Geographic",
    "🔬 Ralph Loop",
])

with t1:
    collection_health.render(DF, DT, TMPL)
with t2:
    delay_distributions.render(DF, DT, TMPL)
with t3:
    route_explorer.render(DF, DT, TMPL)
with t4:
    data_quality.render(DF, DT, TMPL)
with t5:
    geographic.render(DF, DT, TMPL)
with t6:
    ralph_loop.render()
