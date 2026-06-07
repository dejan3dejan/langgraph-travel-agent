"""Interviewer node — gathers the traveler profile via slot-filling.

Each turn it extracts the known fields from the whole conversation, then DECIDES IN
CODE whether enough is known to plan (destination + duration) or what to ask next.
That deterministic gate is what prevents looping / re-asking — it does not rely on
the LLM to remember what has already been answered. A turn-count backstop derived
from the message history (which persists via replay) guarantees the interview ends.
"""

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..llm import get_llm_for_role
from ..logger import get_logger
from ..schemas import UserPreferences
from ..state import AgentState
from ._utils import log_usage

logger = get_logger(__name__)

# After this many user turns, plan with whatever we have (provided we at least have a
# destination) so the conversation can't drag on forever.
MAX_INTERVIEW_TURNS = 3

_EXTRACTION_PROMPT = """
Extract the user's travel preferences from the conversation into structured form.

CRITICAL:
- Leave `destination` and `duration` as EMPTY STRINGS if the user has not stated them.
  Do NOT guess, invent, or default them — empty means "not provided yet".
- Scan the ENTIRE conversation; details from earlier messages still count.

READING BETWEEN THE LINES (infer, don't re-ask):
- "me and my wife" / "honeymoon" -> num_travelers=2, trip_type=romantic, age_range=adults
- "family of 4 with kids" -> num_travelers=4, age_range=mixed, trip_type=family
- "bachelor party" / "spring break" -> trip_type=adventure, age_range=young_adults
- "backpacking" -> trip_type=adventure, budget=Low
- "business trip" -> trip_type=business, age_range=adults
- "retirement trip" -> age_range=seniors, trip_type=relaxation
- "food and nightlife" -> interests=food, nightlife
- "whenever is cheapest" -> season_preference=off_season

MULTI-DESTINATION: if the user names multiple places (e.g. "Barcelona 4 days, Lisbon 7"),
set `destinations` to the ordered list, `destination` to the first, and put the combined
description in `duration` (e.g. "4 days in Barcelona, 7 in Lisbon").

For enrichment fields not mentioned, the schema defaults are fine (budget=Medium,
interests=General Sightseeing, num_travelers=1, age_range=adults).

CONVERSATION:
"""

_FOLLOWUP_PROMPT = """
You are 'Atlas', a warm, concise travel consultant gathering trip details.

You still need to know: {missing}.

Ask ONE short, friendly question (1-2 sentences) to get it. You may also invite the
traveler to mention the vibe (romantic, adventure, family, etc.) or who's coming.
Do NOT re-ask anything they have already told you, and do not summarize back to them.
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


def _to_lc_messages(messages: list[dict]) -> list:
    """Convert stored {role, content} history into LangChain message objects."""
    out = []
    for m in messages:
        if m["role"] == "user":
            out.append(HumanMessage(content=m["content"]))
        else:
            out.append(AIMessage(content=m["content"]))
    return out


async def _ask_for(missing: str, messages: list[dict], t0: float) -> dict:
    """Stream a warm question for the missing required field; stay in the interview."""
    chat_llm = get_llm_for_role("interviewer")
    lc_messages = [SystemMessage(content=_FOLLOWUP_PROMPT.format(missing=missing))] + _to_lc_messages(messages)
    response = await chat_llm.ainvoke(lc_messages, config={"tags": ["final_itinerary"]})
    return {
        "messages": [{"role": "model", "content": response.content}],
        "next_node": "interviewer",
        "debug_logs": [log_usage("interviewer", t0, response)],
    }


def _is_ready(user_details: dict, user_turns: int) -> bool:
    """Decide if there's enough to start planning. Required: a destination plus a
    duration — or, once a destination is known, after the turn-count backstop."""
    has_destination = bool((user_details.get("destination") or "").strip())
    has_duration = bool((user_details.get("duration") or "").strip())
    return has_destination and (has_duration or user_turns >= MAX_INTERVIEW_TURNS)


def _missing_field(user_details: dict) -> str:
    """The required field to ask for next (destination takes priority over duration)."""
    has_destination = bool((user_details.get("destination") or "").strip())
    return "where you'd like to go" if not has_destination else "how many days you're planning"


def _finalize_details(user_details: dict) -> dict:
    """Apply safe defaults and normalize the multi-destination list before planning."""
    if not (user_details.get("duration") or "").strip():
        user_details["duration"] = "3 days"
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
    return user_details


async def interviewer_node(state: AgentState) -> dict:
    t0 = time.time()
    messages = state.get("messages", [])
    user_turns = sum(1 for m in messages if m.get("role") == "user")

    # 1. Extract the currently-known slots from the whole conversation, every turn.
    structured_llm = get_llm_for_role("extraction").with_structured_output(UserPreferences)
    try:
        prefs = await structured_llm.ainvoke(
            [SystemMessage(content=_EXTRACTION_PROMPT), HumanMessage(content=str(messages))]
        )
        user_details = prefs.model_dump()
    except Exception as e:
        # Fail loud: don't fabricate a trip. Ask the user to rephrase and stay put.
        logger.error(f"Extraction failed, asking the user to rephrase: {e}")
        return {
            "messages": [
                {
                    "role": "model",
                    "content": "Sorry — I had trouble pinning down your trip details. "
                    "Could you tell me again where you'd like to go and for how long?",
                }
            ],
            "next_node": "interviewer",
            "debug_logs": [log_usage("interviewer", t0)],
        }

    # 2. Deterministic decision (pure helper) — this is what prevents looping.
    if not _is_ready(user_details, user_turns):
        return await _ask_for(_missing_field(user_details), messages, t0)

    user_details = _finalize_details(user_details)
    season_suggestion = _compute_season_suggestion(user_details)
    log = log_usage("interviewer", t0)

    # If the destination changed from a prior run (only possible with a checkpointer),
    # reset research data. Harmless no-op in the current stateless setup.
    old_dest = state.get("user_details", {}).get("destination")
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
            "next_node": "research",
            "messages": [
                {"role": "model", "content": f"Changing plans to {new_dest}! Let me research that for you..."}
            ],
        }

    return {
        "messages": [{"role": "model", "content": "Great! I'm researching your trip now..."}],
        "user_details": user_details,
        "season_suggestion": season_suggestion,
        "next_node": "research",
        "debug_logs": [log],
    }
