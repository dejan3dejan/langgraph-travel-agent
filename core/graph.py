import time
import json
from typing import Dict, Any, List

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from .state import AgentState
from .schemas import UserPreferences, RestaurantList, ActivityList, HotelList, ItineraryCritique
from .llm import get_llm_for_role

# --- HELPER ---
def log_usage(node_name: str, start_time: float, response: Any = None) -> Dict:
    """Creates a log entry for usage metrics."""
    duration = time.time() - start_time
    tokens = 0
    
    # Try to extract tokens if available
    try:
        if response and hasattr(response, "usage_metadata"):
            tokens = response.usage_metadata.get("total_tokens", 0)
        elif response and hasattr(response, "response_metadata"):
             # Adapting to different LangChain versions
             tokens = response.response_metadata.get("token_usage", {}).get("total_tokens", 0)
    except:
        pass
        
    return {
        "node": node_name,
        "latency_sec": round(duration, 2),
        "total_tokens": tokens,
        "timestamp": time.strftime("%H:%M:%S")
    }

# --- NODES ---

def interviewer_node(state: AgentState) -> Dict:
    t0 = time.time()
    messages = state.get("messages", [])
    
    system_prompt = """
    You are 'Atlas', a charming and intelligent Travel Consultant.
    GOAL: Gather [Destination, Duration, Budget, Interests] to start planning.

    PHASE 1: DEEP SCAN
    Review the ENTIRE conversation history. 
    - Did the user mention their Budget 3 messages ago? -> IT COUNTS.
    - Did the user say "Surprise me"? -> That means Interests = "General Sightseeing".
    
    PHASE 2: VERIFICATION
    Check if we have the minimum requirements:
    1. Destination (City, State, or Country is OK)
    2. Duration (How many days?)
    3. Budget (Amount or Level)

    PHASE 3: ACTION
    - If ALL 3 (Dest, Duration, Budget) are found -> OUTPUT ONLY: "PLANNING_STARTED"
    - If ANY are missing -> Ask for them politely and charmingly.
    
    CRITICAL RULES:
    - NEVER say "I cannot do this". You are an expert planner.
    - If Destination is a region (e.g., "Texas"), ACCEPT IT. Do not ask for specific cities.
    - ONLY output "PLANNING_STARTED" when you have the data.
    """
    
    lc_messages = [SystemMessage(content=system_prompt)]
    for m in messages:
        if m["role"] == "user": lc_messages.append(HumanMessage(content=m["content"]))
        else: lc_messages.append(AIMessage(content=m["content"]))
    # Get models for role
    chat_llm = get_llm_for_role("interviewer")
    extraction_llm = get_llm_for_role("extraction")

    response = chat_llm.invoke(lc_messages)
    content = response.content
    
    log = log_usage("interviewer", t0, response)
    
    if "PLANNING_STARTED" in content.upper():
        # Structured Extraction
        structured_llm = extraction_llm.with_structured_output(UserPreferences)
        
        prompt = """
        Analyze the conversation and extract user preferences.
        If the user hasn't specified a start location, set it to 'the user's current location'.
        If the user only cares about specific things (like just food or just hotels), list them in 'focus'.
        """
        
        extraction_msg = [
            SystemMessage(content=prompt),
            HumanMessage(content=str(messages))
        ]
        try:
            user_prefs = structured_llm.invoke(extraction_msg)
            user_details = user_prefs.model_dump()
            
            # Auto-fill interests if missing
            if not user_details.get("interests") or user_details.get("interests").lower() == "unknown":
                user_details["interests"] = "General Sightseeing"
            
            # Final safety check for start_location
            if not user_details.get("start_location"):
                user_details["start_location"] = "the user's current location"
                
        except Exception as e:
            print(f"Extraction Failed: {e}")
            user_details = {
                "destination": "Paris", 
                "start_location": "the user's current location", 
                "budget": "Medium", 
                "duration": "3 days", 
                "interests": "General",
                "focus": []
            }

        # --- CONTEXT RESET LOGIC ---
        old_details = state.get("user_details", {})
        old_dest = old_details.get("destination")
        new_dest = user_details.get("destination")
        
        if old_dest and old_dest != new_dest:
            print(f"   [Context] Destination changed from {old_dest} to {new_dest}. Resetting research data.")
            return {
                "user_details": user_details,
                "food_data": None,
                "activity_data": None,
                "hotel_data": None,
                "draft_itinerary": None,
                "iteration_count": 0,
                "next_node": "research",
                "messages": [{"role": "model", "content": f"Changing plans to {new_dest}! Let me research that for you..."}]
            }
            
        return {
            "messages": [{"role": "model", "content": "Great! I'm researching your trip now..."}],
            "user_details": user_details,
            "next_node": "research",
            "debug_logs": [log]
        }

    return {
        "messages": [{"role": "model", "content": content}],
        "next_node": "interviewer",
        "debug_logs": [log]
    }

