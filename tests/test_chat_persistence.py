"""Unit tests for trip persistence routing (insert vs in-place update). Pure, no DB."""

from api.chat import _is_trip_update


def test_edit_with_existing_trip_updates():
    assert _is_trip_update(True, object()) is True


def test_edit_without_existing_trip_inserts():
    # an edit that somehow has no prior trip falls back to insert rather than losing the plan
    assert _is_trip_update(True, None) is False


def test_fresh_plan_inserts_even_if_a_trip_exists():
    # a brand-new plan never overwrites an earlier trip, even within the same session
    assert _is_trip_update(False, object()) is False
    assert _is_trip_update(False, None) is False
