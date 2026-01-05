import time
import json
from typing import Dict, Any, List

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.callbacks import adispatch_custom_event

from .state import AgentState
from .schemas import UserPreferences, RestaurantList, ActivityList, HotelList, ItineraryCritique
from .llm import get_llm_for_role, get_llm_with_tools, USE_REACT_AGENT
from .logistics import logistics_agent
from .tools import group_places_by_zone, optimize_day_route, TRAVEL_TOOLS
from .logger import get_logger

logger = get_logger(__name__)

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

async def interviewer_node(state: AgentState) -> Dict:
    t0 = time.time()
    messages = state.get("messages", [])
    interview_count = state.get("interview_count", 0) + 1
    
    MAX_INTERVIEW_ITERATIONS = 4  # Force extraction after this many attempts
    
    system_prompt = """
    You are 'Atlas', a charming and intelligent Travel Consultant.
    GOAL: Gather [Destination, Duration, Budget, Interests] to start planning.

    PHASE 1: DEEP SCAN
    Review the ENTIRE conversation history. 
    - Did the user mention their Budget 3 messages ago? -> IT COUNTS.
    - Did the user say "Surprise me"? -> That means Interests = "General Sightseeing".
    - Did the user mention a region like "Wisconsin" or "Texas"? -> ACCEPT IT as destination.
    - Did the user mention dates like "March 13th to March 17th"? -> Calculate duration from dates.
    
    PHASE 2: SMART DEFAULTS
    If some info is missing but you have enough context, USE SMART DEFAULTS:
    - No budget mentioned but trip details given? -> Assume "Medium budget"
    - No duration but dates given? -> Calculate from dates
    - No specific interests? -> Default to "General Sightseeing"
    
    PHASE 3: VERIFICATION
    Check if we have the MINIMUM requirements:
    1. Destination (City, State, Region, or Country - ANY is OK!)
    2. Duration (Days OR date range)
    3. Budget (Amount, Level, OR assume Medium if trip is detailed)

    PHASE 4: ACTION
    - If you have Destination + Duration (budget can be assumed) -> OUTPUT ONLY: "PLANNING_STARTED"
    - If ONLY destination is truly missing -> Ask for it politely.
    
    CRITICAL RULES:
    - NEVER say "I cannot do this". You are an expert planner.
    - If Destination is a region (e.g., "Texas", "Wisconsin"), ACCEPT IT. Do not ask for specific cities.
    - Be AGGRESSIVE about starting - users want plans, not interviews!
    - If you have destination and ANY hint of duration -> START PLANNING.
    """
    
    lc_messages = [SystemMessage(content=system_prompt)]
    for m in messages:
        if m["role"] == "user": lc_messages.append(HumanMessage(content=m["content"]))
        else: lc_messages.append(AIMessage(content=m["content"]))
    
    # Get models for role
    chat_llm = get_llm_for_role("interviewer")
    extraction_llm = get_llm_for_role("extraction")
    
    # Check if we should force extraction due to max iterations
    force_extraction = interview_count >= MAX_INTERVIEW_ITERATIONS
    
    if force_extraction:
        logger.warning(f"Interviewer hit max iterations ({MAX_INTERVIEW_ITERATIONS}). Forcing extraction...")
        content = "PLANNING_STARTED"  # Force it
    else:
        response = await chat_llm.ainvoke(
            lc_messages,
            config={"tags": ["final_itinerary"]}
        )
        content = response.content
    
    log = log_usage("interviewer", t0, response if not force_extraction else None)
    
    if "PLANNING_STARTED" in content.upper() or force_extraction:
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
            user_prefs = await structured_llm.ainvoke(extraction_msg)
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
                "interview_count": 0,  # Reset interview counter
                "next_node": "research",
                "messages": [{"role": "model", "content": f"Changing plans to {new_dest}! Let me research that for you..."}]
            }
            
        return {
            "messages": [{"role": "model", "content": "Great! I'm researching your trip now..."}],
            "user_details": user_details,
            "interview_count": 0,  # Reset interview counter on success
            "next_node": "research",
            "debug_logs": [log]
        }

    return {
        "messages": [{"role": "model", "content": content}],
        "interview_count": interview_count,  # Track interview iterations
        "next_node": "interviewer",
        "debug_logs": [log]
    }

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
        # Use getattr to safely get content from potential Response object
        grounded_text = getattr(grounded_response, 'content', str(grounded_response))
        
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
        # Use getattr to safely get content from potential Response object
        grounded_text = getattr(grounded_response, 'content', str(grounded_response))
        
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
        # Use getattr to safely get content from potential Response object
        grounded_text = getattr(grounded_response, 'content', str(grounded_response))
        
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