# --- PARALLEL RESEARCH NODES ---

def research_food_node(state: AgentState) -> Dict:
    t0 = time.time()
    details = state.get("user_details", {})
    dest = details.get("destination")
    constraints = details.get('constraints', '')
    print(f"   [Food Agent] Searching restaurants in {dest}...")
    
    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    extraction_llm = get_llm_for_role("extraction")
    
    # STEP 1: Grounded search (plain text) - koristi Google Search
    search_prompt = f"""
    Use Google Search to find 3 REAL, currently operating restaurants in {dest}.
    
    For each restaurant you MUST provide:
    - Exact name
    - Full street address (e.g. "123 Main Street, {dest}")
    - Neighborhood or district name
    - Official website URL (if available)
    - Type of cuisine  
    - Price level ($, $$, $$$, $$$$)
    - Google rating (e.g., 4.5)
    - Why it fits: {details.get('interests')} with budget {details.get('budget')}
    
    Constraints to respect: {constraints}
    
    IMPORTANT: Only include restaurants you found via search. Do not make up names or addresses.
    """
    
    try:
        # Step 1: Get grounded results as plain text
        grounded_response = research_llm.invoke([HumanMessage(content=search_prompt)])
        grounded_text = grounded_response.content
        
        # STEP 2: Parse into structure using extraction_llm (no grounding needed)
        extraction_prompt = f"""
        Extract restaurant information from this text into structured format.
        Make sure to extract the full address and website if mentioned.
        
        {grounded_text}
        """
        structured_extractor = extraction_llm.with_structured_output(RestaurantList)
        result = structured_extractor.invoke([HumanMessage(content=extraction_prompt)])
        data = result.model_dump_json()
        
        log = log_usage("research_food", t0, grounded_response)
    except Exception as e:
        print(f"   [Food Agent] Error: {e}")
        data = "[]"
        log = log_usage("research_food", t0)
        
    return {"food_data": data, "debug_logs": [log]}

def research_activity_node(state: AgentState) -> Dict:
    t0 = time.time()
    details = state.get("user_details", {})
    dest = details.get("destination")
    constraints = details.get('constraints', '')
    print(f"   [Activity Agent] Searching activities in {dest}...")
    
    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    extraction_llm = get_llm_for_role("extraction")
    
    # STEP 1: Grounded search (plain text)
    search_prompt = f"""
    Use Google Search to find 3 REAL activities/attractions in {dest}.
    
    For each activity you MUST provide:
    - Exact name
    - Full street address or specific location (e.g. "Old Town Square, {dest}")
    - Neighborhood or district name
    - Official website or booking URL (if available)
    - Type (Museum, Park, Tour, etc.)
    - Estimated duration to spend there
    - Brief description
    
    Trip duration: {details.get('duration')}
    Constraints to respect: {constraints}
    
    IMPORTANT: Only include activities you found via search. Do not make up names or addresses.
    """
    
    try:
        # Step 1: Get grounded results
        grounded_response = research_llm.invoke([HumanMessage(content=search_prompt)])
        grounded_text = grounded_response.content
        
        # STEP 2: Parse into structure
        extraction_prompt = f"""
        Extract activity information from this text into structured format.
        Make sure to extract the full address and website if mentioned.
        
        {grounded_text}
        """
        structured_extractor = extraction_llm.with_structured_output(ActivityList)
        result = structured_extractor.invoke([HumanMessage(content=extraction_prompt)])
        data = result.model_dump_json()
        
        log = log_usage("research_activity", t0, grounded_response)
    except Exception as e:
        print(f"   [Activity Agent] Error: {e}")
        data = "[]"
        log = log_usage("research_activity", t0)
        
    return {"activity_data": data, "debug_logs": [log]}

