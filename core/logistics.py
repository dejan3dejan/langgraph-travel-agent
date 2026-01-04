import time
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

from .state import AgentState
from .schemas import Restaurant, Activity, Hotel
from .logger import get_logger
from .database import SessionLocal, GeocodingCache

logger = get_logger(__name__)

# Initialize geolocator with a unique user agent
geolocator = Nominatim(user_agent="travel_companion_logistics_v1")

_geocoding_stats = {"exact": 0, "neighborhood": 0, "failed": 0, "api_calls": 0, "cache_hits": 0}

def reset_geocoding_stats():
    """Reset stats for a new run."""
    global _geocoding_stats
    _geocoding_stats = {"exact": 0, "neighborhood": 0, "failed": 0, "api_calls": 0, "cache_hits": 0}

def get_geocoding_stats() -> Dict[str, int]:
    """Get current geocoding statistics."""
    return _geocoding_stats.copy()


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
    Checks PostgreSQL cache before calling Nominatim.
    """
    global _geocoding_stats
    
    if not address: 
        _geocoding_stats["failed"] += 1
        return None, None, "failed"
        
    query = address.strip()
    
    # 1. Check Cache
    db = SessionLocal()
    try:
        cached = db.query(GeocodingCache).filter(GeocodingCache.query == query).first()
        if cached:
            # If it's a success, return it
            if cached.status in ["exact", "neighborhood"]:
                _geocoding_stats["cache_hits"] += 1
                return cached.lat, cached.lon, cached.status
            
            # If it's a failed attempt, we only retry if it's older than 24h
            if cached.status == "failed" and (datetime.utcnow() - cached.created_at) < timedelta(hours=24):
                _geocoding_stats["cache_hits"] += 1
                return None, None, "failed"
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    finally:
        db.close()

    # 2. Not in Cache or Retry needed: Call API
    res = (None, None, "failed")
    for i in range(retries + 1):
        try:
            time.sleep(1.1) # Nominatim policy
            _geocoding_stats["api_calls"] += 1
            
            # Attempt 1: Full Address
            location = geolocator.geocode(address, timeout=10)
            if location:
                res = (location.latitude, location.longitude, "exact")
                break
            
            # Attempt 2: Neighborhood fallback
            if neighborhood:
                time.sleep(1.1)
                _geocoding_stats["api_calls"] += 1
                search_query = f"{neighborhood}, {city}" if city else neighborhood
                location = geolocator.geocode(search_query, timeout=10)
                if location:
                    res = (location.latitude, location.longitude, "neighborhood")
                    break
            
            res = (None, None, "failed")
            break
        except (GeocoderTimedOut, Exception):
            if i == retries: 
                res = (None, None, "failed")
                break
            continue

    # 3. Save to Cache
    db = SessionLocal()
    try:
        # Update or Insert
        cached_entry = db.query(GeocodingCache).filter(GeocodingCache.query == query).first()
        if cached_entry:
            cached_entry.lat, cached_entry.lon, cached_entry.status = res[0], res[1], res[2]
            cached_entry.created_at = datetime.utcnow()
        else:
            new_cache = GeocodingCache(
                query=query,
                lat=res[0],
                lon=res[1],
                status=res[2]
            )
            db.add(new_cache)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to save to cache: {e}")
    finally:
        db.close()

    if res[2] == "failed":
        _geocoding_stats["failed"] += 1
    elif res[2] == "exact":
        _geocoding_stats["exact"] += 1
    elif res[2] == "neighborhood":
        _geocoding_stats["neighborhood"] += 1
        
    return res


def logistics_agent(state: AgentState) -> Dict[str, Any]:
    """
    The Logistics Agent:
    1. Geocodes all locations with fallback to neighborhood.
    2. Assigns zones based on 2km radius from the base hotel.
    3. Returns debug_logs with timing and geocoding statistics.
    """
    t0 = time.time()
    reset_geocoding_stats()  # Fresh stats for this run
    
    logger.info("Geocoding locations and assigning zones (2km radius)...")
    
    food_data = state.get("food_data") or []
    activity_data = state.get("activity_data") or []
    hotel_data = state.get("hotel_data") or []
    city = state.get("user_details", {}).get("destination")
    
    # 1. Geocode everything
    all_items = hotel_data + activity_data + food_data
    items_to_geocode = sum(1 for item in all_items if item.lat is None)
    
    for item in all_items:
        if item.lat is None:
            lat, lon, status = get_coordinates(item.address, getattr(item, 'neighborhood', None), city)
            item.lat, item.lon, item.geocoding_status = lat, lon, status

    # 2. Zoning (Base on the first hotel)
    zone_counts = {"near": 0, "remote": 0, "unknown": 0}
    
    if hotel_data and hotel_data[0].lat:
        base_h = hotel_data[0]
        base_h.zone = "BASE_HOTEL"
        
        for item in (activity_data + food_data):
            if item.lat:
                dist = haversine_distance(base_h.lat, base_h.lon, item.lat, item.lon)
                if dist <= 2.0:
                    item.zone = "Near Hotel (<2km)"
                    zone_counts["near"] += 1
                else:
                    item.zone = f"Remote ({dist:.1f}km)"
                    zone_counts["remote"] += 1
            else:
                item.zone = "Unknown"
                zone_counts["unknown"] += 1

    # 3. Build metrics
    duration = time.time() - t0
    geo_stats = get_geocoding_stats()
    
    logistics_meta = {
        "status": "completed", 
        "zones_summary": zone_counts,
        "geocoding_stats": geo_stats
    }
    
    log_entry = {
        "node": "logistics",
        "latency_sec": round(duration, 2),
        "items_geocoded": items_to_geocode,
        "geocoding": {
            "exact": geo_stats["exact"],
            "neighborhood": geo_stats["neighborhood"],
            "failed": geo_stats["failed"],
            "api_calls": geo_stats["api_calls"],
            "cache_hits": geo_stats["cache_hits"],
            "success_rate": round(
                (geo_stats["exact"] + geo_stats["neighborhood"]) / max(items_to_geocode, 1) * 100, 1
            )
        },
        "zones": zone_counts,
        "timestamp": time.strftime("%H:%M:%S")
    }
    
    logger.info(f"Logistics completed in {duration:.2f}s | Hits: {geo_stats['cache_hits']} | API Calls: {geo_stats['api_calls']}")

    return {
        "food_data": food_data,
        "activity_data": activity_data,
        "hotel_data": hotel_data,
        "logistics": logistics_meta,
        "debug_logs": [log_entry]
    }
