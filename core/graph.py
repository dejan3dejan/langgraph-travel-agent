import time
import json
from typing import Dict, Any, List

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from .state import AgentState
from .schemas import UserPreferences, RestaurantList, ActivityList, HotelList, ItineraryCritique
from .llm import get_llm_for_role
from .logistics import logistics_agent
from .logger import get_logger

logger = get_logger(__name__)

# --- HELPER ---
def log_usage(node_name: str, start_time: float, response: Any = None) -> Dict:
    """Creates a log entry for usage metrics."""
    duration = time.time() - start_time
    tokens = 0
    
    # Try to extract tokens if available
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
            logger.error(f"Extraction Failed: {e}")
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
            logger.info(f"Destination changed from {old_dest} to {new_dest}. Resetting research data.")
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
    logger.info(f"Searching restaurants in {dest}...")
    
    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    extraction_llm = get_llm_for_role("extraction")
    
    search_prompt = f"""
    Use Google Search to find 3 REAL, currently operating restaurants in {dest}.
    
    STRICT REQUIREMENTS (Do NOT skip any):
    1. EXACT NAME: The official restaurant name as it appears on Google Maps.
    2. FULL STREET ADDRESS: Must include street number, street name, and city.
       - GOOD: "87 Borough High Street, London SE1 1NH"
       - BAD: "Near Tower Bridge" or "Shoreditch area"
    3. NEIGHBORHOOD: The district/area name (e.g., "Shoreditch", "Borough Market").
    4. WEBSITE: Official website URL. Write "N/A" if not found.
    5. CUISINE: Type of food (e.g., "British Pie & Mash", "Italian", "Street Food").
    6. PRICE LEVEL: $, $$, $$$, or $$$$.
    7. GOOGLE RATING: e.g., 4.5
    8. WHY IT FITS: How it matches {details.get('interests')} and {details.get('budget')} budget.
    
    Constraints to respect: {constraints}
    
    CRITICAL: If you cannot find a FULL STREET ADDRESS for a restaurant, DO NOT include it.
    Only return restaurants with verified, complete addresses.
    """
    
    try:
        grounded_response = research_llm.invoke([HumanMessage(content=search_prompt)])
        grounded_text = grounded_response.content
        
        extraction_prompt = f"""
        Extract restaurant information from this text into structured format.
        Make sure to extract the full address and website if mentioned.
        
        {grounded_text}
        """
        structured_extractor = extraction_llm.with_structured_output(RestaurantList)
        result = structured_extractor.invoke([HumanMessage(content=extraction_prompt)])
        data = result.items
        
        log = log_usage("research_food", t0, grounded_response)
    except Exception as e:
        logger.error(f"Food Agent Error: {e}")
        data = []
        log = log_usage("research_food", t0)
        
    return {"food_data": data, "debug_logs": [log]}

def research_activity_node(state: AgentState) -> Dict:
    t0 = time.time()
    details = state.get("user_details", {})
    dest = details.get("destination")
    constraints = details.get('constraints', '')
    logger.info(f"Searching activities in {dest}...")
    
    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    extraction_llm = get_llm_for_role("extraction")
    
    search_prompt = f"""
    Use Google Search to find 3 REAL activities/attractions in {dest}.
    
    STRICT REQUIREMENTS (Do NOT skip any):
    1. EXACT NAME: Official name as it appears on Google.
    2. FULL ADDRESS: Street address or well-known landmark location.
       - GOOD: "Tower of London, St Katharine's & Wapping, London EC3N 4AB"
       - BAD: "East London" or "City Center"
    3. NEIGHBORHOOD: District name (e.g., "City of London", "Westminster").
    4. WEBSITE: Official website or booking URL. Write "N/A" if not found.
    5. TYPE: Museum, Park, Historic Site, Tour, Market, etc.
    6. DURATION: How long to spend there (e.g., "2-3 hours").
    7. DESCRIPTION: 1-2 sentences about what makes it special.
    
    User interests: {details.get('interests')}
    Trip duration: {details.get('duration')}
    Constraints: {constraints}
    
    CRITICAL: Only include attractions with verifiable addresses. No vague locations.
    """
    
    try:
        grounded_response = research_llm.invoke([HumanMessage(content=search_prompt)])
        grounded_text = grounded_response.content
        
        extraction_prompt = f"""
        Extract activity information from this text into structured format.
        Make sure to extract the full address and website if mentioned.
        
        {grounded_text}
        """
        structured_extractor = extraction_llm.with_structured_output(ActivityList)
        result = structured_extractor.invoke([HumanMessage(content=extraction_prompt)])
        data = result.items
        
        log = log_usage("research_activity", t0, grounded_response)
    except Exception as e:
        logger.error(f"Activity Agent Error: {e}")
        data = []
        log = log_usage("research_activity", t0)
        
    return {"activity_data": data, "debug_logs": [log]}

