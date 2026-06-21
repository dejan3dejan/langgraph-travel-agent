from typing import Literal

from pydantic import BaseModel, Field


class TravelConstraints(BaseModel):
    """Traveler constraints split by how strictly they bind. hard = must be satisfied (allergies,
    dietary needs incl. halal/kosher/vegetarian, accessibility, hard budget, 'no X'); soft =
    preferences to honor when possible (pace, vibe, timing)."""

    hard: list[str] = Field(
        default_factory=list,
        description="Must be satisfied, never violate: allergies, dietary needs, accessibility, hard limits",
    )
    soft: list[str] = Field(default_factory=list, description="Preferences to honor when possible: pace, vibe, timing")


class IntakePrefs(BaseModel):
    """Preferences captured by the first-run intake, or carried in localStorage for an anonymous
    user. Client-supplied and untrusted: every field is optional and the mappers below clamp lengths
    and list sizes before any value reaches a prompt."""

    home_city: str | None = None
    budget: Literal["Low", "Medium", "High"] | None = None
    pace: Literal["relaxed", "balanced", "packed"] | None = None
    vibe: str | None = None
    interests: list[str] | None = None
    dietary: list[str] | None = None


_MAX_FIELD_LEN = 80
_MAX_LIST_ITEMS = 10


def _clip(value: str | None, limit: int = _MAX_FIELD_LEN) -> str:
    return (value or "").strip()[:limit]


def _clip_list(items: list[str] | None, item_limit: int = _MAX_FIELD_LEN) -> list[str]:
    """Strip, drop blanks, clamp each entry, and cap the list length."""
    out = []
    for item in items or []:
        cleaned = _clip(item, item_limit)
        if cleaned:
            out.append(cleaned)
        if len(out) >= _MAX_LIST_ITEMS:
            break
    return out


# Pace maps to a soft preference; balanced is the neutral default and carries no signal.
_PACE_SOFT = {"relaxed": "relaxed pace", "packed": "packed schedule"}


def _intake_constraints(prefs: IntakePrefs) -> dict | None:
    """Build the {hard, soft} constraint set from dietary needs (hard) and pace (soft)."""
    hard = _clip_list(prefs.dietary)
    soft = [_PACE_SOFT[prefs.pace]] if prefs.pace in _PACE_SOFT else []
    return {"hard": hard, "soft": soft} if (hard or soft) else None


def intake_to_seeded(prefs: IntakePrefs | None) -> dict | None:
    """Map intake prefs into the seeded-prefs shape the interviewer consumes (same keys as
    api.chat._seeded_prefs). Returns None when nothing was provided, so an empty intake seeds
    nothing. Pure and clamped: this is the boundary where untrusted client values are bounded
    before they reach the extraction prompt."""
    if prefs is None:
        return None
    out: dict = {}
    if prefs.budget:
        out["budget"] = prefs.budget
    interests = _clip_list(prefs.interests)
    if interests:
        out["interests"] = ", ".join(interests)
    if home := _clip(prefs.home_city):
        out["start_location"] = home
    if vibe := _clip(prefs.vibe):
        out["trip_type"] = vibe
    constraints = _intake_constraints(prefs)
    if constraints:
        out["constraints"] = constraints
    return out or None


def intake_to_preference_columns(prefs: IntakePrefs | None) -> dict:
    """Map intake prefs onto UserPreference column assignments for persistence at signup. Only
    provided fields are returned, so unset ones keep their column defaults on a fresh row."""
    if prefs is None:
        return {}
    out: dict = {}
    if prefs.budget:
        out["default_budget"] = prefs.budget
    interests = _clip_list(prefs.interests)
    if interests:
        out["default_interests"] = ", ".join(interests)
    if home := _clip(prefs.home_city):
        out["start_location"] = home
    if vibe := _clip(prefs.vibe):
        out["trip_type"] = vibe
    constraints = _intake_constraints(prefs)
    if constraints:
        out["travel_constraints"] = constraints
    return out


def render_constraints(value) -> tuple[str, str]:
    """Render constraints to (hard_text, soft_text) for prompts. Tolerant of the structured dict, a
    TravelConstraints, a legacy free-text string (treated as soft), or None."""
    if value is None:
        return "", ""
    if isinstance(value, str):
        return "", value.strip()
    if isinstance(value, TravelConstraints):
        hard, soft = value.hard, value.soft
    elif isinstance(value, dict):
        hard, soft = value.get("hard") or [], value.get("soft") or []
    else:
        return "", ""
    return ", ".join(hard), ", ".join(soft)