def research_hotel_node(state: AgentState) -> Dict:
    t0 = time.time()
    details = state.get("user_details", {})
    dest = details.get("destination")
    constraints = details.get('constraints', '')
    print(f"   [Hotel Agent] Searching hotels in {dest}...")
    
    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    extraction_llm = get_llm_for_role("extraction")
    
    # STEP 1: Grounded search (plain text)
    search_prompt = f"""
    Use Google Search to find 3 REAL hotels in {dest}.
    
    For each hotel you MUST provide:
    - Exact hotel name
    - Full street address (e.g. "123 Main Street, {dest}")
    - Neighborhood or district name
    - Official website or booking URL (if available)
    - Price range per night
    - Key advantages (pros)
    
    Budget level: {details.get('budget')}
    Constraints to respect: {constraints}
    
    IMPORTANT: Only include hotels you found via search. Do not make up names or addresses.
    """
    
    try:
        # Step 1: Get grounded results
        grounded_response = research_llm.invoke([HumanMessage(content=search_prompt)])
        grounded_text = grounded_response.content
        
        # STEP 2: Parse into structure
        extraction_prompt = f"""
        Extract hotel information from this text into structured format.
        Make sure to extract the full address and website if mentioned.
        
        {grounded_text}
        """
        structured_extractor = extraction_llm.with_structured_output(HotelList)
        result = structured_extractor.invoke([HumanMessage(content=extraction_prompt)])
        data = result.model_dump_json()
        
        log = log_usage("research_hotel", t0, grounded_response)
    except Exception as e:
        print(f"   [Hotel Agent] Error: {e}")
        data = "[]"
        log = log_usage("research_hotel", t0)
        
    return {"hotel_data": data, "debug_logs": [log]}

# --- COMPILER & CRITIC ---

def compiler_node(state: AgentState) -> Dict:
    t0 = time.time()
    print("   [Compiler] Writing draft...")
    user_details = state.get("user_details", {})
    
    chat_llm = get_llm_for_role("compiler")
    
    prompt = f"""
The traveler is departing from {user_details.get('start_location', 'their home location')} and heading to {user_details.get('destination')}.

CRITICAL: You MUST include a clear "Getting There" or "Arrival & Transport" section explaining realistic travel options from the starting location (flights, train, bus, driving – no hallucinations).

Duration: {user_details.get('duration')}
Budget: {user_details.get('budget')}
Interests: {user_details.get('interests')}

Available Data:
- Restaurants: {state.get('food_data')}
- Activities: {state.get('activity_data')}
- Hotels: {state.get('hotel_data')}

Full user request for context: {json.dumps(user_details, ensure_ascii=False)}

TASK: Create a beautiful, practical Markdown itinerary with the following structure:

# {user_details.get('duration', 'Your')} Trip from {user_details.get('start_location', 'Home')} to {user_details.get('destination')}

## Overview
## Recommended Accommodation
## Day-by-Day Itinerary
### Day 1: [Theme]
...
## Getting There & Logistics
(Include transport from {user_details.get('start_location')} – this section is REQUIRED)
## Tips & Final Notes

Output ONLY the Markdown itinerary. No additional text.
"""
    response = chat_llm.invoke([SystemMessage(content="You are a Travel Editor."), HumanMessage(content=prompt)])
    draft = response.content
    log = log_usage("compiler", t0, response)
    
    return {
        "draft_itinerary": draft,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "next_node": "critic",
        "debug_logs": [log]
    }

