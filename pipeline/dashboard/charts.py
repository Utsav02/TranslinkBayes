"""Plotting helpers shared across tabs."""
from dashboard.constants import ANOMALY_ROUTES, FIFA_MATCH_DATES, HOLDOUT_ROUTES


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
