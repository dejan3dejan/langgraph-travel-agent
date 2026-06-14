"""Geo helpers for proximity-based itinerary planning."""

import re
import unicodedata
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
                "_type": nearest.get("_type"),
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


# Map payload: turn the route-optimized zone groups into per-day markers for the client.

_ZONE_ORDER = ["near", "medium", "far", "remote"]
_ZONE_LABELS = {"near": "Walkable", "medium": "Short transit", "far": "Across town", "remote": "Day trip"}


def build_itinerary_geo(zone_groups: dict[str, list[dict]], hotel: dict | None) -> dict[str, Any]:
    """Assemble the {hotel, days} map payload from route-optimized proximity zones.

    Each non-empty zone becomes a day, numbered in proximity order, keeping the optimized visiting
    order so the client can draw the route line. Pure: no I/O. An anchor-less or fully un-geocoded
    plan yields {hotel: None, days: []}, which the frontend renders as a no-map fallback.
    """
    days = []
    for zone in _ZONE_ORDER:
        places = [
            {"name": p.get("name"), "lat": p["lat"], "lon": p["lon"], "kind": p.get("_type") or "place"}
            for p in zone_groups.get(zone, [])
            if p.get("lat") is not None and p.get("lon") is not None
        ]
        if not places:
            continue
        days.append({"day": len(days) + 1, "zone": zone, "label": _ZONE_LABELS[zone], "places": places})

    hotel_out = None
    if hotel and hotel.get("lat") is not None and hotel.get("lon") is not None:
        hotel_out = {"name": hotel.get("name"), "lat": hotel["lat"], "lon": hotel["lon"]}

    return {"hotel": hotel_out, "days": days}


# build_itinerary_geo_from_days: the same map payload, but days come from the itinerary's real day
# assignment (which stops are Day 1, Day 2, ...) rather than proximity zones, so a multi-day trip in
# a compact city no longer collapses to a single map day.


def _normalize_name(name: str) -> str:
    """Loose key for matching an LLM-emitted stop name back to a geocoded place: lowercase, strip
    accents and punctuation, drop a leading 'the'. Tolerates minor drift like 'The Louvre' vs
    'Louvre' or 'Musee dOrsay' vs 'Musée d'Orsay'."""
    decomposed = unicodedata.normalize("NFKD", name or "")
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9 ]", "", ascii_only.lower())
    cleaned = re.sub(r"^the ", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _build_place_index(places: list[dict]) -> dict[str, dict]:
    """Normalized-name -> slim geocoded place. Places without coords are skipped: they can't be
    plotted, so a stop pointing at one is treated as unmatched."""
    index = {}
    for p in places:
        if p.get("lat") is None or p.get("lon") is None:
            continue
        index[_normalize_name(p.get("name", ""))] = {
            "name": p.get("name"),
            "lat": p["lat"],
            "lon": p["lon"],
            "kind": p.get("_type") or "place",
        }
    return index


def build_itinerary_geo_from_days(days: list[dict[str, Any]], places: list[dict], hotel: dict | None) -> dict[str, Any]:
    """Assemble the {hotel, days} map payload from the itinerary's real per-day assignment.

    `days` is the compiler's structured pass: [{"day", "title", "stops": [place names]}], where each
    stop names a place from `places`. Stops are matched back to their geocoded place to attach
    coords, preserving the given order so the route line follows the narrative. The itinerary's own
    day numbers and titles are kept, so the map's day count matches the text. A day whose stops all
    fail to match is dropped (it can't be plotted). Pure: no I/O.
    """
    index = _build_place_index(places)
    out_days = []
    for d in days:
        located = []
        for name in d.get("stops", []):
            place = index.get(_normalize_name(name))
            if place is not None:
                located.append(place)
        if located:
            out_days.append({"day": d.get("day"), "title": d.get("title"), "places": located})

    hotel_out = None
    if hotel and hotel.get("lat") is not None and hotel.get("lon") is not None:
        hotel_out = {"name": hotel.get("name"), "lat": hotel["lat"], "lon": hotel["lon"]}

    return {"hotel": hotel_out, "days": out_days}
