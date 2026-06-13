"""
Fetch Environment & Climate Change Canada (ECCC) hourly weather and emit a
parquet keyed on Pacific (service_date, hour) for joining to processed_stops.

Free, no API key. Source: the ECCC "bulk data" endpoint, which returns one
month of hourly observations per request:

    https://climate.weather.gc.ca/climate_data/bulk_data_e.html
        ?format=csv&stationID=<ID>&Year=<Y>&Month=<M>&Day=1
        &timeframe=1&submit=Download+Data
    (timeframe=1 = hourly; Day is ignored for hourly — the whole month returns)

Supports model-loop candidate C7. The output joins to the model features on the
SAME hour definition process_delays.py uses (America/Vancouver local hour).

⚠ Timezone correctness (the easy bug): ECCC "Date/Time (LST)" is Local STANDARD
Time — for BC that is UTC-8 ALL YEAR (no daylight saving). America/Vancouver in
summer is PDT = UTC-7. A naive hour-for-hour join would be off by one hour for
the entire FIFA window. This script localizes LST as a fixed UTC-8 offset,
converts to UTC, then to America/Vancouver, so the (date, hour) key matches
process_delays' `_add_temporal()` exactly.

Station IDs are the ECCC INTERNAL stationID (not the climate ID):
    Vancouver Harbour CS   climate 1108446   stationID 888   (downtown, closest
                                                              to BC Place)
    Vancouver Intl A (YVR) climate 1108395   stationID 51442 (airport, fallback)
The internal stationID is verified on first fetch (the CSV header echoes the
station name); if it is wrong the script aborts loudly rather than write a
parquet keyed to the wrong place.

Usage:
    python pipeline/fetch_weather_eccc.py --since 2026-05-01           # to today
    python pipeline/fetch_weather_eccc.py --since 2026-05-01 --until 2026-06-30
    python pipeline/fetch_weather_eccc.py --station 51442 --since 2026-06-01
    python pipeline/fetch_weather_eccc.py --since 2026-06-01 --dry-run  # no write
"""
import argparse
import io
import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from config import EXPORT_DIR, LOG_DIR, PACIFIC_TZ, ROOT

BULK_URL = "https://climate.weather.gc.ca/climate_data/bulk_data_e.html"

# Default: Vancouver Harbour CS — downtown, the relevant micro-climate for the
# BC Place / downtown routes that carry FIFA crowds.
DEFAULT_STATION_ID   = 888
EXPECTED_STATION_HINT = "VANCOUVER HARBOUR"   # substring expected in the CSV header

LST_TZ   = timezone(timedelta(hours=-8))      # BC Local Standard Time, fixed UTC-8
RAW_DIR  = ROOT / "data" / "weather"
OUT_PATH = EXPORT_DIR / "weather_hourly.parquet"

LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    filename=str(LOG_DIR / "fetch_weather_eccc.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ECCC hourly column names (stable across years). We keep a small, modelling-
# relevant subset; rename to snake_case the loop join script expects.
_COLMAP = {
    "Date/Time (LST)":  "lst_str",
    "Temp (°C)":        "temp_c",
    "Dew Point Temp (°C)": "dew_point_c",
    "Rel Hum (%)":      "rel_hum_pct",
    "Precip. Amount (mm)": "precip_mm",
    "Wind Spd (km/h)":  "wind_kmh",
    "Stn Press (kPa)":  "stn_press_kpa",
    "Weather":          "weather_desc",
}


def _months(since: date, until: date):
    """Yield (year, month) tuples spanning the inclusive range."""
    y, m = since.year, since.month
    while (y, m) <= (until.year, until.month):
        yield y, m
        m += 1
        if m > 12:
            m, y = 1, y + 1


def _fetch_month(station_id: int, year: int, month: int) -> str:
    params = {
        "format": "csv", "stationID": station_id,
        "Year": year, "Month": month, "Day": 1,
        "timeframe": 1, "submit": "Download Data",
    }
    r = requests.get(BULK_URL, params=params, timeout=60)
    r.raise_for_status()
    return r.text


def _parse_month(csv_text: str) -> pd.DataFrame:
    # ECCC CSVs are clean CSV with a single header row (the legacy multi-line
    # preamble is gone on the bulk endpoint when format=csv). Read, then keep
    # the subset of columns that exist (older months may lack a few).
    df = pd.read_csv(io.StringIO(csv_text))
    present = {k: v for k, v in _COLMAP.items() if k in df.columns}
    if "Date/Time (LST)" not in present:
        raise ValueError("CSV missing 'Date/Time (LST)' — endpoint format changed")
    df = df[list(present)].rename(columns=present)
    return df


def _to_pacific_keys(df: pd.DataFrame) -> pd.DataFrame:
    # LST string -> aware UTC-8 -> America/Vancouver, then derive the join keys
    # exactly as process_delays._add_temporal does (local date + local hour).
    lst = pd.to_datetime(df["lst_str"], errors="coerce")
    aware = lst.dt.tz_localize(LST_TZ)
    pac = aware.dt.tz_convert(PACIFIC_TZ)
    df = df.drop(columns=["lst_str"])
    df.insert(0, "service_date", pac.dt.strftime("%Y-%m-%d"))
    df.insert(1, "hour", pac.dt.hour.astype("Int64"))
    df = df.dropna(subset=["service_date", "hour"])
    # Precip NaN in ECCC hourly usually means "no measurable precip" → 0.0 is the
    # modelling-honest fill ONLY for precip; leave temp/wind NaN (genuinely missing).
    if "precip_mm" in df.columns:
        df["precip_mm"] = pd.to_numeric(df["precip_mm"], errors="coerce").fillna(0.0)
    return df


def fetch(station_id: int, since: date, until: date, dry_run: bool) -> pd.DataFrame:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    verified = False
    for year, month in _months(since, until):
        cache = RAW_DIR / f"eccc_{station_id}_{year}-{month:02d}.csv"
        if cache.exists():
            csv_text = cache.read_text()
            logging.info("Cache hit %s", cache.name)
        else:
            logging.info("Fetching ECCC station=%s %d-%02d", station_id, year, month)
            csv_text = _fetch_month(station_id, year, month)
            cache.write_text(csv_text)
        # Verify we asked for the station we think we did (header echoes name).
        if not verified:
            head = csv_text[:2000].upper()
            if EXPECTED_STATION_HINT not in head and station_id == DEFAULT_STATION_ID:
                raise SystemExit(
                    f"Station verification failed: '{EXPECTED_STATION_HINT}' not in "
                    f"CSV header for stationID={station_id}. Header start:\n{csv_text[:300]}\n"
                    "Refusing to write a parquet keyed to the wrong station. "
                    "Pass the correct --station."
                )
            verified = True
        frames.append(_parse_month(csv_text))

    raw = pd.concat(frames, ignore_index=True)
    out = _to_pacific_keys(raw)
    # Clip to the requested service-date range (months overshoot at the edges).
    out = out[(out["service_date"] >= since.isoformat()) &
              (out["service_date"] <= until.isoformat())]
    # One row per (date, hour): ECCC hourly already is, but guard against the
    # DST "fall-back" duplicate hour (not in summer, but be safe).
    out = out.drop_duplicates(subset=["service_date", "hour"], keep="first")
    out = out.sort_values(["service_date", "hour"]).reset_index(drop=True)

    logging.info("Parsed %d hourly rows %s..%s", len(out), since, until)
    if dry_run:
        print("[dry-run] no parquet written")
        print(out.head(12).to_string(index=False))
        print(f"... {len(out)} rows total")
        miss = out["temp_c"].isna().mean() if "temp_c" in out else float("nan")
        print(f"temp_c missing: {100*miss:.1f}%   "
              f"precip_mm>0 hours: {(out.get('precip_mm', pd.Series()).gt(0)).sum()}")
        return out

    OUT_PATH.parent.mkdir(exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(out):,} hourly rows → {OUT_PATH}")
    print(f"  range: {out['service_date'].min()} .. {out['service_date'].max()}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fetch ECCC hourly weather → parquet")
    p.add_argument("--station", type=int, default=DEFAULT_STATION_ID,
                   help=f"ECCC internal stationID (default {DEFAULT_STATION_ID} = Vancouver Harbour CS)")
    p.add_argument("--since", required=True, help="ISO date lower bound (inclusive)")
    p.add_argument("--until", help="ISO date upper bound (inclusive); default = today")
    p.add_argument("--dry-run", action="store_true", help="parse + print, do not write parquet")
    args = p.parse_args()

    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until) if args.until else datetime.now(LST_TZ).date()
    fetch(args.station, since, until, args.dry_run)
