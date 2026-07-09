"""Tests for the VehiclePositions collection path in
pipeline/collect_realtime_v2.py.

Covers the pure protobuf-parse function (`parse_vehicle_positions`) with
synthesised feed messages so we can stress specific edge cases, plus
`collect_vehicle_positions` end-to-end against an in-memory SQLite so we
verify the INSERT OR IGNORE semantics and the graceful-failure contract.
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from google.transit import gtfs_realtime_pb2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from collect_realtime_v2 import (  # noqa: E402
    collect_vehicle_positions,
    parse_vehicle_positions,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mk_feed(*vehicles) -> bytes:
    """Build a serialized GTFS-RT FeedMessage containing the given VehiclePosition
    entities. Each `vehicle` is a dict of fields to set."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    for i, v in enumerate(vehicles):
        entity = feed.entity.add()
        entity.id = str(i)
        vp = entity.vehicle
        if "bus_id" in v:
            vp.vehicle.id = v["bus_id"]
        if "label" in v:
            vp.vehicle.label = v["label"]
        if "trip_id" in v:
            vp.trip.trip_id = v["trip_id"]
        if "route_id" in v:
            vp.trip.route_id = v["route_id"]
        if "stop_id" in v:
            vp.stop_id = v["stop_id"]
        if "lat" in v or "lon" in v:
            vp.position.latitude = v.get("lat", 0.0)
            vp.position.longitude = v.get("lon", 0.0)
        if "timestamp" in v:
            vp.timestamp = v["timestamp"]
    return feed.SerializeToString()


def _mk_trip_only_feed() -> bytes:
    """A feed that has only trip_update entities and no vehicle entities.
    parse_vehicle_positions must ignore these entirely."""
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    entity = feed.entity.add()
    entity.id = "trip_only"
    entity.trip_update.trip.trip_id = "T1"
    entity.trip_update.trip.route_id = "R1"
    stu = entity.trip_update.stop_time_update.add()
    stu.stop_id = "S1"
    stu.arrival.time = 1720400000
    return feed.SerializeToString()


# ── parse_vehicle_positions ─────────────────────────────────────────────────

def test_parse_extracts_all_fields_from_a_complete_entity():
    pb = _mk_feed({
        "bus_id": "B123",
        "label": "1234",
        "trip_id": "T-abc",
        "route_id": "R-14",
        "stop_id": "S-60123",
        "lat": 49.2827,
        "lon": -123.1207,
        "timestamp": 1720400000,  # 2024-07-08 01:33:20 UTC
    })

    rows = parse_vehicle_positions(pb)

    assert len(rows) == 1
    ts, route, trip, stop, lat, lon, bus, label = rows[0]
    assert bus == "B123"
    assert label == "1234"
    assert trip == "T-abc"
    assert route == "R-14"
    assert stop == "S-60123"
    # Protobuf serializes position.{latitude,longitude} as float32, so a
    # double-precision literal gets slightly rounded on the round-trip.
    assert lat == pytest.approx(49.2827, abs=1e-4)
    assert lon == pytest.approx(-123.1207, abs=1e-4)
    # timestamp comes from the feed's unix time, UTC. 1720400000 → 2024-07-08 00:53:20Z.
    assert ts.startswith("2024-07-08T00:53:20")
    assert ts.endswith("+00:00")   # explicit UTC offset in the ISO string


def test_parse_skips_entities_without_bus_id():
    # Two vehicles, only the first has bus_id — the second must be dropped
    pb = _mk_feed(
        {"bus_id": "B1", "lat": 49.0, "lon": -123.0, "timestamp": 1720400000},
        {"lat": 49.1, "lon": -123.1, "timestamp": 1720400060},           # no bus_id
    )
    rows = parse_vehicle_positions(pb)
    assert len(rows) == 1
    assert rows[0][6] == "B1"


def test_parse_falls_back_to_injected_now_when_feed_timestamp_missing():
    # Missing feed timestamp → parser uses the injected `now_utc` clock so tests
    # are deterministic (production uses datetime.now(timezone.utc)).
    pb = _mk_feed({"bus_id": "B_notime", "lat": 49.0, "lon": -123.0})
    fixed_now = datetime(2026, 7, 9, 20, 30, 0, tzinfo=timezone.utc)

    rows = parse_vehicle_positions(pb, now_utc=fixed_now)

    assert len(rows) == 1
    assert rows[0][0] == fixed_now.isoformat()


def test_parse_leaves_optional_fields_as_none_when_missing():
    # A vehicle with only bus_id + timestamp — route/trip/stop/label all empty.
    pb = _mk_feed({"bus_id": "B_bare", "timestamp": 1720400000})

    rows = parse_vehicle_positions(pb)

    assert len(rows) == 1
    ts, route, trip, stop, lat, lon, bus, label = rows[0]
    assert bus == "B_bare"
    # Empty protobuf string fields must become None so the SQLite column is NULL
    assert route is None
    assert trip is None
    assert stop is None
    assert label is None
    # position defaults to (0.0, 0.0) when unset — parser passes those through
    # (no field-presence check on lat/lon since proto3 has no HasField for scalars)
    # We assert the entity did have position set; here it didn't, so lat/lon None.
    assert lat is None and lon is None


def test_parse_ignores_trip_update_entities():
    # A feed containing ONLY trip-updates yields zero vehicle rows.
    rows = parse_vehicle_positions(_mk_trip_only_feed())
    assert rows == []


