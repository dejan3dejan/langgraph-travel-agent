import asyncio
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from geopy.geocoders import Nominatim

from .database import GeocodingCache, SessionLocal
from .logger import get_logger
from .state import AgentState

logger = get_logger(__name__)

geolocator = Nominatim(user_agent="travel_companion_logistics_v1")


def _new_stats() -> dict[str, int]:
    return {"exact": 0, "neighborhood": 0, "failed": 0, "api_calls": 0, "cache_hits": 0}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    if not all([lat1, lon1, lat2, lon2]):
        return 0.0

    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon1 - lon2
    dlat = lat1 - lat2
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return c * 6371


def _geocode_sync(address: str, timeout: int = 10):
    """Blocking geocode call, meant to run in a thread executor."""
    return geolocator.geocode(address, timeout=timeout)


def get_coordinates(
    address: str,
    neighborhood: str | None = None,
    city: str | None = None,
    retries: int = 1,
    stats: dict[str, int] | None = None,
) -> tuple[float | None, float | None, str]:
    """Sync geocode with DB cache fallback. Used by LangChain tools (sync-only)."""
    if stats is None:
        stats = _new_stats()

    if not address:
        stats["failed"] += 1
        return None, None, "failed"

    query = address.strip()

    db = SessionLocal()
    try:
        cached = db.query(GeocodingCache).filter(GeocodingCache.query == query).first()
        if cached:
            if cached.status in ["exact", "neighborhood"]:
                stats["cache_hits"] += 1
                return cached.lat, cached.lon, cached.status
            if cached.status == "failed" and (datetime.now(UTC) - cached.created_at.replace(tzinfo=UTC)) < timedelta(
                hours=24
            ):
                stats["cache_hits"] += 1
                return None, None, "failed"
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    finally:
        db.close()

    res = (None, None, "failed")
    for i in range(retries + 1):
        try:
            time.sleep(1.1)
            stats["api_calls"] += 1
            location = _geocode_sync(address)
            if location:
                res = (location.latitude, location.longitude, "exact")
                break
            if neighborhood:
                time.sleep(1.1)
                stats["api_calls"] += 1
                search_query = f"{neighborhood}, {city}" if city else neighborhood
                location = _geocode_sync(search_query)
                if location:
                    res = (location.latitude, location.longitude, "neighborhood")
                    break
            break
        except Exception:
            if i == retries:
                break
            continue

    _save_to_geocoding_cache(query, res)

    stats[res[2]] += 1

    return res


async def aget_coordinates(
    address: str,
    neighborhood: str | None = None,
    city: str | None = None,
    retries: int = 1,
    stats: dict[str, int] | None = None,
) -> tuple[float | None, float | None, str]:
    """Async geocode — runs blocking Nominatim call in a thread executor."""
    if stats is None:
        stats = _new_stats()
    loop = asyncio.get_running_loop()

    if not address:
        stats["failed"] += 1
        return None, None, "failed"

    query = address.strip()

    db = SessionLocal()
    try:
        cached = db.query(GeocodingCache).filter(GeocodingCache.query == query).first()
        if cached:
            if cached.status in ["exact", "neighborhood"]:
                stats["cache_hits"] += 1
                return cached.lat, cached.lon, cached.status
            if cached.status == "failed" and (datetime.now(UTC) - cached.created_at.replace(tzinfo=UTC)) < timedelta(
                hours=24
            ):
                stats["cache_hits"] += 1
                return None, None, "failed"
    except Exception as e:
        logger.warning(f"Cache lookup failed: {e}")
    finally:
        db.close()

    res = (None, None, "failed")
    for i in range(retries + 1):
        try:
            await asyncio.sleep(1.1)
            stats["api_calls"] += 1
            location = await loop.run_in_executor(None, _geocode_sync, address)
            if location:
                res = (location.latitude, location.longitude, "exact")
                break
            if neighborhood:
                await asyncio.sleep(1.1)
                stats["api_calls"] += 1
                search_query = f"{neighborhood}, {city}" if city else neighborhood
                location = await loop.run_in_executor(None, _geocode_sync, search_query)
                if location:
                    res = (location.latitude, location.longitude, "neighborhood")
                    break
            break
        except Exception:
            if i == retries:
                break
            continue

    _save_to_geocoding_cache(query, res)

    stats[res[2]] += 1

    return res


def _save_to_geocoding_cache(query: str, res: tuple) -> None:
    """Upsert geocoding result into PostgreSQL cache."""
    db = SessionLocal()
    try:
        cached_entry = db.query(GeocodingCache).filter(GeocodingCache.query == query).first()
        if cached_entry:
            cached_entry.lat, cached_entry.lon, cached_entry.status = res[0], res[1], res[2]
            cached_entry.created_at = datetime.now(UTC)
        else:
            new_cache = GeocodingCache(query=query, lat=res[0], lon=res[1], status=res[2])
            db.add(new_cache)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to save to cache: {e}")
    finally:
        db.close()


async def logistics_agent(state: AgentState) -> dict[str, Any]:
    """Geocode all locations and assign proximity zones relative to the base hotel."""
    t0 = time.time()
    stats = _new_stats()

    logger.info("Geocoding locations and assigning zones (2km radius)...")

    food_data = state.get("food_data") or []
    activity_data = state.get("activity_data") or []
    hotel_data = state.get("hotel_data") or []
    city = state.get("user_details", {}).get("destination")

    all_items = hotel_data + activity_data + food_data
    items_to_geocode = sum(1 for item in all_items if item.lat is None)

    for item in all_items:
        if item.lat is None:
            lat, lon, status = await aget_coordinates(
                item.address, getattr(item, "neighborhood", None), city, stats=stats
            )
            item.lat, item.lon, item.geocoding_status = lat, lon, status

    zone_counts = {"near": 0, "remote": 0, "unknown": 0}

    if hotel_data and hotel_data[0].lat:
        base_h = hotel_data[0]
        base_h.zone = "BASE_HOTEL"

        for item in activity_data + food_data:
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

    duration = time.time() - t0

    logistics_meta = {"status": "completed", "zones_summary": zone_counts, "geocoding_stats": stats}

    log_entry = {
        "node": "logistics",
        "latency_sec": round(duration, 2),
        "items_geocoded": items_to_geocode,
        "geocoding": {
            "exact": stats["exact"],
            "neighborhood": stats["neighborhood"],
            "failed": stats["failed"],
            "api_calls": stats["api_calls"],
            "cache_hits": stats["cache_hits"],
            "success_rate": round((stats["exact"] + stats["neighborhood"]) / max(items_to_geocode, 1) * 100, 1),
        },
        "zones": zone_counts,
        "timestamp": time.strftime("%H:%M:%S"),
    }

    logger.info(
        f"Logistics completed in {duration:.2f}s | Hits: {stats['cache_hits']} | API Calls: {stats['api_calls']}"
    )

    return {
        "food_data": food_data,
        "activity_data": activity_data,
        "hotel_data": hotel_data,
        "logistics": logistics_meta,
        "debug_logs": [log_entry],
    }