async def compiler_node(state: AgentState) -> Dict:
    t0 = time.time()
    # Explicit signal to reset any streaming buffers (useful if critic loops back)
    await adispatch_custom_event("reset_itinerary", {"message": "Refining itinerary..."})

    logger.info("Writing itinerary draft with smart zone grouping...")
    user_details = state.get("user_details", {})
    
    # Pre-format data for the LLM
    food_data = state.get("food_data") or []
    activity_data = state.get("activity_data") or []
    hotel_data = state.get("hotel_data") or []
    logistics = state.get("logistics") or {}
    
    # Convert to dicts for processing
    food_dicts = [f.model_dump() if hasattr(f, 'model_dump') else f for f in food_data]
    activity_dicts = [a.model_dump() if hasattr(a, 'model_dump') else a for a in activity_data]
    hotel_dicts = [h.model_dump() if hasattr(h, 'model_dump') else h for h in hotel_data]
    
    # Get hotel coordinates for zone calculation
    hotel_lat, hotel_lon = None, None
    selected_hotel = None
    if hotel_dicts:
        selected_hotel = hotel_dicts[0]
        hotel_lat = selected_hotel.get("lat")
        hotel_lon = selected_hotel.get("lon")
    
    # Group all places by proximity zones
    zone_groups = {"near": [], "medium": [], "far": [], "remote": []}
    
    if hotel_lat and hotel_lon:
        # Combine activities and restaurants for grouping
        all_places = []
        for a in activity_dicts:
            a["_type"] = "activity"
            all_places.append(a)
        for f in food_dicts:
            f["_type"] = "restaurant"
            all_places.append(f)
        
        raw_zone_groups = group_places_by_zone(all_places, hotel_lat, hotel_lon)
        
        # Programmatically optimize each zone's route before giving it to LLM
        for zone, places in raw_zone_groups.items():
            if places:
                optimization = optimize_day_route.invoke({
                    "places": places,
                    "hotel_lat": hotel_lat,
                    "hotel_lon": hotel_lon
                })
                # Replace the raw list with the mathematically optimized order
                zone_groups[zone] = optimization.get("optimized_order", [])
            else:
                zone_groups[zone] = []
    
    # Build pre-grouped and OPTIMIZED data for the LLM
    grouped_data = {
        "near_hotel": {
            "description": "Walking distance (< 2km, 10-25 min walk). OPTIMIZED ROUTE PROVIDED.",
            "places": zone_groups.get("near", [])
        },
        "medium_distance": {
            "description": "Short transit (2-5km, 15-20 min by bus/metro). OPTIMIZED ROUTE PROVIDED.", 
            "places": zone_groups.get("medium", [])
        },
        "far_from_hotel": {
            "description": "Requires dedicated transport (5-15km, 30-45 min). OPTIMIZED ROUTE PROVIDED.",
            "places": zone_groups.get("far", [])
        },
        "day_trip_territory": {
            "description": "Remote locations (15+ km, 1+ hours). OPTIMIZED ROUTE PROVIDED.",
            "places": zone_groups.get("remote", [])
        }
    }
    
    grouped_json = json.dumps(grouped_data, indent=2, ensure_ascii=False)
    hotel_json = json.dumps(hotel_dicts, indent=2, ensure_ascii=False)
    
    chat_llm = get_llm_for_role("compiler")
    
    prompt = f"""
You are writing a practical travel itinerary for a trip to {user_details.get('destination')}.

TRAVELER INFO:
- Departing from: {user_details.get('start_location', 'their home location')}
- Duration: {user_details.get('duration')}
- Budget: {user_details.get('budget')}
- Interests: {user_details.get('interests')}

ACCOMMODATION OPTIONS:
{hotel_json}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 PRE-GROUPED PLACES BY PROXIMITY (USE THIS FOR DAY PLANNING!)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{grouped_json}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 CRITICAL RULES FOR SMART ITINERARY:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **USE THE ZONE GROUPS ABOVE!** Each day should focus on ONE zone:
   - Day 1: Explore "near_hotel" places (easy start, jet lag friendly)
   - Day 2: Tackle "medium_distance" zone
   - Day 3+: Plan "far_from_hotel" or "day_trip_territory" as dedicated excursions

2. **NEVER MIX ZONES IN ONE DAY** unless absolutely necessary:
   - BAD: Morning in near_hotel zone, afternoon 50km away, dinner back near hotel
   - GOOD: Full day exploring one area, with lunch and dinner in the same zone

3. **ALWAYS MENTION TRAVEL INFO:**
   - Distance from hotel
   - Estimated travel time
   - Transport recommendation (walk/metro/bus/taxi)

4. **BE SPECIFIC:** Use exact names, addresses from the data above.

5. **REMOTE LOCATIONS WARNING:** If using "day_trip_territory" places, add a note:
   "⚠️ This is a day trip - allow extra travel time"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

OUTPUT FORMAT (Markdown):

# {user_details.get('duration', 'Your')} Trip to {user_details.get('destination')}

## Overview
(Brief summary + travel style based on budget)

## Recommended Accommodation
(Pick ONE hotel, explain why, include address)

## Day-by-Day Itinerary

### Day 1: [Zone Theme - e.g., "Exploring the Hotel Neighborhood"]
- **Morning:** [Activity] (X.X km from hotel, ~Y min walk/transit)
- **Lunch:** [Restaurant] (Address) - [Cuisine], [Price]
- **Afternoon:** [Activity]
- **Evening:** [Dinner spot]

### Day 2: [Zone Theme]
...continue for each day...

## Getting There & Transport
(How to get from {user_details.get('start_location')} to {user_details.get('destination')})

## Tips & Budget Notes

Output ONLY the raw Markdown text. Do NOT wrap the output in ```markdown code blocks. No preamble.
"""
    # Check if we should use ReAct Agent mode
    if USE_REACT_AGENT:
        draft, log = await _run_compiler_agent(user_details, hotel_dicts, grouped_data, t0)
    else:
        response = await chat_llm.ainvoke(
            [SystemMessage(content="You are a Travel Editor specializing in efficient, logical itineraries."), HumanMessage(content=prompt)],
            config={"tags": ["final_itinerary"]}
        )
        draft = response.content
        log = log_usage("compiler", t0, response)
    
    return {
        "draft_itinerary": draft,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "next_node": "critic",
        "debug_logs": [log]
    }