def test_parse_handles_mixed_trip_update_and_vehicle_entities():
    # Real TransLink feeds sometimes have both. We must extract the vehicle
    # and ignore the trip_update entity in the same message.
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    # A trip-only entity
    e1 = feed.entity.add(); e1.id = "1"; e1.trip_update.trip.trip_id = "T1"
    # A vehicle-only entity
    e2 = feed.entity.add(); e2.id = "2"
    e2.vehicle.vehicle.id = "B_mixed"
    e2.vehicle.timestamp = 1720400000
    e2.vehicle.position.latitude = 49.28
    e2.vehicle.position.longitude = -123.12

    rows = parse_vehicle_positions(feed.SerializeToString())

    assert len(rows) == 1
    assert rows[0][6] == "B_mixed"


def test_parse_returns_empty_list_on_empty_feed():
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    assert parse_vehicle_positions(feed.SerializeToString()) == []


# ── collect_vehicle_positions (end-to-end with in-memory SQLite) ────────────

def _mk_temp_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE realtime_vehicle_positions (
            timestamp     TEXT,
            route_id      TEXT,
            trip_id       TEXT,
            stop_id       TEXT,
            latitude      REAL,
            longitude     REAL,
            bus_id        TEXT,
            vehicle_label TEXT,
            PRIMARY KEY (bus_id, timestamp)
        );
    """)
    return conn


def test_collect_inserts_rows_from_a_good_feed(monkeypatch):
    conn = _mk_temp_db()
    pb = _mk_feed(
        {"bus_id": "B1", "trip_id": "T1", "route_id": "R1", "lat": 49.28,
         "lon": -123.12, "timestamp": 1720400000, "label": "1234"},
        {"bus_id": "B2", "trip_id": "T2", "route_id": "R2", "lat": 49.29,
         "lon": -123.11, "timestamp": 1720400060, "label": "1235"},
    )
    # Monkey-patch the module-level fetcher so we don't hit the network
    import collect_realtime_v2 as mod
    monkeypatch.setattr(mod, "_fetch", lambda url: pb)

    n = collect_vehicle_positions(conn)

    assert n == 2
    rows = conn.execute(
        "SELECT bus_id, route_id, latitude, longitude FROM realtime_vehicle_positions ORDER BY bus_id"
    ).fetchall()
    # Two rows, correct bus_id + route_id + Vancouver-area coords (float32 rounding)
    assert [r[0] for r in rows] == ["B1", "B2"]
    assert [r[1] for r in rows] == ["R1", "R2"]
    assert rows[0][2] == pytest.approx(49.28, abs=1e-4)
    assert rows[0][3] == pytest.approx(-123.12, abs=1e-4)
    assert rows[1][2] == pytest.approx(49.29, abs=1e-4)
    assert rows[1][3] == pytest.approx(-123.11, abs=1e-4)


def test_collect_returns_0_on_fetch_failure(monkeypatch):
    conn = _mk_temp_db()
    import collect_realtime_v2 as mod
    monkeypatch.setattr(mod, "_fetch", lambda url: None)  # simulate network error

    n = collect_vehicle_positions(conn)

    assert n == 0
    # No rows inserted
    assert conn.execute("SELECT COUNT(*) FROM realtime_vehicle_positions").fetchone()[0] == 0


def test_collect_swallows_parse_errors(monkeypatch):
    conn = _mk_temp_db()
    import collect_realtime_v2 as mod
    # Return garbage bytes that will fail protobuf parse
    monkeypatch.setattr(mod, "_fetch", lambda url: b"\x00\x01\x02not a real protobuf")

    n = collect_vehicle_positions(conn)

    assert n == 0
    assert conn.execute("SELECT COUNT(*) FROM realtime_vehicle_positions").fetchone()[0] == 0


def test_collect_is_idempotent_on_duplicate_pk(monkeypatch):
    # INSERT OR IGNORE means running the same feed twice must not raise and
    # must not double-count rows.
    conn = _mk_temp_db()
    pb = _mk_feed(
        {"bus_id": "B_dup", "lat": 49.0, "lon": -123.0, "timestamp": 1720400000},
    )
    import collect_realtime_v2 as mod
    monkeypatch.setattr(mod, "_fetch", lambda url: pb)

    n1 = collect_vehicle_positions(conn)
    n2 = collect_vehicle_positions(conn)

    assert n1 == 1 and n2 == 1
    # But only one row actually persisted (INSERT OR IGNORE)
    assert conn.execute("SELECT COUNT(*) FROM realtime_vehicle_positions").fetchone()[0] == 1


def test_collect_writes_positions_within_vancouver_bbox_when_data_is_realistic(monkeypatch):
    # Sanity: a well-formed feed with Vancouver-area coords produces rows
    # whose lat/lon fall in the plausible Metro Vancouver bbox. This is a
    # defensive check against a schema swap (lat↔lon) or unit error.
    conn = _mk_temp_db()
    pb = _mk_feed(
        {"bus_id": "B_vp", "lat": 49.28, "lon": -123.12, "timestamp": 1720400000},
    )
    import collect_realtime_v2 as mod
    monkeypatch.setattr(mod, "_fetch", lambda url: pb)

    collect_vehicle_positions(conn)

    lat, lon = conn.execute(
        "SELECT latitude, longitude FROM realtime_vehicle_positions"
    ).fetchone()
    # Metro Vancouver bbox (loose): lat ~49.0..49.5, lon ~-123.3..-122.5
    assert 49.0 < lat < 49.5, f"lat {lat} outside Metro Vancouver — swapped with lon?"
    assert -123.3 < lon < -122.5, f"lon {lon} outside Metro Vancouver — swapped with lat?"
