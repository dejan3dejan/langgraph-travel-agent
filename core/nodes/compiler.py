"""Compiler node — writes the itinerary draft from research data."""

import json
import time

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import HumanMessage, SystemMessage

from ..geo import group_places_by_zone, optimize_day_route
from ..llm import get_llm_for_role
from ..logger import get_logger
from ..state import AgentState
from ._utils import log_usage

logger = get_logger(__name__)

_INTERNAL_KEYS = {"geocoding_status", "_type"}


def _slim_place(d: dict) -> dict:
    """Strip internal metadata keys that the LLM doesn't need."""
    return {k: v for k, v in d.items() if k not in _INTERNAL_KEYS and v is not None}


# Narrative helpers


def _get_narrative_style(num_travelers: int, age_range: str, trip_type: str | None) -> str:
    style = []

    if num_travelers == 1:
        style.append("- Address the traveler as 'you' (singular)")
    else:
        style.append(f"- Address as 'you' (plural) - remember there are {num_travelers} travelers")

    tone_map = {
        "romantic": [
            "- Use romantic, intimate language ('your evening together', 'a cozy dinner for two')",
            "- Emphasize ambiance and special moments",
        ],
        "family": [
            "- Family-friendly language ('the kids will love...', 'parents can relax while...')",
            "- Mention logistics (restrooms, snack stops, break times)",
        ],
        "adventure": [
            "- Energetic, action-oriented language ('conquer', 'explore', 'challenge yourself')",
            "- Emphasize physical experiences and adrenaline",
        ],
        "business": ["- Professional tone, efficient pacing", "- Mention wifi/workspace availability"],
        "workation": ["- Professional tone, efficient pacing", "- Mention wifi/workspace availability"],
        "relaxation": [
            "- Calm, soothing language ('unwind', 'leisurely', 'at your own pace')",
            "- Minimize packed schedules",
        ],
    }
    style.extend(tone_map.get(trip_type, ["- Balanced, informative tone"]))

    age_map = {
        "kids": ["- Build in rest breaks and flexible timing", "- Shorter activity blocks (1-2 hours max)"],
        "mixed": ["- Build in rest breaks and flexible timing", "- Shorter activity blocks (1-2 hours max)"],
        "seniors": ["- Emphasize comfort and accessibility", "- Slower pacing, more sitting/rest opportunities"],
        "young_adults": ["- Pack activities densely if interests allow", "- Mention social/nightlife options"],
    }
    style.extend(age_map.get(age_range, []))

    return "\n".join(style)


def _get_overview_guidance(trip_type: str | None, age_range: str, num_travelers: int) -> str:
    guides = {
        "romantic": "(Write a romantic intro: 'Your romantic escape to [dest]...', mention couple-friendly highlights)",
        "family": f"(Family-focused intro for {num_travelers} travelers, mention kid-friendly highlights and parent conveniences)",
        "adventure": "(Energetic intro highlighting outdoor activities, physical challenges, and natural beauty)",
        "business": "(Professional intro balancing work needs with cultural exploration)",
    }
    return guides.get(trip_type, "(Brief summary of destination highlights tailored to traveler interests)")


def _get_day_structure_guide(age_range: str, trip_type: str | None) -> str:
    if age_range in ("kids", "mixed"):
        return """
- **Morning:** (Kid-friendly activity, finish before lunch nap time)
- **Lunch:** (Restaurant with kids menu, note high chairs/changing facilities)
- **Afternoon:** (Lighter activity or hotel break for naps)
- **Evening:** (Early dinner, family-friendly restaurant)
"""
    if trip_type == "romantic":
        return """
- **Morning:** (Leisurely start, romantic breakfast spot)
- **Midday:** (Couple's activity or scenic walk)
- **Afternoon:** (Cultural site or relaxing experience)
- **Evening:** (Romantic dinner with ambiance notes)
"""
    if trip_type == "adventure":
        return """
- **Early Morning:** (Start early for best light/fewer crowds)
- **Morning-Afternoon:** (Main adventure activity, 3-5 hours)
- **Late Afternoon:** (Recovery time or lighter exploration)
- **Evening:** (Hearty meal to refuel)
"""
    return """
- **Morning:** [Activity] (X.X km from hotel, ~Y min walk/transit)
- **Lunch:** [Restaurant] (Address) - [Cuisine], [Price]
- **Afternoon:** [Activity]
- **Evening:** [Dinner spot]
"""


