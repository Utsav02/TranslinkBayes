import os
import requests
import sqlite3
import logging
from google.transit import gtfs_realtime_pb2
from datetime import datetime, timezone
import pytz
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Load API key from .env
load_dotenv()
API_KEY = os.getenv("API_KEY")

# GTFS Realtime API Endpoints
REALTIME_VEHICLE_URL = f"https://gtfsapi.translink.ca/v3/gtfsposition?apikey={API_KEY}"
TRIP_UPDATES_URL = f"https://gtfsapi.translink.ca/v3/gtfsrealtime?apikey={API_KEY}"

# Set up logging
LOG_FILE = "logs/collect_realtime.log"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Connect to databases
conn_realtime = sqlite3.connect("database/gtfs_realtime.db")
cursor_realtime = conn_realtime.cursor()

conn_static = sqlite3.connect("database/gtfs_static.db")
cursor_static = conn_static.cursor()

# 🚀 Helper Functions
PACIFIC_TZ = pytz.timezone("America/Vancouver")

def convert_to_pacific(utc_time_str):
    """Convert UTC time to Pacific Time."""
    if utc_time_str:
        utc_time = datetime.fromisoformat(utc_time_str.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        return utc_time.astimezone(PACIFIC_TZ).strftime("%Y-%m-%d %H:%M:%S")
    return None

def fetch_realtime_data(url, data_type):
    """Fetch GTFS Realtime data from TransLink API."""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            logging.info(f"✅ Successfully fetched {data_type} data from API.")
            return response.content
        else:
            logging.error(f"❌ API request failed for {data_type}: {response.status_code}")
            return None
    except requests.RequestException as e:
        logging.error(f"❌ Network error fetching {data_type}: {e}")
        return None

def preload_scheduled_arrivals():
    """Preload scheduled arrival times from stop_times to reduce database queries."""
    cursor_static.execute("SELECT trip_id, stop_id, arrival_time FROM stop_times")
    return {(row[0], row[1]): row[2] for row in cursor_static.fetchall()}

def get_scheduled_arrival(trip_id, stop_id):
    """Retrieve scheduled arrival time from preloaded data."""
    return scheduled_arrivals.get((trip_id, stop_id), None)

def get_bus_id_for_trip(trip_id):
    """Retrieve the latest bus_id for a trip from vehicle positions."""
    cursor_realtime.execute("""
        SELECT bus_id FROM realtime_vehicle_positions 
        WHERE trip_id = ? ORDER BY timestamp DESC LIMIT 1
    """, (trip_id,))
    result = cursor_realtime.fetchone()
    return result[0] if result else None

# 🚏 Load scheduled arrivals to optimize queries
scheduled_arrivals = preload_scheduled_arrivals()

# 🚦 Store Trip Updates (Delays)
def store_trip_updates():
    """Fetch and store trip delay information."""
    data = fetch_realtime_data(TRIP_UPDATES_URL, "trip_updates")
    if not data: 
        logging.info("⚠️ No trip updates available.")
        return

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(data)

    count = 0
    trip_updates = []

    for entity in feed.entity:
        if entity.HasField("trip_update"):
            trip_update = entity.trip_update
            trip_id = trip_update.trip.trip_id
            route_id = trip_update.trip.route_id  # ✅ Added route_id
            bus_id = get_bus_id_for_trip(trip_id)

            for stop_time_update in trip_update.stop_time_update:
                stop_id = stop_time_update.stop_id
                stop_sequence = stop_time_update.stop_sequence
                actual_arrival_utc = datetime.fromtimestamp(stop_time_update.arrival.time, timezone.utc) if stop_time_update.arrival.time else None
                actual_arrival_pacific = convert_to_pacific(actual_arrival_utc.isoformat()) if actual_arrival_utc else None
                delay_seconds = stop_time_update.arrival.delay if stop_time_update.arrival.HasField("delay") else None
                scheduled_arrival = get_scheduled_arrival(trip_id, stop_id)

                trip_updates.append((
                    trip_id, route_id, stop_id, stop_sequence, actual_arrival_utc, actual_arrival_pacific, delay_seconds,
                    bus_id, datetime.now(timezone.utc)
                ))

    logging.info(f"📝 Preparing {len(trip_updates)} trip updates for insertion.")

    cursor_realtime.executemany("""
        INSERT INTO stop_delays (
            trip_id, route_id, stop_id, stop_sequence, actual_arrival, actual_arrival_pacific, delay_seconds, 
            bus_id, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trip_id, stop_id) DO UPDATE SET 
            actual_arrival = excluded.actual_arrival,
            actual_arrival_pacific = excluded.actual_arrival_pacific,
            delay_seconds = excluded.delay_seconds,
            bus_id = excluded.bus_id
    """, trip_updates)

    conn_realtime.commit()
    logging.info(f"✅ Stored {len(trip_updates)} trip updates successfully.")

# 🚀 Run Collection
logging.info("🚀 Running collect_realtime.py...")
store_trip_updates()
logging.info("✅ Finished collecting real-time data.")

conn_realtime.close()
conn_static.close()
