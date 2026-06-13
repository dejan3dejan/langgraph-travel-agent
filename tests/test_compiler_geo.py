"""The compiler emits a structured map payload on a fresh plan, and none on an in-place edit.

The LLM and the custom-event dispatch are stubbed and coordinates are pre-set, so this runs with no
network and no live graph context.
"""

import pytest

from core.nodes import compiler as compiler_mod
from core.nodes.compiler import compiler_node


class _FakeResponse:
    content = "# 3 days in Rome\n## Day-by-Day Itinerary\n### Day 1\nColosseum, then lunch."
    usage_metadata = {"total_tokens": 7}


class _FakeLLM:
    async def ainvoke(self, messages, config=None):
        return _FakeResponse()


@pytest.fixture(autouse=True)
def _stub_llm_and_events(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(compiler_mod, "get_llm_for_role", lambda role: _FakeLLM())
    monkeypatch.setattr(compiler_mod, "adispatch_custom_event", _noop)


async def test_compiler_emits_geo_for_a_fresh_plan():
    state = {
        "user_details": {
            "destination": "Rome",
            "duration": "3 days",
            "num_travelers": 2,
            "needs_accommodation": True,
        },
        "hotel_data": [{"name": "Hotel Roma", "address": "Rome", "lat": 41.8919, "lon": 12.4900}],
        "activity_data": [{"name": "Colosseum", "address": "Rome", "lat": 41.8902, "lon": 12.4922}],
        "food_data": [{"name": "Trattoria", "address": "Rome", "lat": 41.8930, "lon": 12.4880}],
        "iteration_count": 0,
    }

    result = await compiler_node(state)

    geo = result["itinerary_geo"]
    assert geo["hotel"]["name"] == "Hotel Roma"
    assert geo["days"]

    places = [p for day in geo["days"] for p in day["places"]]
    assert {"Colosseum", "Trattoria"} <= {p["name"] for p in places}
    assert all(p["lat"] and p["lon"] for p in places)
    assert {p["kind"] for p in places} == {"activity", "restaurant"}


async def test_compiler_emits_no_geo_on_an_edit():
    state = {
        "edit_instruction": "swap the Tuesday restaurant for something cheaper",
        "base_itinerary": "# 3 days in Rome\n## Day 1\nLunch at X",
        "iteration_count": 1,
    }

    result = await compiler_node(state)

    assert result["draft_itinerary"]
    assert "itinerary_geo" not in result
