"""Role LLM factory: model registry resolution, the provider:model parser, and the
per-call temperature override. Pure construction, no API calls."""

import pytest

from core.llm import RoleModel, get_llm_for_role, parse_model_spec, resolve_registry


def test_default_temperatures_preserved():
    assert get_llm_for_role("compiler").temperature == 0.7
    assert get_llm_for_role("interviewer").temperature == 0.3
    assert get_llm_for_role("extraction").temperature == 0


def test_temperature_override_applies():
    assert get_llm_for_role("compiler", temperature=0.9).temperature == 0.9
    assert get_llm_for_role("research", temperature=0.8).temperature == 0.8


def test_parse_model_spec_valid():
    assert parse_model_spec("openai:gpt-4o-mini") == ("openai", "gpt-4o-mini")
    assert parse_model_spec("gemini:gemini-2.5-flash") == ("gemini", "gemini-2.5-flash")
    assert parse_model_spec(" OpenAI : gpt-4o ") == ("openai", "gpt-4o")


@pytest.mark.parametrize("spec", ["", "gpt-4o-mini", "openai:", ":gpt-4o-mini"])
def test_parse_model_spec_rejects_malformed(spec):
    with pytest.raises(ValueError):
        parse_model_spec(spec)


def test_parse_model_spec_rejects_unknown_provider():
    with pytest.raises(ValueError):
        parse_model_spec("anthropic:claude-3")


def test_env_override_swaps_a_role_model(monkeypatch):
    monkeypatch.setenv("MODEL_RESEARCH", "openai:gpt-4o")
    llm = get_llm_for_role("research")
    assert llm.model == "gpt-4o"
    # An override changes only the targeted role; the rest keep the defaults.
    assert get_llm_for_role("compiler").model == "gpt-4o-mini"


def test_explicit_config_honored_over_env(monkeypatch):
    monkeypatch.setenv("MODEL_RESEARCH", "openai:gpt-4o")
    # A passed config wins outright; the env override is ignored when config is given.
    llm = get_llm_for_role("research", config={"research": "openai:gpt-4o-mini"})
    assert llm.model == "gpt-4o-mini"


def test_config_accepts_role_model_and_is_partial():
    config = {"compiler": RoleModel("openai", "gpt-4o", 0.2)}
    assert get_llm_for_role("compiler", config=config).model == "gpt-4o"
    assert get_llm_for_role("compiler", config=config).temperature == 0.2
    # Roles absent from the config inherit the defaults.
    assert get_llm_for_role("interviewer", config=config).model == "gpt-4o-mini"


def test_config_rejects_unknown_role():
    with pytest.raises(ValueError):
        resolve_registry({"summarizer": "openai:gpt-4o"})