def research_hotel_node(state: AgentState) -> Dict:
    t0 = time.time()
    details = state.get("user_details", {})
    dest = details.get("destination")
    constraints = details.get('constraints', '')
    logger.info(f"Searching hotels in {dest}...")
    
    research_llm = get_llm_for_role("research").bind_tools(tools=[{"google_search": {}}])
    extraction_llm = get_llm_for_role("extraction")
    
    search_prompt = f"""
    Use Google Search to find 3 REAL hotels in {dest}.
    
    STRICT REQUIREMENTS (Do NOT skip any):
    1. EXACT NAME: Official hotel name as listed on booking sites.
    2. FULL STREET ADDRESS: Must include street number and name.
       - GOOD: "22 Whitechapel High St, London E1 7PW"
       - BAD: "Central London" or "Near the station"
    3. NEIGHBORHOOD: District name (e.g., "Bloomsbury", "Covent Garden").
    4. WEBSITE: Official website or Booking.com link. Write "N/A" if not found.
    5. PRICE RANGE: Approximate price per night (e.g., "$120-180/night").
    6. PROS: 2-3 key advantages (location, amenities, value).
    
    Budget level: {details.get('budget')}
    Constraints: {constraints}
    
    CRITICAL: Only include hotels with verified, complete street addresses.
    """
    
    try:
        grounded_response = research_llm.invoke([HumanMessage(content=search_prompt)])
        grounded_text = grounded_response.content
        
        extraction_prompt = f"""
        Extract hotel information from this text into structured format.
        Make sure to extract the full address and website if mentioned.
        
        {grounded_text}
        """
        structured_extractor = extraction_llm.with_structured_output(HotelList)
        result = structured_extractor.invoke([HumanMessage(content=extraction_prompt)])
        data = result.items
        
        log = log_usage("research_hotel", t0, grounded_response)
    except Exception as e:
        logger.error(f"Hotel Agent Error: {e}")
        data = []
        log = log_usage("research_hotel", t0)
        
    return {"hotel_data": data, "debug_logs": [log]}

# --- COMPILER & CRITIC ---

def compiler_node(state: AgentState) -> Dict:
    t0 = time.time()
    logger.info("Writing itinerary draft...")
    user_details = state.get("user_details", {})
    
    # Pre-format data for the LLM
    food_data = state.get("food_data") or []
    activity_data = state.get("activity_data") or []
    hotel_data = state.get("hotel_data") or []
    logistics = state.get("logistics") or {}
    
    # Extract model data to dicts for JSON serialization
    food_json = json.dumps([f.model_dump() if hasattr(f, 'model_dump') else f for f in food_data], indent=2, ensure_ascii=False)
    activity_json = json.dumps([a.model_dump() if hasattr(a, 'model_dump') else a for a in activity_data], indent=2, ensure_ascii=False)
    hotel_json = json.dumps([h.model_dump() if hasattr(h, 'model_dump') else h for h in hotel_data], indent=2, ensure_ascii=False)
    logistics_json = json.dumps(logistics, indent=2, ensure_ascii=False)
    
    chat_llm = get_llm_for_role("compiler")
    
    prompt = f"""
You are writing a practical travel itinerary for a trip to {user_details.get('destination')}.

TRAVELER INFO:
- Departing from: {user_details.get('start_location', 'their home location')}
- Duration: {user_details.get('duration')}
- Budget: {user_details.get('budget')}
- Interests: {user_details.get('interests')}

AVAILABLE RESEARCH DATA:
- Restaurants: {food_json}
- Activities: {activity_json}
- Hotels: {hotel_json}

LOGISTICS & SPATIAL DATA (USE THIS!):
{logistics_json}

Each item above has a "zone" field that tells you how far it is from the hotel:
- "Near Hotel (<2km)" = Walking distance (10-20 min walk)
- "Remote (X.Xkm)" = Requires transport (tube/bus/taxi)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL RULES FOR THE ITINERARY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. GROUP BY PROXIMITY: Combine activities that are in the SAME ZONE into the same day/half-day.
   Example: If Tower of London and a restaurant are both "Remote (5.2km)", schedule them together.

2. ALWAYS MENTION DISTANCE: When you mention a place, add how far it is.
   - GOOD: "Walk to The British Museum (0.8km from hotel, ~10 min walk)"
   - BAD: "Visit The British Museum"

3. BE SPECIFIC: Use the exact names, addresses, and websites from the research data.
   - GOOD: "Dinner at Dishoom King's Cross (5 Stable St, London N1C 4AB) - Indian, $$"
   - BAD: "Find a nice Indian restaurant nearby"

4. TRANSPORT TIPS: For "Remote" locations, suggest specific transport.
   - Example: "Take the Central Line from Holborn to Tower Hill station (15 min)"

5. INCLUDE A "Getting There" SECTION: Realistic travel options from {user_details.get('start_location')}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OUTPUT FORMAT (Markdown):

# {user_details.get('duration', 'Your')} Trip to {user_details.get('destination')}

## Overview
(Brief summary + travel style based on budget)

## Recommended Accommodation
(Pick ONE hotel from the list, explain why)

## Day-by-Day Itinerary

    ### Day 1: [Theme based on zone/area]
    - **Morning:** [Activity Name] ([distance from hotel], [walk/transport tip])
    - **Lunch:** [Restaurant Name] ([address], [cuisine], [price])
    - **Afternoon:** [Activity Name]
    - **Evening:** [Dinner spot]
    
    [... Follow this structure for Day 2, Day 3, etc. ...]

## Getting There & Transport
(How to get from {user_details.get('start_location')} to {user_details.get('destination')})

## Tips & Budget Notes

Output ONLY the Markdown itinerary. No preamble or commentary.
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
    logger.info("Reviewing itinerary draft...")
    
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
        logger.error(f"Critic Error: {e}")
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
workflow.add_node("logistics", logistics_agent)
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
workflow.add_edge("research_food", "logistics")
workflow.add_edge("research_activity", "logistics")
workflow.add_edge("research_hotel", "logistics")
workflow.add_edge("logistics", "compiler")
workflow.add_conditional_edges("compiler", router)
workflow.add_conditional_edges("critic", router)

app = workflow.compile()
