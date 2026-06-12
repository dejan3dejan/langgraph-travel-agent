from typing import Any

from .graph import app
from .history import bound_history


class TravelOrchestrator:
    def __init__(self):
        self.app = app

    async def chat(
        self, user_message: str, history: list[dict[str, str]], user_prefs: dict[str, Any] | None = None
    ) -> tuple[str, list[dict[str, str]], list[dict[str, Any]], dict[str, Any], bool, bool]:
        """Standard invocation of the LangGraph workflow."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {"messages": bound_history(updated_history), "iteration_count": 0, "seeded_prefs": user_prefs}

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
            )

        except Exception as e:
            return f"System Error: {str(e)}", history, [], {}, False, False

    async def stream_chat(
        self, user_message: str, history: list[dict[str, str]], user_prefs: dict[str, Any] | None = None
    ):
        """Asynchronous generator that yields clean dict events from LangGraph."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {"messages": bound_history(updated_history), "iteration_count": 0, "seeded_prefs": user_prefs}

        produced_itinerary = False
        captured_user_details = {}
        captured_is_edit = False
        captured_edit_summary = ""
        marker = "PLANNING_STARTED"  # interviewer trigger token; must never reach the user
        pending = ""
        status_map = {
            "interviewer": "Atlas is thinking...",
            "research_food": "🔍 Searching for the best restaurants...",
            "research_activity": "🏛 Researching activities...",
            "research_hotel": "🏨 Finding accommodations...",
            "logistics": "🗺️ Mapping the route...",
            "compiler": "✍️ Compiling your itinerary...",
            "critic": "🔎 Reviewing the plan...",
        }
        async for event in self.app.astream_events(inputs, version="v2", config={"recursion_limit": 25}):
            kind = event["event"]

            # LangGraph surfaces node boundaries as on_chain_start with the node name.
            if kind == "on_chain_start":
                node_name = event.get("name")
                if node_name == "compiler":
                    produced_itinerary = True
                msg = status_map.get(node_name)
                if msg:
                    yield {"type": "status", "content": msg, "node": node_name}

            elif kind == "on_chain_end" and event.get("name") == "interviewer":
                # The interviewer finalizes user_details (when it starts planning) and, for an edit,
                # flags is_edit and carries the change instruction. Capturing all three lets the trip
                # save with the real destination, the edit path update the existing trip instead of
                # inserting, and the client show what changed.
                out = event["data"].get("output")
                if isinstance(out, dict):
                    if out.get("user_details"):
                        captured_user_details = out["user_details"]
                    if out.get("is_edit"):
                        captured_is_edit = True
                    if out.get("edit_instruction"):
                        captured_edit_summary = out["edit_instruction"]

            elif kind == "on_chat_model_stream":
                if "final_itinerary" in event.get("tags", []):
                    content = event["data"]["chunk"].content
                    if not content:
                        continue
                    # Strip the PLANNING_STARTED trigger from the stream without
                    # breaking the typing effect: drop complete markers, and hold
                    # back only a tail that could be the marker's start.
                    pending += content
                    pending = pending.replace(marker, "")
                    hold = 0
                    for k in range(min(len(marker) - 1, len(pending)), 0, -1):
                        if pending.endswith(marker[:k]):
                            hold = k
                            break
                    emit = pending[: len(pending) - hold]
                    pending = pending[len(pending) - hold :]
                    if emit:
                        yield {"type": "token", "content": emit}

            elif kind == "on_custom_event":
                if event["name"] == "reset_itinerary":
                    yield {"type": "reset", "content": event["data"].get("message")}
                elif event["name"] == "status_update":
                    yield {"type": "status", "content": event["data"].get("message")}

        leftover = pending.replace(marker, "")
        if leftover:
            yield {"type": "token", "content": leftover}

        yield {
            "type": "end",
            "is_itinerary": produced_itinerary,
            "user_details": captured_user_details,
            "is_edit": captured_is_edit,
            "edit_summary": captured_edit_summary,
        }
