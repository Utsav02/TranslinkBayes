from pathlib import Path
from dotenv import load_dotenv
import os

ROOT = Path(__file__).parent.parent

load_dotenv(ROOT / ".env")

API_KEY = os.getenv("API_KEY")

# Databases — v1 is legacy (read-only), v2 is new collection
DB_REALTIME_LEGACY = str(ROOT / "database" / "gtfs_realtime.db")
DB_REALTIME        = str(ROOT / "database" / "gtfs_realtime_v2.db")
DB_STATIC          = str(ROOT / "database" / "gtfs_static.db")

EXPORT_DIR = ROOT / "exports"
LOG_DIR    = ROOT / "logs"

TRIP_UPDATES_URL = f"https://gtfsapi.translink.ca/v3/gtfsrealtime?apikey={API_KEY}"
VEHICLE_URL      = f"https://gtfsapi.translink.ca/v3/gtfsposition?apikey={API_KEY}"

PACIFIC_TZ = "America/Vancouver"
