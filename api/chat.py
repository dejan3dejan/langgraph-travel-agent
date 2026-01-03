"""
Smart Chat API endpoint powered by the new Travel Orchestrator.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import uuid

from core.logger import get_logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from core.database import get_db, ChatSession, Trip
from core.orchestrator import TravelOrchestrator

logger = get_logger(__name__)
router = APIRouter()

# Initialize Orchestrator (stateless usage)
orchestrator = TravelOrchestrator()

# --- Data Models ---

class ChatMessage(BaseModel):
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    message: str

class ChatResponse(BaseModel):
    session_id: str
    message: str
    state: str # 'chatting' | 'planning' | 'completed'
    itinerary: Optional[str] = None # Markdown string

@router.post("/chat", response_model=ChatResponse)
async def chat(chat_message: ChatMessage, db: Session = Depends(get_db)):
    """
    Chat endpoint that delegates to the Orchestrator.
    """
    # 1. Get/Create Session
    session_id = chat_message.session_id or str(uuid.uuid4())
    db_session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    
    if not db_session:
        db_session = ChatSession(
            session_id=session_id,
            user_id=chat_message.user_id,
            data={"history": []} # Store chat history here
        )
        db.add(db_session)
        db.commit()
    
    # 2. Get History from DB
    history = db_session.data.get("history", [])
    
    # 3. Process Message
    user_text = chat_message.message.strip()
    
    try:
        response_text, updated_history, _, user_details = orchestrator.chat(user_text, history)
        
        # 4. Save Updated History
        db_session.data["history"] = updated_history
        flag_modified(db_session, "data")
        db.commit()
        
        # 5. Check if Planning Happened
        if "# Day 1" in response_text or "##" in response_text:
             # SAVE STRUCTURED DATA FOR ANALYTICS
             try:
                 new_trip = Trip(
                     session_id=session_id,
                     destination=str(user_details.get("destination", "Unknown")),
                     duration=str(user_details.get("duration", "Unknown")),
                     budget=str(user_details.get("budget", "Unknown")),
                     interests=str(user_details.get("interests", "Unknown")),
                     itinerary_text=response_text
                 )
                 db.add(new_trip)
                 db.commit()
                 logger.info(f"Saved trip to {new_trip.destination}")
             except Exception as e:
                 logger.error(f"Failed to save trip: {e}")

             return ChatResponse(
                session_id=session_id,
                message="Here is your trip plan!",
                state="completed",
                itinerary=response_text
            )
        else:
            return ChatResponse(
                session_id=session_id,
                message=response_text,
                state="chatting"
            )
            
    except Exception as e:
        logger.error(f"Orchestrator Error: {e}")
        return ChatResponse(
            session_id=session_id,
            message=f"I encountered an error: {str(e)}",
            state="error"
        )
