import json
import time
from typing import Any

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from .llm import USE_REACT_AGENT, get_llm_for_role, get_llm_with_tools
from .logger import get_logger
from .logistics import logistics_agent
from .schemas import ActivityList, HotelList, ItineraryCritique, RestaurantList, UserPreferences
from .semantic_cache import cache_research_results, semantic_search, should_use_cache
from .state import AgentState
from .tools import TRAVEL_TOOLS, group_places_by_zone, optimize_day_route

logger = get_logger(__name__)


def _get_narrative_style(num_travelers: int, age_range: str, trip_type: str | None) -> str:
    """Generate narrative tone guidance for compiler."""

    style = []

    # Addressing style
    if num_travelers == 1:
        style.append("- Address the traveler as 'you' (singular)")
    else:
        style.append(f"- Address as 'you' (plural) - remember there are {num_travelers} travelers")

    # Tone by trip type
    if trip_type == "romantic":
        style.append("- Use romantic, intimate language ('your evening together', 'a cozy dinner for two')")
        style.append("- Emphasize ambiance and special moments")
    elif trip_type == "family":
        style.append("- Family-friendly language ('the kids will love...', 'parents can relax while...')")
        style.append("- Mention logistics (restrooms, snack stops, break times)")
    elif trip_type == "adventure":
        style.append("- Energetic, action-oriented language ('conquer', 'explore', 'challenge yourself')")
        style.append("- Emphasize physical experiences and adrenaline")
    elif trip_type == "business" or trip_type == "workation":
        style.append("- Professional tone, efficient pacing")
        style.append("- Mention wifi/workspace availability")
    elif trip_type == "relaxation":
        style.append("- Calm, soothing language ('unwind', 'leisurely', 'at your own pace')")
        style.append("- Minimize packed schedules")
    else:
        style.append("- Balanced, informative tone")

    # Pacing by age
    if age_range == "kids" or age_range == "mixed":
        style.append("- Build in rest breaks and flexible timing")
        style.append("- Shorter activity blocks (1-2 hours max)")
    elif age_range == "seniors":
        style.append("- Emphasize comfort and accessibility")
        style.append("- Slower pacing, more sitting/rest opportunities")
    elif age_range == "young_adults":
        style.append("- Pack activities densely if interests allow")
        style.append("- Mention social/nightlife options")

    return "\n".join(style)


def _get_overview_guidance(trip_type: str | None, age_range: str, num_travelers: int) -> str:
    """Generate guidance for Overview section."""

    if trip_type == "romantic":
        return "(Write a romantic intro: 'Your romantic escape to [dest]...', mention couple-friendly highlights)"
    elif trip_type == "family":
        return f"(Family-focused intro for {num_travelers} travelers, mention kid-friendly highlights and parent conveniences)"
    elif trip_type == "adventure":
        return "(Energetic intro highlighting outdoor activities, physical challenges, and natural beauty)"
    elif trip_type == "business":
        return "(Professional intro balancing work needs with cultural exploration)"
    else:
        return "(Brief summary of destination highlights tailored to traveler interests)"


def _get_day_structure_guide(age_range: str, trip_type: str | None) -> str:
    """Generate guidance for daily schedule structure."""

    if age_range == "kids" or age_range == "mixed":
        return """
- **Morning:** (Kid-friendly activity, finish before lunch nap time)
- **Lunch:** (Restaurant with kids menu, note high chairs/changing facilities)
- **Afternoon:** (Lighter activity or hotel break for naps)
- **Evening:** (Early dinner, family-friendly restaurant)
"""
    elif trip_type == "romantic":
        return """
- **Morning:** (Leisurely start, romantic breakfast spot)
- **Midday:** (Couple's activity or scenic walk)
- **Afternoon:** (Cultural site or relaxing experience)
- **Evening:** (Romantic dinner with ambiance notes)
"""
    elif trip_type == "adventure":
        return """
- **Early Morning:** (Start early for best light/fewer crowds)
- **Morning-Afternoon:** (Main adventure activity, 3-5 hours)
- **Late Afternoon:** (Recovery time or lighter exploration)
- **Evening:** (Hearty meal to refuel)
"""
    else:
        return """
- **Morning:** [Activity] (X.X km from hotel, ~Y min walk/transit)
- **Lunch:** [Restaurant] (Address) - [Cuisine], [Price]
- **Afternoon:** [Activity]
- **Evening:** [Dinner spot]
"""


