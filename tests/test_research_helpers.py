"""Unit tests for research helper functions — pure, no API/DB."""

from core.nodes import research as research_mod
from core.nodes.research import (
    _build_search_prompt,
    _build_search_query,
    _filter_to_destination,
    _get_activity_focus,
    _get_destinations,
    _local_focus_block,
    _personalization_suffix,
    _should_refresh,
    _wants_local,
)
from core.schemas import Restaurant


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


# regenerate refresh: rebuild food and activities live, keep the stable hotel pool cached


def test_refresh_food_and_activities_on_regenerate():
    assert _should_refresh("restaurants", regenerate=True) is True
    assert _should_refresh("activities", regenerate=True) is True


def test_keeps_hotels_cached_on_regenerate():
    assert _should_refresh("hotels", regenerate=True) is False


def test_no_refresh_without_regenerate():
    assert _should_refresh("restaurants", regenerate=False) is False
    assert _should_refresh("activities", regenerate=False) is False


# personalize before retrieve: fold vibe + areas into the cache key and the search prompt


def test_wants_local_detects_soft_vibe():
    assert _wants_local({"constraints": {"soft": ["local, non-touristy spots"]}}) is True
    assert _wants_local({"constraints": {"soft": ["authentic hidden gems"]}}) is True


def test_wants_local_false_without_vibe():
    assert _wants_local({"constraints": {"soft": ["relaxed pace"]}}) is False
    assert _wants_local({}) is False


def test_personalization_suffix_includes_vibe_and_areas():
    s = _personalization_suffix(
        {"constraints": {"soft": ["local, non-touristy"]}, "preferred_areas": ["Trastevere", "Prati"]}
    )
    low = s.lower()
    assert "local" in low
    assert "trastevere" in low and "prati" in low


def test_personalization_suffix_empty_when_nothing_expressed():
    assert _personalization_suffix({}) == ""
    assert _personalization_suffix({"constraints": {"soft": ["relaxed pace"]}, "preferred_areas": []}) == ""


def test_search_query_unchanged_for_a_generic_request():
    # No vibe, no area: the cache key must stay identical so generic requests keep hitting the warm cache.
    q = _build_search_query("restaurants", "Rome", {"age_range": "adults", "budget": "Medium"})
    assert q == "best restaurants in Rome for adults Medium budget"


def test_search_query_personalized_when_local_and_areas_given():
    q = _build_search_query(
        "restaurants",
        "Rome",
        {
            "age_range": "adults",
            "budget": "Medium",
            "constraints": {"soft": ["local, non-touristy"]},
            "preferred_areas": ["Trastevere"],
        },
    )
    assert q != "best restaurants in Rome for adults Medium budget"
    assert "Trastevere" in q
    assert "local" in q.lower()


def test_local_focus_block_present_only_when_expressed():
    assert _local_focus_block({}) == ""
    block = _local_focus_block({"constraints": {"soft": ["non-touristy"]}, "preferred_areas": ["Trastevere"]})
    low = block.lower()
    assert "local" in low and "tourist" in low
    assert "Trastevere" in block


# geocode hallucination filter: drop places that fail to geocode or land outside the destination


def _restaurant(name, address):
    return Restaurant(name=name, address=address, cuisine="bistro", price_level="$$", rating=4.5, reason="fits")


# Paris centroid plus a real in-city address, a fabricated address that geocodes to Rome, and one
# that does not geocode at all.
_FAKE_GEO = {
    "Paris": (48.8566, 2.3522, "exact"),
    "10 Rue de Rivoli, Paris": (48.8566, 2.3505, "exact"),
    "999 Imaginary Plaza, Paris": (41.9028, 12.4964, "exact"),
    "0 Nonexistent St, Paris": (None, None, "failed"),
}


async def _fake_geocode(address, neighborhood=None, city=None, retries=1, stats=None):
    return _FAKE_GEO.get(address, (None, None, "failed"))


def _sample_places():
    return [
        _restaurant("Real Bistro", "10 Rue de Rivoli, Paris"),
        _restaurant("Hallucinated Grill", "999 Imaginary Plaza, Paris"),
        _restaurant("Phantom Cafe", "0 Nonexistent St, Paris"),
    ]


async def test_filter_drops_out_of_city_and_ungeocodable(monkeypatch):
    monkeypatch.setattr(research_mod, "aget_coordinates", _fake_geocode)
    kept, dropped = await _filter_to_destination("restaurants", "Paris", _sample_places())
    assert [r.name for r in kept] == ["Real Bistro"]
    assert dropped == 2
    # Surviving places carry the coordinates resolved during filtering, so logistics need not refetch.
    assert kept[0].lat == 48.8566 and kept[0].lon == 2.3505


async def test_filter_keeps_all_when_centroid_geocode_fails(monkeypatch):
    monkeypatch.setattr(research_mod, "aget_coordinates", _fake_geocode)
    # "Atlantis" is absent from the fake map, so the centroid lookup fails and nothing is dropped.
    places = _sample_places()
    kept, dropped = await _filter_to_destination("restaurants", "Atlantis", places)
    assert kept == places
    assert dropped == 0


async def test_filter_logs_drop_count(monkeypatch):
    monkeypatch.setattr(research_mod, "aget_coordinates", _fake_geocode)
    messages = []
    sink_id = research_mod.logger.add(lambda m: messages.append(str(m)), level="INFO")
    try:
        await _filter_to_destination("restaurants", "Paris", _sample_places())
    finally:
        research_mod.logger.remove(sink_id)
    assert any("dropped 2" in m for m in messages)
