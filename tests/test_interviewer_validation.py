"""The interviewer's pre-plan sanity gate: out-of-range or infeasible requests stay in the interview
with a clarification instead of reaching research. The feasibility LLM call is stubbed.
"""

from core.nodes import interviewer as iv
from core.nodes.interviewer import _validate_request, interviewer_node
from core.schemas import TripFeasibility, UserPreferences


def _feas(feasible, clarification=""):
    async def _f(user_details, request_text):
        return TripFeasibility(feasible=feasible, clarification=clarification)

    return _f


# _validate_request: bounds first, then feasibility, with the documented fail behaviors


async def test_validate_rejects_too_long_without_consulting_feasibility(monkeypatch):
    consulted = False

    async def _spy(user_details, request_text):
        nonlocal consulted
        consulted = True
        return TripFeasibility(feasible=True)

    monkeypatch.setattr(iv, "_check_feasibility", _spy)
    msg = await _validate_request({"destination": "Paris", "duration": "109 days"}, "109 day trip to Paris")
    assert msg is not None and "30" in msg
    assert consulted is False  # deterministic bound short-circuits the LLM call


async def test_validate_rejects_zero_days(monkeypatch):
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    assert await _validate_request({"destination": "Paris", "duration": "0 days"}, "0 day trip") is not None


async def test_validate_proceeds_on_feasible(monkeypatch):
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    assert await _validate_request({"destination": "Paris", "duration": "3 days"}, "3 days in Paris") is None


async def test_validate_clarifies_on_infeasible(monkeypatch):
    monkeypatch.setattr(
        iv, "_check_feasibility", _feas(False, "I couldn't find that destination. Where would you like to go?")
    )
    msg = await _validate_request({"destination": "Wakanda", "duration": "3 days"}, "3 days in Wakanda")
    assert msg and "couldn't find" in msg.lower()


async def test_validate_proceeds_when_feasibility_errors(monkeypatch):
    async def _errored(user_details, request_text):
        return None  # _check_feasibility returns None on its own failure

    monkeypatch.setattr(iv, "_check_feasibility", _errored)
    assert await _validate_request({"destination": "Paris", "duration": "3 days"}, "3 days in Paris") is None


# Node wiring: a ready-but-absurd request stays in the interview, never reaching research


class _Structured:
    def __init__(self, prefs):
        self._prefs = prefs

    async def ainvoke(self, messages, config=None):
        return self._prefs


class _Fake:
    """Stands in for the interviewer/extraction LLM: structured calls yield the preset preferences,
    a plain call yields a conversational reply (used by the confirm beat)."""

    def __init__(self, prefs, reply="Before I start planning, is there anything else I should know?"):
        self._prefs = prefs
        self._reply = reply

    def with_structured_output(self, schema):
        return _Structured(self._prefs)

    async def ainvoke(self, messages, config=None):
        return type("_R", (), {"content": self._reply, "usage_metadata": {"total_tokens": 3}})()


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
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready(duration="109 days")))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    result = await interviewer_node({"messages": [{"role": "user", "content": "109 day trip to Paris"}]})
    assert result["next_node"] == "interviewer"
    assert "30" in result["messages"][0]["content"]


async def test_node_asks_confirm_beat_before_planning(monkeypatch):
    # Ready and valid, but the "anything else?" beat has not happened yet: ask it, do not plan.
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready()))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    result = await interviewer_node({"messages": [{"role": "user", "content": "3 day trip to Paris"}]})
    assert result["next_node"] == "interviewer"
    assert "before i start planning" in result["messages"][0]["content"].lower()


async def test_node_plans_after_confirm_beat(monkeypatch):
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready()))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    messages = [
        {"role": "user", "content": "3 day trip to Paris"},
        {"role": "model", "content": "Before I start planning, anything else I should know?"},
        {"role": "user", "content": "no, that covers it"},
    ]
    result = await interviewer_node({"messages": messages})
    assert result["next_node"] == "research"


async def test_node_honors_plan_it_now(monkeypatch):
    # An explicit "plan it now" skips the confirm beat and plans immediately.
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready()))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    result = await interviewer_node({"messages": [{"role": "user", "content": "plan it now"}]})
    assert result["next_node"] == "research"
