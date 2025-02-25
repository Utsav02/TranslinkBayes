from haversine import haversine
import sqlite3

def compute_stop_distances():
    """Fetch stop lat/lon from GTFS and store distances in stop_distances table."""
    conn = sqlite3.connect("database/gtfs_static.db")
    cursor = conn.cursor()

    # Fetch all consecutive stops in each trip
    cursor.execute("""
        SELECT s1.trip_id, s1.stop_id, s1.stop_sequence, 
               s2.stop_id AS next_stop_id, s2.stop_sequence,
               st1.stop_lat, st1.stop_lon, st2.stop_lat, st2.stop_lon
        FROM stop_times AS s1
        JOIN stop_times AS s2 
          ON s1.trip_id = s2.trip_id 
         AND s1.stop_sequence + 1 = s2.stop_sequence
        JOIN stops AS st1 
          ON s1.stop_id = st1.stop_id
        JOIN stops AS st2 
          ON s2.stop_id = st2.stop_id
    """)

    updates = []
    for row in cursor.fetchall():
        trip_id, stop_id, stop_seq, next_stop_id, next_seq, lat1, lon1, lat2, lon2 = row
        distance_km = haversine((lat1, lon1), (lat2, lon2))
        updates.append((trip_id, stop_id, next_stop_id, distance_km))

    # Insert into stop_distances table
    cursor.executemany("""
        INSERT INTO stop_distances (trip_id, stop_id, next_stop_id, distance_km)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (trip_id, stop_id, next_stop_id) DO UPDATE SET
            distance_km = excluded.distance_km
    """, updates)

    conn.commit()
    conn.close()
    print(f"✅ Updated {len(updates)} stop distances.")

if __name__ == "__main__":
    compute_stop_distances()
