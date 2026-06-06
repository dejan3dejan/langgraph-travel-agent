import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

load_dotenv()

# Temporary: Gemini prepay quota is depleted, so research/extraction/critic are
# routed to OpenAI for now. Flip back to True (with Gemini billing/quota) to
# restore the hybrid setup and live Google Search grounding in research.
USE_GEMINI = False

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables")
if USE_GEMINI and not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables")


def _openai(model: str, temperature: float):
    return ChatOpenAI(model=model, api_key=OPENAI_API_KEY, temperature=temperature)


def _gemini(model: str, temperature: float):
    return ChatGoogleGenerativeAI(model=model, google_api_key=GEMINI_API_KEY, temperature=temperature)


def get_llm_for_role(role: str):
    """Return the best-fit LLM for each pipeline role.

    Hybrid OpenAI + Gemini when USE_GEMINI is True; OpenAI-only otherwise
    (research loses live Google Search grounding in OpenAI-only mode).
    """
    if role == "interviewer":
        return _openai("gpt-4o-mini", temperature=0.3)

    if role == "compiler":
        return _openai("gpt-4o-mini", temperature=0.7)

    if role == "research":
        return _gemini("gemini-2.5-flash", temperature=0.2) if USE_GEMINI else _openai("gpt-4o-mini", temperature=0.3)

    if role == "extraction":
        return _gemini("gemini-2.5-flash-lite", temperature=0) if USE_GEMINI else _openai("gpt-4o-mini", temperature=0)

    if role == "critic":
        return (
            _gemini("gemini-2.5-flash-lite", temperature=0.1) if USE_GEMINI else _openai("gpt-4o-mini", temperature=0.1)
        )

    return _openai("gpt-4o-mini", temperature=0)
