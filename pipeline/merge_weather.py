"""
Merge weather_hourly.parquet (Vancouver Harbour CS 888) with
weather_hourly_yvr.parquet (Vancouver Intl A / YVR 51442) into a single
`exports/weather_hourly.parquet` with a `source_station` column so downstream
consumers can see which station each row came from.

Rule:
  - Prefer Harbour on every (service_date, hour) where Harbour has non-null
    temp_c. Harbour is the downtown micro-climate closest to BC Place and the
    FIFA-affected bus routes.
  - Fall back to YVR when Harbour temp_c is NULL (station outage 2026-06-13
    → 2026-06-30 in the current data; may recur).
  - `source_station` = 'harbour_888' or 'yvr_51442'.

Idempotent — writing the merged file twice produces the same result. Safe to
re-run after either fetch script.

Usage:
    python pipeline/merge_weather.py
"""
from pathlib import Path

import pandas as pd

from config import EXPORT_DIR

HARBOUR_PATH = EXPORT_DIR / "weather_hourly.parquet"          # will be overwritten
YVR_PATH     = EXPORT_DIR / "weather_hourly_yvr.parquet"
HARBOUR_STAGE = EXPORT_DIR / "weather_hourly_harbour.parquet"  # source of truth for harbour rows


def main() -> None:
    # If the current weather_hourly.parquet already has source_station, someone's
    # merged before — treat it as the merge output, not the harbour source, and
    # fail loudly.
    if HARBOUR_PATH.exists():
        head = pd.read_parquet(HARBOUR_PATH, columns=None)
        if "source_station" in head.columns and not HARBOUR_STAGE.exists():
            # Preserve the pre-existing harbour-only slice as the stage.
            # A harbour row is one where source_station starts with 'harbour'.
            harbour_only = head[head["source_station"].str.startswith("harbour")].copy()
            harbour_only = harbour_only.drop(columns=["source_station"])
            harbour_only.to_parquet(HARBOUR_STAGE, index=False)
            print(f"Extracted harbour rows to {HARBOUR_STAGE}")

    if not HARBOUR_STAGE.exists():
        # First-time run — the current weather_hourly.parquet is pure harbour.
        # Save as the stage before we overwrite it with the merged result.
        pd.read_parquet(HARBOUR_PATH).to_parquet(HARBOUR_STAGE, index=False)
        print(f"Staged current harbour parquet to {HARBOUR_STAGE}")

    harbour = pd.read_parquet(HARBOUR_STAGE)
    yvr     = pd.read_parquet(YVR_PATH)

    key = ["service_date", "hour"]
    harbour["source_station"] = "harbour_888"
    yvr["source_station"]     = "yvr_51442"

    # Harbour rows we can keep (temp_c is populated OR any other feature we care about)
    # Simplest rule: keep every harbour row where temp_c is present; substitute YVR
    # for the harbour rows where temp_c is null.
    good_harbour = harbour[harbour["temp_c"].notna()].copy()
    bad_harbour_keys = harbour.loc[harbour["temp_c"].isna(), key]

    yvr_replace = yvr.merge(bad_harbour_keys, on=key, how="inner")

    # And YVR-only rows that harbour doesn't have at all (rare, but future-proof)
    yvr_only = yvr.merge(harbour[key], on=key, how="left", indicator=True)
    yvr_only = yvr_only[yvr_only["_merge"] == "left_only"].drop(columns=["_merge"])

    merged = pd.concat([good_harbour, yvr_replace, yvr_only], ignore_index=True)
    merged = merged.drop_duplicates(subset=key, keep="first")
    merged = merged.sort_values(key).reset_index(drop=True)

    # Sanity: any (date, hour) with NULL temp_c after merge?
    remaining_null = merged["temp_c"].isna().sum()

    merged.to_parquet(HARBOUR_PATH, index=False)
    print(f"Wrote merged {len(merged):,} rows → {HARBOUR_PATH}")
    print("Source composition:")
    print(merged["source_station"].value_counts().to_string())
    print(f"\ntemp_c still NaN after merge: {remaining_null} rows ({100*remaining_null/len(merged):.2f}%)")


if __name__ == "__main__":
    main()
