from typing import Any

from .graph import app


class TravelOrchestrator:
    def __init__(self):
        self.app = app

    async def chat(
        self, user_message: str, history: list[dict[str, str]]
    ) -> tuple[str, list[dict[str, str]], list[dict[str, Any]], dict[str, Any]]:
        """Standard invocation of the LangGraph workflow."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {"messages": updated_history, "iteration_count": 0}

        try:
            result = await self.app.ainvoke(inputs, config={"recursion_limit": 100})

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

            return final_response, updated_history, result.get("debug_logs", []), result.get("user_details", {})

        except Exception as e:
            return f"System Error: {str(e)}", history, [], {}

    async def stream_chat(self, user_message: str, history: list[dict[str, str]]):
        """Asynchronous generator that yields clean dict events from LangGraph."""
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})

        inputs = {"messages": updated_history, "iteration_count": 0}

        async for event in self.app.astream_events(inputs, version="v2", config={"recursion_limit": 100}):
            kind = event["event"]

            if kind == "on_node_start":
                node_name = event["name"]
                if node_name == "compiler":
                    yield {"type": "reset", "content": "Refining the itinerary based on feedback..."}

                status_map = {
                    "interviewer": "Atlas is thinking...",
                    "research_food": "🔍 Searching for the best restaurants...",
                    "research_activity": "🏛 Researching activities...",
                    "research_hotel": "🏨 Finding accommodations...",
                    "compiler": "✍️ Compiling your itinerary...",
                }
                msg = status_map.get(node_name)
                if msg:
                    yield {"type": "status", "content": msg, "node": node_name}

            elif kind == "on_chat_model_stream":
                if "final_itinerary" in event.get("tags", []):
                    content = event["data"]["chunk"].content
                    if content:
                        yield {"type": "token", "content": content}

            elif kind == "on_custom_event":
                if event["name"] == "reset_itinerary":
                    yield {"type": "reset", "content": event["data"].get("message")}
                elif event["name"] == "status_update":
                    yield {"type": "status", "content": event["data"].get("message")}

        yield {"type": "end"}
