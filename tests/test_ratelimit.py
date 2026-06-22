"""Unit tests for the pure sliding-window rate-limit helper. No clock, no I/O."""

from core.ratelimit import within_limit


def test_within_limit_allows_until_the_cap_then_blocks():
    hits = []
    now = 1000.0
    # max 3 in the window: first three allowed, fourth blocked.
    for _ in range(3):
        allowed, hits = within_limit(hits, now, window_seconds=60, max_hits=3)
        assert allowed is True
    allowed, hits = within_limit(hits, now, window_seconds=60, max_hits=3)
    assert allowed is False
    # a blocked attempt is not recorded, so the stored count stays at the cap
    assert len(hits) == 3


def test_within_limit_drops_hits_outside_the_window():
    # three old hits well outside the 60s window plus one recent one
    hits = [10.0, 20.0, 30.0, 990.0]
    now = 1000.0
    allowed, hits = within_limit(hits, now, window_seconds=60, max_hits=3)
    assert allowed is True
    # only the in-window hit (990) and the new one (1000) survive
    assert hits == [990.0, 1000.0]


def test_within_limit_recovers_after_the_window_passes():
    hits = []
    now = 1000.0
    for _ in range(3):
        _, hits = within_limit(hits, now, window_seconds=60, max_hits=3)
    blocked, hits = within_limit(hits, now, window_seconds=60, max_hits=3)
    assert blocked is False
    # advance past the window: the old hits expire and a new attempt is allowed
    later = now + 61
    allowed, hits = within_limit(hits, later, window_seconds=60, max_hits=3)
    assert allowed is True
    assert hits == [later]


def test_within_limit_does_not_mutate_the_input_list():
    hits = [990.0]
    within_limit(hits, 1000.0, window_seconds=60, max_hits=3)
    assert hits == [990.0]