async def _run_compiler_agent(user_details: Dict, hotel_dicts: List, grouped_data: Dict, t0: float) -> tuple:
    """
    ReAct Agent version of the compiler.
    Uses tools to verify and optimize the route before writing.
    """
    logger.info("Running ReAct Agent Compiler with tools...")
    
    from langchain_core.messages import AIMessage
    
    # Get LLM with tools
    llm_with_tools = get_llm_with_tools(TRAVEL_TOOLS)
    
    # Build context
    hotel_json = json.dumps(hotel_dicts[:1], indent=2, ensure_ascii=False) if hotel_dicts else "{}"
    grouped_json = json.dumps(grouped_data, indent=2, ensure_ascii=False)
    
    agent_prompt = f"""
You are Atlas, a Travel Planner Agent with access to tools for route optimization.

TASK: Create a {user_details.get('duration')} itinerary for {user_details.get('destination')}.

TRAVELER INFO:
- Start: {user_details.get('start_location', 'their location')}
- Budget: {user_details.get('budget')}
- Interests: {user_details.get('interests')}

HOTEL (Base Location):
{hotel_json}

PLACES GROUPED BY ZONE:
{grouped_json}

AVAILABLE TOOLS:
1. optimize_day_route - Optimize order of places for a day (minimizes travel)
2. calculate_distance - Check distance between two points
3. check_zone - Verify which zone a place is in

YOUR WORKFLOW:
1. FIRST: Use optimize_day_route for each day's activities to find the best order
2. THEN: Write the final itinerary using the optimized order

OUTPUT FORMAT (After using tools):
Write a complete Markdown itinerary with:
- Overview
- Recommended Accommodation  
- Day-by-Day Itinerary (using optimized routes)
- Getting There & Transport
- Tips & Budget Notes

Start by analyzing the zones and calling optimize_day_route if needed.
"""
    
    messages = [
        SystemMessage(content="You are a Travel Planner Agent. Use tools to optimize routes, then write the itinerary."),
        HumanMessage(content=agent_prompt)
    ]
    
    # Agent loop (max 3 iterations for tool use)
    max_iterations = 3
    for i in range(max_iterations):
        response = await llm_with_tools.ainvoke(
            messages,
            config={"tags": ["final_itinerary"]}
        )
        messages.append(response)
        
        # Check if there are tool calls
        if hasattr(response, 'tool_calls') and response.tool_calls:
            # Execute tools
            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
                
                # Find and execute the tool
                tool_result = None
                for tool in TRAVEL_TOOLS:
                    if tool.name == tool_name:
                        try:
                            tool_result = tool.invoke(tool_args)
                        except Exception as e:
                            tool_result = f"Error: {e}"
                        break
                
                if tool_result is None:
                    tool_result = f"Unknown tool: {tool_name}"
                
                # Add tool result to messages
                from langchain_core.messages import ToolMessage
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_call.get("id", "")
                ))
        else:
            # No more tool calls, we have the final response
            break
    
    # Extract final content
    draft = response.content if hasattr(response, 'content') else str(response)
    log = log_usage("compiler_agent", t0, response)
    
    return draft, log


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
