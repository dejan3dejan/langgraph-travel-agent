import random
from typing import Any

from .graph import app, variant_app
from .history import bound_history

_STATUS_MAP = {
    "interviewer": "Atlas is thinking...",
    "research_food": "🔍 Searching for the best restaurants...",
    "research_activity": "🏛 Researching activities...",
    "research_hotel": "🏨 Finding accommodations...",
    "logistics": "🗺️ Mapping the route...",
    "compiler": "✍️ Compiling your itinerary...",
    "critic": "🔎 Reviewing the plan...",
}
_MARKER = "PLANNING_STARTED"  # interviewer trigger token; must never reach the user


def _should_compare(compare: bool, produced_itinerary: bool, is_edit: bool) -> bool:
    """A second variant is warranted only for a freshly produced plan that was explicitly requested
    for comparison. An interview turn (no plan) or an in-place edit never spawns a variant B."""
    return bool(compare and produced_itinerary and not is_edit)


def _tag_event(event: dict, variant: str | None) -> dict:
    """Tag a stream event with its variant ("A"/"B") for compare mode. Untagged when variant is None,
    so the single-itinerary flow stays byte-for-byte identical for existing clients."""
    if variant:
        return {**event, "variant": variant}
    return event


def _variant_b_inputs(captured: dict, nonce: int) -> dict:
    """Build the compiler-only graph inputs for variant B from variant A's captured state: reuse A's
    research pools verbatim and take the regenerate path (diversify against A) so a compare request
    pays for one extra compile, not a second research pass."""
    return {
        "messages": [],
        "user_details": captured.get("user_details", {}),
        "season_suggestion": captured.get("season_suggestion"),
        "food_data": captured.get("food_data") or [],
        "activity_data": captured.get("activity_data") or [],
        "hotel_data": captured.get("hotel_data") or [],
        "regenerate": True,
        "base_itinerary": captured.get("draft"),
        "request_nonce": nonce,
        "iteration_count": 0,
    }


