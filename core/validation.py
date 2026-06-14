"""Sanity checks on a trip request before the pipeline spends a research+compile cycle on it.

Pure and I/O-free: parsing and bounds only. The feasibility judgment (fictional place, impossible
logistics) lives in the interviewer, which has the LLM.
"""

import re

MIN_TRIP_DAYS = 1
MAX_TRIP_DAYS = 30


def parse_trip_days(duration: str) -> int | None:
    """Best-effort day count from the free-text duration. Sums the integers it finds, so a
    multi-destination string ("4 days in Barcelona, 7 in Lisbon") yields the total length. Returns
    None when there is no number to read: extraction usually normalizes phrases like "a week" to
    "7 days", and an unreadable value is left for the pipeline rather than blocked.
    """
    nums = [int(n) for n in re.findall(r"-?\d+", duration or "")]
    return sum(nums) if nums else None


def duration_issue(days: int) -> str | None:
    """A user-facing clarification when the trip length is out of range, else None. Deterministic and
    fail-closed: this is the one hard bound on trip length."""
    if days < MIN_TRIP_DAYS:
        return f"A trip needs to be at least {MIN_TRIP_DAYS} day. How many days would you like to plan?"
    if days > MAX_TRIP_DAYS:
        return (
            f"{days} days is longer than I can plan well. I cover trips up to {MAX_TRIP_DAYS} days. "
            "How many days would you like to plan?"
        )
    return None
