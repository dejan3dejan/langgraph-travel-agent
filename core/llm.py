import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

def get_llm_for_role(role: str):
    """Role-based model selection using stable Google models."""
    if role in ["critic", "interviewer"]:
        return get_llm("gemini-2.5-pro", temperature=0.1)
    
    if role == "compiler":
        return get_llm("gemini-2.0-flash", temperature=0.7)
        
    return get_llm("gemini-2.5-flash-lite", temperature=0)

def get_llm(model_name: str = "gemini-2.5-flash-lite", temperature: float = 0.7):
    """Factory function to get an LLM instance."""
    if "gemini" in model_name.lower():
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables")
            
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=temperature
        )
    
    raise ValueError(f"Unsupported model: {model_name}")
