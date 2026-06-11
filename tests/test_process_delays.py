"""Smoke tests for the pure temporal/spatial feature derivation in
pipeline/process_delays.py. No database needed — these functions take and
return plain DataFrames.
"""
import sys
from pathlib import Path

import pandas as pd

# pipeline/ scripts import each other top-level (`from config import ...`),
# so put pipeline/ itself on sys.path, same as running a script from there.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from process_delays import _add_temporal, _normalize_dist  # noqa: E402


def test_add_temporal_converts_utc_to_pacific_and_flags():
    df = pd.DataFrame({
        "timestamp": [
            "2026-06-08T15:30:00Z",  # Mon 08:30 PDT — morning rush
            "2026-06-09T23:30:00Z",  # Tue 16:30 PDT — evening rush
            "2026-06-10T19:00:00Z",  # Wed 12:00 PDT — midday, not rush
            "2026-06-07T03:00:00Z",  # Sat 20:00 PDT (Jun 6) — weekend
        ]
    })

    out = _add_temporal(df)

    assert out["hour"].tolist() == [8, 16, 12, 20]
    assert out["dow"].tolist() == [0, 1, 2, 5]          # Mon, Tue, Wed, Sat
    assert out["is_rush_hour"].tolist() == [1, 1, 0, 0]
    assert out["is_weekend"].tolist() == [0, 0, 0, 1]


def test_add_temporal_rush_hour_boundaries():
    # Rush is 7-9 and 16-18 inclusive (Pacific). 06:59 and 19:00 are not rush.
    df = pd.DataFrame({
        "timestamp": [
            "2026-06-08T13:59:00Z",  # Mon 06:59 PDT — just before morning rush
            "2026-06-08T14:00:00Z",  # Mon 07:00 PDT — rush starts
            "2026-06-08T16:59:00Z",  # Mon 09:59 PDT — hour 9 still rush
            "2026-06-09T02:00:00Z",  # Mon 19:00 PDT — rush over
        ]
    })

    out = _add_temporal(df)

    assert out["is_rush_hour"].tolist() == [0, 1, 1, 0]


def test_normalize_dist_rebases_each_trip_to_zero():
    df = pd.DataFrame({
        "trip_id": ["A", "A", "A", "B", "B"],
        "shape_dist_traveled": [100.0, 250.0, 400.0, 7000.0, 7500.0],
    })

    out = _normalize_dist(df)

    # Each trip starts at 0; relative spacing within the trip is preserved.
    assert out[out["trip_id"] == "A"]["shape_dist_traveled"].tolist() == [0.0, 150.0, 300.0]
    assert out[out["trip_id"] == "B"]["shape_dist_traveled"].tolist() == [0.0, 500.0]


def test_normalize_dist_keeps_nan_rows_nan():
    # Unmatched stop_times joins leave NaN distances; normalization must not
    # invent values for them, and must still rebase the non-NaN rows.
    df = pd.DataFrame({
        "trip_id": ["A", "A", "A"],
        "shape_dist_traveled": [200.0, float("nan"), 500.0],
    })

    out = _normalize_dist(df)
    vals = out["shape_dist_traveled"]

    assert vals.iloc[0] == 0.0
    assert pd.isna(vals.iloc[1])
    assert vals.iloc[2] == 300.0
