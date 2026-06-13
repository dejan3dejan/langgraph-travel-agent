"""Unit tests for trip persistence routing (insert vs in-place update). Pure, no DB."""

from api.chat import _is_trip_update, _merge_geo


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
