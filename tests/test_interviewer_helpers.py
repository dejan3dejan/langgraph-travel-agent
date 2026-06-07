"""Unit tests for interviewer helper functions — pure, no API."""

from core.nodes.interviewer import (
    _compute_season_suggestion,
    _finalize_details,
    _is_ready,
    _latest_itinerary,
    _missing_field,
    _plan_in_history,
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


# ── readiness decision (the anti-loop gate) ──────────────────────────────────


def test_ready_with_destination_and_duration():
    assert _is_ready({"destination": "Rome", "duration": "5 days"}, user_turns=1) is True


def test_not_ready_without_duration_early():
    assert _is_ready({"destination": "Rome", "duration": ""}, user_turns=1) is False


def test_backstop_plans_with_destination_after_max_turns():
    # No duration, but enough turns + a destination -> plan anyway.
    assert _is_ready({"destination": "Rome", "duration": ""}, user_turns=3) is True


def test_never_ready_without_destination():
    # Even past the backstop, no destination means we can't plan.
    assert _is_ready({"destination": "", "duration": "5 days"}, user_turns=9) is False


def test_blank_strings_count_as_missing():
    assert _is_ready({"destination": "   ", "duration": "   "}, user_turns=1) is False


def test_missing_field_prioritizes_destination():
    assert "where" in _missing_field({"destination": "", "duration": ""})
    assert "days" in _missing_field({"destination": "Rome", "duration": ""})


# ── finalize details ─────────────────────────────────────────────────────────


def test_finalize_defaults_blank_duration():
    out = _finalize_details({"destination": "Rome", "duration": ""})
    assert out["duration"] == "3 days"


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


# ── post-plan detection ──────────────────────────────────────────────────────


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
