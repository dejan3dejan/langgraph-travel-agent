"""Unit tests for the critic's deterministic re-research / re-compile decisions."""

from core.nodes import critic as critic_mod
from core.nodes.critic import _missing_categories, critic_node
from core.schemas import ItineraryCritique


def test_no_missing_when_all_present():
    assert _missing_categories([{"name": "a"}], [{"name": "b"}], [{"name": "c"}]) == []


def test_flags_only_empty_categories():
    assert _missing_categories([], [{"name": "b"}], []) == ["food", "hotels"]


def test_all_empty():
    assert _missing_categories([], [], []) == ["food", "activities", "hotels"]


def test_none_treated_as_empty():
    assert _missing_categories(None, None, None) == ["food", "activities", "hotels"]


def test_empty_hotels_not_missing_when_accommodation_not_needed():
    # already-sorted lodging: empty hotels must not trigger a wasted re-research loop
    assert _missing_categories([{"name": "a"}], [{"name": "b"}], [], needs_accommodation=False) == []
    assert _missing_categories([], [], [], needs_accommodation=False) == ["food", "activities"]


def test_empty_hotels_missing_when_accommodation_needed():
    assert _missing_categories([{"name": "a"}], [{"name": "b"}], [], needs_accommodation=True) == ["hotels"]


# hard-constraint re-check routing (the safety loop)


class _FakeCriticLLM:
    def __init__(self, critique):
        self._critique = critique

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages, config=None):
        return self._critique


def _reviewable_state(**overrides):
    # research present so nothing is "missing"; the routing then turns on hard_violations
    state = {
        "draft_itinerary": "# Trip to Rome\n## Day 1\nLunch at Seafood Palace.",
        "user_details": {"destination": "Rome", "constraints": {"hard": ["allergic to shellfish"], "soft": []}},
        "food_data": [{"name": "x"}],
        "activity_data": [{"name": "y"}],
        "hotel_data": [{"name": "z"}],
        "iteration_count": 1,
    }
    state.update(overrides)
    return state


async def test_critic_recompiles_on_hard_violation(monkeypatch):
    critique = ItineraryCritique(approved=True, feedback="ok", score=8, hard_violations=["Seafood Palace"])
    monkeypatch.setattr(critic_mod, "get_llm_for_role", lambda role: _FakeCriticLLM(critique))
    result = await critic_node(_reviewable_state())
    assert result["next_node"] == "compiler"
    assert result["critique"]["approved"] is False
    assert result["critique"]["hard_violations"] == ["Seafood Palace"]


async def test_critic_approves_compliant_plan(monkeypatch):
    critique = ItineraryCritique(approved=True, feedback="great", score=9, hard_violations=[])
    monkeypatch.setattr(critic_mod, "get_llm_for_role", lambda role: _FakeCriticLLM(critique))
    result = await critic_node(
        _reviewable_state(user_details={"destination": "Rome", "constraints": {"hard": [], "soft": []}})
    )
    assert result["next_node"] == "approved"
    assert result["critique"]["approved"] is True
