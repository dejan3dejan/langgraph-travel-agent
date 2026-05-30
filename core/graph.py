"""LangGraph workflow — wires nodes into the travel planning pipeline."""

from langgraph.graph import END, START, StateGraph

from .logistics import logistics_agent
from .nodes import (
    compiler_node,
    critic_node,
    interviewer_node,
    research_activity_node,
    research_food_node,
    research_hotel_node,
)
from .state import AgentState

workflow = StateGraph(AgentState)

workflow.add_node("interviewer", interviewer_node)
workflow.add_node("research_food", research_food_node)
workflow.add_node("research_activity", research_activity_node)
workflow.add_node("research_hotel", research_hotel_node)
workflow.add_node("logistics", logistics_agent)
workflow.add_node("compiler", compiler_node)
workflow.add_node("critic", critic_node)

workflow.add_edge(START, "interviewer")


def router(state: AgentState):
    next_node = state.get("next_node")

    if state.get("iteration_count", 0) >= 3:
        return END

    if next_node == "research":
        critique = state.get("critique", {})
        missing = critique.get("missing_data", [])
        user_details = state.get("user_details", {})
        focus = user_details.get("focus", [])

        if missing:
            targets = []
            if "food" in missing:
                targets.append("research_food")
            if "activities" in missing:
                targets.append("research_activity")
            if "hotels" in missing:
                targets.append("research_hotel")
            return targets

        if focus:
            targets = []
            if "food" in focus:
                targets.append("research_food")
            if "activities" in focus:
                targets.append("research_activity")
            if "hotels" in focus:
                targets.append("research_hotel")
            if targets:
                return targets

        return ["research_food", "research_activity", "research_hotel"]

    if next_node == "interviewer":
        return END
    if next_node == "approved":
        return END
    if next_node == "critic":
        return "critic"
    if next_node == "compiler":
        return "compiler"

    return END


workflow.add_conditional_edges("interviewer", router)
workflow.add_edge("research_food", "logistics")
workflow.add_edge("research_activity", "logistics")
workflow.add_edge("research_hotel", "logistics")
workflow.add_edge("logistics", "compiler")
workflow.add_conditional_edges("compiler", router)
workflow.add_conditional_edges("critic", router)

app = workflow.compile()
