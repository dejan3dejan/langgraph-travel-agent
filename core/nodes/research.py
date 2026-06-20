"""Research nodes — food, activity, and hotel research with semantic cache + Google Search."""

import time
from typing import Any

from langchain_core.messages import HumanMessage

from ..llm import USE_GEMINI, get_llm_for_role
from ..logger import get_logger
from ..schemas import Activity, ActivityList, Hotel, HotelList, Restaurant, RestaurantList, render_constraints
from ..semantic_cache import cache_research_results, semantic_search, should_use_cache
from ..state import AgentState

logger = get_logger(__name__)


def _should_refresh(category: str, regenerate: bool) -> bool:
    """On a regenerate, rebuild the food and activity pools live (they drive day-to-day variety) but
    keep the stable hotel pool cached, since only one hotel is picked anyway."""
    return regenerate and category in ("restaurants", "activities")


def _get_destinations(details: dict) -> list[str]:
    """Return list of destinations to research (supports multi-destination)."""
    dests = details.get("destinations") or []
    primary = details.get("destination", "")
    if dests:
        return dests
    return [primary] if primary else []


def _get_activity_focus(trip_type: str, age_range: str, interests: str) -> str:
    """Returns a string summary of what kind of activities to focus on."""
    focus = []
    if trip_type:
        focus.append(trip_type)
    if "art" in interests.lower():
        focus.append("art")
    if "history" in interests.lower():
        focus.append("history")
    if age_range.lower() == "adults":
        focus.append("adult-friendly")
    elif age_range.lower() == "children":
        focus.append("kid-friendly")
    elif age_range.lower() == "seniors":
        focus.append("senior-friendly")
    return ", ".join(focus) if focus else "general sightseeing"


# Research configuration per category

_RESEARCH_CONFIG = {
    "restaurants": {
        "schema_class": Restaurant,
        "list_class": RestaurantList,
        "similarity_threshold": 0.80,
        "max_age_days": 30,
        "freshness_days": 30,
        "state_key": "food_data",
        "node_name": "research_food",
        "count": 6,
    },
    "activities": {
        "schema_class": Activity,
        "list_class": ActivityList,
        "similarity_threshold": 0.75,
        "max_age_days": 45,
        "freshness_days": 45,
        "state_key": "activity_data",
        "node_name": "research_activity",
        "count": 8,
    },
    "hotels": {
        "schema_class": Hotel,
        "list_class": HotelList,
        "similarity_threshold": 0.85,
        "max_age_days": 14,
        "freshness_days": 14,
        "state_key": "hotel_data",
        "node_name": "research_hotel",
        "count": 3,
    },
}


_LOCAL_VIBE_SIGNALS = (
    "local",
    "non-touristy",
    "non touristy",
    "not touristy",
    "less touristy",
    "authentic",
    "hidden gem",
    "off the beaten",
    "like a local",
    "avoid tourist",
)


def _wants_local(details: dict) -> bool:
    """True when the traveler asked for a local, non-touristy feel (captured as a soft preference)."""
    soft = (details.get("constraints") or {}).get("soft") or []
    text = " ".join(soft).lower()
    return any(s in text for s in _LOCAL_VIBE_SIGNALS)


def _personalization_suffix(details: dict) -> str:
    """Personalize-before-retrieve: fold the local vibe and named areas into the cache key so a
    'local near Trastevere' request stops colliding with the generic bundle. Empty when neither was
    expressed, so plain requests keep hitting the warm cache."""
    parts = []
    if _wants_local(details):
        parts.append("local non-touristy spots")
    areas = details.get("preferred_areas") or []
    if areas:
        parts.append("near " + ", ".join(areas))
    return (", " + ", ".join(parts)) if parts else ""


def _local_focus_block(details: dict) -> str:
    """A research-prompt steer toward local spots in the named areas, added only when the traveler
    asked for it. This is the steer that previously only fired on a regenerate."""
    areas = details.get("preferred_areas") or []
    if not (_wants_local(details) or areas):
        return ""
    near = (" Prioritize options in or near: " + ", ".join(areas) + ".") if areas else ""
    return (
        "\n\nLOCAL FOCUS: The traveler wants local, non-touristy places, not the usual tourist-trap "
        "landmarks. Favor well-rated spots locals actually go to." + near
    )


