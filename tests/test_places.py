"""Unit tests for the Overpass places boundary.

parse_overpass and the query builders are pure and tested against a trimmed real Overpass response
(tests/fixtures/overpass_paris.json) with no network. fetch_pois is exercised with its HTTP call
stubbed; a live integration test against the real API is marked `integration`.
"""

import json
from pathlib import Path

import httpx
import pytest

from core import places
from core.places import Candidate, _area_clause, _classify, _coords, build_overpass_query, fetch_pois, parse_overpass

FIXTURE = Path(__file__).parent / "fixtures" / "overpass_paris.json"


@pytest.fixture(autouse=True)
def _clear_cache():
    places._cache.clear()
    yield
    places._cache.clear()


def _load_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# parse_overpass against the real fixture


def test_parse_returns_named_coordinate_bearing_places():
    candidates = parse_overpass(_load_fixture())
    assert len(candidates) == 8
    assert all(isinstance(c, Candidate) for c in candidates)
    assert all(c.name for c in candidates)
    assert all(-90 <= c.lat <= 90 and -180 <= c.lon <= 180 for c in candidates)


def test_parse_classifies_by_tags():
    by_cat: dict[str, list[str]] = {}
    for c in parse_overpass(_load_fixture()):
        by_cat.setdefault(c.category, []).append(c.name)
    assert len(by_cat["restaurants"]) == 4
    assert len(by_cat["hotels"]) == 2
    # the attraction node and the museum way both land under attractions
    assert set(by_cat["attractions"]) == {"Place du Carrousel", "Bourse de Commerce"}


def test_parse_extracts_useful_tags():
    by_name = {c.name: c for c in parse_overpass(_load_fixture())}

    uno = by_name["Uno"]
    assert uno.cuisine == "italian;pizza"
    assert uno.website == "https://unoparis.com/"
    assert uno.osm_type == "node"
    assert uno.osm_id == 247439841
    assert uno.source == "overpass"

    # a place with no cuisine/website tag carries None, not a fabricated value
    desi = by_name["Desi Road"]
    assert desi.cuisine == "indian"
    assert desi.website is None


def test_parse_reads_way_center_and_contact_website_fallback():
    by_name = {c.name: c for c in parse_overpass(_load_fixture())}

    # the museum is a way: coordinates come from `center`, website from `contact:website`
    bourse = by_name["Bourse de Commerce"]
    assert bourse.osm_type == "way"
    assert bourse.lat == pytest.approx(48.8628167)
    assert bourse.lon == pytest.approx(2.3428183)
    assert bourse.website == "https://www.boursedecommerce.fr"

    # a hotel node that only has contact:website also resolves via the fallback
    assert by_name["Hôtel Saint-Honoré"].website == "https://www.hotelsthonore.com"


# parse_overpass edge cases (small inline inputs)


def test_parse_skips_unnamed_places():
    payload = {"elements": [{"type": "node", "id": 1, "lat": 48.86, "lon": 2.34, "tags": {"amenity": "restaurant"}}]}
    assert parse_overpass(payload) == []


def test_parse_skips_places_without_resolvable_coordinates():
    # a relation whose geometry did not resolve: named, but no lat/lon and no center
    payload = {"elements": [{"type": "relation", "id": 2, "tags": {"name": "Ghost Museum", "tourism": "museum"}}]}
    assert parse_overpass(payload) == []


def test_parse_skips_out_of_category_elements():
    payload = {
        "elements": [
            {"type": "node", "id": 3, "lat": 48.86, "lon": 2.34, "tags": {"name": "A Bench", "amenity": "bench"}}
        ]
    }
    assert parse_overpass(payload) == []


def test_parse_drops_out_of_range_coordinates():
    payload = {
        "elements": [
            {"type": "node", "id": 4, "lat": 999.0, "lon": 2.34, "tags": {"name": "Nowhere", "amenity": "restaurant"}}
        ]
    }
    assert parse_overpass(payload) == []


def test_parse_handles_empty_response():
    assert parse_overpass({"elements": []}) == []
    assert parse_overpass({}) == []


def test_classify_maps_each_category():
    assert _classify({"amenity": "restaurant"}) == "restaurants"
    assert _classify({"tourism": "hotel"}) == "hotels"
    assert _classify({"tourism": "attraction"}) == "attractions"
    assert _classify({"tourism": "museum"}) == "attractions"
    assert _classify({"amenity": "bench"}) is None


def test_coords_prefers_node_then_center():
    assert _coords({"lat": 1.0, "lon": 2.0}) == (1.0, 2.0)
    assert _coords({"center": {"lat": 3.0, "lon": 4.0}}) == (3.0, 4.0)
    assert _coords({"tags": {"name": "x"}}) is None


# query building


def test_area_clause_supports_center_radius_and_bbox():
    assert _area_clause((48.86, 2.34)) == f"(around:{places.DEFAULT_RADIUS_METERS},48.86,2.34)"
    assert _area_clause((48.86, 2.34, 500)) == "(around:500.0,48.86,2.34)"
    assert _area_clause((48.8, 2.3, 48.9, 2.4)) == "(48.8,2.3,48.9,2.4)"


def test_area_clause_rejects_malformed_area():
    with pytest.raises(ValueError):
        _area_clause((48.86,))
    with pytest.raises(ValueError):
        _area_clause("paris")


def test_build_query_includes_selector_and_all_element_types():
    query = build_overpass_query((48.86, 2.34), "restaurants", 30)
    assert '["amenity"="restaurant"]' in query
    assert query.count("(around:") == 3  # one per node/way/relation line
    assert "node[" in query and "way[" in query and "relation[" in query
    assert "out center tags 30;" in query


