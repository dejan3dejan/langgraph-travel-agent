"""Unit tests for conversation-history bounding (A2). Pure, no I/O."""

from core.history import bound_history


def _plain(n):
    return [{"role": "user" if i % 2 == 0 else "model", "content": f"m{i}"} for i in range(n)]


def test_short_history_unchanged():
    msgs = [{"role": "user", "content": "hi"}, {"role": "model", "content": "hello"}]
    assert bound_history(msgs) == msgs


def test_returns_a_copy():
    msgs = [{"role": "user", "content": "hi"}]
    out = bound_history(msgs)
    out[0]["content"] = "mutated"
    assert msgs[0]["content"] == "hi"


def test_keeps_first_and_recent_drops_middle():
    msgs = _plain(14)
    out = bound_history(msgs, keep_recent=4)
    assert out[0]["content"] == "m0"
    assert out[-1]["content"] == "m13"
    assert len(out) < len(msgs)
    contents = [m["content"] for m in out]
    assert "m6" not in contents  # a middle turn is dropped


def test_latest_itinerary_kept_for_post_plan_detection():
    msgs = (
        [{"role": "user", "content": "plan rome"}]
        + _plain(10)
        + [{"role": "model", "content": "# 3 days Trip to Rome\n## Day 1: Colosseum"}]
    )
    out = bound_history(msgs, keep_recent=4)
    assert any("## Day" in m["content"] for m in out)


def test_older_itinerary_stubbed_latest_kept():
    msgs = [
        {"role": "user", "content": "plan rome"},
        {"role": "model", "content": "# Trip to Rome\n## Day 1: old"},
        {"role": "user", "content": "now tokyo"},
        {"role": "user", "content": "f1"},
        {"role": "model", "content": "a1"},
        {"role": "user", "content": "f2"},
        {"role": "model", "content": "a2"},
        {"role": "user", "content": "f3"},
        {"role": "model", "content": "a3"},
        {"role": "model", "content": "# Trip to Tokyo\n## Day 1: new"},
    ]
    out = bound_history(msgs, keep_recent=4)
    joined = "\n".join(m["content"] for m in out)
    assert "Day 1: new" in joined
    assert "Day 1: old" not in joined
    assert "omitted" in joined


def test_first_message_preferences_survive_long_history():
    msgs = [{"role": "user", "content": "honeymoon in Rome, we love wine"}] + _plain(20)
    out = bound_history(msgs, keep_recent=4)
    assert out[0]["content"] == "honeymoon in Rome, we love wine"
