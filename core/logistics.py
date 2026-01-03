import time
import math
from typing import List, Dict, Any, Optional, Tuple
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

from .state import AgentState
from .schemas import Restaurant, Activity, Hotel
from .logger import get_logger

logger = get_logger(__name__)

# Initialize geolocator with a unique user agent
geolocator = Nominatim(user_agent="travel_companion_logistics_v1")

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) in kilometers.
    """
    if not all([lat1, lon1, lat2, lon2]): return 0.0
    
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon1 - lon2 
    dlat = lat1 - lat2 
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a)) 
    r = 6371 # Earth radius
    return c * r

def get_coordinates(address: str, neighborhood: Optional[str] = None, city: Optional[str] = None, retries: int = 1) -> Tuple[Optional[float], Optional[float], str]:
    """
    Helper to get lat/lon from address with fallback to neighborhood.
    """
    if not address: return None, None, "failed"
        
    for i in range(retries + 1):
        try:
            time.sleep(1.1) # Nominatim policy
            # Attempt 1: Full Address
            location = geolocator.geocode(address, timeout=10)
            if location:
                return location.latitude, location.longitude, "exact"
            
            # Attempt 2: Neighborhood fallback
            if neighborhood:
                time.sleep(1.1)
                search_query = f"{neighborhood}, {city}" if city else neighborhood
                location = geolocator.geocode(search_query, timeout=10)
                if location:
                    return location.latitude, location.longitude, "neighborhood"
            
            return None, None, "failed"
        except (GeocoderTimedOut, Exception):
            if i == retries: return None, None, "failed"
            continue
            
    return None, None, "failed"

def logistics_agent(state: AgentState) -> Dict[str, Any]:
    """
    The Logistics Agent:
    1. Geocodes all locations with fallback to neighborhood.
    2. Assigns zones based on 2km radius from the base hotel.
    """
    logger.info("Geocoding locations and assigning zones (2km radius)...")
    
    food_data = state.get("food_data") or []
    activity_data = state.get("activity_data") or []
    hotel_data = state.get("hotel_data") or []
    city = state.get("user_details", {}).get("destination")
    
    # 1. Geocode everything
    all_items = hotel_data + activity_data + food_data
    for item in all_items:
        if item.lat is None:
            lat, lon, status = get_coordinates(item.address, getattr(item, 'neighborhood', None), city)
            item.lat, item.lon, item.geocoding_status = lat, lon, status

    # 2. Zoning (Base on the first hotel)
    logistics_meta = {"status": "completed", "zones_summary": {}}
    
    if hotel_data and hotel_data[0].lat:
        base_h = hotel_data[0]
        base_h.zone = "BASE_HOTEL"
        
        for item in (activity_data + food_data):
            if item.lat:
                dist = haversine_distance(base_h.lat, base_h.lon, item.lat, item.lon)
                if dist <= 2.0:
                    item.zone = "Near Hotel (<2km)"
                else:
                    # Optional: We could add more complex clustering here later
                    item.zone = f"Remote ({dist:.1f}km)"
            else:
                item.zone = "Unknown"

    return {
        "food_data": food_data,
        "activity_data": activity_data,
        "hotel_data": hotel_data,
        "logistics": logistics_meta
    }