def test_build_query_attractions_fold_in_museums():
    query = build_overpass_query((48.86, 2.34), "attractions", 10)
    assert '["tourism"~"^(attraction|museum)$"]' in query


def test_build_query_rejects_unknown_category():
    with pytest.raises(ValueError):
        build_overpass_query((48.86, 2.34), "nightclubs", 10)


# fetch_pois with the HTTP call stubbed


async def test_fetch_pois_returns_parsed_candidates(monkeypatch):
    async def _fake_post(query):
        return _load_fixture()

    monkeypatch.setattr(places, "_post_overpass", _fake_post)
    out = await fetch_pois((48.86, 2.34), "restaurants")
    assert len(out) == 8


async def test_fetch_pois_returns_empty_on_failed_request(monkeypatch):
    async def _fake_post(query):
        return None

    monkeypatch.setattr(places, "_post_overpass", _fake_post)
    out = await fetch_pois((48.86, 2.34), "restaurants")
    assert out == []


async def test_fetch_pois_does_not_cache_failed_request(monkeypatch):
    # A None payload is a transient failure (throttle/timeout), not a verdict that the area is empty.
    # It must not stick in the cache: the next call has to re-hit _post_overpass.
    calls = {"n": 0}

    async def _fake_post(query):
        calls["n"] += 1
        return None

    monkeypatch.setattr(places, "_post_overpass", _fake_post)
    first = await fetch_pois((48.86, 2.34), "restaurants")
    second = await fetch_pois((48.86, 2.34), "restaurants")
    assert first == [] and second == []
    assert calls["n"] == 2  # failure was retried, not served from a cached []


async def test_fetch_pois_caches_empty_but_valid_response(monkeypatch):
    # A present-but-empty payload is a genuine "nothing here" answer and is cached like any result.
    calls = {"n": 0}

    async def _fake_post(query):
        calls["n"] += 1
        return {"elements": []}

    monkeypatch.setattr(places, "_post_overpass", _fake_post)
    first = await fetch_pois((48.86, 2.34), "restaurants")
    second = await fetch_pois((48.86, 2.34), "restaurants")
    assert first == [] and second == []
    assert calls["n"] == 1  # second lookup served from cache


async def test_fetch_pois_caches_per_query(monkeypatch):
    calls = {"n": 0}

    async def _fake_post(query):
        calls["n"] += 1
        return _load_fixture()

    monkeypatch.setattr(places, "_post_overpass", _fake_post)
    first = await fetch_pois((48.86, 2.34), "restaurants")
    second = await fetch_pois((48.86, 2.34), "restaurants")
    assert first == second
    assert calls["n"] == 1  # second lookup served from cache


# _post_overpass retry/backoff against transient throttles, with the HTTP transport stubbed


class _SeqPost:
    """Stand in for httpx.AsyncClient.post, returning a scripted sequence of responses and counting
    calls. Set as a class attribute it is not a descriptor, so it is invoked as post(url, **kwargs)
    with no bound client."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def __call__(self, url, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


@pytest.fixture
def _no_rate_gap(monkeypatch):
    # Neutralize the politeness gap so the only sleeps a test sees are the backoff waits, and make
    # those instant while recording their durations.
    places._last_call_monotonic = 0.0
    sleeps: list[float] = []

    async def _record(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(places.asyncio, "sleep", _record)
    return sleeps


async def test_post_overpass_retries_throttle_then_succeeds(monkeypatch, _no_rate_gap):
    post = _SeqPost(
        [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"elements": []}),
        ]
    )
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    out = await places._post_overpass("q")
    assert out == {"elements": []}
    assert post.calls == 2  # retried past the 429
    assert _no_rate_gap  # backed off before retrying


async def test_post_overpass_gives_up_after_retry_budget(monkeypatch, _no_rate_gap):
    post = _SeqPost([httpx.Response(429, headers={"Retry-After": "0"})] * 10)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    out = await places._post_overpass("q")
    assert out is None  # exhausted: degrades to None, fetch_pois will not cache it
    assert post.calls == places.MAX_OVERPASS_RETRIES + 1


async def test_post_overpass_caps_retry_after(monkeypatch, _no_rate_gap):
    # A hostile Retry-After must not stall a planning turn: the wait is capped.
    post = _SeqPost(
        [
            httpx.Response(503, headers={"Retry-After": "999"}),
            httpx.Response(200, json={"elements": []}),
        ]
    )
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    out = await places._post_overpass("q")
    assert out == {"elements": []}
    assert max(_no_rate_gap) <= places.RETRY_BACKOFF_CAP_SECONDS


async def test_post_overpass_does_not_retry_non_retryable_status(monkeypatch, _no_rate_gap):
    # A 400 is a bad query, not a transient blip: fail fast, no retry.
    post = _SeqPost([httpx.Response(400, json={})])
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    out = await places._post_overpass("q")
    assert out is None
    assert post.calls == 1
    assert _no_rate_gap == []  # never backed off


async def test_post_overpass_retries_network_error(monkeypatch, _no_rate_gap):
    # A timeout/network blip is transient too: retry, then succeed.
    calls = {"n": 0}
    payload = {"elements": []}

    class _FlakyPost:
        async def __call__(self, url, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectTimeout("boom")
            return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "post", _FlakyPost())
    out = await places._post_overpass("q")
    assert out == payload
    assert calls["n"] == 2


@pytest.mark.integration
async def test_fetch_pois_live_returns_real_paris_places():
    # Acceptance: a real city + category returns real places with valid coordinates. Network; runs
    # only under `pytest -m integration`.
    out = await fetch_pois((48.8606, 2.3376, 600), "restaurants", limit=10)
    assert out
    assert all(c.name and c.source == "overpass" for c in out)
    assert all(48.0 < c.lat < 49.5 and 1.5 < c.lon < 3.0 for c in out)
