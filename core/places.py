"""OpenStreetMap Overpass boundary: fetch real, mappable places (POIs) for a destination.

This is the data source that will replace LLM-invented venues (task G2). It stays in the same data
family as the app's existing Nominatim geocoding (core/logistics.py): OpenStreetMap, free, no API
key. All network I/O lives here. The JSON-to-Candidate parsing is the pure parse_overpass helper
below so it can be unit-tested against a saved fixture with no network.

On an empty or failed response fetch_pois returns [] and logs; it never invents a place.

Alternatives if OSM coverage turns out thin for a category:
  - OpenTripMap (https://opentripmap.io): good attraction/POI coverage with ratings and wikidata
    links, free tier ~ a few thousand calls/day, needs an API key. Worth layering in for the
    attractions category, where OSM tagging is uneven; weaker for restaurants/hotels.
  - Foursquare Places (https://location.foursquare.com): strong restaurant/venue coverage and
    popularity signals, free tier with an API key and stricter rate limits and ToS on caching.
Both add a key and a second client; we start with Overpass (keyless, same data family) and only
add one of these per-category if real-city spot checks show gaps.
"""

import asyncio
import os
import time

import httpx
from pydantic import BaseModel, Field

from .logger import get_logger

logger = get_logger(__name__)

DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Server-side query budget and the (slightly longer) client read timeout around it.
QUERY_TIMEOUT_SECONDS = 25
CLIENT_TIMEOUT_SECONDS = 30.0

# Politeness: Overpass is a shared free service. Serialize our calls and keep a minimum gap between
# them (the Nominatim path in logistics.py sleeps similarly), and cache results so a repeated
# (area, category) lookup never re-hits the API within a day.
MIN_INTERVAL_SECONDS = 1.0
CACHE_TTL_SECONDS = 24 * 3600
DEFAULT_RADIUS_METERS = 2000

USER_AGENT = "travel_companion_places_v1"

# Overpass tag selectors per category. Attractions fold in museums, which OSM tags separately.
_CATEGORY_SELECTORS = {
    "restaurants": '["amenity"="restaurant"]',
    "hotels": '["tourism"="hotel"]',
    "attractions": '["tourism"~"^(attraction|museum)$"]',
}


class Candidate(BaseModel):
    """A real place sourced from OpenStreetMap, ready to be geocoded-for-free (coords are already
    known) and mapped. The G2 pipeline maps these onto the planner's Restaurant/Activity/Hotel
    schemas; here we keep the raw OSM-useful fields only."""

    name: str
    lat: float
    lon: float
    category: str = Field(description="restaurants | hotels | attractions")
    cuisine: str | None = Field(default=None, description="OSM cuisine tag, may be ';'-separated")
    website: str | None = None
    source: str = "overpass"
    osm_type: str | None = Field(default=None, description="node | way | relation")
    osm_id: int | None = None


def _area_clause(area: tuple | list) -> str:
    """Render the destination as an Overpass area filter. Accepts a center (lat, lon), a center with
    radius (lat, lon, radius_m), or a bounding box (south, west, north, east). Raises ValueError on
    anything else: a malformed area is a caller bug, not a runtime data condition to swallow."""
    if not isinstance(area, tuple | list):
        raise ValueError(f"area must be a tuple/list, got {type(area).__name__}")
    nums = [float(v) for v in area]
    if len(nums) == 2:
        lat, lon = nums
        return f"(around:{DEFAULT_RADIUS_METERS},{lat},{lon})"
    if len(nums) == 3:
        lat, lon, radius = nums
        return f"(around:{radius},{lat},{lon})"
    if len(nums) == 4:
        south, west, north, east = nums
        return f"({south},{west},{north},{east})"
    raise ValueError(f"area must have 2 (center), 3 (center+radius), or 4 (bbox) values, got {len(nums)}")


def build_overpass_query(area: tuple | list, category: str, limit: int) -> str:
    """Build the Overpass QL for one category over an area. Queries node/way/relation so a POI mapped
    as a building (way) or a multipolygon (relation) is included; `out center` attaches a single
    representative coordinate to each. Pure."""
    if category not in _CATEGORY_SELECTORS:
        raise ValueError(f"unknown category {category!r}; expected one of {sorted(_CATEGORY_SELECTORS)}")
    selector = _CATEGORY_SELECTORS[category]
    clause = _area_clause(area)
    body = "\n".join(f"  {element}{selector}{clause};" for element in ("node", "way", "relation"))
    return f"[out:json][timeout:{QUERY_TIMEOUT_SECONDS}];\n(\n{body}\n);\nout center tags {limit};"


