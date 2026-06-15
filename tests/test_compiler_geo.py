"""The compiler builds the map payload from the itinerary's real per-day structure (not proximity
zones), emits it on a fresh plan, and emits none on an in-place edit.

The markdown call and the structured day-assignment call are both stubbed, and coordinates are
pre-set, so this runs with no network and no live graph context.
"""

import pytest

from core.nodes import compiler as compiler_mod
from core.nodes.compiler import compiler_node
from core.schemas import ItineraryDay, ItineraryDayPlan


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.usage_metadata = {"total_tokens": 7}


class _FakeStructured:
    """Stands in for llm.with_structured_output(ItineraryDayPlan). Returns a preset plan, or raises
    when handed an exception, to exercise the fallback."""

    def __init__(self, day_plan):
        self._day_plan = day_plan

    async def ainvoke(self, messages, config=None):
        if isinstance(self._day_plan, Exception):
            raise self._day_plan
        return self._day_plan


class _FakeLLM:
    def __init__(self, markdown, day_plan):
        self._markdown = markdown
        self._day_plan = day_plan

    async def ainvoke(self, messages, config=None):
        return _FakeResponse(self._markdown)

    def with_structured_output(self, schema):
        return _FakeStructured(self._day_plan)


@pytest.fixture(autouse=True)
def _stub_events(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(compiler_mod, "adispatch_custom_event", _noop)


def _patch_llm(monkeypatch, markdown="# Trip\n", day_plan=None):
    plan = day_plan if day_plan is not None else ItineraryDayPlan(days=[])
    monkeypatch.setattr(compiler_mod, "get_llm_for_role", lambda role: _FakeLLM(markdown, plan))


async def test_compiler_emits_geo_for_a_fresh_plan(monkeypatch):
    _patch_llm(
        monkeypatch,
        markdown="# 3 days in Rome\n## Day 1\nColosseum, then lunch.",
        day_plan=ItineraryDayPlan(days=[ItineraryDay(day=1, title="Ancient Rome", stops=["Colosseum", "Trattoria"])]),
    )
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


async def test_compiler_follows_itinerary_days_in_a_compact_city(monkeypatch):
    # The P2 bug: a two-day plan where every stop is walkable from the hotel sits in one proximity
    # zone, so the old zone-driven map collapsed it to a single day. The map must instead follow the
    # itinerary's two days.
    lat, lon = 48.8566, 2.3522
    markdown = "# 2 days in Paris\n## Day 1\nLouvre then dinner.\n## Day 2\nOrsay then the tower."
    day_plan = ItineraryDayPlan(
        days=[
            ItineraryDay(day=1, title="Right bank", stops=["Louvre", "Le Comptoir"]),
            ItineraryDay(day=2, title="Left bank", stops=["Musee d'Orsay", "Eiffel Tower"]),
        ]
    )
    _patch_llm(monkeypatch, markdown=markdown, day_plan=day_plan)
    state = {
        "user_details": {"destination": "Paris", "duration": "2 days", "needs_accommodation": True},
        "hotel_data": [{"name": "Hotel Paris", "address": "Paris", "lat": lat, "lon": lon}],
        "activity_data": [
            {"name": "Louvre", "address": "Paris", "lat": lat + 0.004, "lon": lon},
            {"name": "Musee d'Orsay", "address": "Paris", "lat": lat + 0.005, "lon": lon},
            {"name": "Eiffel Tower", "address": "Paris", "lat": lat + 0.006, "lon": lon},
        ],
        "food_data": [{"name": "Le Comptoir", "address": "Paris", "lat": lat + 0.007, "lon": lon}],
        "iteration_count": 0,
    }

    result = await compiler_node(state)

    geo = result["itinerary_geo"]
    assert [d["day"] for d in geo["days"]] == [1, 2]
    assert [d["title"] for d in geo["days"]] == ["Right bank", "Left bank"]
    assert [p["name"] for p in geo["days"][0]["places"]] == ["Louvre", "Le Comptoir"]


async def test_compiler_falls_back_to_zones_when_day_pass_fails(monkeypatch):
    # Fail loud but degrade: if the structured pass errors, the map still renders via proximity zones
    # rather than vanishing. Zone days carry a "zone" key; itinerary days do not.
    _patch_llm(monkeypatch, markdown="# 2 days in Paris\n", day_plan=RuntimeError("structured pass down"))
    lat, lon = 48.8566, 2.3522
    state = {
        "user_details": {"destination": "Paris", "duration": "2 days", "needs_accommodation": True},
        "hotel_data": [{"name": "Hotel Paris", "address": "Paris", "lat": lat, "lon": lon}],
        "activity_data": [{"name": "Louvre", "address": "Paris", "lat": lat + 0.004, "lon": lon}],
        "food_data": [{"name": "Le Comptoir", "address": "Paris", "lat": lat + 0.007, "lon": lon}],
        "iteration_count": 0,
    }

    result = await compiler_node(state)

    geo = result["itinerary_geo"]
    assert geo["days"]
    assert "zone" in geo["days"][0]


async def test_compiler_emits_no_geo_on_an_edit(monkeypatch):
    _patch_llm(monkeypatch)
    state = {
        "edit_instruction": "swap the Tuesday restaurant for something cheaper",
        "base_itinerary": "# 3 days in Rome\n## Day 1\nLunch at X",
        "iteration_count": 1,
    }

    result = await compiler_node(state)

    assert result["draft_itinerary"]
    assert "itinerary_geo" not in result


async def test_compiler_prompt_includes_constraints(monkeypatch):
    # Allergies/dietary captured into constraints must reach the writer so the plan honors them.
    captured = {}

    class _CapturingLLM:
        async def ainvoke(self, messages, config=None):
            captured["prompt"] = " ".join(getattr(m, "content", "") for m in messages)
            return _FakeResponse("# 2 days in Rome\n## Day 1\nColosseum.")

        def with_structured_output(self, schema):
            return _FakeStructured(ItineraryDayPlan(days=[ItineraryDay(day=1, title="Day", stops=["Colosseum"])]))

    monkeypatch.setattr(compiler_mod, "get_llm_for_role", lambda role: _CapturingLLM())
    state = {
        "user_details": {
            "destination": "Rome",
            "duration": "2 days",
            "needs_accommodation": False,
            "constraints": {"hard": ["allergic to shellfish"], "soft": ["relaxed pace"]},
        },
        "activity_data": [{"name": "Colosseum", "address": "Rome", "lat": 41.89, "lon": 12.49}],
        "food_data": [],
        "hotel_data": [],
        "iteration_count": 0,
    }

    await compiler_node(state)

    # hard constraint lands in the enforce block, soft in the prefer block
    assert "allergic to shellfish" in captured["prompt"]
    assert "relaxed pace" in captured["prompt"]
    assert "Hard requirements" in captured["prompt"] and "never violate" in captured["prompt"]


async def test_compiler_avoids_prior_hard_violations(monkeypatch):
    # When the critic sent the plan back for a hard-constraint violation, the recompile prompt must
    # tell the writer to avoid the offending venue.
    captured = {}

    class _CapturingLLM:
        async def ainvoke(self, messages, config=None):
            captured["prompt"] = " ".join(getattr(m, "content", "") for m in messages)
            return _FakeResponse("# 2 days in Rome\n## Day 1\nColosseum.")

        def with_structured_output(self, schema):
            return _FakeStructured(ItineraryDayPlan(days=[ItineraryDay(day=1, title="Day", stops=["Colosseum"])]))

    monkeypatch.setattr(compiler_mod, "get_llm_for_role", lambda role: _CapturingLLM())
    state = {
        "user_details": {
            "destination": "Rome",
            "duration": "2 days",
            "needs_accommodation": False,
            "constraints": {"hard": ["allergic to shellfish"], "soft": []},
        },
        "critique": {"hard_violations": ["Seafood Palace"]},
        "activity_data": [{"name": "Colosseum", "address": "Rome", "lat": 41.89, "lon": 12.49}],
        "food_data": [],
        "hotel_data": [],
        "iteration_count": 1,
    }

    await compiler_node(state)

    assert "MUST AVOID" in captured["prompt"]
    assert "Seafood Palace" in captured["prompt"]
