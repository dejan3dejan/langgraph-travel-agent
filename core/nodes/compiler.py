"""Compiler node — writes the itinerary draft from research data."""

import json
import time

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import HumanMessage, SystemMessage

from ..geo import build_itinerary_geo, build_itinerary_geo_from_days, group_places_by_zone, optimize_day_route
from ..llm import get_llm_for_role
from ..logger import get_logger
from ..schemas import ItineraryDayPlan, render_constraints
from ..state import AgentState
from ._utils import _in_destination, log_usage

logger = get_logger(__name__)

_INTERNAL_KEYS = {"geocoding_status", "_type"}


def _slim_place(d: dict) -> dict:
    """Strip internal metadata keys that the LLM doesn't need."""
    return {k: v for k, v in d.items() if k not in _INTERNAL_KEYS and v is not None}


def rotate_for_variety(items: list, seed: int) -> list:
    """Rotate a candidate list by a per-request seed so a regenerate features the same pool in a
    different order, without dropping or adding any place."""
    if not items:
        return items
    k = seed % len(items)
    return items[k:] + items[:k]


def _build_regenerate_directive(base_itinerary: str) -> str:
    """Tell the writer to produce a plan that differs from the one the traveler already has, with the
    prior plan included only as the thing to avoid repeating."""
    return f"""REGENERATION REQUEST: the traveler wants a genuinely different plan from the one below.
Feature different restaurants and activities where the data allows, give the days different themes and a
different order, and vary the daily structure. Keep the same traveler profile and satisfy every hard
requirement. Do not reproduce the previous arrangement.

PREVIOUS PLAN (produce something different from this):
{base_itinerary}
"""


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


def _get_day_structure_guide(age_range: str, trip_type: str | None, base_label: str = "your hotel") -> str:
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
    return f"""
- **Morning:** [Activity] (X.X km from {base_label}, ~Y min walk/transit)
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


# Situation-aware sections (accommodation, transport, proximity anchor)


def _anchor_coords(hotel_dicts: list[dict], place_dicts: list[dict]) -> tuple[float | None, float | None]:
    """Anchor for proximity grouping: the hotel when there is one, else the centroid of the
    researched places, else nothing (the caller then skips grouping). Lets an already-in-city day
    plan still cluster by walking distance without a hotel to anchor on."""
    if hotel_dicts and hotel_dicts[0].get("lat") and hotel_dicts[0].get("lon"):
        return hotel_dicts[0]["lat"], hotel_dicts[0]["lon"]
    coords = [(p["lat"], p["lon"]) for p in place_dicts if p.get("lat") and p.get("lon")]
    if not coords:
        return None, None
    return sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords)


def _base_label(needs_accommodation: bool, in_destination: bool) -> str:
    """How the narrative refers to the day's anchor point, so we stop saying 'hotel' when there
    isn't one."""
    if needs_accommodation:
        return "your hotel"
    return "the city centre" if in_destination else "where you're staying"


def _accommodation_data_block(needs_accommodation: bool, hotel_json: str) -> str:
    """Hotel options handed to the writer, or empty when the user already has lodging sorted."""
    if not needs_accommodation:
        return ""
    return f"""
═══════════════════════════════════════════════════════════════
ACCOMMODATION OPTIONS
═══════════════════════════════════════════════════════════════
{hotel_json}
"""


def _accommodation_format_section(needs_accommodation: bool) -> str:
    """The 'Recommended Accommodation' output section, or empty when the user doesn't need it."""
    if not needs_accommodation:
        return ""
    return (
        "\n## Recommended Accommodation\n"
        "(Pick ONE hotel that matches the traveler profile - explain why it fits their needs)\n"
    )


def _origin_known(start_location: str | None) -> bool:
    """True when we have a real starting city. The default placeholder ('...current location') and
    the decline sentinel ('declined') both mean unknown and must degrade rather than leak into a
    'from X' transport line."""
    s = (start_location or "").strip().lower()
    return bool(s) and "current location" not in s and s != "declined"


