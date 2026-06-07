"""Geo helpers for proximity-based itinerary planning."""

from typing import Any

from .logistics import haversine_distance


def optimize_day_route(places: list[dict[str, Any]], hotel_lat: float, hotel_lon: float) -> dict[str, Any]:
    """Order places for a single day via nearest-neighbor, starting and ending at the hotel."""
    if not places:
        return {"optimized_order": [], "total_distance_km": 0}

    remaining = list(places)
    ordered = []
    current_lat, current_lon = hotel_lat, hotel_lon
    total_distance = 0

    while remaining:
        nearest = min(
            remaining, key=lambda p: haversine_distance(current_lat, current_lon, p.get("lat", 0), p.get("lon", 0))
        )

        dist = haversine_distance(current_lat, current_lon, nearest.get("lat", 0), nearest.get("lon", 0))
        total_distance += dist

        ordered.append(
            {
                "name": nearest.get("name", "Unknown"),
                "lat": nearest.get("lat"),
                "lon": nearest.get("lon"),
                "distance_from_previous_km": round(dist, 2),
            }
        )

        current_lat, current_lon = nearest.get("lat", 0), nearest.get("lon", 0)
        remaining.remove(nearest)

    return_dist = haversine_distance(current_lat, current_lon, hotel_lat, hotel_lon)
    total_distance += return_dist

    return {
        "optimized_order": ordered,
        "total_distance_km": round(total_distance, 2),
        "return_to_hotel_km": round(return_dist, 2),
        "estimated_travel_time_min": int(total_distance * 3),
    }


def group_places_by_zone(places: list[dict], hotel_lat: float, hotel_lon: float) -> dict[str, list[dict]]:
    """Group places into proximity zones: near (<2km), medium (2-5), far (5-15), remote (15+)."""
    zones = {"near": [], "medium": [], "far": [], "remote": []}

    for place in places:
        lat = place.get("lat")
        lon = place.get("lon")

        if lat is None or lon is None:
            zones["remote"].append(place)
            continue

        dist = haversine_distance(lat, lon, hotel_lat, hotel_lon)

        if dist <= 2.0:
            zones["near"].append(place)
        elif dist <= 5.0:
            zones["medium"].append(place)
        elif dist <= 15.0:
            zones["far"].append(place)
        else:
            zones["remote"].append(place)

    return zones
