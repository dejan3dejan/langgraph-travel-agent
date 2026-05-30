import os
from typing import Any

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

USE_REACT_AGENT = os.getenv("USE_REACT_AGENT", "false").lower() == "true"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables")


def get_llm_for_role(role: str):
    """Return a ChatOpenAI tuned for a specific pipeline role."""
    if role == "critic":
        return get_llm("gpt-4o-mini", temperature=0.1)

    if role == "interviewer":
        return get_llm("gpt-4o-mini", temperature=0.3)

    if role == "compiler":
        return get_llm("gpt-4o-mini", temperature=0.7)

    if role == "compiler_agent":
        return get_llm("gpt-4o-mini", temperature=0.3)

    return get_llm("gpt-4o-mini", temperature=0)


def get_llm(model_name: str = "gpt-4o-mini", temperature: float = 0.7):
    """Instantiate an OpenAI chat model."""
    return ChatOpenAI(model=model_name, api_key=OPENAI_API_KEY, temperature=temperature)


def get_llm_with_tools(tools: list[Any], role: str = "compiler_agent"):
    """Get LLM with tools bound for agent use."""
    llm = get_llm_for_role(role)
    return llm.bind_tools(tools)