def _get_tips_guidance(age_range: str, trip_type: str | None, num_travelers: int) -> str:
    """Generate guidance for Tips section."""

    tips = []

    if age_range == "kids" or age_range == "mixed":
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


def _get_activity_focus(trip_type: str, age_range: str, interests: str) -> str:
    """
    Returns a string summary of what kind of activities to focus on,
    based on trip type, age range, and interests.
    """
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


def log_usage(node_name: str, start_time: float, response: Any = None) -> dict:
    """Build a timing/token-count log entry for debug_logs."""
    duration = time.time() - start_time
    tokens = 0

    try:
        if response:
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens = response.usage_metadata.get("total_tokens", 0)
            elif hasattr(response, "response_metadata") and response.response_metadata:
                tokens = response.response_metadata.get("token_usage", {}).get("total_tokens", 0)
    except Exception:
        pass

    return {
        "node": node_name,
        "latency_sec": round(duration, 2),
        "total_tokens": tokens,
        "timestamp": time.strftime("%H:%M:%S"),
    }


async def interviewer_node(state: AgentState) -> dict:
    t0 = time.time()
    messages = state.get("messages", [])
    interview_count = state.get("interview_count", 0) + 1

    MAX_INTERVIEW_ITERATIONS = 4

    system_prompt = """
    You are 'Atlas', a charming and intelligent Travel Consultant.
    GOAL: Gather [Destination, Duration, Budget, Interests] to start planning.

═══════════════════════════════════════════════════════════════
PHASE 1: DEEP SCAN
═══════════════════════════════════════════════════════════════
Review the ENTIRE conversation history.
- Did the user mention their Budget 3 messages ago? -> IT COUNTS.
- Did the user say "Surprise me"? -> That means Interests = "General Sightseeing".
- Did the user mention a region like "Wisconsin" or "Texas"? -> ACCEPT IT as destination.
- Did the user mention dates like "March 13th to March 17th"? -> Calculate duration from dates.

TEMPORAL CLUES (highest priority):
- Specific dates: "March 13th to 17th" → travel_dates = "March 13-17, 2026"
- Month mentions: "going in summer" → season_preference = "peak"
- Flexibility signals: "whenever is cheapest" → season_preference = "off_season"
- Budget+timing link: "low budget, flexible dates" → suggest off-season

TRAVELER COMPOSITION:
- Plural language: "we", "us", "our" → num_travelers ≥ 2
- Explicit numbers: "me and my wife" → 2, "family of 4" → 4
- Age hints: "with kids", "elderly parents", "college friends" → age_range
- Relationship clues: "honeymoon", "bachelor party", "anniversary" → trip_type + age_range

TRIP PURPOSE (often implicit):
- Language style: "romantic getaway" → romantic, "team building" → business
- Activity preferences: "hiking trails" → adventure, "museums + cafes" → cultural
- Pace indicators: "slow travel", "whirlwind tour", "relax" → trip_type

═══════════════════════════════════════════════════════════════
PHASE 2: SMART DEFAULTS
═══════════════════════════════════════════════════════════════
If some info is missing but you have enough context, USE SMART DEFAULTS:

TIMING:
- No dates mentioned → season_preference = "flexible"
- Budget = "Low" + no dates → season_preference = "off_season" (actively suggest this!)
- Budget = "High" + no dates → season_preference = "peak" (they can afford it)

TRAVELERS:
- No plural language → num_travelers = 1
- "We" but no count → num_travelers = 2 (most common)
- "Family" but no details → num_travelers = 4, age_range = "mixed"

TRIP TYPE:
- Extract from interests:
  * "food, wine, romance" → romantic
  * "hiking, camping, nature" → adventure
  * "museums, history, art" → cultural
  * No clear signal → None (let compiler be generic)

- No budget mentioned but trip details given? -> Assume "Medium budget"
- No duration but dates given? -> Calculate from dates
- No specific interests? -> Default to "General Sightseeing"

═══════════════════════════════════════════════════════════════
PHASE 3: SEASON INTELLIGENCE
═══════════════════════════════════════════════════════════════
If travel_dates is None and season_preference is "flexible":

1. Consider destination climate:
   - Tropical: avoid rainy season
   - Mediterranean: suggest shoulder season (cheaper, less crowded)
   - Northern Europe: avoid deep winter unless budget allows indoor activities

2. Cross-reference with budget:
   - Low budget → "Off-season (Nov-Mar except holidays) = 30-50% cheaper hotels"
   - Medium budget → "Shoulder season (Apr-May, Sep-Oct) = good weather + reasonable prices"
   - High budget → "Peak season if you want best weather, or off-peak for exclusivity"

3. Store suggestion internally (will be added to state later)

═══════════════════════════════════════════════════════════════
PHASE 4: VERIFICATION (Immediate Extraction Check)
═══════════════════════════════════════════════════════════════
DO NOT WRITE CONVERSATIONAL RESPONSES IF YOU HAVE DATA!

Check if you have the MINIMUM requirements:
1. Destination (City, State, Region, or Country - ANY is OK!)
2. Duration (Days OR date range)
3. Budget (Amount, Level, OR assume Medium if trip is detailed)

IF ALL 3 ARE PRESENT → YOU MUST OUTPUT "PLANNING_STARTED" IMMEDIATELY.

DO NOT:
- Write travel advice
- Describe what you'll plan
- Ask for confirmation
- Suggest timing options in conversational way

ONLY:
- Output "PLANNING_STARTED" to trigger research

Example of what NOT to do:
❌ "I'm envisioning a luxurious trip... let me start putting a sketch together"
❌ "Based on your preferences, I'll create a romantic itinerary"
❌ "Let me research that for you..."

Example of what TO do:
✅ "PLANNING_STARTED"

═══════════════════════════════════════════════════════════════
PHASE 5: PROGRESSIVE QUESTIONING (Only if critical data missing)
═══════════════════════════════════════════════════════════════
IF (missing destination OR duration):
    → Ask THE MOST IMPORTANT missing field
    → Keep it casual: "Quick question – where are you thinking of going?"
    → MAX 1-2 sentences

ELIF (interview_count >= 4):
    → Force "PLANNING_STARTED" with best guesses

EXAMPLES:
- Missing destination: "Where would you like to go?"
- Missing duration: "How many days are you thinking?"
- Has everything: "PLANNING_STARTED" (no extra text!)

═══════════════════════════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════════════════════════
1. NEVER say "I cannot do this". You are an expert planner.
2. If Destination is a region (e.g., "Texas", "Wisconsin"), ACCEPT IT. Do not ask for specific cities.
3. Be AGGRESSIVE about starting - users want plans, not interviews!
4. If you have destination and ANY hint of duration → OUTPUT "PLANNING_STARTED".
5. If the user's FIRST message contains Destination + Duration → IMMEDIATELY "PLANNING_STARTED"
6. Your job is to EXTRACT and TRIGGER, not to PRE-PLAN. Research nodes will do the work.
"""

    lc_messages = [SystemMessage(content=system_prompt)]
    for m in messages:
        if m["role"] == "user":
            lc_messages.append(HumanMessage(content=m["content"]))
        else:
            lc_messages.append(AIMessage(content=m["content"]))

    chat_llm = get_llm_for_role("interviewer")
    extraction_llm = get_llm_for_role("extraction")

    force_extraction = interview_count >= MAX_INTERVIEW_ITERATIONS

    if force_extraction:
        logger.warning(f"Interviewer hit max iterations ({MAX_INTERVIEW_ITERATIONS}). Forcing extraction...")
        content = "PLANNING_STARTED"
    else:
        response = await chat_llm.ainvoke(lc_messages, config={"tags": ["final_itinerary"]})
        content = response.content

    log = log_usage("interviewer", t0, response if not force_extraction else None)

    # Override: if the LLM wrote a conversational reply but we already have
    # both destination + duration in the first message, force extraction anyway
    if "PLANNING_STARTED" not in content.upper():
        last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")

        destination_keywords = [
            "paris",
            "london",
            "rome",
            "tokyo",
            "new york",
            "barcelona",
            "amsterdam",
            "berlin",
            "prague",
            "vienna",
            "dublin",
            "lisbon",
            "madrid",
            "athens",
            "trip to",
            "visit",
            "going to",
            "traveling to",
            "travel to",
            "explore",
        ]
        has_destination = any(word in last_user_msg.lower() for word in destination_keywords)

        duration_keywords = [
            "day",
            "week",
            "weekend",
            "night",
            "3-day",
            "five days",
            "two weeks",
            "1 day",
            "2 days",
            "3 days",
            "4 days",
            "5 days",
            "6 days",
            "7 days",
        ]
        has_duration = any(word in last_user_msg.lower() for word in duration_keywords)

        if has_destination and has_duration and interview_count == 1:
            logger.info("FORCING EXTRACTION: First message contains destination + duration")
            content = "PLANNING_STARTED"

    if "PLANNING_STARTED" in content.upper() or force_extraction:
        structured_llm = extraction_llm.with_structured_output(UserPreferences)

        prompt = """
Analyze the conversation and extract user preferences.

EXTRACTION RULES:
1. If the user hasn't specified a start location, set it to 'the user's current location'.
2. Extract num_travelers from plural language ("we" = 2, "family" = 4, solo words = 1)
3. Extract age_range from context ("kids", "honeymoon" = adults, etc.)
4. Extract trip_type from language ("romantic", "adventure", "family", etc.)
5. If user mentions specific dates, put them in travel_dates
6. If user mentions timing preferences (cheap, off-season), set season_preference
7. Auto-fill interests if missing with "General Sightseeing"
8. Extract budget from context (if not mentioned, use "Medium")
9. MULTI-DESTINATION: If the user mentions multiple cities/regions (e.g. "Paris and Rome",
   "Barcelona then Lisbon", "tour of Italy and Greece"), set `destinations` to the ordered list
   AND set `destination` to the first one. If only one destination, leave `destinations` empty.

CONVERSATION:
"""

        extraction_msg = [SystemMessage(content=prompt), HumanMessage(content=str(messages))]

        try:
            user_prefs = await structured_llm.ainvoke(extraction_msg)
            user_details = user_prefs.model_dump()

            if not user_details.get("interests") or user_details.get("interests").lower() == "unknown":
                user_details["interests"] = "General Sightseeing"

            if not user_details.get("start_location"):
                user_details["start_location"] = "the user's current location"

            # Ensure primary destination is first in the multi-dest list
            dests = user_details.get("destinations") or []
            primary = user_details.get("destination", "")
            if dests and primary and primary not in dests:
                dests.insert(0, primary)
            elif not dests and primary:
                dests = []
            user_details["destinations"] = dests

            season_suggestion = None
            if not user_details.get("travel_dates"):
                budget = user_details.get("budget", "Medium")

                if budget.lower() == "low":
                    season_suggestion = (
                        "Off-season (typically Nov-Mar for Europe): 30-50% cheaper accommodations and fewer crowds"
                    )
                elif budget.lower() == "high":
                    season_suggestion = (
                        "Peak season (late spring/early autumn): Best weather and full availability of experiences"
                    )
                else:
                    season_suggestion = (
                        "Shoulder season (April-May or Sept-Oct): Great balance of weather, prices, and crowd levels"
                    )

        except Exception as e:
            logger.error(f"Extraction Failed: {e}")
            user_details = {
                "destination": "Paris",
                "start_location": "the user's current location",
                "budget": "Medium",
                "duration": "3 days",
                "interests": "General",
                "focus": [],
                "num_travelers": 2,
                "age_range": "adults",
                "trip_type": None,
                "travel_dates": None,
                "season_preference": "flexible",
            }
            season_suggestion = None

        old_details = state.get("user_details", {})
        old_dest = old_details.get("destination")
        new_dest = user_details.get("destination")

        if old_dest and old_dest != new_dest:
            logger.info(f"Destination changed from {old_dest} to {new_dest}. Resetting research data.")
            return {
                "user_details": user_details,
                "season_suggestion": season_suggestion,
                "food_data": None,
                "activity_data": None,
                "hotel_data": None,
                "draft_itinerary": None,
                "iteration_count": 0,
                "interview_count": 0,
                "next_node": "research",
                "messages": [
                    {"role": "model", "content": f"Changing plans to {new_dest}! Let me research that for you..."}
                ],
            }

        return {
            "messages": [{"role": "model", "content": "Great! I'm researching your trip now..."}],
            "user_details": user_details,
            "season_suggestion": season_suggestion,
            "interview_count": 0,
            "next_node": "research",
            "debug_logs": [log],
        }

    return {
        "messages": [{"role": "model", "content": content}],
        "interview_count": interview_count,
        "next_node": "interviewer",
        "debug_logs": [log],
    }


