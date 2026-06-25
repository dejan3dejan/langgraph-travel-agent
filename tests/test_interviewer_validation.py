"""The interviewer's pre-plan sanity gate: out-of-range or infeasible requests stay in the interview
with a clarification instead of reaching research. The feasibility LLM call is stubbed.
"""

from core.nodes import interviewer as iv
from core.nodes.interviewer import MAX_INTERVIEW_TURNS, _validate_request, interviewer_node
from core.schemas import TripFeasibility, UserPreferences


def _feas(feasible, clarification="", issue="unknown_place"):
    async def _f(user_details, request_text):
        return TripFeasibility(feasible=feasible, clarification=clarification, issue=issue if not feasible else "none")

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


async def test_validate_skips_feasibility_when_in_destination(monkeypatch):
    # already-in-town trips skip the feasibility LLM, which misreads "in X, explore X" as contradictory
    async def _should_not_run(user_details, request_text):
        raise AssertionError("feasibility must be skipped for in-destination trips")

    monkeypatch.setattr(iv, "_check_feasibility", _should_not_run)
    ud = {"destination": "Bratislava", "start_location": "Bratislava", "duration": "1 day"}
    assert await _validate_request(ud, "food") is None


async def test_validate_ignores_vague_infeasibility(monkeypatch):
    # feasible=false with no concrete issue (the model over-flagging an already-there / sparse trip)
    # must NOT block a real, plannable request
    monkeypatch.setattr(iv, "_check_feasibility", _feas(False, "are you already there?", issue="other"))
    assert await _validate_request({"destination": "Bratislava", "duration": "1 day"}, "food") is None


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
    # Out-of-range length keeps us in the interview with a streamed clarification, never planning.
    assert result["next_node"] == "interviewer"
    assert result["messages"][0]["content"]


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


async def test_node_plans_at_turn_budget_even_with_short_window(monkeypatch):
    # The loop bug: user_turns was counted from the TRIMMED replay window, so the backstop never
    # fired and a never-answered soft slot (here origin) was re-asked forever. The true count is
    # threaded in as user_turn_count; past the budget the node plans instead of re-asking.
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready(start_location="")))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    messages = [
        {"role": "user", "content": "Paris 3 days, into food"},
        {"role": "model", "content": "Where will you be travelling from? (you can skip this)"},
        {"role": "user", "content": "anyway"},
    ]
    result = await interviewer_node({"messages": messages, "user_turn_count": MAX_INTERVIEW_TURNS})
    assert result["next_node"] == "research"


async def test_node_does_not_reask_a_slot_the_prior_turn_filled(monkeypatch):
    # Durable slots: the prior turn captured the duration, this turn's extraction drops it. The merge
    # must restore it so the gate never re-asks something already answered.
    asked = []

    async def _spy_ask(question_key, user_details, messages, t0):
        asked.append(question_key)
        return {"messages": [{"role": "model", "content": "q"}], "next_node": "interviewer", "debug_logs": []}

    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready(duration="")))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    monkeypatch.setattr(iv, "_ask_for", _spy_ask)
    prior = _ready().model_dump()  # a complete profile from earlier turns, including the duration
    messages = [
        {"role": "user", "content": "3 day trip to Paris"},
        {"role": "model", "content": "what are you in the mood for?"},
        {"role": "user", "content": "food"},
    ]
    result = await interviewer_node({"messages": messages, "user_details": prior})
    assert "duration" not in asked  # restored by the merge, never re-asked
    assert result["user_details"]["duration"] == "3 days"


async def test_node_asks_a_soft_slot_at_most_once(monkeypatch):
    # An ignored soft slot (origin) is asked once and recorded; the next turn skips it instead of
    # nagging, even though it is still unanswered.
    asked_keys = []

    async def _spy_ask(question_key, user_details, messages, t0):
        asked_keys.append(question_key)
        return {"messages": [{"role": "model", "content": "q"}], "next_node": "interviewer", "debug_logs": []}

    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready(start_location="")))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    monkeypatch.setattr(iv, "_ask_for", _spy_ask)
    messages = [{"role": "user", "content": "Paris 3 days, food"}]

    r1 = await interviewer_node({"messages": messages, "user_turn_count": 1})
    assert asked_keys == ["origin"] and "origin" in r1["asked_slots"]

    asked_keys.clear()
    r2 = await interviewer_node({"messages": messages, "user_turn_count": 2, "asked_slots": r1["asked_slots"]})
    assert "origin" not in asked_keys  # not re-asked
    assert r2["next_node"] == "interviewer"  # moved on to the confirm beat, not the origin question


async def test_node_regenerate_replans_fresh_instead_of_editing(monkeypatch):
    # "regenerate the plan" on an existing plan must re-run the pipeline (fresh full plan), not route
    # to the post-plan edit/follow-up path that can degrade off a brief base.
    monkeypatch.setattr(iv, "get_llm_for_role", lambda role: _Fake(_ready()))
    monkeypatch.setattr(iv, "_check_feasibility", _feas(True))
    messages = [
        {"role": "user", "content": "romantic weekend in Paris"},
        {"role": "model", "content": "# 2 days Trip to Paris\n## Day 1: Louvre\n## Day 2: Le Marais"},
        {"role": "user", "content": "regenerate the plan"},
    ]
    result = await interviewer_node({"messages": messages})
    assert result["next_node"] == "research"
