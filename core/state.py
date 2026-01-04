from typing import TypedDict, List, Dict, Optional, Any, Annotated
import operator
from .schemas import Restaurant, Activity, Hotel

class AgentState(TypedDict):
    """
    The memory of the agent workflow.
    """
    # Chat history (list of role/content dicts)
    messages: Annotated[List[Dict[str, str]], operator.add] 
    
    # Structured Data
    user_details: Optional[Dict[str, Any]] # {destination, budget, etc.}
    
    # Parallel Research Data (Will be enriched by Logistics Agent)
    food_data: Optional[List[Restaurant]]
    activity_data: Optional[List[Activity]]
    hotel_data: Optional[List[Hotel]]
    
    # Logistics Hub - Global map and calculations
    # Stores clusters, distance matrices, and transport suggestions
    logistics: Optional[Dict[str, Any]] 
    
    # Plan State
    draft_itinerary: Optional[str] # The markdown draft
    critique: Optional[Dict[str, Any]] # The Judge's feedback
    
    # Control Flow
    iteration_count: int # To prevent infinite loops in compiler/critic
    interview_count: int # To prevent infinite loops in interviewer
    next_node: str # Where to go next

    # Metrics & Debugging
    debug_logs: Annotated[List[Dict[str, Any]], operator.add]
