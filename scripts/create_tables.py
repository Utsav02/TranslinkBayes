import sqlite3
import os

# Ensure the database directory exists
os.makedirs("database", exist_ok=True)

# Connect to the databases
conn_static = sqlite3.connect("database/gtfs_static.db")
cursor_static = conn_static.cursor()

conn_realtime = sqlite3.connect("database/gtfs_realtime.db")
cursor_realtime = conn_realtime.cursor()

# 🚏 GTFS Static Tables (Schedules, Routes, Stops)
cursor_static.executescript("""
CREATE TABLE IF NOT EXISTS stops (
    stop_id TEXT PRIMARY KEY,
    stop_name TEXT,
    stop_lat REAL,
    stop_lon REAL
);

CREATE TABLE IF NOT EXISTS routes (
    route_id TEXT PRIMARY KEY,
    route_short_name TEXT,
    route_long_name TEXT
);

CREATE TABLE IF NOT EXISTS trips (
    trip_id TEXT PRIMARY KEY,
    route_id TEXT,
    service_id TEXT,
    trip_headsign TEXT,
    FOREIGN KEY (route_id) REFERENCES routes(route_id)
);

CREATE TABLE IF NOT EXISTS stop_times (
    trip_id TEXT,
    stop_id TEXT,
    stop_sequence INTEGER,
    arrival_time TEXT,
    departure_time TEXT,
    shape_dist_traveled REAL,  -- ✅ Uses GTFS-provided distance
    PRIMARY KEY (trip_id, stop_id),
    FOREIGN KEY (trip_id) REFERENCES trips(trip_id),
    FOREIGN KEY (stop_id) REFERENCES stops(stop_id)
);

-- Add Index for Performance
CREATE INDEX IF NOT EXISTS idx_stop_times_trip_stop ON stop_times (trip_id, stop_id);
""")

# 🕒 Real-Time GTFS Tables (Live Positions, Delays)
cursor_realtime.executescript("""
CREATE TABLE IF NOT EXISTS realtime_vehicle_positions (
    timestamp TEXT,
    route_id TEXT,
    trip_id TEXT,
    stop_id TEXT,
    latitude REAL,
    longitude REAL,
    bus_id TEXT,
    vehicle_label TEXT,
    PRIMARY KEY (bus_id, timestamp),
    FOREIGN KEY (trip_id) REFERENCES trips(trip_id),
    FOREIGN KEY (stop_id) REFERENCES stops(stop_id)
);

CREATE TABLE IF NOT EXISTS stop_delays (
    trip_id TEXT,
    route_id TEXT,
    stop_id TEXT,
    stop_sequence INTEGER,
    actual_arrival TEXT,
    actual_arrival_pacific TEXT,
    delay_seconds INTEGER,
    bus_id TEXT,
    previous_stop_delay INTEGER,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (trip_id, stop_id),
    FOREIGN KEY (trip_id) REFERENCES trips(trip_id),
    FOREIGN KEY (stop_id) REFERENCES stops(stop_id)
);

-- Add Index for Performance
CREATE INDEX IF NOT EXISTS idx_stop_delays_trip_stop ON stop_delays (trip_id, stop_id);
""")

# Commit & Close
conn_static.commit()
conn_realtime.commit()
conn_static.close()
conn_realtime.close()

print("✅ Database tables created successfully.")
