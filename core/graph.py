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


def _research_targets(categories) -> list[str]:
    """Map research categories to node names, in the fixed order food, activity, hotel."""
    node_for = {"food": "research_food", "activities": "research_activity", "hotels": "research_hotel"}
    return [node_for[c] for c in ("food", "activities", "hotels") if c in categories]


def router(state: AgentState):
    next_node = state.get("next_node")

    if state.get("iteration_count", 0) >= 3:
        return END

    if next_node == "research":
        critique = state.get("critique", {})
        missing = critique.get("missing_data", [])
        user_details = state.get("user_details", {})

        if missing:
            targets = _research_targets(missing)
        else:
            # User-chosen focus narrows the default; empty/unrecognized falls back to all three.
            targets = _research_targets(user_details.get("focus", [])) or [
                "research_food",
                "research_activity",
                "research_hotel",
            ]

        # Only research lodging when the user actually needs it. Single choke point so the default,
        # focus, and critic re-research paths all honor it; never leave the list empty.
        if user_details.get("needs_accommodation") is False:
            targets = [t for t in targets if t != "research_hotel"] or ["research_food", "research_activity"]

        return targets

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


# A second, minimal graph for variant B of an A/B compare request: it re-runs only the compiler on
# variant A's already-researched data, so a compare request costs one extra compile rather than a
# second full research+logistics+critic pipeline. The compiler's regenerate path diversifies the
# result against variant A.
variant_workflow = StateGraph(AgentState)
variant_workflow.add_node("compiler", compiler_node)
variant_workflow.add_edge(START, "compiler")
variant_workflow.add_edge("compiler", END)
variant_app = variant_workflow.compile()
