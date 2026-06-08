"""Bound the conversation history that gets replayed to the LLM each turn.

The graph is stateless, so the message history is its only memory and it is replayed in full
every turn. Delivered itineraries (~3.7k chars each) accumulate there, so a few planning turns
would blow the model's context window and balloon cost. This trims what is sent to the graph
without losing what it needs: the first message (destination/intent), the recent turns, and the
latest itinerary (post-plan detection and follow-up answers depend on it). The full untrimmed
history still lives in the DB.
"""

_ITINERARY_MARKERS = ("## Day", "Trip to")


def _is_itinerary(message: dict) -> bool:
    content = message.get("content", "")
    return message.get("role") == "model" and any(m in content for m in _ITINERARY_MARKERS)


def bound_history(messages: list[dict], keep_recent: int = 8) -> list[dict]:
    """Return a trimmed copy of the history that is safe to replay to the graph.

    Keeps the first message, the last `keep_recent` messages, and the most recent itinerary
    intact. Older itinerary bodies are replaced with a short stub (the full text is preserved in
    the DB and the trips table). Older plain conversational turns outside the window are dropped.
    Short histories are returned unchanged.
    """
    n = len(messages)
    if n <= keep_recent + 1:
        return [dict(m) for m in messages]

    latest_itin = next((i for i in range(n - 1, -1, -1) if _is_itinerary(messages[i])), None)

    keep = set(range(n - keep_recent, n))
    keep.add(0)
    if latest_itin is not None:
        keep.add(latest_itin)

    out = []
    for i, m in enumerate(messages):
        if i in keep:
            out.append(dict(m))
        elif _is_itinerary(m):
            out.append({"role": "model", "content": "[earlier itinerary omitted to save context]"})
        # older plain conversational turns outside the window are dropped
    return out
