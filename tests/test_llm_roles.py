"""Per-call temperature override for the role LLM factory. Pure construction, no API calls."""

from core.llm import get_llm_for_role


def test_default_temperatures_preserved():
    assert get_llm_for_role("compiler").temperature == 0.7
    assert get_llm_for_role("interviewer").temperature == 0.3
    assert get_llm_for_role("extraction").temperature == 0


def test_temperature_override_applies():
    assert get_llm_for_role("compiler", temperature=0.9).temperature == 0.9
    assert get_llm_for_role("research", temperature=0.8).temperature == 0.8