def _get_destinations(details: dict) -> list[str]:
    """Return list of destinations to research (supports multi-destination)."""
    dests = details.get("destinations") or []
    primary = details.get("destination", "")
    if dests:
        return dests
    return [primary] if primary else []


async def _research_food_for_dest(dest: str, details: dict) -> list:
    """Research restaurants for a single destination."""
    from .schemas import Restaurant

    constraints = details.get("constraints", "")
    num_travelers = details.get("num_travelers", 1)
    age_range = details.get("age_range", "adults")
    budget = details.get("budget", "Medium")

    search_query = f"best restaurants in {dest} for {age_range} {budget} budget"

    cache_hit = await semantic_search(
        query=search_query, category="restaurants", destination=dest, similarity_threshold=0.80, max_age_days=30
    )
    use_cache, reason = await should_use_cache(cache_hit, "restaurants")

    if use_cache and cache_hit:
        logger.info(f"[{dest}] Cache hit for restaurants ({reason})")
        return [Restaurant(**item) for item in cache_hit["results"]]

    logger.info(f"[{dest}] Cache miss for restaurants — searching Google...")

    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    age_filters = {
        "kids": "- MUST be kid-friendly (high chairs, kids menu)",
        "seniors": "- Accessible (ground floor or elevator, comfortable seating)",
        "young_adults": "- Trendy, Instagram-worthy spots welcome",
    }.get(age_range, "")

    search_prompt = f"""
    Use Google Search to find 3 REAL, currently operating restaurants in {dest}.

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

    grounded_response = await research_llm.ainvoke([HumanMessage(content=search_prompt)])
    grounded_text = getattr(grounded_response, "content", str(grounded_response))

    extraction_llm = get_llm_for_role("extraction")
    structured_extractor = extraction_llm.with_structured_output(RestaurantList)
    result = await structured_extractor.ainvoke(
        [
            HumanMessage(
                content=f"Extract restaurant information from this text into structured format.\n{grounded_text}"
            )
        ]
    )
    data = result.items

    if data:
        data_dicts = [item.model_dump() for item in data]
        await cache_research_results(
            query=search_query, category="restaurants", destination=dest, results=data_dicts, freshness_days=30
        )
    return data


async def research_food_node(state: AgentState) -> dict:
    """Food research — iterates over all destinations for multi-city trips."""
    t0 = time.time()
    details = state.get("user_details", {})
    destinations = _get_destinations(details)

    all_data = []
    for dest in destinations:
        try:
            data = await _research_food_for_dest(dest, details)
            all_data.extend(data)
        except Exception as e:
            logger.error(f"Food Agent Error [{dest}]: {e}")

    log = {
        "node": "research_food",
        "latency_sec": round(time.time() - t0, 2),
        "destinations": destinations,
        "results_total": len(all_data),
        "timestamp": time.strftime("%H:%M:%S"),
    }
    return {"food_data": all_data, "debug_logs": [log]}


async def _research_activity_for_dest(dest: str, details: dict) -> list:
    """Research activities for a single destination."""
    from .schemas import Activity

    constraints = details.get("constraints", "")
    age_range = details.get("age_range", "adults")
    trip_type = details.get("trip_type")
    num_travelers = details.get("num_travelers", 1)
    interests = details.get("interests", "General Sightseeing")

    search_query = f"best activities in {dest} for {age_range} {trip_type or 'sightseeing'} {interests}"

    cache_hit = await semantic_search(
        query=search_query, category="activities", destination=dest, similarity_threshold=0.75, max_age_days=45
    )
    use_cache, reason = await should_use_cache(cache_hit, "activities")

    if use_cache and cache_hit:
        logger.info(f"[{dest}] Cache hit for activities ({reason})")
        return [Activity(**item) for item in cache_hit["results"]]

    logger.info(f"[{dest}] Cache miss for activities — searching Google...")

    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    activity_focus = _get_activity_focus(trip_type, age_range, interests)

    search_prompt = f"""
    Use Google Search to find 3 REAL activities/attractions in {dest}.

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

    grounded_response = await research_llm.ainvoke([HumanMessage(content=search_prompt)])
    grounded_text = getattr(grounded_response, "content", str(grounded_response))

    extraction_llm = get_llm_for_role("extraction")
    structured_extractor = extraction_llm.with_structured_output(ActivityList)
    result = await structured_extractor.ainvoke(
        [HumanMessage(content=f"Extract activity information from this text into structured format.\n{grounded_text}")]
    )
    data = result.items

    if data:
        data_dicts = [item.model_dump() for item in data]
        await cache_research_results(
            query=search_query, category="activities", destination=dest, results=data_dicts, freshness_days=45
        )
    return data


