import sqlite3
import pandas as pd
import os
import subprocess

# Database path
DB_FILE = "database/gtfs_static.db"
STATIC_GTFS_DIR = "data/gtfs_static/"

def get_latest_gtfs_folder():
    """Finds the most recent GTFS static folder in 'data/gtfs_static/'."""
    subfolders = [f for f in os.listdir(STATIC_GTFS_DIR) if os.path.isdir(os.path.join(STATIC_GTFS_DIR, f))]
    if not subfolders:
        return STATIC_GTFS_DIR  # If no subfolders, use the current directory
    latest_folder = max(subfolders)  # Sort by date format
    return os.path.join(STATIC_GTFS_DIR, latest_folder)

# Detect latest static GTFS folder
latest_gtfs_dir = get_latest_gtfs_folder()
print(f"Using latest GTFS static data from: {latest_gtfs_dir}")

# Connect to SQLite
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

try:
    # Load static files
    stops = pd.read_csv(os.path.join(latest_gtfs_dir, "stops.txt"))
    routes = pd.read_csv(os.path.join(latest_gtfs_dir, "routes.txt"))
    stop_times = pd.read_csv(os.path.join(latest_gtfs_dir, "stop_times.txt"))
    trips = pd.read_csv(os.path.join(latest_gtfs_dir, "trips.txt"))

    # Insert into database
    stops.to_sql("stops", conn, if_exists="replace", index=False)
    routes.to_sql("routes", conn, if_exists="replace", index=False)
    stop_times.to_sql("stop_times", conn, if_exists="replace", index=False)
    trips.to_sql("trips", conn, if_exists="replace", index=False)

    conn.commit()
    print("✅ Static GTFS Data Processed Successfully.")
    
except Exception as e:
    print(f"❌ Error loading GTFS static data: {e}")

# Close connection
conn.close()
