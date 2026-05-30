"""Shared utilities for graph nodes."""

import time
from typing import Any


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
