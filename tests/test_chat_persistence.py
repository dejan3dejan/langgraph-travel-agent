"""Unit tests for trip persistence routing (insert vs in-place update). Pure, no DB."""

from api.chat import _is_trip_update, _merge_constraints, _merge_geo


def test_edit_with_existing_trip_updates():
    assert _is_trip_update(True, object()) is True


def test_edit_without_existing_trip_inserts():
    # an edit that somehow has no prior trip falls back to insert rather than losing the plan
    assert _is_trip_update(True, None) is False


def test_fresh_plan_inserts_even_if_a_trip_exists():
    # a brand-new plan never overwrites an earlier trip, even within the same session
    assert _is_trip_update(False, object()) is False
    assert _is_trip_update(False, None) is False


def test_merge_geo_keeps_prior_map_on_a_geoless_edit():
    # an in-place text edit does not re-geocode, so it must not wipe the saved map
    prior = {"hotel": None, "days": [{"day": 1, "places": []}]}
    assert _merge_geo(prior, None) == prior


def test_merge_geo_takes_fresh_coordinates_when_present():
    fresh = {"hotel": None, "days": [{"day": 1, "places": []}]}
    assert _merge_geo({"days": []}, fresh) == fresh


def test_merge_geo_handles_no_prior_map():
    assert _merge_geo(None, None) is None
    assert _merge_geo(None, {"days": []}) == {"days": []}


# constraints memory (remembering allergies/dietary needs across trips)


def test_merge_constraints_unions_new_values():
    assert _merge_constraints("vegetarian", "allergic to shellfish") == "vegetarian, allergic to shellfish"


def test_merge_constraints_dedupes_case_insensitively_keeping_saved_order():
    assert _merge_constraints("Vegetarian", "vegetarian, no stairs") == "Vegetarian, no stairs"


def test_merge_constraints_handles_empties():
    assert _merge_constraints(None, "vegan") == "vegan"
    assert _merge_constraints("vegan", "") == "vegan"
    assert _merge_constraints(None, None) == ""
    assert _merge_constraints("  ", "  ") == ""
