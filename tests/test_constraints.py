"""Unit tests for the structured traveler-constraints model and prompt rendering. Pure, no API."""

from core.schemas import TravelConstraints, UserPreferences, render_constraints


def test_travel_constraints_defaults_empty():
    c = TravelConstraints()
    assert c.hard == []
    assert c.soft == []


def test_user_preferences_constraints_default_is_empty_structured():
    p = UserPreferences(destination="Paris", duration="3 days")
    assert isinstance(p.constraints, TravelConstraints)
    assert p.constraints.hard == [] and p.constraints.soft == []


def test_render_constraints_from_structured_dict():
    hard, soft = render_constraints({"hard": ["allergic to shellfish", "halal"], "soft": ["relaxed pace"]})
    assert hard == "allergic to shellfish, halal"
    assert soft == "relaxed pace"


def test_render_constraints_from_model():
    hard, soft = render_constraints(TravelConstraints(hard=["wheelchair accessible"], soft=[]))
    assert hard == "wheelchair accessible"
    assert soft == ""


def test_render_constraints_legacy_string_is_soft():
    # Legacy free-text constraints are treated as a soft preference until re-extracted.
    assert render_constraints("pet friendly") == ("", "pet friendly")


def test_render_constraints_handles_none_and_empty():
    assert render_constraints(None) == ("", "")
    assert render_constraints({}) == ("", "")
