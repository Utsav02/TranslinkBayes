"""Tab 6 — Ralph Loop (stub until first model-fit iteration)."""
import streamlit as st


def render():
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
