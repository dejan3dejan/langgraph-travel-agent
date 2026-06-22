"""Pure sliding-window rate limiting.

The decision (is this caller over the cap?) is separated from where the hit timestamps are kept, so
it is testable without a clock or a store. Callers own the list of prior hit timestamps (e.g. an
in-memory dict keyed by email) and pass it in.
"""


def within_limit(hits: list[float], now: float, window_seconds: float, max_hits: int) -> tuple[bool, list[float]]:
    """Decide whether an attempt at ``now`` is within the cap, given prior hit timestamps.

    Returns ``(allowed, updated_hits)``. ``updated_hits`` always drops timestamps older than the
    window; when allowed it also records ``now``. A blocked attempt is not recorded, so a caller
    cannot push its own window out by hammering the endpoint. Does not mutate the input list.
    """
    fresh = [t for t in hits if t > now - window_seconds]
    if len(fresh) >= max_hits:
        return False, fresh
    fresh.append(now)
    return True, fresh