async def research_activity_node(state: AgentState) -> dict:
    """Activity research — iterates over all destinations for multi-city trips."""
    t0 = time.time()
    details = state.get("user_details", {})
    destinations = _get_destinations(details)

    all_data = []
    for dest in destinations:
        try:
            data = await _research_activity_for_dest(dest, details)
            all_data.extend(data)
        except Exception as e:
            logger.error(f"Activity Agent Error [{dest}]: {e}")

    log = {
        "node": "research_activity",
        "latency_sec": round(time.time() - t0, 2),
        "destinations": destinations,
        "results_total": len(all_data),
        "timestamp": time.strftime("%H:%M:%S"),
    }
    return {"activity_data": all_data, "debug_logs": [log]}


async def _research_hotel_for_dest(dest: str, details: dict) -> list:
    """Research hotels for a single destination."""
    from .schemas import Hotel

    constraints = details.get("constraints", "")
    budget = details.get("budget", "Medium")
    num_travelers = details.get("num_travelers", 1)

    search_query = f"best hotels in {dest} {budget} budget for {num_travelers} travelers"

    cache_hit = await semantic_search(
        query=search_query, category="hotels", destination=dest, similarity_threshold=0.85, max_age_days=14
    )
    use_cache, reason = await should_use_cache(cache_hit, "hotels")

    if use_cache and cache_hit:
        logger.info(f"[{dest}] Cache hit for hotels ({reason})")
        return [Hotel(**item) for item in cache_hit["results"]]

    logger.info(f"[{dest}] Cache miss for hotels — searching Google...")

    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])

    search_prompt = f"""
    Use Google Search to find 3 REAL hotels in {dest}.

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

    grounded_response = await research_llm.ainvoke([HumanMessage(content=search_prompt)])
    grounded_text = getattr(grounded_response, "content", str(grounded_response))

    extraction_llm = get_llm_for_role("extraction")
    structured_extractor = extraction_llm.with_structured_output(HotelList)
    result = await structured_extractor.ainvoke(
        [HumanMessage(content=f"Extract hotel information from this text into structured format.\n{grounded_text}")]
    )
    data = result.items

    if data:
        data_dicts = [item.model_dump() for item in data]
        await cache_research_results(
            query=search_query, category="hotels", destination=dest, results=data_dicts, freshness_days=14
        )
    return data


async def research_hotel_node(state: AgentState) -> dict:
    """Hotel research — iterates over all destinations for multi-city trips."""
    t0 = time.time()
    details = state.get("user_details", {})
    destinations = _get_destinations(details)

    all_data = []
    for dest in destinations:
        try:
            data = await _research_hotel_for_dest(dest, details)
            all_data.extend(data)
        except Exception as e:
            logger.error(f"Hotel Agent Error [{dest}]: {e}")

    log = {
        "node": "research_hotel",
        "latency_sec": round(time.time() - t0, 2),
        "destinations": destinations,
        "results_total": len(all_data),
        "timestamp": time.strftime("%H:%M:%S"),
    }
    return {"hotel_data": all_data, "debug_logs": [log]}


_INTERNAL_KEYS = {"geocoding_status", "zone", "_type"}


def _slim_place(d: dict) -> dict:
    """Strip internal metadata keys that the LLM doesn't need."""
    return {k: v for k, v in d.items() if k not in _INTERNAL_KEYS and v is not None}


