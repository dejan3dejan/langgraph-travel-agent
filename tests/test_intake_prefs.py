"""Unit tests for intake-pref mapping and seeding resolution. Pure, no DB."""

from api.chat import _resolve_prefs
from core.schemas import IntakePrefs, intake_to_preference_columns, intake_to_seeded


def test_seeded_maps_each_field_to_the_interviewer_keys():
    prefs = IntakePrefs(
        home_city="Berlin",
        budget="High",
        pace="relaxed",
        vibe="romantic",
        interests=["food", "museums"],
        dietary=["vegetarian", "no shellfish"],
    )
    assert intake_to_seeded(prefs) == {
        "budget": "High",
        "interests": "food, museums",
        "start_location": "Berlin",
        "trip_type": "romantic",
        "constraints": {"hard": ["vegetarian", "no shellfish"], "soft": ["relaxed pace"]},
    }


def test_seeded_packed_pace_becomes_a_soft_constraint():
    assert intake_to_seeded(IntakePrefs(pace="packed")) == {"constraints": {"hard": [], "soft": ["packed schedule"]}}


def test_seeded_balanced_pace_is_neutral_and_adds_nothing():
    # balanced is the default cadence, so it carries no preference signal
    assert intake_to_seeded(IntakePrefs(pace="balanced")) is None


def test_seeded_empty_prefs_is_none():
    assert intake_to_seeded(IntakePrefs()) is None


def test_seeded_omits_constraints_when_no_dietary_or_pace():
    assert intake_to_seeded(IntakePrefs(budget="Low")) == {"budget": "Low"}


def test_seeded_clamps_overlong_strings_and_oversized_lists():
    prefs = IntakePrefs(
        home_city="x" * 200,
        vibe="y" * 200,
        interests=[f"i{n}" for n in range(50)],
        dietary=[f"d{n}" for n in range(50)],
    )
    seeded = intake_to_seeded(prefs)
    assert len(seeded["start_location"]) <= 80
    assert len(seeded["trip_type"]) <= 80
    assert len(seeded["interests"].split(", ")) <= 10
    assert len(seeded["constraints"]["hard"]) <= 10


def test_seeded_drops_blank_list_entries():
    prefs = IntakePrefs(interests=["food", "  ", ""], dietary=["", "vegan"])
    seeded = intake_to_seeded(prefs)
    assert seeded["interests"] == "food"
    assert seeded["constraints"]["hard"] == ["vegan"]


def test_preference_columns_only_sets_provided_fields():
    prefs = IntakePrefs(budget="Medium", home_city="Lisbon")
    assert intake_to_preference_columns(prefs) == {
        "default_budget": "Medium",
        "start_location": "Lisbon",
    }


def test_preference_columns_maps_interests_and_constraints():
    prefs = IntakePrefs(interests=["food", "nightlife"], dietary=["halal"], pace="relaxed", vibe="cultural")
    assert intake_to_preference_columns(prefs) == {
        "default_interests": "food, nightlife",
        "trip_type": "cultural",
        "travel_constraints": {"hard": ["halal"], "soft": ["relaxed pace"]},
    }


def test_preference_columns_empty_is_empty():
    assert intake_to_preference_columns(IntakePrefs()) == {}


# Resolution: an authed user's saved prefs always win over client-supplied intake prefs.


def test_resolve_prefers_saved_over_client():
    saved = {"budget": "High"}
    client = IntakePrefs(budget="Low")
    assert _resolve_prefs(saved, client) == saved


def test_resolve_falls_back_to_client_when_no_saved():
    client = IntakePrefs(budget="Low")
    assert _resolve_prefs(None, client) == {"budget": "Low"}


def test_resolve_none_when_neither():
    assert _resolve_prefs(None, None) is None
