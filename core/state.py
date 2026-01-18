import operator
from typing import Annotated, Any, TypedDict

from .schemas import Activity, Hotel, Restaurant


class AgentState(TypedDict):
    """
    The memory of the agent workflow.
    """

    # Chat history (list of role/content dicts)
    messages: Annotated[list[dict[str, str]], operator.add]

    # Structured Data
    user_details: dict[str, Any] | None  # {destination, budget, etc.}

    # Parallel Research Data (Will be enriched by Logistics Agent)
    food_data: list[Restaurant] | None
    activity_data: list[Activity] | None
    hotel_data: list[Hotel] | None

    # Logistics Hub - Global map and calculations
    # Stores clusters, distance matrices, and transport suggestions
    logistics: dict[str, Any] | None

    # Plan State
    draft_itinerary: str | None  # The markdown draft
    critique: dict[str, Any] | None  # The Judge's feedback

    # Control Flow
    iteration_count: int  # To prevent infinite loops in compiler/critic
    interview_count: int  # To prevent infinite loops in interviewer
    next_node: str  # Where to go next

    # Metrics & Debugging
    debug_logs: Annotated[list[dict[str, Any]], operator.add]
