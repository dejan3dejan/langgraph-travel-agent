"""LangChain tools for geocoding, distance, zone classification, and route optimization."""

from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from .logger import get_logger
from .logistics import get_coordinates, haversine_distance

logger = get_logger(__name__)


class GeocodeInput(BaseModel):
    address: str = Field(description="The address or place name to geocode")
    city: str | None = Field(default=None, description="City name for context")


class DistanceInput(BaseModel):
    lat1: float = Field(description="Latitude of first point")
    lon1: float = Field(description="Longitude of first point")
    lat2: float = Field(description="Latitude of second point")
    lon2: float = Field(description="Longitude of second point")


class ZoneCheckInput(BaseModel):
    place_lat: float = Field(description="Latitude of the place to check")
    place_lon: float = Field(description="Longitude of the place to check")
    hotel_lat: float = Field(description="Latitude of the hotel (base)")
    hotel_lon: float = Field(description="Longitude of the hotel (base)")


class RouteOptimizerInput(BaseModel):
    places: list[dict[str, Any]] = Field(description="List of places with lat/lon to optimize")
    hotel_lat: float = Field(description="Hotel latitude (start/end point)")
    hotel_lon: float = Field(description="Hotel longitude (start/end point)")


@tool(args_schema=GeocodeInput)
def geocode_address(address: str, city: str | None = None) -> dict[str, Any]:
    """
    Get latitude and longitude for an address.
    Use this to verify if a location exists and get its coordinates.
    Returns lat, lon, and status (exact/neighborhood/failed).
    """
    lat, lon, status = get_coordinates(address, city=city)
    return {"address": address, "lat": lat, "lon": lon, "status": status, "found": status != "failed"}


@tool(args_schema=DistanceInput)
def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> dict[str, Any]:
    """
    Calculate distance between two points in kilometers.
    Use this to check how far apart two locations are.
    """
    distance_km = haversine_distance(lat1, lon1, lat2, lon2)

    walk_time_min = int(distance_km * 12)
    transit_time_min = int(distance_km * 3)

    return {
        "distance_km": round(distance_km, 2),
        "walk_time_min": walk_time_min,
        "transit_time_min": transit_time_min,
        "is_walkable": distance_km <= 2.0,
        "recommendation": "Walk" if distance_km <= 2.0 else "Use public transport or taxi",
    }


@tool(args_schema=ZoneCheckInput)
def check_zone(place_lat: float, place_lon: float, hotel_lat: float, hotel_lon: float) -> dict[str, Any]:
    """
    Check which zone a place falls into relative to the hotel.
    Use this to group activities by proximity.
    """
    distance_km = haversine_distance(place_lat, place_lon, hotel_lat, hotel_lon)

    if distance_km <= 1.0:
        zone = "immediate"
        description = "Right next to hotel (5-10 min walk)"
    elif distance_km <= 2.0:
        zone = "near"
        description = "Walking distance (10-25 min walk)"
    elif distance_km <= 5.0:
        zone = "medium"
        description = "Short transit ride (15-20 min by bus/metro)"
    elif distance_km <= 15.0:
        zone = "far"
        description = "Requires dedicated transport (30-45 min)"
    else:
        zone = "remote"
        description = "Day trip territory (1+ hours)"

    return {
        "zone": zone,
        "distance_km": round(distance_km, 2),
        "description": description,
        "group_priority": ["immediate", "near", "medium", "far", "remote"].index(zone),
    }


@tool(args_schema=RouteOptimizerInput)
def optimize_day_route(places: list[dict[str, Any]], hotel_lat: float, hotel_lon: float) -> dict[str, Any]:
    """
    Optimize the order of places for a single day, starting and ending at hotel.
    Use this to create efficient day itineraries that minimize travel time.
    """
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


TRAVEL_TOOLS = [geocode_address, calculate_distance, check_zone, optimize_day_route]