def critic_node(state: AgentState) -> Dict:
    t0 = time.time()
    draft = state.get("draft_itinerary", "")
    user_details = state.get("user_details", {})
    print("   [Critic] Reviewing draft...")
    
    extraction_llm = get_llm_for_role("extraction")
    structured_critic = extraction_llm.with_structured_output(ItineraryCritique)
    
    prompt = f"""
    Critique this itinerary for a trip to {user_details.get('destination')}.
    
    CHECKLIST:
    1. Logic Gaps: Are there transport options from {user_details.get('start_location')}?
    2. Data Quality: Are the restaurants and activities specific and real (not generic)?
    3. User Needs: Does it respect the budget ({user_details.get('budget')}) and interests ({user_details.get('interests')})?
    
    If data for food, activities, or hotels is missing, poor quality, or irrelevant, list them in 'missing_data'.
    If 'missing_data' is NOT empty, 'approved' MUST be False.

    ITINERARY:
    {draft}
    """
    
    try:
        result = structured_critic.invoke([HumanMessage(content=prompt)])
        critique = result.model_dump()
        log = log_usage("critic", t0, result)
        
        # Determine next step
        if critique.get("approved"):
            next_node = "approved"
        elif critique.get("missing_data"):
            next_node = "research"
        else:
            next_node = "compiler" # Just a rewrite needed
            
    except Exception as e:
        print(f"   [Critic] Error: {e}")
        critique = {"approved": True, "feedback": "Auto Approved (Critic Error)", "score": 10, "missing_data": []}
        next_node = "approved"
        log = log_usage("critic", t0)
        
    return {
        "critique": critique,
        "next_node": next_node,
        "debug_logs": [log]
    }

# --- GRAPH DEFINITION ---

workflow = StateGraph(AgentState)

workflow.add_node("interviewer", interviewer_node)
workflow.add_node("research_food", research_food_node)
workflow.add_node("research_activity", research_activity_node)
workflow.add_node("research_hotel", research_hotel_node)
workflow.add_node("compiler", compiler_node)
workflow.add_node("critic", critic_node)

workflow.set_entry_point("interviewer")

def router(state: AgentState):
    next_node = state.get("next_node")
    
    # CRITICAL FIX: Loop Breaker - "Good Enough" Logic
    if state.get("iteration_count", 0) >= 3:
        return END 

    if next_node == "research":
        critique = state.get("critique", {})
        missing = critique.get("missing_data", [])
        user_details = state.get("user_details", {})
        focus = user_details.get("focus", [])
        
        # 1. If Critic identified missing data, prioritize that
        if missing:
            targets = []
            if "food" in missing: targets.append("research_food")
            if "activities" in missing: targets.append("research_activity")
            if "hotels" in missing: targets.append("research_hotel")
            return targets
        
        # 2. If it's the initial run and User has specific focus
        if focus:
            targets = []
            if "food" in focus: targets.append("research_food")
            if "activities" in focus: targets.append("research_activity")
            if "hotels" in focus: targets.append("research_hotel")
            if targets: return targets

        # 3. Default: run all
        return ["research_food", "research_activity", "research_hotel"]

    if next_node == "interviewer": return END
    if next_node == "approved": return END
    if next_node == "critic": return "critic"
    if next_node == "compiler": return "compiler" 
    
    return END

workflow.add_conditional_edges("interviewer", router)
workflow.add_edge("research_food", "compiler")
workflow.add_edge("research_activity", "compiler")
workflow.add_edge("research_hotel", "compiler")
workflow.add_conditional_edges("compiler", router)
workflow.add_conditional_edges("critic", router)

app = workflow.compile()
