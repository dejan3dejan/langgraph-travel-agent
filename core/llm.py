import os
from typing import Any

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

load_dotenv()

USE_REACT_AGENT = os.getenv("USE_REACT_AGENT", "false").lower() == "true"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY not found in environment variables")


def _openai(model: str, temperature: float):
    return ChatOpenAI(model=model, api_key=OPENAI_API_KEY, temperature=temperature)


def _gemini(model: str, temperature: float):
    return ChatGoogleGenerativeAI(model=model, google_api_key=GEMINI_API_KEY, temperature=temperature)


def get_llm_for_role(role: str):
    """Return the best-fit LLM for each pipeline role (hybrid OpenAI + Gemini)."""
    if role == "interviewer":
        return _openai("gpt-4o-mini", temperature=0.3)

    if role == "compiler":
        return _openai("gpt-4o-mini", temperature=0.7)

    if role == "compiler_agent":
        return _openai("gpt-4o-mini", temperature=0.3)

    if role == "research":
        return _gemini("gemini-2.5-flash", temperature=0.2)

    if role == "extraction":
        return _gemini("gemini-2.5-flash-lite", temperature=0)

    if role == "critic":
        return _gemini("gemini-2.5-flash-lite", temperature=0.1)

    return _openai("gpt-4o-mini", temperature=0)


def get_llm(model_name: str = "gpt-4o-mini", temperature: float = 0.7):
    """Instantiate a chat model by name. Defaults to OpenAI."""
    if "gemini" in model_name.lower():
        return _gemini(model_name, temperature)
    return _openai(model_name, temperature)


def get_llm_with_tools(tools: list[Any], role: str = "compiler_agent"):
    """Get LLM with tools bound for agent use."""
    llm = get_llm_for_role(role)
    return llm.bind_tools(tools)