def _classify(tags: dict) -> str | None:
    """Map an element's tags to one of our categories, or None if it is neither. Lets parse_overpass
    stay category-agnostic and self-describing from the data."""
    if tags.get("amenity") == "restaurant":
        return "restaurants"
    if tags.get("tourism") == "hotel":
        return "hotels"
    if tags.get("tourism") in ("attraction", "museum"):
        return "attractions"
    return None


def _coords(element: dict) -> tuple[float, float] | None:
    """Pull a (lat, lon) from a node's own coords or a way/relation's `center`. Returns None when no
    valid coordinate is present, so an element with unresolved geometry is dropped rather than
    plotted at (None, None) or an out-of-range point."""
    lat, lon = element.get("lat"), element.get("lon")
    if lat is None or lon is None:
        center = element.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")
    if lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return float(lat), float(lon)


def parse_overpass(response_json: dict) -> list[Candidate]:
    """Turn a raw Overpass JSON response into Candidates. Pure: no network, no clock. Drops elements
    with no name (unusable for an itinerary) or no resolvable coordinate (unmappable), and elements
    whose tags fall outside our categories. The category is inferred from tags so a mixed response
    parses correctly."""
    candidates = []
    for element in response_json.get("elements", []):
        tags = element.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        category = _classify(tags)
        if category is None:
            continue
        coords = _coords(element)
        if coords is None:
            continue
        lat, lon = coords
        candidates.append(
            Candidate(
                name=name,
                lat=lat,
                lon=lon,
                category=category,
                cuisine=tags.get("cuisine"),
                website=tags.get("website") or tags.get("contact:website"),
                osm_type=element.get("type"),
                osm_id=element.get("id"),
            )
        )
    return candidates


# Module-level politeness state: a lock serializes outbound calls and _last_call_monotonic enforces
# the minimum gap. The cache keys on the exact query string, so identical lookups are free.
_rate_lock = asyncio.Lock()
_last_call_monotonic = 0.0
_cache: dict[str, tuple[float, list[Candidate]]] = {}


def _overpass_url() -> str:
    """Read the endpoint at call time so an env override (or a mirror) is picked up without a reload."""
    return os.getenv("OVERPASS_API_URL", DEFAULT_OVERPASS_URL).strip() or DEFAULT_OVERPASS_URL


def _cache_get(key: str) -> list[Candidate] | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    expiry, value = entry
    if time.monotonic() > expiry:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: list[Candidate]) -> None:
    _cache[key] = (time.monotonic() + CACHE_TTL_SECONDS, value)


async def _respect_rate_limit() -> None:
    """Sleep just enough to keep at least MIN_INTERVAL_SECONDS between outbound calls. Caller holds
    _rate_lock, so this also serializes concurrent fetches."""
    global _last_call_monotonic
    wait = MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call_monotonic)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call_monotonic = time.monotonic()


async def _post_overpass(query: str) -> dict | None:
    """POST one query to Overpass. Returns the parsed JSON, or None on any network/HTTP/decoding
    failure (logged). Failing to None lets fetch_pois degrade to [] without fabricating."""
    async with _rate_lock:
        await _respect_rate_limit()
        try:
            async with httpx.AsyncClient(timeout=CLIENT_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    _overpass_url(),
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                )
        except httpx.HTTPError as e:
            logger.warning(f"Overpass request failed: {type(e).__name__}")
            return None

    if resp.status_code != 200:
        logger.warning(f"Overpass returned status {resp.status_code}")
        return None
    try:
        return resp.json()
    except ValueError:
        logger.warning("Overpass returned a non-JSON body")
        return None


async def fetch_pois(bbox_or_center: tuple | list, category: str, limit: int = 30) -> list[Candidate]:
    """Fetch real POIs of one category around a center or within a bounding box.

    `bbox_or_center` is (lat, lon), (lat, lon, radius_m), or (south, west, north, east). Returns up
    to `limit` Candidates with valid coordinates. A failed request or a genuinely empty area yields
    [] (logged), never an invented place. A successful result (including a genuinely empty one) is
    cached per exact query for CACHE_TTL_SECONDS, so repeated lookups stay polite to the shared API; a
    failed request is not cached, so a transient throttle is retried on the next call.
    """
    query = build_overpass_query(bbox_or_center, category, limit)

    cached = _cache_get(query)
    if cached is not None:
        return cached

    payload = await _post_overpass(query)
    if payload is None:
        # A failed request (network/HTTP/decode) is a transient blip, not evidence the area is empty.
        # Return [] without caching so the next call retries, rather than sticking [] for 24h and
        # suppressing a whole category after one throttle.
        return []

    candidates = parse_overpass(payload)
    if not candidates:
        logger.info(f"Overpass returned no usable {category} places for area={bbox_or_center}; returning []")
    # Only a present payload is cached: a genuinely empty area legitimately caches [].
    _cache_set(query, candidates)
    return candidates
