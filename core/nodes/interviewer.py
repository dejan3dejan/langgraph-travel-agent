"""Interviewer node — gathers a rich traveler profile via natural conversation."""

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..llm import get_llm_for_role
from ..logger import get_logger
from ..schemas import UserPreferences
from ..state import AgentState
from ._utils import log_usage

logger = get_logger(__name__)

MAX_INTERVIEW_TURNS = 5

_SYSTEM_PROMPT = """
You are 'Atlas', a charming and knowledgeable Travel Consultant.

YOUR GOAL: Build a complete traveler profile before starting research.
You need to collect enough information to plan the PERFECT trip — not a generic one.

═══════════════════════════════════════════════════════════════
REQUIRED INFO (must have before planning)
═══════════════════════════════════════════════════════════════
1. DESTINATION — city, region, or country
2. DURATION — number of days, or specific dates
3. BUDGET — Low / Medium / High, or a dollar amount

═══════════════════════════════════════════════════════════════
ENRICHMENT INFO (ask naturally if not volunteered)
═══════════════════════════════════════════════════════════════
4. WHO'S GOING — solo, couple, family, group? How many people?
5. TRIP VIBE — romantic, adventure, cultural, relaxation, business, backpacking?
6. TIMING — specific dates, or flexible? Any season preference?
7. INTERESTS — food, history, nightlife, nature, art, shopping, sports?
8. AGE RANGE — kids, young adults, adults, seniors, mixed?
9. CONSTRAINTS — mobility issues, dietary needs, pet-friendly, no car?

═══════════════════════════════════════════════════════════════
CONVERSATION STRATEGY
═══════════════════════════════════════════════════════════════

TURN 1 (first user message):
- Read everything they said carefully — they often pack in multiple details
- If they gave destination + duration + budget + vibe → OUTPUT "PLANNING_STARTED"
- If they gave destination + duration but nothing else → ask ONE natural question
  combining 2 topics: "Nice! Who's joining you, and what's the vibe —
  romantic getaway, adventure, family fun?"
- If missing destination or duration → ask for what's missing, keep it warm

TURN 2-3 (follow-up):
- Fill in gaps from what they said — DON'T re-ask things they already answered
- Combine questions naturally: "Got it! Any timing preference — specific dates,
  or more of a 'whenever is cheapest' situation? And roughly what budget
  are you working with?"
- If you now have the 3 required + at least trip vibe OR who's going → "PLANNING_STARTED"

TURN 4+ (wrap up):
- You have enough. Use smart defaults for anything missing and OUTPUT "PLANNING_STARTED"

═══════════════════════════════════════════════════════════════
READING BETWEEN THE LINES
═══════════════════════════════════════════════════════════════
Extract implicit info — don't ask for what they already told you:
- "me and my wife" → num_travelers=2, trip_type=romantic, age_range=adults
- "family of 4 with kids" → num_travelers=4, age_range=mixed, trip_type=family
- "bachelor party" → trip_type=adventure, age_range=young_adults
- "honeymoon" → trip_type=romantic, num_travelers=2
- "backpacking through Europe" → trip_type=adventure, budget=Low
- "business trip" → trip_type=business, age_range=adults
- "retirement trip" → age_range=seniors, trip_type=relaxation
- "we want to explore food and nightlife" → interests=food,nightlife
- "whenever is cheapest" → season_preference=off_season
- "spring break" → season_preference=peak, age_range=young_adults

═══════════════════════════════════════════════════════════════
SMART DEFAULTS (use when info is missing after enough turns)
═══════════════════════════════════════════════════════════════
- No budget mentioned → "Medium"
- No interests → "General Sightseeing"
- No num_travelers → 1 (unless "we"/"us" → 2)
- No age_range → "adults"
- No trip_type → None (compiler will be generic)
- No dates → season_preference = "flexible"
- No start_location → "the user's current location"

═══════════════════════════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════════════════════════
1. When you have enough info → output ONLY the word "PLANNING_STARTED". No preamble.
2. NEVER say "I cannot do this." You are an expert planner.
3. Accept regions (e.g. "Texas", "Balkans", "Southeast Asia") — don't force a specific city.
4. Keep questions SHORT (1-2 sentences max). Be conversational, not robotic.
5. NEVER repeat back their info as a summary before starting — just say "PLANNING_STARTED".
6. Ask at MOST 2-3 questions total before starting. Users want plans, not interviews.
"""

_EXTRACTION_PROMPT = """
Analyze the conversation and extract ALL user preferences into structured format.

EXTRACTION RULES:
1. Scan the ENTIRE conversation — info from early messages still counts.
2. Extract num_travelers from plural language ("we"=2, "family"=4, solo=1).
3. Extract age_range: "kids"→mixed, "honeymoon"→adults, "college"→young_adults, "parents"→seniors.
4. Extract trip_type: "romantic", "adventure", "family", "business", "cultural", "relaxation", "backpacking".
5. If user mentions specific dates, put them in travel_dates.
6. If user mentions timing preferences ("cheap", "off-season", "summer"), set season_preference.
7. MULTI-DESTINATION: If user mentions multiple cities (e.g. "Paris and Rome"), set `destinations`
   to the ordered list AND set `destination` to the first one.
8. Apply smart defaults for anything truly missing:
   - No budget → "Medium"
   - No interests → "General Sightseeing"
   - No start_location → "the user's current location"
   - No num_travelers → 1
   - No age_range → "adults"

CONVERSATION:
"""


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

    force_extraction = interview_count >= MAX_INTERVIEW_TURNS

    if force_extraction:
        logger.warning(f"Interviewer hit max turns ({MAX_INTERVIEW_TURNS}). Forcing extraction with smart defaults...")
        content = "PLANNING_STARTED"
    else:
        response = await chat_llm.ainvoke(lc_messages, config={"tags": ["final_itinerary"]})
        content = response.content

    log = log_usage("interviewer", t0, response if not force_extraction else None)

    if "PLANNING_STARTED" in content.upper() or force_extraction:
        structured_llm = extraction_llm.with_structured_output(UserPreferences)
        extraction_msg = [SystemMessage(content=_EXTRACTION_PROMPT), HumanMessage(content=str(messages))]

        try:
            user_prefs = await structured_llm.ainvoke(extraction_msg)
            user_details = user_prefs.model_dump()

            if not user_details.get("interests") or user_details["interests"].lower() == "unknown":
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
            # Fail loud: don't fabricate a destination and silently plan the wrong
            # trip. Tell the user and stay in the interview so they can retry.
            logger.error(f"Extraction failed, asking the user to rephrase: {e}")
            return {
                "messages": [
                    {
                        "role": "model",
                        "content": "Sorry — I had trouble pinning down your trip details. "
                        "Could you tell me again where you'd like to go and for how long?",
                    }
                ],
                "interview_count": interview_count,
                "next_node": "interviewer",
                "debug_logs": [log],
            }

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