class UserPreferences(BaseModel):
    destination: str = Field(description="Primary city or region for the trip")
    destinations: list[str] = Field(
        default_factory=list,
        description="All destinations in order (e.g. ['Paris', 'Rome']). Empty means single-destination trip.",
    )
    start_location: str = Field(default="the user's current location", description="Where the user is starting from")
    duration: str = Field(description="Total length of stay (e.g. 7 days)")
    budget: str = Field(default="Medium", description="Budget level (Low, Medium, High)")
    interests: str = Field(default="General Sightseeing", description="Comma-separated interests")
    num_travelers: int = Field(default=1, description="Number of people traveling")
    age_range: str = Field(
        default="adults",
        description="Age group: kids, young_adults, adults, seniors, or mixed",
    )
    trip_type: str | None = Field(
        default=None,
        description="Trip style: romantic, family, adventure, business, workation, relaxation, cultural, or None",
    )
    travel_dates: str | None = Field(default=None, description="Specific dates if mentioned (e.g. 'March 13-17, 2026')")
    season_preference: str = Field(
        default="flexible",
        description="Timing preference: peak, off_season, shoulder, flexible",
    )
    constraints: TravelConstraints = Field(
        default_factory=TravelConstraints,
        description=(
            "Traveler constraints split into hard (must satisfy: allergies, dietary needs like halal/"
            "kosher/vegetarian, accessibility, hard budget, 'no X') and soft (preferences: pace, vibe, "
            "timing). Capture the actionable need, never a protected attribute like religion."
        ),
    )
    needs_accommodation: bool | None = Field(
        default=None,
        description=(
            "True if the user needs lodging researched; False if already sorted "
            "(hotel booked, staying with friends, local, or already in the destination city); "
            "None if not stated yet."
        ),
    )
    preferred_areas: list[str] = Field(
        default_factory=list,
        description=(
            "Neighborhoods or areas the traveler wants to be near or base around "
            "(e.g. ['Trastevere', 'near the Vatican']). Empty if none mentioned."
        ),
    )
    focus: list[Literal["food", "activities", "hotels"]] = Field(default_factory=list)


class LogisticsBase(BaseModel):
    """Base class for all items that need geocoding."""

    lat: float | None = Field(None, description="Latitude coordinate")
    lon: float | None = Field(None, description="Longitude coordinate")
    geocoding_status: Literal["exact", "neighborhood", "failed"] | None = Field(
        None, description="Precision of geocoding"
    )
    zone: str | None = Field(None, description="Logistical zone (e.g., 'Near Hotel', 'Remote', 'Cluster A')")


class Restaurant(LogisticsBase):
    name: str = Field(description="Name of the restaurant")
    address: str = Field(description="Full street address and city. Essential for logistics.")
    neighborhood: str | None = Field(None, description="Neighborhood or district name")
    website: str | None = Field(None, description="Official website URL")
    cuisine: str = Field(description="Type of cuisine")
    price_level: str = Field(description="Price level ($ to $$$$)")
    rating: float = Field(description="Google rating")
    reason: str = Field(description="Why it fits the user's request")


class RestaurantList(BaseModel):
    items: list[Restaurant]


class Activity(LogisticsBase):
    name: str = Field(description="Name of the activity")
    address: str = Field(description="Full street address and city. Essential for logistics.")
    neighborhood: str | None = Field(None, description="Neighborhood or district name")
    website: str | None = Field(None, description="Official website URL")
    type: str = Field(description="Type of activity (e.g., museum, park, tour)")
    price_level: str = Field(description="Price level ($ to $$$$)")
    rating: float = Field(description="Google rating")
    reason: str = Field(description="Why it fits the user's request")


class ActivityList(BaseModel):
    items: list[Activity]


class Hotel(LogisticsBase):
    name: str = Field(description="Name of the hotel")
    address: str = Field(description="Full street address and city. Essential for logistics.")
    neighborhood: str | None = Field(None, description="Neighborhood or district name")
    website: str | None = Field(None, description="Official website URL")
    price_level: str = Field(description="Price level ($ to $$$$)")
    rating: float = Field(description="Google rating")
    amenities: list[str] = Field(default_factory=list, description="List of amenities (e.g., wifi, pool)")
    reason: str = Field(description="Why it fits the user's request")


class HotelList(BaseModel):
    items: list[Hotel]


class ItineraryCritique(BaseModel):
    approved: bool = Field(description="Whether the itinerary is approved")
    feedback: str = Field(description="Detailed feedback on the itinerary")
    score: int = Field(description="Score from 1-10")
    missing_data: list[Literal["food", "activities", "hotels"]] = Field(default_factory=list)
    hard_violations: list[str] = Field(
        default_factory=list,
        description=(
            "Places or activities in the plan that violate a hard constraint (allergy, dietary need, "
            "accessibility); empty if the plan complies"
        ),
    )


class ItineraryDay(BaseModel):
    """One day of the delivered itinerary. Drives the map's per-day grouping and (later) per-day cards."""

    day: int = Field(description="1-based day number, matching the itinerary text")
    title: str = Field(description="Short theme for the day, e.g. 'Historic centre'")
    stops: list[str] = Field(
        default_factory=list,
        description="Place names visited this day, in visiting order, drawn ONLY from the provided list",
    )


class ItineraryDayPlan(BaseModel):
    """The itinerary's day-by-day structure, extracted from the written plan to drive the map."""

    days: list[ItineraryDay] = Field(default_factory=list)


class TripFeasibility(BaseModel):
    """Sanity check on a trip request before planning: is it actually plannable, or fictional /
    physically impossible / self-contradictory?"""

    feasible: bool = Field(description="True unless the request is clearly fictional, impossible, or contradictory")
    issue: Literal["none", "unknown_place", "impossible_logistics", "contradictory", "other"] = Field(
        default="none", description="The kind of problem when not feasible"
    )
    clarification: str = Field(
        default="", description="One short, friendly question to fix the problem; empty when feasible"
    )


class TurnIntent(BaseModel):
    """How to handle a turn that arrives after a plan was delivered."""

    intent: Literal["modify", "question", "unsure"] = Field(
        description=(
            "modify = change the existing plan; question = ask about it without changing it; "
            "unsure = ambiguous, ask one clarifying question before doing anything"
        )
    )
