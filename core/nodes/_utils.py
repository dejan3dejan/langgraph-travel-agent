"""Shared utilities for graph nodes."""

import time
from typing import Any


def _in_destination(user_details: dict) -> bool:
    """True when the traveler is starting from the destination itself ("I'm already in X").

    Drives already-there framing (local transport, no "getting there") and the accommodation
    default. The default placeholder start ("the user's current location") is never in-destination.
    Matches by case-insensitive substring so a bare city name lines up with a geocoded
    "City, Country" on either side.
    """
    start = (user_details.get("start_location") or "").strip().lower()
    dest = (user_details.get("destination") or "").strip().lower()
    if not start or not dest or "current location" in start:
        return False
    return start == dest or start in dest or dest in start


def _origin_pending(user_details: dict) -> bool:
    """True when we have not yet captured or been declined a starting point (empty, or the schema
    default placeholder), so the interviewer should ask for it. A real city or the 'declined'
    sentinel both count as resolved, so the gate stops asking."""
    s = (user_details.get("start_location") or "").strip().lower()
    return s == "" or "current location" in s


def log_usage(node_name: str, start_time: float, response: Any = None) -> dict:
    """Build a timing/token-count log entry for debug_logs."""
    duration = time.time() - start_time
    tokens = 0

    try:
        if response:
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                tokens = response.usage_metadata.get("total_tokens", 0)
            elif hasattr(response, "response_metadata") and response.response_metadata:
                tokens = response.response_metadata.get("token_usage", {}).get("total_tokens", 0)
    except Exception:
        pass

    return {
        "node": node_name,
        "latency_sec": round(duration, 2),
        "total_tokens": tokens,
        "timestamp": time.strftime("%H:%M:%S"),
    }
