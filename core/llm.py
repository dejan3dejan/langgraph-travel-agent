import os
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables")

_PROVIDERS = ("openai", "gemini")

# Pipeline roles whose model is swappable via a MODEL_<ROLE> env var. The eval-only
# "judge" role is intentionally excluded (see DEFAULT_REGISTRY) so a bake-off never
# routes the judge through the same env knobs as the roles under test.
ROLES = ("interviewer", "compiler", "research", "extraction", "critic")


@dataclass(frozen=True)
class RoleModel:
    """Resolved model for a role: which provider, which model id, and the role's
    default temperature."""

    provider: str
    model: str
    temperature: float


# Default role -> model mapping. Every pipeline role runs on OpenAI gpt-4o-mini; swap
# any role's provider/model with a MODEL_<ROLE> env var (e.g.
# MODEL_RESEARCH=gemini:gemini-2.5-flash) with no code change. Resolving a role to a
# provider:model is all this registry does; nodes read provider/model off the result.
DEFAULT_REGISTRY = {
    "interviewer": RoleModel("openai", "gpt-4o-mini", 0.3),
    "compiler": RoleModel("openai", "gpt-4o-mini", 0.7),
    "research": RoleModel("openai", "gpt-4o-mini", 0.3),
    "extraction": RoleModel("openai", "gpt-4o-mini", 0.0),
    "critic": RoleModel("openai", "gpt-4o-mini", 0.1),
    # Offline eval only (pairwise itinerary judge). A stronger model than the pipeline
    # roles under test (gpt-4o vs gpt-4o-mini) to blunt self-preference bias, temperature
    # 0 for a stable verdict. Not in ROLES, so it is not swept by MODEL_<ROLE> env vars.
    "judge": RoleModel("openai", "gpt-4o", 0.0),
}

# Used for any role not present in the registry (mirrors the old catch-all default).
_FALLBACK = RoleModel("openai", "gpt-4o-mini", 0.0)


def parse_model_spec(spec: str) -> tuple[str, str]:
    """Parse a "provider:model" string into (provider, model).

    Pure. Fails loud on a malformed spec or an unknown provider rather than
    silently defaulting, so a typo in a MODEL_<ROLE> env var surfaces at startup.
    """
    provider, sep, model = spec.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if not sep or not provider or not model:
        raise ValueError(f"Invalid model spec '{spec}'; expected 'provider:model'")
    if provider not in _PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}' in model spec '{spec}' (expected one of {_PROVIDERS})")
    return provider, model


def _spec_to_role_model(spec: str, base: RoleModel) -> RoleModel:
    provider, model = parse_model_spec(spec)
    return RoleModel(provider, model, base.temperature)


def _env_overrides() -> dict[str, RoleModel]:
    overrides: dict[str, RoleModel] = {}
    for role in ROLES:
        spec = os.getenv(f"MODEL_{role.upper()}")
        if spec:
            overrides[role] = _spec_to_role_model(spec, DEFAULT_REGISTRY[role])
    return overrides


def _coerce_config(config) -> dict[str, RoleModel]:
    """Build a registry from an explicit config layered over the defaults.

    config is a partial mapping of role -> "provider:model" or role -> RoleModel, so a
    caller (M2's config-A/config-B bake-off) can override just the roles it cares about
    and inherit the rest.
    """
    registry = dict(DEFAULT_REGISTRY)
    items = config.items() if isinstance(config, dict) else config
    for role, value in items:
        if role not in DEFAULT_REGISTRY:
            raise ValueError(f"Unknown role '{role}' in config (expected one of {tuple(DEFAULT_REGISTRY)})")
        if isinstance(value, RoleModel):
            registry[role] = value
        elif isinstance(value, str):
            registry[role] = _spec_to_role_model(value, DEFAULT_REGISTRY[role])
        else:
            raise ValueError(f"Invalid config value for role '{role}': {value!r}")
    return registry


def resolve_registry(config=None) -> dict[str, RoleModel]:
    """Effective role -> RoleModel map. An explicit config wins; otherwise the
    defaults overlaid with MODEL_<ROLE> env overrides."""
    if config is not None:
        return _coerce_config(config)
    return {**DEFAULT_REGISTRY, **_env_overrides()}


def _build_llm(rm: RoleModel, temperature: float):
    if rm.provider == "openai":
        return ChatOpenAI(model=rm.model, api_key=OPENAI_API_KEY, temperature=temperature)
    if rm.provider == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
        return ChatGoogleGenerativeAI(model=rm.model, google_api_key=GEMINI_API_KEY, temperature=temperature)
    raise ValueError(f"Unknown provider '{rm.provider}'")


def get_llm_for_role(role: str, temperature: float | None = None, config=None):
    """Return the configured LLM for a pipeline role.

    The role -> model mapping comes from DEFAULT_REGISTRY, overridable per role via
    MODEL_<ROLE> env vars or an explicit config argument (a partial dict of
    role -> "provider:model" or role -> RoleModel). Pass temperature to override the
    role default (a regenerate raises it to diversify).
    """
    rm = resolve_registry(config).get(role, _FALLBACK)
    temp = rm.temperature if temperature is None else temperature
    return _build_llm(rm, temp)
