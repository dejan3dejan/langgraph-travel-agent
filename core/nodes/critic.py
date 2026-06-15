"""Critic node — reviews the itinerary and decides re-research deterministically."""

import time

from langchain_core.messages import HumanMessage

from ..llm import get_llm_for_role
from ..logger import get_logger
from ..schemas import ItineraryCritique, render_constraints
from ..state import AgentState
from ._utils import log_usage

logger = get_logger(__name__)


def _missing_categories(food: list, activities: list, hotels: list, needs_accommodation: bool = True) -> list[str]:
    """Categories whose research came back empty. This drives the re-research loop, instead of the
    LLM's subjective "is this generic" judgment, which rejected ungrounded data on every pass and
    burned all three iterations re-researching with the same model (no improvement).

    Hotels only count as missing when the user needs lodging; for an already-sorted stay the empty
    hotel list is expected, so flagging it would loop re-research against a skipped category."""
    missing = []
    if not food:
        missing.append("food")
    if not activities:
        missing.append("activities")
    if needs_accommodation and not hotels:
        missing.append("hotels")
    return missing


async def critic_node(state: AgentState) -> dict:
    t0 = time.time()
    draft = state.get("draft_itinerary", "")
    user_details = state.get("user_details", {})
    food = state.get("food_data") or []
    activities = state.get("activity_data") or []
    hotels = state.get("hotel_data") or []
    logger.info("Reviewing itinerary draft...")

    needs_accommodation = user_details.get("needs_accommodation", True) is not False
    missing = _missing_categories(food, activities, hotels, needs_accommodation)

    # Advisory quality note (feedback + score). It does NOT control the loop; only genuinely
    # missing research (empty category) sends us back. We still run it for the feedback/score.
    extraction_llm = get_llm_for_role("extraction")
    structured_critic = extraction_llm.with_structured_output(ItineraryCritique)
    hard_text, _ = render_constraints(user_details.get("constraints"))
    prompt = f"""
    Briefly review this itinerary for a trip to {user_details.get('destination')}.
    Check transport from {user_details.get('start_location')}, and whether it respects the budget
    ({user_details.get('budget')}) and interests ({user_details.get('interests')}).
    Give a short feedback note and a score from 1-10. Leave missing_data empty.

    REQUIRED CONSTRAINTS (must not be violated): {hard_text or 'none'}
    In hard_violations, list any specific place or activity in the plan that conflicts with a required
    constraint (e.g. a seafood restaurant under a shellfish allergy, a non-halal venue under halal).
    Leave hard_violations empty if the plan fully complies.

    ITINERARY:
    {draft}
    """

    try:
        result = await structured_critic.ainvoke([HumanMessage(content=prompt)])
        critique = result.model_dump()
        log = log_usage("critic", t0, result)
    except Exception as e:
        # Fail open: release the draft so the user still gets an itinerary, but flag the skip.
        logger.error(f"Critic review failed, releasing the draft without a note: {e}")
        critique = {"approved": True, "feedback": "Automated quality review was skipped.", "score": None}
        log = log_usage("critic", t0)

    # Loop control is decided here in code, not by the LLM.
    critique["missing_data"] = missing
    hard_violations = critique.get("hard_violations") or []
    if missing:
        critique["approved"] = False
        next_node = "research"
    elif hard_violations:
        # The plan breaks a hard requirement (e.g. an allergy). Re-compile to fix it; the router's
        # iteration cap stops the loop if it cannot be satisfied.
        critique["approved"] = False
        next_node = "compiler"
        logger.info(f"Hard-constraint violations, recompiling: {hard_violations}")
    else:
        critique["approved"] = True
        next_node = "approved"

    return {"critique": critique, "next_node": next_node, "debug_logs": [log]}
