import operator
from typing import Annotated, Any, TypedDict

from .schemas import Activity, Hotel, Restaurant


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph workflow."""

    messages: Annotated[list[dict[str, str]], operator.add]
    user_details: dict[str, Any] | None

    # Research data — populated by parallel research nodes, enriched by logistics
    food_data: list[Restaurant] | None
    activity_data: list[Activity] | None
    hotel_data: list[Hotel] | None
    logistics_meta: dict[str, Any] | None

    draft_itinerary: str | None
    critique: dict[str, Any] | None
    season_suggestion: str | None

    # Loop guard: caps compiler/critic revision cycles
    iteration_count: int
    next_node: str

    debug_logs: Annotated[list[dict[str, Any]], operator.add]
