"""Unit tests for research helper functions — pure, no API/DB."""

from core.nodes.research import _build_search_prompt, _build_search_query, _get_activity_focus, _get_destinations


def test_build_search_query_restaurants():
    q = _build_search_query("restaurants", "Rome", {"age_range": "adults", "budget": "High"})
    assert "restaurants" in q
    assert "Rome" in q
    assert "High" in q


def test_build_search_query_hotels_uses_traveler_count():
    q = _build_search_query("hotels", "Rome", {"budget": "Low", "num_travelers": 4})
    assert "hotels" in q
    assert "4 travelers" in q


def test_build_search_query_activities_uses_trip_type():
    q = _build_search_query("activities", "Rome", {"trip_type": "romantic", "interests": "art"})
    assert "activities" in q
    assert "romantic" in q


def test_get_destinations_single():
    assert _get_destinations({"destination": "Rome"}) == ["Rome"]


def test_get_destinations_multi_uses_list():
    assert _get_destinations({"destination": "Paris", "destinations": ["Paris", "Rome"]}) == ["Paris", "Rome"]


def test_get_destinations_empty():
    assert _get_destinations({}) == []


def test_get_activity_focus_combines_signals():
    focus = _get_activity_focus("romantic", "adults", "art, history")
    assert "romantic" in focus
    assert "art" in focus
    assert "history" in focus
    assert "adult-friendly" in focus


def test_get_activity_focus_fallback():
    assert _get_activity_focus("", "whatever", "") == "general sightseeing"


# research breadth: enough places that multi-day trips have something to pin on each day


def test_search_prompt_requests_several_activities():
    p = _build_search_prompt("activities", "Tokyo", {"trip_type": "family", "interests": "food"})
    assert "8 REAL" in p


def test_search_prompt_requests_several_restaurants():
    p = _build_search_prompt("restaurants", "Tokyo", {"age_range": "adults", "budget": "Medium"})
    assert "6 REAL" in p
