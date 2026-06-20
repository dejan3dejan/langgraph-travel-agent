import operator
from typing import Annotated, Any, TypedDict

from .schemas import Activity, Hotel, Restaurant


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph workflow."""

    messages: Annotated[list[dict[str, str]], operator.add]
    user_details: dict[str, Any] | None
    seeded_prefs: dict[str, Any] | None  # authed user's saved defaults, seeded into extraction

    # Research data — populated by parallel research nodes, enriched by logistics
    food_data: list[Restaurant] | None
    activity_data: list[Activity] | None
    hotel_data: list[Hotel] | None
    logistics_meta: dict[str, Any] | None

    draft_itinerary: str | None
    itinerary_geo: dict[str, Any] | None  # {hotel, days[]} for the map view; None on text-only replies
    critique: dict[str, Any] | None
    season_suggestion: str | None

    # Loop guard: caps compiler/critic revision cycles
    iteration_count: int
    next_node: str

    # Itinerary edit flow: a post-plan modification carries the prior plan and the change
    # instruction to the compiler, which revises in place instead of re-researching.
    edit_instruction: str | None
    base_itinerary: str | None
    is_edit: bool

    # Regenerate flow: a fresh-plan request after a plan already exists re-runs the full pipeline
    # with the prior plan as an avoid-this reference and a per-request seed, to diversify the result.
    regenerate: bool
    request_nonce: int | None

    debug_logs: Annotated[list[dict[str, Any]], operator.add]
