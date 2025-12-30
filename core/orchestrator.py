from typing import List, Dict, Tuple, Any
from .graph import app

class TravelOrchestrator:
    def __init__(self):
        self.app = app

    def chat(self, user_message: str, history: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, str]], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Invokes the LangGraph workflow.
        Returns: (response_text, updated_history, metrics_logs, user_details)
        """
        updated_history = list(history)
        updated_history.append({"role": "user", "content": user_message})
        
        inputs = {
            "messages": updated_history,
            "iteration_count": 0
        }
        
        try:
            result = self.app.invoke(inputs, config={"recursion_limit": 100})
            
            messages = result.get("messages", [])
            if messages:
                last_msg_obj = messages[-1]
                if isinstance(last_msg_obj, dict):
                    last_content = last_msg_obj.get("content", "")
                else:
                    last_content = last_msg_obj.content
            else:
                last_content = "I'm not sure what to say."

            updated_history.append({"role": "model", "content": last_content})

            final_response = last_content
            if result.get("draft_itinerary"):
                critique = result.get("critique", {})
                if critique.get("approved"):
                    final_response = result["draft_itinerary"]
                else:
                    final_response = f"{result['draft_itinerary']}\n\n*Reviewer Note: {critique.get('feedback')}*"
            
            logs = result.get("debug_logs", [])
            user_details = result.get("user_details", {})
            
            return final_response, updated_history, logs, user_details
            
        except Exception as e:
            return f"System Error: {str(e)}", history, [], {}