def _build_search_query(category: str, dest: str, details: dict) -> str:
    """Build the semantic cache search query for a category."""
    age_range = details.get("age_range", "adults")
    budget = details.get("budget", "Medium")
    trip_type = details.get("trip_type")
    interests = details.get("interests", "General Sightseeing")
    num_travelers = details.get("num_travelers", 1)

    if category == "restaurants":
        base = f"best restaurants in {dest} for {age_range} {budget} budget"
    elif category == "activities":
        base = f"best activities in {dest} for {age_range} {trip_type or 'sightseeing'} {interests}"
    else:
        base = f"best hotels in {dest} {budget} budget for {num_travelers} travelers"
    return base + _personalization_suffix(details)


def _build_search_prompt(category: str, dest: str, details: dict) -> str:
    """Build the LLM research prompt for a category."""
    hard, soft = render_constraints(details.get("constraints"))
    constraints = f"Must satisfy: {hard or 'none'}; prefer: {soft or 'none'}"
    # Enough places that a multi-day itinerary has something to pin on each day's map. A generous
    # fixed count rather than per-day scaling, because the semantic cache keys on a duration-less
    # query, so a per-day count would just be reused across trip lengths anyway.
    n = _RESEARCH_CONFIG[category]["count"]
    num_travelers = details.get("num_travelers", 1)
    age_range = details.get("age_range", "adults")
    budget = details.get("budget", "Medium")
    trip_type = details.get("trip_type")
    interests = details.get("interests", "General Sightseeing")

    if category == "restaurants":
        age_filters = {
            "kids": "- MUST be kid-friendly (high chairs, kids menu)",
            "seniors": "- Accessible (ground floor or elevator, comfortable seating)",
            "young_adults": "- Trendy, Instagram-worthy spots welcome",
        }.get(age_range, "")

        return f"""
    Use Google Search to find {n} REAL, currently operating restaurants in {dest}.

    TRAVELER PROFILE:
    - Number of travelers: {num_travelers}
    - Age range: {age_range}
    - Budget level: {budget}

    FILTERING RULES:
    {age_filters}
    {"- Group-friendly (reservations for " + str(num_travelers) + "+)" if num_travelers >= 5 else ""}

    STRICT REQUIREMENTS (Do NOT skip any):
    1. EXACT NAME: Official restaurant name
    2. FULL STREET ADDRESS: Street number, street name, city
    3. NEIGHBORHOOD: District name
    4. WEBSITE: Official website or "N/A"
    5. CUISINE: Type of food
    6. PRICE LEVEL: $, $$, $$$, or $$$$
    7. GOOGLE RATING: e.g., 4.5
    8. WHY IT FITS: How it matches the traveler profile

    Constraints: {constraints}
    """

    elif category == "activities":
        activity_focus = _get_activity_focus(trip_type, age_range, interests)

        return f"""
    Use Google Search to find {n} REAL activities/attractions in {dest}.

    TRAVELER PROFILE:
    - Age range: {age_range}
    - Trip type: {trip_type or "general sightseeing"}
    - Number of travelers: {num_travelers}
    - Interests: {interests}

    ACTIVITY FOCUS: {activity_focus}

    STRICT REQUIREMENTS (Do NOT skip any):
    1. EXACT NAME  2. FULL ADDRESS  3. NEIGHBORHOOD  4. WEBSITE or "N/A"
    5. TYPE  6. DURATION  7. DESCRIPTION (1-2 sentences)

    Trip duration: {details.get('duration')}
    Constraints: {constraints}
    CRITICAL: Only include attractions suitable for {age_range} travelers.
    """

    else:
        return f"""
    Use Google Search to find {n} REAL hotels in {dest}.

    REQUIREMENTS:
    - Budget level: {budget}
    - Number of travelers: {num_travelers}
    {f"- Group accommodation (rooms for {num_travelers}+ people)" if num_travelers >= 5 else ""}

    STRICT REQUIREMENTS (Do NOT skip any):
    1. EXACT NAME  2. FULL STREET ADDRESS  3. NEIGHBORHOOD  4. WEBSITE or "N/A"
    5. PRICE RANGE (per night)  6. PROS (2-3 advantages)

    Budget level: {budget}
    Constraints: {constraints}
    CRITICAL: Only include hotels with verified, complete street addresses.
    """


