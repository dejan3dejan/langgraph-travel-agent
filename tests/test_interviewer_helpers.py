"""Unit tests for interviewer helper functions — pure, no API."""

from core.nodes.interviewer import _compute_season_suggestion


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