def _transport_section(in_destination: bool, start_location: str, destination: str) -> str:
    """Transport output section, by situation: getting around once on the ground, getting there from
    a known origin, or arriving when the origin is unknown (no placeholder leakage)."""
    if in_destination:
        return f"\n## Getting Around {destination}\n(Local transport for hopping between the day's stops)\n"
    if _origin_known(start_location):
        return f"\n## Getting There & Transport\n(How to get from {start_location} to {destination})\n"
    return (
        f"\n## Arriving in {destination}\n"
        "(Main airport or station, how to reach the centre, and local transport for getting around)\n"
    )


def _build_edit_prompt(base_itinerary: str, edit_instruction: str) -> str:
    """Prompt for revising a delivered itinerary in place: apply only the requested change and keep
    the rest of the plan identical. The 'what changed' summary is surfaced separately (the user's own
    instruction), so the plan itself stays clean Markdown with no edit note baked in."""
    return f"""You are revising a travel itinerary the traveler already has. Apply ONLY the change
they ask for, plus any small fix it forces (for example the surrounding day's flow). Keep every
other day, heading, and detail exactly as it is.

EXISTING ITINERARY:
{base_itinerary}

REQUESTED CHANGE:
{edit_instruction}

Output the full revised itinerary in the same Markdown format, starting with its title.
Output ONLY the raw Markdown. No preamble, no code fences."""


def _build_day_assignment_prompt(draft_markdown: str, place_names: list[str]) -> str:
    """Prompt for the structured day pass: read the itinerary that was just written and report, per
    day, which known places it visits and in what order. Stops must be drawn only from the provided
    names so the caller can match them back to geocoded coordinates."""
    names = "\n".join(f"- {n}" for n in place_names)
    return f"""Read this travel itinerary and report its day-by-day structure for a map view.

For each day the itinerary describes, return:
- day: the day number as written
- title: a short theme for that day
- stops: the places visited that day, in the order they appear, using ONLY names from the list
  below. Skip anything not in the list; do not invent places.

AVAILABLE PLACES:
{names}

ITINERARY:
{draft_markdown}"""


async def _compile_edit(state: AgentState, t0: float) -> dict:
    """Edit mode: stream a revised itinerary from the prior plan and the change instruction. Skips
    research and the critic (next_node 'approved'); the critic counts empty research as missing data
    and would otherwise force a full re-research of a plan we deliberately did not re-research."""
    await adispatch_custom_event("reset_itinerary", {"message": "Updating your itinerary..."})
    chat_llm = get_llm_for_role("compiler")
    prompt = _build_edit_prompt(state["base_itinerary"], state["edit_instruction"])
    response = await chat_llm.ainvoke(
        [
            SystemMessage(content="You are a Travel Editor revising an existing itinerary."),
            HumanMessage(content=prompt),
        ],
        config={"tags": ["final_itinerary"]},
    )
    return {
        "draft_itinerary": response.content,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "next_node": "approved",
        "debug_logs": [log_usage("compiler", t0, response)],
    }


async def _assign_days(draft_markdown: str, places: list[dict]) -> tuple[list[dict] | None, dict]:
    """Second structured pass: read the itinerary just written and report each day's title and the
    places visited that day, in order. Returns (day list, log), or (None, log) when the pass fails or
    there is nothing to map, so the caller can fall back to proximity-zone days. Fail-open, like the
    critic, so a flaky extraction never blocks delivering the plan."""
    t0 = time.time()
    names = [p["name"] for p in places if p.get("name")]
    if not names:
        return None, log_usage("compiler_days", t0)
    structured = get_llm_for_role("extraction").with_structured_output(ItineraryDayPlan)
    try:
        result = await structured.ainvoke([HumanMessage(content=_build_day_assignment_prompt(draft_markdown, names))])
        return [d.model_dump() for d in result.days], log_usage("compiler_days", t0, result)
    except Exception as e:
        logger.warning(f"Day-assignment pass failed; map will fall back to zones: {e}")
        return None, log_usage("compiler_days", t0)


# Compiler node