async def compiler_node(state: AgentState) -> dict:
    t0 = time.time()
    # Signal frontend to clear the previous draft (matters when critic loops back)
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

        # Nearest-neighbor optimization per zone before passing to the LLM
        for zone, places in raw_zone_groups.items():
            if places:
                optimization = optimize_day_route.invoke(
                    {"places": places, "hotel_lat": hotel_lat, "hotel_lon": hotel_lon}
                )
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

    if USE_REACT_AGENT:
        draft, log = await _run_compiler_agent(user_details, hotel_dicts, grouped_data, t0)
    else:
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


async def _run_compiler_agent(user_details: dict, hotel_dicts: list, grouped_data: dict, t0: float) -> tuple:
    """ReAct agent compiler — uses tools to optimize routes before writing."""
    logger.info("Running ReAct Agent Compiler with tools...")

    llm_with_tools = get_llm_with_tools(TRAVEL_TOOLS)

    hotel_json = json.dumps(hotel_dicts[:1], indent=2, ensure_ascii=False) if hotel_dicts else "{}"
    grouped_json = json.dumps(grouped_data, indent=2, ensure_ascii=False)

    agent_prompt = f"""
You are Atlas, a Travel Planner Agent with access to tools for route optimization.

TASK: Create a {user_details.get('duration')} itinerary for {user_details.get('destination')}.

TRAVELER INFO:
- Start: {user_details.get('start_location', 'their location')}
- Budget: {user_details.get('budget')}
- Interests: {user_details.get('interests')}

HOTEL (Base Location):
{hotel_json}

PLACES GROUPED BY ZONE:
{grouped_json}

AVAILABLE TOOLS:
1. optimize_day_route - Optimize order of places for a day (minimizes travel)
2. calculate_distance - Check distance between two points
3. check_zone - Verify which zone a place is in

YOUR WORKFLOW:
1. FIRST: Use optimize_day_route for each day's activities to find the best order
2. THEN: Write the final itinerary using the optimized order

OUTPUT FORMAT (After using tools):
Write a complete Markdown itinerary with:
- Overview
- Recommended Accommodation
- Day-by-Day Itinerary (using optimized routes)
- Getting There & Transport
- Tips & Budget Notes

Start by analyzing the zones and calling optimize_day_route if needed.
"""

    messages = [
        SystemMessage(
            content="You are a Travel Planner Agent. Use tools to optimize routes, then write the itinerary."
        ),
        HumanMessage(content=agent_prompt),
    ]

    max_iterations = 3
    for _ in range(max_iterations):
        response = await llm_with_tools.ainvoke(messages, config={"tags": ["final_itinerary"]})
        messages.append(response)

        if hasattr(response, "tool_calls") and response.tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})

                tool_result = None
                for tool in TRAVEL_TOOLS:
                    if tool.name == tool_name:
                        try:
                            tool_result = tool.invoke(tool_args)
                        except Exception as e:
                            tool_result = f"Error: {e}"
                        break

                if tool_result is None:
                    tool_result = f"Unknown tool: {tool_name}"

                from langchain_core.messages import ToolMessage

                messages.append(ToolMessage(content=str(tool_result), tool_call_id=tool_call.get("id", "")))
        else:
            break

    draft = response.content if hasattr(response, "content") else str(response)
    log = log_usage("compiler_agent", t0, response)

    return draft, log


