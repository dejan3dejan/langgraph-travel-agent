"""Unit tests for the graph router — pure control-flow logic."""

from langgraph.graph import END

from core.graph import router


def test_loop_guard_ends_after_3_iterations():
    # The iteration guard fires regardless of next_node.
    assert router({"next_node": "compiler", "iteration_count": 3}) == END


def test_research_default_runs_all_three():
    out = router({"next_node": "research", "iteration_count": 0})
    assert set(out) == {"research_food", "research_activity", "research_hotel"}


def test_research_targets_only_missing_data():
    state = {"next_node": "research", "iteration_count": 0, "critique": {"missing_data": ["food"]}}
    assert router(state) == ["research_food"]


def test_research_respects_user_focus():
    state = {"next_node": "research", "iteration_count": 0, "user_details": {"focus": ["hotels"]}}
    assert router(state) == ["research_hotel"]


def test_missing_data_takes_priority_over_focus():
    state = {
        "next_node": "research",
        "iteration_count": 0,
        "critique": {"missing_data": ["activities"]},
        "user_details": {"focus": ["hotels"]},
    }
    assert router(state) == ["research_activity"]


def test_skips_hotel_research_when_accommodation_not_needed():
    state = {"next_node": "research", "iteration_count": 0, "user_details": {"needs_accommodation": False}}
    assert set(router(state)) == {"research_food", "research_activity"}


def test_keeps_hotel_research_when_accommodation_needed():
    state = {"next_node": "research", "iteration_count": 0, "user_details": {"needs_accommodation": True}}
    assert set(router(state)) == {"research_food", "research_activity", "research_hotel"}


def test_unknown_accommodation_still_researches_hotels():
    # None/absent means not-yet-decided; default to researching (preserves prior behavior)
    state = {"next_node": "research", "iteration_count": 0, "user_details": {"needs_accommodation": None}}
    assert set(router(state)) == {"research_food", "research_activity", "research_hotel"}


def test_hotel_only_focus_falls_back_when_not_needed():
    # contradictory input (focus hotels but no lodging needed): still return real places to plan a day
    state = {
        "next_node": "research",
        "iteration_count": 0,
        "user_details": {"needs_accommodation": False, "focus": ["hotels"]},
    }
    assert set(router(state)) == {"research_food", "research_activity"}


def test_approved_ends():
    assert router({"next_node": "approved", "iteration_count": 0}) == END


def test_interviewer_ends():
    assert router({"next_node": "interviewer", "iteration_count": 0}) == END


def test_critic_routes_to_critic():
    assert router({"next_node": "critic", "iteration_count": 0}) == "critic"


def test_compiler_routes_to_compiler():
    assert router({"next_node": "compiler", "iteration_count": 0}) == "compiler"


def test_unknown_next_node_ends():
    assert router({"next_node": None, "iteration_count": 0}) == END