class TravelOrchestrator:
    def __init__(self):
        self.app = app

    async def chat(
        self,
        user_message: str,
        history: list[dict[str, str]],
        user_prefs: dict[str, Any] | None = None,
        learned_context: str | None = None,
    ) -> tuple[str, list[dict[str, str]], list[dict[str, Any]], dict[str, Any], bool, bool, bool]:
        """Standard invocation of the LangGraph workflow."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {
            "messages": bound_history(updated_history),
            "iteration_count": 0,
            "seeded_prefs": user_prefs,
            "learned_context": learned_context,
            "request_nonce": random.randint(0, 1_000_000),
        }

        try:
            result = await self.app.ainvoke(inputs, config={"recursion_limit": 25})

            messages = result.get("messages", [])
            last_content = messages[-1]["content"] if messages else "I'm not sure what to say."
            updated_history.append({"role": "model", "content": last_content})

            final_response = last_content
            if result.get("draft_itinerary"):
                critique = result.get("critique", {})
                if critique.get("approved"):
                    final_response = result["draft_itinerary"]
                else:
                    final_response = f"{result['draft_itinerary']}\n\n*Reviewer Note: {critique.get('feedback')}*"

            is_itinerary = bool(result.get("draft_itinerary"))
            return (
                final_response,
                updated_history,
                result.get("debug_logs", []),
                result.get("user_details", {}),
                is_itinerary,
                result.get("is_edit", False),
                bool(result.get("regenerate", False)),
            )

        except Exception as e:
            return f"System Error: {str(e)}", history, [], {}, False, False, False

    async def _stream_graph_events(self, graph, inputs: dict, variant: str | None, capture: dict):
        """Stream one graph run: yield cleaned status/token/reset events (tagged with `variant`) and
        fold everything the caller needs later into `capture` (produced_itinerary, user_details,
        season_suggestion, the logistics-enriched research pools, the draft, geo, and edit metadata).
        The end event is built by the caller, which alone knows whether another variant follows."""
        pending = ""
        async for event in graph.astream_events(inputs, version="v2", config={"recursion_limit": 25}):
            kind = event["event"]

            # LangGraph surfaces node boundaries as on_chain_start with the node name.
            if kind == "on_chain_start":
                node_name = event.get("name")
                if node_name == "compiler":
                    capture["produced_itinerary"] = True
                msg = _STATUS_MAP.get(node_name)
                if msg:
                    yield _tag_event({"type": "status", "content": msg, "node": node_name}, variant)

            elif kind == "on_chain_end" and event.get("name") == "interviewer":
                # The interviewer finalizes user_details (when it starts planning) and, for an edit,
                # flags is_edit and carries the change instruction. Capturing these lets the trip save
                # with the real destination, the edit path update the existing trip instead of
                # inserting, and (via season_suggestion + research pools) variant B reuse A's research.
                out = event["data"].get("output")
                if isinstance(out, dict):
                    if out.get("user_details"):
                        capture["user_details"] = out["user_details"]
                    if out.get("season_suggestion") is not None:
                        capture["season_suggestion"] = out["season_suggestion"]
                    if out.get("is_edit"):
                        capture["is_edit"] = True
                    if out.get("regenerate"):
                        capture["regenerate"] = True
                    if out.get("edit_instruction"):
                        capture["edit_summary"] = out["edit_instruction"]

            elif kind == "on_chain_end" and event.get("name") == "logistics":
                # The logistics output carries the geocoded research pools; capture them so variant B
                # recompiles from the same data instead of paying for a second research pass.
                out = event["data"].get("output")
                if isinstance(out, dict):
                    for key in ("food_data", "activity_data", "hotel_data"):
                        if out.get(key) is not None:
                            capture[key] = out[key]

            elif kind == "on_chain_end" and event.get("name") == "compiler":
                # The compiler emits the structured map payload (per-day coords) on a fresh plan; an
                # in-place edit returns none, so the client keeps the map it already has. An edit also
                # returns a short "what changed" summary, which replaces the raw-instruction fallback.
                # The draft text is captured as variant B's avoid-this reference.
                out = event["data"].get("output")
                if isinstance(out, dict):
                    if out.get("draft_itinerary"):
                        capture["draft"] = out["draft_itinerary"]
                    if out.get("itinerary_geo"):
                        capture["geo"] = out["itinerary_geo"]
                    if out.get("edit_summary"):
                        capture["edit_summary"] = out["edit_summary"]

            elif kind == "on_chat_model_stream":
                if "final_itinerary" in event.get("tags", []):
                    content = event["data"]["chunk"].content
                    if not content:
                        continue
                    # Strip the PLANNING_STARTED trigger from the stream without
                    # breaking the typing effect: drop complete markers, and hold
                    # back only a tail that could be the marker's start.
                    pending += content
                    pending = pending.replace(_MARKER, "")
                    hold = 0
                    for k in range(min(len(_MARKER) - 1, len(pending)), 0, -1):
                        if pending.endswith(_MARKER[:k]):
                            hold = k
                            break
                    emit = pending[: len(pending) - hold]
                    pending = pending[len(pending) - hold :]
                    if emit:
                        yield _tag_event({"type": "token", "content": emit}, variant)

            elif kind == "on_custom_event":
                if event["name"] == "reset_itinerary":
                    yield _tag_event({"type": "reset", "content": event["data"].get("message")}, variant)
                elif event["name"] == "status_update":
                    yield _tag_event({"type": "status", "content": event["data"].get("message")}, variant)

        leftover = pending.replace(_MARKER, "")
        if leftover:
            yield _tag_event({"type": "token", "content": leftover}, variant)

    async def stream_chat(
        self,
        user_message: str,
        history: list[dict[str, str]],
        user_prefs: dict[str, Any] | None = None,
        compare: bool = False,
        learned_context: str | None = None,
    ):
        """Asynchronous generator that yields clean dict events from LangGraph. With compare=True a
        freshly produced plan streams two diversified variants (A then B): every event is tagged with
        its variant and each variant is closed by its own end event, with is_final marking the last."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {
            "messages": bound_history(updated_history),
            "iteration_count": 0,
            "seeded_prefs": user_prefs,
            "learned_context": learned_context,
            "request_nonce": random.randint(0, 1_000_000),
        }

        variant_tag = "A" if compare else None
        capture_a: dict[str, Any] = {}
        async for event in self._stream_graph_events(self.app, inputs, variant_tag, capture_a):
            yield event

        produced_a = capture_a.get("produced_itinerary", False)
        is_edit_a = capture_a.get("is_edit", False)
        do_compare = _should_compare(compare, produced_a, is_edit_a)

        yield _tag_event(
            {
                "type": "end",
                "is_itinerary": produced_a,
                "user_details": capture_a.get("user_details", {}),
                "is_edit": is_edit_a,
                "regenerate": capture_a.get("regenerate", False),
                "edit_summary": capture_a.get("edit_summary", ""),
                "geo": capture_a.get("geo"),
                "is_final": not do_compare,
            },
            variant_tag,
        )

        if not do_compare:
            return

        # Variant B: recompile A's research with the regenerate diversification, one extra compile.
        capture_b: dict[str, Any] = {}
        b_inputs = _variant_b_inputs(capture_a, random.randint(0, 1_000_000))
        async for event in self._stream_graph_events(variant_app, b_inputs, "B", capture_b):
            yield event

        yield _tag_event(
            {
                "type": "end",
                "is_itinerary": True,
                "user_details": capture_a.get("user_details", {}),
                "is_edit": False,
                "edit_summary": "",
                "geo": capture_b.get("geo"),
                "is_final": True,
            },
            "B",
        )