async def critic_node(state: AgentState) -> dict:
    t0 = time.time()
    draft = state.get("draft_itinerary", "")
    user_details = state.get("user_details", {})
    logger.info("Reviewing itinerary draft...")

    extraction_llm = get_llm_for_role("extraction")
    structured_critic = extraction_llm.with_structured_output(ItineraryCritique)

    prompt = f"""
    Critique this itinerary for a trip to {user_details.get('destination')}.

    CHECKLIST:
    1. Logic Gaps: Are there transport options from {user_details.get('start_location')}?
    2. Data Quality: Are the restaurants and activities specific and real (not generic)?
    3. User Needs: Does it respect the budget ({user_details.get('budget')}) and interests ({user_details.get('interests')})?

    If data for food, activities, or hotels is missing, poor quality, or irrelevant, list them in 'missing_data'.
    If 'missing_data' is NOT empty, 'approved' MUST be False.

    ITINERARY:
    {draft}
    """

    try:
        result = await structured_critic.ainvoke([HumanMessage(content=prompt)])
        critique = result.model_dump()
        log = log_usage("critic", t0, result)

        if critique.get("approved"):
            next_node = "approved"
        elif critique.get("missing_data"):
            next_node = "research"
        else:
            next_node = "compiler"

    except Exception as e:
        logger.error(f"Critic Error: {e}")
        critique = {"approved": True, "feedback": "Auto Approved (Critic Error)", "score": 10, "missing_data": []}
        next_node = "approved"
        log = log_usage("critic", t0)

    return {"critique": critique, "next_node": next_node, "debug_logs": [log]}