async def _research_for_dest(category: str, dest: str, details: dict, force_refresh: bool = False) -> list:
    """Generic research function — works for restaurants, activities, and hotels. On force_refresh
    (a regenerate) it skips the cache and searches live at a higher temperature for a fresh pool."""
    config = _RESEARCH_CONFIG[category]
    schema_class = config["schema_class"]
    list_class = config["list_class"]

    search_query = _build_search_query(category, dest, details)

    if not force_refresh:
        cache_hit = await semantic_search(
            query=search_query,
            category=category,
            destination=dest,
            similarity_threshold=config["similarity_threshold"],
            max_age_days=config["max_age_days"],
        )
        use_cache, reason = await should_use_cache(cache_hit, category)

        if use_cache and cache_hit:
            logger.info(f"[{dest}] Cache hit for {category} ({reason})")
            return [schema_class(**item) for item in cache_hit["results"]]

    logger.info(f"[{dest}] {'Refreshing' if force_refresh else 'Cache miss for'} {category}, searching via Gemini...")

    research_llm = get_llm_for_role("research", temperature=0.8 if force_refresh else None)
    # Google Search grounding is Gemini-only; OpenAI-only mode runs ungrounded.
    if USE_GEMINI:
        research_llm = research_llm.bind_tools(tools=[{"google_search": {}}])
    search_prompt = _build_search_prompt(category, dest, details) + _local_focus_block(details)
    if force_refresh:
        search_prompt += (
            "\n\nThe traveler has already seen the usual top picks. Prefer fresh, less obvious, "
            "well-rated options they likely have not seen before."
        )

    grounded_response = await research_llm.ainvoke([HumanMessage(content=search_prompt)])
    grounded_text = getattr(grounded_response, "content", str(grounded_response))

    extraction_llm = get_llm_for_role("extraction")
    structured_extractor = extraction_llm.with_structured_output(list_class)
    result = await structured_extractor.ainvoke(
        [
            HumanMessage(
                content=f"Extract {category} information from this text into structured format.\n{grounded_text}"
            )
        ]
    )
    data = result.items

    if data:
        data_dicts = [item.model_dump() for item in data]
        await cache_research_results(
            query=search_query,
            category=category,
            destination=dest,
            results=data_dicts,
            freshness_days=config["freshness_days"],
        )
    return data


async def _research_node(category: str, state: AgentState) -> dict[str, Any]:
    """Generic research node — iterates over all destinations."""
    config = _RESEARCH_CONFIG[category]
    t0 = time.time()
    details = state.get("user_details", {})
    destinations = _get_destinations(details)
    force_refresh = _should_refresh(category, state.get("regenerate", False))

    all_data = []
    for dest in destinations:
        try:
            data = await _research_for_dest(category, dest, details, force_refresh=force_refresh)
            all_data.extend(data)
        except Exception as e:
            logger.error(f"{category.title()} Agent Error [{dest}]: {e}")

    log = {
        "node": config["node_name"],
        "latency_sec": round(time.time() - t0, 2),
        "destinations": destinations,
        "results_total": len(all_data),
        "timestamp": time.strftime("%H:%M:%S"),
    }
    return {config["state_key"]: all_data, "debug_logs": [log]}


async def research_food_node(state: AgentState) -> dict:
    """Food research — iterates over all destinations for multi-city trips."""
    return await _research_node("restaurants", state)


async def research_activity_node(state: AgentState) -> dict:
    """Activity research — iterates over all destinations for multi-city trips."""
    return await _research_node("activities", state)


async def research_hotel_node(state: AgentState) -> dict:
    """Hotel research — iterates over all destinations for multi-city trips."""
    return await _research_node("hotels", state)
