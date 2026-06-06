"""Unit tests for the pure geo helpers — no I/O, no API, fully deterministic."""

from core.logistics import haversine_distance
from core.tools import group_places_by_zone, optimize_day_route

PARIS = (48.8566, 2.3522)


def test_haversine_known_distance():
    # Louvre area to Arc de Triomphe area is ~1.1-1.2 km.
    d = haversine_distance(48.8566, 2.3522, 48.8606, 2.3376)
    assert 1.0 < d < 1.3


def test_haversine_identical_points_is_zero():
    assert haversine_distance(48.8566, 2.3522, 48.8566, 2.3522) == 0.0


def test_haversine_guard_returns_zero_on_missing_coord():
    # The all([...]) guard treats a 0/None coord as missing and returns 0.0.
    assert haversine_distance(0, 0, 0, 0) == 0.0


def test_group_places_by_zone_buckets_by_distance():
    lat, lon = PARIS
    places = [
        {"name": "near", "lat": lat + 0.01, "lon": lon},  # ~1.1 km
        {"name": "medium", "lat": lat + 0.03, "lon": lon},  # ~3.3 km
        {"name": "far", "lat": lat + 0.10, "lon": lon},  # ~11 km
        {"name": "remote", "lat": lat + 0.50, "lon": lon},  # ~55 km
    ]
    zones = group_places_by_zone(places, lat, lon)
    assert [p["name"] for p in zones["near"]] == ["near"]
    assert [p["name"] for p in zones["medium"]] == ["medium"]
    assert [p["name"] for p in zones["far"]] == ["far"]
    assert [p["name"] for p in zones["remote"]] == ["remote"]


def test_group_places_by_zone_missing_coords_go_remote():
    lat, lon = PARIS
    places = [{"name": "no_coords", "lat": None, "lon": None}]
    zones = group_places_by_zone(places, lat, lon)
    assert [p["name"] for p in zones["remote"]] == ["no_coords"]


def test_optimize_day_route_empty():
    result = optimize_day_route([], *PARIS)
    assert result["optimized_order"] == []
    assert result["total_distance_km"] == 0


def test_optimize_day_route_visits_nearest_first():
    lat, lon = PARIS
    places = [
        {"name": "far", "lat": lat + 0.05, "lon": lon},
        {"name": "near", "lat": lat + 0.005, "lon": lon},
    ]
    result = optimize_day_route(places, lat, lon)
    order = [p["name"] for p in result["optimized_order"]]
    assert order == ["near", "far"]
    assert result["total_distance_km"] > 0
    assert "return_to_hotel_km" in result
