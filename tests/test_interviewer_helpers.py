"""Unit tests for interviewer helper functions. Pure, no API."""

from core.nodes.interviewer import (
    MAX_INTERVIEW_TURNS,
    _compute_season_suggestion,
    _finalize_details,
    _intent_vague,
    _is_ready,
    _latest_itinerary,
    _next_question,
    _plan_in_history,
    _question_text,
)


def test_no_suggestion_when_dates_given():
    assert _compute_season_suggestion({"travel_dates": "March 1-5", "budget": "Low"}) is None


def test_low_budget_suggests_off_season():
    assert "Off-season" in _compute_season_suggestion({"budget": "Low"})


def test_high_budget_suggests_peak():
    assert "Peak season" in _compute_season_suggestion({"budget": "High"})


def test_medium_budget_suggests_shoulder():
    assert "Shoulder" in _compute_season_suggestion({"budget": "Medium"})


def test_missing_budget_defaults_to_shoulder():
    assert "Shoulder" in _compute_season_suggestion({})


# intent vagueness


def test_intent_vague_when_empty_or_default():
    assert _intent_vague({"interests": ""}) is True
    assert _intent_vague({"interests": "unknown"}) is True
    assert _intent_vague({"interests": "General Sightseeing"}) is True
    assert _intent_vague({}) is True


def test_intent_not_vague_with_concrete_interests():
    assert _intent_vague({"interests": "food, history"}) is False
    assert _intent_vague({"interests": "Nightlife"}) is False


# the gate: what to ask next (the anti-loop decision)


def _ready_details():
    """A fully-specified profile: nothing left to ask."""
    return {"destination": "Rome", "duration": "5 days", "needs_accommodation": True, "interests": "food"}


def test_asks_destination_first():
    assert _next_question({"destination": "", "duration": "5 days"}, user_turns=1) == "destination"


def test_asks_duration_when_destination_known():
    assert _next_question({"destination": "Rome", "duration": ""}, user_turns=1) == "duration"


def test_asks_accommodation_when_unknown():
    d = {"destination": "Rome", "duration": "5 days", "needs_accommodation": None, "interests": "food"}
    assert _next_question(d, user_turns=1) == "accommodation"


def test_asks_intent_when_vague_and_accommodation_known():
    d = {"destination": "Rome", "duration": "5 days", "needs_accommodation": True, "interests": ""}
    assert _next_question(d, user_turns=1) == "intent"


def test_asks_intent_even_when_accommodation_not_needed():
    # already-in-city (needs_accommodation False) still needs the intent narrowed down
    d = {"destination": "Bratislava", "duration": "1 day", "needs_accommodation": False, "interests": ""}
    assert _next_question(d, user_turns=1) == "intent"


def test_ready_when_all_slots_filled():
    assert _next_question(_ready_details(), user_turns=1) is None


def test_backstop_plans_despite_unknown_soft_slots():
    # past the turn budget, plan with whatever we have rather than dragging on
    d = {"destination": "Rome", "duration": "5 days", "needs_accommodation": None, "interests": ""}
    assert _next_question(d, user_turns=MAX_INTERVIEW_TURNS) is None


def test_backstop_never_skips_destination():
    assert _next_question({"destination": "", "duration": "5 days"}, user_turns=9) == "destination"


def test_backstop_never_skips_duration():
    # the task is explicit: ask if unknown, do not silently plan without a duration
    assert _next_question({"destination": "Rome", "duration": ""}, user_turns=9) == "duration"


def test_blank_strings_count_as_missing():
    assert _next_question({"destination": "   ", "duration": "   "}, user_turns=1) == "destination"


def test_is_ready_wraps_next_question():
    assert _is_ready(_ready_details(), user_turns=1) is True
    assert _is_ready({"destination": "Rome", "duration": ""}, user_turns=1) is False


# question phrasing


def test_question_text_per_slot():
    assert "where" in _question_text("destination", {}).lower()
    assert "long" in _question_text("duration", {}).lower() or "day" in _question_text("duration", {}).lower()
    assert "stay" in _question_text("accommodation", {}).lower()
    intent = _question_text("intent", {"interests": ""}).lower()
    assert "food" in intent and "nightlife" in intent


def test_intent_question_acknowledges_already_there():
    d = {"destination": "Bratislava", "start_location": "Bratislava", "needs_accommodation": False, "interests": ""}
    text = _question_text("intent", d).lower()
    assert "already" in text  # acknowledges they're in town, no lodging needed


# finalize details


def test_finalize_defaults_blank_duration_away_from_home():
    out = _finalize_details({"destination": "Rome", "duration": ""})
    assert out["duration"] == "3 days"


def test_finalize_defaults_blank_duration_when_already_there():
    out = _finalize_details({"destination": "Bratislava", "start_location": "Bratislava", "duration": ""})
    assert out["duration"] == "1 day"


def test_finalize_defaults_accommodation_true_away_from_home():
    out = _finalize_details({"destination": "Rome", "duration": "5 days", "needs_accommodation": None})
    assert out["needs_accommodation"] is True


def test_finalize_defaults_accommodation_false_when_already_there():
    out = _finalize_details(
        {"destination": "Bratislava", "start_location": "Bratislava", "duration": "1 day", "needs_accommodation": None}
    )
    assert out["needs_accommodation"] is False


def test_finalize_preserves_explicit_accommodation():
    assert (
        _finalize_details({"destination": "Rome", "duration": "3 days", "needs_accommodation": False})[
            "needs_accommodation"
        ]
        is False
    )
    assert (
        _finalize_details({"destination": "Rome", "duration": "3 days", "needs_accommodation": True})[
            "needs_accommodation"
        ]
        is True
    )


def test_finalize_defaults_interests_and_start_location():
    out = _finalize_details({"destination": "Rome", "duration": "5 days", "interests": "", "start_location": ""})
    assert out["interests"] == "General Sightseeing"
    assert out["start_location"] == "the user's current location"


def test_finalize_prepends_primary_to_destinations():
    out = _finalize_details({"destination": "Paris", "duration": "3 days", "destinations": ["Rome"]})
    assert out["destinations"] == ["Paris", "Rome"]


def test_finalize_single_destination_leaves_list_empty():
    out = _finalize_details({"destination": "Rome", "duration": "3 days", "destinations": []})
    assert out["destinations"] == []


# post-plan detection


def test_plan_in_history_detects_itinerary():
    msgs = [
        {"role": "user", "content": "plan rome"},
        {"role": "model", "content": "# 3 days Trip to Rome\n## Day 1: Colosseum"},
    ]
    assert _plan_in_history(msgs) is True


def test_plan_in_history_false_for_plain_chat():
    msgs = [
        {"role": "user", "content": "rome"},
        {"role": "model", "content": "How many days are you planning?"},
    ]
    assert _plan_in_history(msgs) is False


def test_latest_itinerary_returns_most_recent():
    msgs = [
        {"role": "model", "content": "# Trip to Rome\n## Day 1"},
        {"role": "user", "content": "now tokyo"},
        {"role": "model", "content": "# Trip to Tokyo\n## Day 1"},
    ]
    assert "Tokyo" in _latest_itinerary(msgs)


def test_latest_itinerary_empty_when_none():
    assert _latest_itinerary([{"role": "user", "content": "hi"}]) == ""
