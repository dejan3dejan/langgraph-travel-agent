"""Critic node — reviews and scores the itinerary draft."""

import time

from langchain_core.messages import HumanMessage

from ..llm import get_llm_for_role
from ..logger import get_logger
from ..schemas import ItineraryCritique
from ..state import AgentState
from ._utils import log_usage

logger = get_logger(__name__)


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
