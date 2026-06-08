"""Unit tests for the critic's deterministic re-research decision. Pure, no API."""

from core.nodes.critic import _missing_categories


def test_no_missing_when_all_present():
    assert _missing_categories([{"name": "a"}], [{"name": "b"}], [{"name": "c"}]) == []


def test_flags_only_empty_categories():
    assert _missing_categories([], [{"name": "b"}], []) == ["food", "hotels"]


def test_all_empty():
    assert _missing_categories([], [], []) == ["food", "activities", "hotels"]


def test_none_treated_as_empty():
    assert _missing_categories(None, None, None) == ["food", "activities", "hotels"]
