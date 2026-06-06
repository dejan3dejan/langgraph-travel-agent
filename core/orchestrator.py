from typing import Any

from .graph import app


class TravelOrchestrator:
    def __init__(self):
        self.app = app

    async def chat(
        self, user_message: str, history: list[dict[str, str]]
    ) -> tuple[str, list[dict[str, str]], list[dict[str, Any]], dict[str, Any], bool]:
        """Standard invocation of the LangGraph workflow."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {"messages": updated_history, "iteration_count": 0}

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
            )

        except Exception as e:
            return f"System Error: {str(e)}", history, [], {}, False

    async def stream_chat(self, user_message: str, history: list[dict[str, str]]):
        """Asynchronous generator that yields clean dict events from LangGraph."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {"messages": updated_history, "iteration_count": 0}

        produced_itinerary = False
        marker = "PLANNING_STARTED"  # interviewer trigger token; must never reach the user
        pending = ""
        status_map = {
            "interviewer": "Atlas is thinking...",
            "research_food": "🔍 Searching for the best restaurants...",
            "research_activity": "🏛 Researching activities...",
            "research_hotel": "🏨 Finding accommodations...",
            "compiler": "✍️ Compiling your itinerary...",
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

        yield {"type": "end", "is_itinerary": produced_itinerary}
