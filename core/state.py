from typing import TypedDict, List, Dict, Optional, Any, Annotated
import operator

class AgentState(TypedDict):
    """
    The memory of the agent workflow.
    """
    # Chat history (list of role/content dicts)
    messages: Annotated[List[Dict[str, str]], operator.add] 
    
    # Structured Data
    user_details: Optional[Dict[str, Any]] # {destination, budget, etc.}
    
    # Parallel Research Data
    food_data: Optional[str]
    activity_data: Optional[str]
    hotel_data: Optional[str]
    
    # Plan State
    draft_itinerary: Optional[str] # The markdown draft
    critique: Optional[Dict[str, Any]] # The Judge's feedback
    
    # Control Flow
    iteration_count: int # To prevent infinite loops
    next_node: str # Where to go next

    # Metrics & Debugging
    # Stores logs from each agent: {"agent": "food", "latency": 0.5, "tokens": 150}
    debug_logs: Annotated[List[Dict[str, Any]], operator.add]