def _get_tips_guidance(age_range: str, trip_type: str | None, num_travelers: int) -> str:
    tips = []
    if age_range in ("kids", "mixed"):
        tips.append("(Include: baby changing facilities, playgrounds nearby, kid-friendly restaurants)")
    if age_range == "seniors":
        tips.append("(Include: elevator access, rest benches, taxi/accessible transport options)")
    if trip_type == "romantic":
        tips.append("(Include: reservation tips for romantic restaurants, sunset timing, couple's spa options)")
    if num_travelers >= 5:
        tips.append("(Include: group reservation tips, split-check restaurant policies, group transport options)")
    if not tips:
        tips.append("(Standard budget tips and local customs)")
    return "\n".join(tips)


# Compiler node


async def compiler_node(state: AgentState) -> dict:
    t0 = time.time()
    await adispatch_custom_event("reset_itinerary", {"message": "Refining itinerary..."})

    logger.info("Writing itinerary draft with smart zone grouping...")
    user_details = state.get("user_details", {})

    food_data = state.get("food_data") or []
    activity_data = state.get("activity_data") or []
    hotel_data = state.get("hotel_data") or []

    food_dicts = [_slim_place(f.model_dump() if hasattr(f, "model_dump") else f) for f in food_data]
    activity_dicts = [_slim_place(a.model_dump() if hasattr(a, "model_dump") else a) for a in activity_data]
    hotel_dicts = [_slim_place(h.model_dump() if hasattr(h, "model_dump") else h) for h in hotel_data]

    hotel_lat, hotel_lon = None, None
    if hotel_dicts:
        hotel_lat = hotel_dicts[0].get("lat")
        hotel_lon = hotel_dicts[0].get("lon")

    zone_groups = {"near": [], "medium": [], "far": [], "remote": []}

    if hotel_lat and hotel_lon:
        all_places = []
        for a in activity_dicts:
            a["_type"] = "activity"
            all_places.append(a)
        for f in food_dicts:
            f["_type"] = "restaurant"
            all_places.append(f)

        raw_zone_groups = group_places_by_zone(all_places, hotel_lat, hotel_lon)

        for zone, places in raw_zone_groups.items():
            if places:
                optimization = optimize_day_route(places, hotel_lat, hotel_lon)
                zone_groups[zone] = optimization.get("optimized_order", [])
            else:
                zone_groups[zone] = []

    grouped_data = {
        "near_hotel": {
            "description": "Walking distance (< 2km, 10-25 min walk). OPTIMIZED ROUTE PROVIDED.",
            "places": zone_groups.get("near", []),
        },
        "medium_distance": {
            "description": "Short transit (2-5km, 15-20 min by bus/metro). OPTIMIZED ROUTE PROVIDED.",
            "places": zone_groups.get("medium", []),
        },
        "far_from_hotel": {
            "description": "Requires dedicated transport (5-15km, 30-45 min). OPTIMIZED ROUTE PROVIDED.",
            "places": zone_groups.get("far", []),
        },
        "day_trip_territory": {
            "description": "Remote locations (15+ km, 1+ hours). OPTIMIZED ROUTE PROVIDED.",
            "places": zone_groups.get("remote", []),
        },
    }

    grouped_json = json.dumps(grouped_data, indent=2, ensure_ascii=False)
    hotel_json = json.dumps(hotel_dicts, indent=2, ensure_ascii=False)

    num_travelers = user_details.get("num_travelers", 1)
    age_range = user_details.get("age_range", "adults")
    trip_type = user_details.get("trip_type")
    season_suggestion = state.get("season_suggestion")

    narrative_style = _get_narrative_style(num_travelers, age_range, trip_type)
    overview_guidance = _get_overview_guidance(trip_type, age_range, num_travelers)
    day_structure_guide = _get_day_structure_guide(age_range, trip_type)
    tips_guidance = _get_tips_guidance(age_range, trip_type, num_travelers)

    chat_llm = get_llm_for_role("compiler")

    prompt = f"""
You are writing a practical travel itinerary for a trip to {user_details.get('destination')}.

═══════════════════════════════════════════════════════════════
TRAVELER PROFILE (use this to personalize the narrative)
═══════════════════════════════════════════════════════════════
- Departing from: {user_details.get('start_location', 'their home location')}
- Number of travelers: {num_travelers}
- Age range: {age_range}
- Trip type: {trip_type or "general sightseeing"}
- Duration: {user_details.get('duration')}
- Budget: {user_details.get('budget')}
- Interests: {user_details.get('interests')}

{f"🌍 TIMING RECOMMENDATION: {season_suggestion}" if season_suggestion else ""}

═══════════════════════════════════════════════════════════════
NARRATIVE STYLE GUIDE
═══════════════════════════════════════════════════════════════
{narrative_style}

═══════════════════════════════════════════════════════════════
ACCOMMODATION OPTIONS
═══════════════════════════════════════════════════════════════
{hotel_json}

═══════════════════════════════════════════════════════════════
🗺️ PRE-GROUPED PLACES BY PROXIMITY (USE THIS FOR DAY PLANNING!)
═══════════════════════════════════════════════════════════════
{grouped_json}

═══════════════════════════════════════════════════════════════
🎯 CRITICAL RULES FOR SMART ITINERARY
═══════════════════════════════════════════════════════════════
1. **USE THE ZONE GROUPS ABOVE!** Each day should focus on ONE zone:
   - Day 1: Explore "near_hotel" places (easy start, jet lag friendly)
   - Day 2: Tackle "medium_distance" zone
   - Day 3+: Plan "far_from_hotel" or "day_trip_territory" as dedicated excursions

2. **NEVER MIX ZONES IN ONE DAY** unless absolutely necessary:
   - BAD: Morning in near_hotel zone, afternoon 50km away, dinner back near hotel
   - GOOD: Full day exploring one area, with lunch and dinner in the same zone

3. **ALWAYS MENTION TRAVEL INFO:**
   - Distance from hotel
   - Estimated travel time
   - Transport recommendation (walk/metro/bus/taxi)

4. **BE SPECIFIC:** Use exact names, addresses from the data above.

5. **PERSONALIZE FOR TRAVELER PROFILE:**
   - Adjust pacing based on age_range
   - Match activity difficulty to trip_type
   - Use appropriate language tone (romantic vs family vs adventure)

6. **REMOTE LOCATIONS WARNING:** If using "day_trip_territory" places, add a note:
   "⚠️ This is a day trip - allow extra travel time"

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT (Markdown)
═══════════════════════════════════════════════════════════════

# {user_details.get('duration', 'Your')} {trip_type.title() if trip_type else ''} Trip to {user_details.get('destination')}

## Overview
{overview_guidance}

{f"## 🌤️ Best Time to Visit\\n{season_suggestion}\\n" if season_suggestion else ""}

## Recommended Accommodation
(Pick ONE hotel that matches the traveler profile - explain why it fits their needs)

## Day-by-Day Itinerary

### Day 1: [Zone Theme - e.g., "Settling In Near Your Hotel"]
{day_structure_guide}

### Day 2: [Zone Theme]
(Continue for each day, following the zone grouping strategy)

## Getting There & Transport
(How to get from {user_details.get('start_location')} to {user_details.get('destination')})

## Tips & Budget Notes
{tips_guidance}

═══════════════════════════════════════════════════════════════
Output ONLY the raw Markdown text. Do NOT wrap the output in ```markdown code blocks. No preamble.
"""

    response = await chat_llm.ainvoke(
        [
            SystemMessage(content="You are a Travel Editor specializing in efficient, logical itineraries."),
            HumanMessage(content=prompt),
        ],
        config={"tags": ["final_itinerary"]},
    )
    draft = response.content
    log = log_usage("compiler", t0, response)

    return {
        "draft_itinerary": draft,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "next_node": "critic",
        "debug_logs": [log],
    }
