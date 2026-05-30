"""Interviewer node — gathers user preferences via conversation."""

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..llm import get_llm_for_role
from ..logger import get_logger
from ..schemas import UserPreferences
from ..state import AgentState
from ._utils import log_usage

logger = get_logger(__name__)

_SYSTEM_PROMPT = """
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

_EXTRACTION_PROMPT = """
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

_DESTINATION_KEYWORDS = [
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

_DURATION_KEYWORDS = [
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

MAX_INTERVIEW_ITERATIONS = 4


def _should_force_extraction(content: str, messages: list, interview_count: int) -> bool:
    """Check if we should bypass the LLM response and force extraction."""
    if "PLANNING_STARTED" in content.upper():
        return True

    last_user_msg = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    lower = last_user_msg.lower()

    has_destination = any(word in lower for word in _DESTINATION_KEYWORDS)
    has_duration = any(word in lower for word in _DURATION_KEYWORDS)

    if has_destination and has_duration and interview_count == 1:
        logger.info("FORCING EXTRACTION: First message contains destination + duration")
        return True

    return False


def _compute_season_suggestion(user_details: dict) -> str | None:
    """Generate season suggestion based on budget when no dates are specified."""
    if user_details.get("travel_dates"):
        return None

    budget = user_details.get("budget", "Medium").lower()
    suggestions = {
        "low": "Off-season (typically Nov-Mar for Europe): 30-50% cheaper accommodations and fewer crowds",
        "high": "Peak season (late spring/early autumn): Best weather and full availability of experiences",
    }
    return suggestions.get(
        budget, "Shoulder season (April-May or Sept-Oct): Great balance of weather, prices, and crowd levels"
    )


async def interviewer_node(state: AgentState) -> dict:
    t0 = time.time()
    messages = state.get("messages", [])
    interview_count = state.get("interview_count", 0) + 1

    lc_messages = [SystemMessage(content=_SYSTEM_PROMPT)]
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

    if _should_force_extraction(content, messages, interview_count) or force_extraction:
        structured_llm = extraction_llm.with_structured_output(UserPreferences)
        extraction_msg = [SystemMessage(content=_EXTRACTION_PROMPT), HumanMessage(content=str(messages))]

        try:
            user_prefs = await structured_llm.ainvoke(extraction_msg)
            user_details = user_prefs.model_dump()

            if not user_details.get("interests") or user_details.get("interests").lower() == "unknown":
                user_details["interests"] = "General Sightseeing"

            if not user_details.get("start_location"):
                user_details["start_location"] = "the user's current location"

            dests = user_details.get("destinations") or []
            primary = user_details.get("destination", "")
            if dests and primary and primary not in dests:
                dests.insert(0, primary)
            elif not dests and primary:
                dests = []
            user_details["destinations"] = dests

            season_suggestion = _compute_season_suggestion(user_details)

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