workflow = StateGraph(AgentState)

workflow.add_node("interviewer", interviewer_node)
workflow.add_node("research_food", research_food_node)
workflow.add_node("research_activity", research_activity_node)
workflow.add_node("research_hotel", research_hotel_node)
workflow.add_node("logistics", logistics_agent)
workflow.add_node("compiler", compiler_node)
workflow.add_node("critic", critic_node)

workflow.add_edge(START, "interviewer")


def router(state: AgentState):
    next_node = state.get("next_node")

    if state.get("iteration_count", 0) >= 3:
        return END

    if next_node == "research":
        critique = state.get("critique", {})
        missing = critique.get("missing_data", [])
        user_details = state.get("user_details", {})
        focus = user_details.get("focus", [])

        # 1. If Critic identified missing data, prioritize that
        if missing:
            targets = []
            if "food" in missing:
                targets.append("research_food")
            if "activities" in missing:
                targets.append("research_activity")
            if "hotels" in missing:
                targets.append("research_hotel")
            return targets

        # 2. If it's the initial run and User has specific focus
        if focus:
            targets = []
            if "food" in focus:
                targets.append("research_food")
            if "activities" in focus:
                targets.append("research_activity")
            if "hotels" in focus:
                targets.append("research_hotel")
            if targets:
                return targets

        # 3. Default: run all
        return ["research_food", "research_activity", "research_hotel"]

    if next_node == "interviewer":
        return END
    if next_node == "approved":
        return END
    if next_node == "critic":
        return "critic"
    if next_node == "compiler":
        return "compiler"

    return END


workflow.add_conditional_edges("interviewer", router)
workflow.add_edge("research_food", "logistics")
workflow.add_edge("research_activity", "logistics")
workflow.add_edge("research_hotel", "logistics")
workflow.add_edge("logistics", "compiler")
workflow.add_conditional_edges("compiler", router)
workflow.add_conditional_edges("critic", router)

app = workflow.compile()