async def compiler_node(state: AgentState) -> dict:
    t0 = time.time()

    # A post-plan edit revises the prior itinerary in place rather than recompiling from research.
    if state.get("edit_instruction") and state.get("base_itinerary"):
        return await _compile_edit(state, t0)

    await adispatch_custom_event("reset_itinerary", {"message": "Refining itinerary..."})

    logger.info("Writing itinerary draft with smart zone grouping...")
    user_details = state.get("user_details", {})

    food_data = state.get("food_data") or []
    activity_data = state.get("activity_data") or []
    hotel_data = state.get("hotel_data") or []

    food_dicts = [_slim_place(f.model_dump() if hasattr(f, "model_dump") else f) for f in food_data]
    activity_dicts = [_slim_place(a.model_dump() if hasattr(a, "model_dump") else a) for a in activity_data]
    hotel_dicts = [_slim_place(h.model_dump() if hasattr(h, "model_dump") else h) for h in hotel_data]

    # A regenerate rotates the pools by the per-request seed so different places get featured first.
    if state.get("regenerate"):
        seed = state.get("request_nonce") or 0
        food_dicts = rotate_for_variety(food_dicts, seed)
        activity_dicts = rotate_for_variety(activity_dicts, seed + 1)

    in_destination = _in_destination(user_details)
    needs_accommodation = user_details.get("needs_accommodation", True) is not False

    all_places = []
    for a in activity_dicts:
        a["_type"] = "activity"
        all_places.append(a)
    for f in food_dicts:
        f["_type"] = "restaurant"
        all_places.append(f)

    # Anchor on the hotel when there is one, otherwise the centroid of the places, so an
    # already-in-city day still groups by walking distance.
    anchor_lat, anchor_lon = _anchor_coords(hotel_dicts, all_places)

    zone_groups = {"near": [], "medium": [], "far": [], "remote": []}
    if anchor_lat and anchor_lon:
        raw_zone_groups = group_places_by_zone(all_places, anchor_lat, anchor_lon)
        for zone, places in raw_zone_groups.items():
            if places:
                optimization = optimize_day_route(places, anchor_lat, anchor_lon)
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

    base_label = _base_label(needs_accommodation, in_destination)
    narrative_style = _get_narrative_style(num_travelers, age_range, trip_type)
    overview_guidance = _get_overview_guidance(trip_type, age_range, num_travelers)
    day_structure_guide = _get_day_structure_guide(age_range, trip_type, base_label)
    tips_guidance = _get_tips_guidance(age_range, trip_type, num_travelers)

    accommodation_data = _accommodation_data_block(needs_accommodation, hotel_json)
    accommodation_format = _accommodation_format_section(needs_accommodation)
    start_location = user_details.get("start_location", "")
    transport_section = _transport_section(in_destination, start_location, user_details.get("destination", ""))
    hard_constraints, soft_constraints = render_constraints(user_details.get("constraints"))
    prior_violations = ", ".join((state.get("critique") or {}).get("hard_violations") or [])

    if in_destination:
        origin_line = f"- Currently in: {user_details.get('destination', '')}"
    elif _origin_known(start_location):
        origin_line = f"- Departing from: {start_location}"
    else:
        origin_line = "- Departing from: (not specified)"

    chat_llm = get_llm_for_role("compiler", temperature=0.9 if state.get("regenerate") else None)

    prompt = f"""
You are writing a practical travel itinerary for a trip to {user_details.get('destination')}.

═══════════════════════════════════════════════════════════════
TRAVELER PROFILE (use this to personalize the narrative)
═══════════════════════════════════════════════════════════════
{origin_line}
- Number of travelers: {num_travelers}
- Age range: {age_range}
- Trip type: {trip_type or "general sightseeing"}
- Duration: {user_details.get('duration')}
- Budget: {user_details.get('budget')}
- Interests: {user_details.get('interests')}
- Hard requirements (MUST satisfy, never violate): {hard_constraints or 'none'}
- Soft preferences (honor when possible): {soft_constraints or 'none'}
{f"- MUST AVOID (the previous draft violated these hard requirements): {prior_violations}" if prior_violations else ""}

{f"🌍 TIMING RECOMMENDATION: {season_suggestion}" if season_suggestion else ""}

═══════════════════════════════════════════════════════════════
NARRATIVE STYLE GUIDE
═══════════════════════════════════════════════════════════════
{narrative_style}
{accommodation_data}
═══════════════════════════════════════════════════════════════
🗺️ PRE-GROUPED PLACES BY PROXIMITY (USE THIS FOR DAY PLANNING!)
═══════════════════════════════════════════════════════════════
{grouped_json}

═══════════════════════════════════════════════════════════════
🎯 CRITICAL RULES FOR SMART ITINERARY
═══════════════════════════════════════════════════════════════
1. **FILL EVERY DAY OF THE TRIP.** Produce one section per day for the full duration, and anchor every
   day on at least one real researched place (plus a meal or two where it fits) so no day is left empty
   or vague. Spread the places across ALL the days rather than cramming them into the first few and
   leaving the rest as unstructured "free time".

2. **KEEP EACH DAY GEOGRAPHICALLY FOCUSED** using the zone groups: group nearby places on the same day,
   and for a longer trip split a large zone across several days instead of packing it into one.

3. **ALWAYS MENTION TRAVEL INFO:**
   - Distance from {base_label}
   - Estimated travel time
   - Transport recommendation (walk/metro/bus/taxi)

4. **BE SPECIFIC:** Use exact names, addresses from the data above.

5. **PERSONALIZE FOR TRAVELER PROFILE:**
   - Adjust pacing based on age_range
   - Match activity difficulty to trip_type
   - Use appropriate language tone (romantic vs family vs adventure)

6. **REMOTE LOCATIONS WARNING:** If using "day_trip_territory" places, add a note:
   "⚠️ This is a day trip - allow extra travel time"

7. **HARD REQUIREMENTS ARE NON-NEGOTIABLE:** Every recommendation MUST satisfy the hard requirements
   above. Allergies and dietary needs (including halal, kosher, vegetarian) are safety-critical:
   never suggest food or venues that conflict with them. Honor the soft preferences when you can.

═══════════════════════════════════════════════════════════════
OUTPUT FORMAT (Markdown)
═══════════════════════════════════════════════════════════════

# {user_details.get('duration', 'Your')} {trip_type.title() if trip_type else ''} Trip to {user_details.get('destination')}

## Overview
{overview_guidance}

{f"## 🌤️ Best Time to Visit\\n{season_suggestion}\\n" if season_suggestion else ""}
{accommodation_format}
## Day-by-Day Itinerary

### Day 1: [Zone Theme - e.g., "Getting Oriented Near {base_label}"]
{day_structure_guide}

### Day 2: [Zone Theme]
(Continue for each day, following the zone grouping strategy)
{transport_section}
## Tips & Budget Notes
{tips_guidance}

═══════════════════════════════════════════════════════════════
Output ONLY the raw Markdown text. Do NOT wrap the output in ```markdown code blocks. No preamble.
"""

    base_itinerary = state.get("base_itinerary")
    if state.get("regenerate") and base_itinerary:
        prompt = _build_regenerate_directive(base_itinerary) + "\n" + prompt

    response = await chat_llm.ainvoke(
        [
            SystemMessage(content="You are a Travel Editor specializing in efficient, logical itineraries."),
            HumanMessage(content=prompt),
        ],
        config={"tags": ["final_itinerary"]},
    )
    draft = response.content
    logs = [log_usage("compiler", t0, response)]

    # Drive the map's days from the itinerary's real day structure (a structured pass over the plan
    # just written), not proximity zones, so a multi-day trip in a compact city keeps its days.
    hotel = hotel_dicts[0] if hotel_dicts else None
    day_plan, day_log = await _assign_days(draft, all_places)
    logs.append(day_log)

    itinerary_geo = build_itinerary_geo_from_days(day_plan, all_places, hotel) if day_plan else None
    if not itinerary_geo or not itinerary_geo["days"]:
        if day_plan:
            logger.warning("Day-assignment matched no plottable stops; map fell back to proximity zones")
        itinerary_geo = build_itinerary_geo(zone_groups, hotel)

    return {
        "draft_itinerary": draft,
        "itinerary_geo": itinerary_geo,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "next_node": "critic",
        "debug_logs": logs,
    }
