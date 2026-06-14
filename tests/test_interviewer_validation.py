"""The interviewer's pre-plan sanity gate: out-of-range or infeasible requests stay in the interview
with a clarification instead of reaching research. The feasibility LLM call is stubbed.
"""

from core.nodes import interviewer as iv
from core.nodes.interviewer import _validate_request, interviewer_node
from core.schemas import TripFeasibility, UserPreferences


def _feas(feasible, clarification=""):
    async def _f(user_details):
        return TripFeasibility(feasible=feasible, clarification=clarification)

    return _f


# _validate_request: bounds first, then feasibility, with the documented fail behaviors


async def test_validate_rejects_too_long_without_consulting_feasibility(monkeypatch):
    consulted = False

    async def _spy(user_details):
        nonlocal consulted
        consulted = True
        return TripFeasibility(feasible=True)

    monkeypatch.setattr(iv, "_check_feasibility", _spy)
    msg = await _validate_request({"destination": "Paris", "duration": "109 days"})
    assert msg is not None and "30" in msg
    assert consulted is False  # deterministic bound short-circuits the LLM call


async def test_validate_rejects_zero_days(monkeypatch):
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    assert await _validate_request({"destination": "Paris", "duration": "0 days"}) is not None


async def test_validate_proceeds_on_feasible(monkeypatch):
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    assert await _validate_request({"destination": "Paris", "duration": "3 days"}) is None


async def test_validate_clarifies_on_infeasible(monkeypatch):
    monkeypatch.setattr(
        iv, "_check_feasibility", _feas(False, "I couldn't find that destination. Where would you like to go?")
    )
    msg = await _validate_request({"destination": "Wakanda", "duration": "3 days"})
    assert msg and "couldn't find" in msg.lower()


async def test_validate_proceeds_when_feasibility_errors(monkeypatch):
    async def _errored(user_details):
        return None  # _check_feasibility returns None on its own failure

    monkeypatch.setattr(iv, "_check_feasibility", _errored)
    assert await _validate_request({"destination": "Paris", "duration": "3 days"}) is None


# Node wiring: a ready-but-absurd request stays in the interview, never reaching research


class _FakePrefsLLM:
    def __init__(self, prefs):
        self._prefs = prefs

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, messages, config=None):
        return self._prefs


def _ready(**overrides):
    base = {
        "destination": "Paris",
        "duration": "3 days",
        "needs_accommodation": False,
        "interests": "food",
        "start_location": "Madrid",
    }
    base.update(overrides)
    return UserPreferences(**base)


async def test_node_stays_in_interview_for_absurd_length(monkeypatch):
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _FakePrefsLLM(_ready(duration="109 days")))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    result = await interviewer_node({"messages": [{"role": "user", "content": "109 day trip to Paris"}]})
    assert result["next_node"] == "interviewer"
    assert "30" in result["messages"][0]["content"]


async def test_node_proceeds_to_research_when_valid(monkeypatch):
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _FakePrefsLLM(_ready()))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    result = await interviewer_node({"messages": [{"role": "user", "content": "3 day trip to Paris"}]})
    assert result["next_node"] == "research"
