"""Unit tests for the pure geo helpers — no I/O, no API, fully deterministic."""

from core.geo import build_itinerary_geo, group_places_by_zone, optimize_day_route
from core.logistics import haversine_distance

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


def test_optimize_day_route_carries_place_type():
    # The map payload needs to know whether a stop is an activity or a restaurant.
    lat, lon = PARIS
    result = optimize_day_route([{"name": "x", "lat": lat + 0.01, "lon": lon, "_type": "restaurant"}], lat, lon)
    assert result["optimized_order"][0]["_type"] == "restaurant"


# build_itinerary_geo — the map payload assembled from route-optimized zone groups


def _place(name, lat, lon, kind="activity"):
    return {"name": name, "lat": lat, "lon": lon, "_type": kind}


def test_build_itinerary_geo_numbers_nonempty_zones_in_order():
    zone_groups = {
        "near": [_place("A", 48.86, 2.35)],
        "medium": [],
        "far": [_place("B", 48.90, 2.35), _place("C", 48.91, 2.36)],
        "remote": [],
    }
    out = build_itinerary_geo(zone_groups, {"name": "Hotel", "lat": 48.85, "lon": 2.35})

    assert out["hotel"] == {"name": "Hotel", "lat": 48.85, "lon": 2.35}
    assert [d["day"] for d in out["days"]] == [1, 2]
    assert [d["zone"] for d in out["days"]] == ["near", "far"]
    # Each place is slimmed to exactly what the map needs.
    assert out["days"][0]["places"][0] == {"name": "A", "lat": 48.86, "lon": 2.35, "kind": "activity"}


def test_build_itinerary_geo_preserves_given_order():
    zone_groups = {
        "near": [_place("first", 1.0, 1.0), _place("second", 2.0, 2.0)],
        "medium": [],
        "far": [],
        "remote": [],
    }
    out = build_itinerary_geo(zone_groups, None)
    assert [p["name"] for p in out["days"][0]["places"]] == ["first", "second"]


def test_build_itinerary_geo_without_hotel_still_yields_days():
    # Situation-aware: a hotel-less, centroid-grouped plan still maps.
    zone_groups = {"near": [_place("market", 41.39, 2.16, "restaurant")], "medium": [], "far": [], "remote": []}
    out = build_itinerary_geo(zone_groups, None)
    assert out["hotel"] is None
    assert len(out["days"]) == 1
    assert out["days"][0]["places"][0]["kind"] == "restaurant"


def test_build_itinerary_geo_skips_places_missing_coords():
    zone_groups = {
        "near": [_place("ok", 1.0, 1.0), {"name": "nocoord", "lat": None, "lon": None, "_type": "activity"}],
        "medium": [],
        "far": [],
        "remote": [],
    }
    out = build_itinerary_geo(zone_groups, None)
    assert [p["name"] for p in out["days"][0]["places"]] == ["ok"]


def test_build_itinerary_geo_empty_when_no_coords_anywhere():
    out = build_itinerary_geo({"near": [], "medium": [], "far": [], "remote": []}, None)
    assert out == {"hotel": None, "days": []}


def test_build_itinerary_geo_drops_hotel_without_coords():
    out = build_itinerary_geo(
        {"near": [_place("A", 1.0, 1.0)], "medium": [], "far": [], "remote": []},
        {"name": "H", "lat": None, "lon": None},
    )
    assert out["hotel"] is None
    assert len(out["days"]) == 1


def test_build_itinerary_geo_labels_each_zone():
    zone_groups = {
        "near": [_place("A", 1.0, 1.0)],
        "medium": [_place("B", 2.0, 2.0)],
        "far": [_place("C", 3.0, 3.0)],
        "remote": [_place("D", 4.0, 4.0)],
    }
    out = build_itinerary_geo(zone_groups, None)
    assert {d["zone"]: d["label"] for d in out["days"]} == {
        "near": "Walkable",
        "medium": "Short transit",
        "far": "Across town",
        "remote": "Day trip",
    }
