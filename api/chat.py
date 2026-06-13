"""DB-backed chat router with standard and streaming endpoints."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from core.database import ChatSession, SessionLocal, Trip, User, UserPreference, get_db
from core.logger import get_logger
from core.orchestrator import TravelOrchestrator

from .auth import get_current_user

logger = get_logger(__name__)
router = APIRouter()
orchestrator = TravelOrchestrator()


class ChatMessage(BaseModel):
    session_id: str | None = None
    message: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    session_id: str
    message: str
    state: str
    itinerary: str | None = None


def get_or_create_session(db: Session, session_id: str | None, user: User | None) -> tuple[str, ChatSession]:
    sid = session_id or str(uuid.uuid4())
    db_session = db.query(ChatSession).filter(ChatSession.session_id == sid).first()

    if not db_session:
        db_session = ChatSession(
            session_id=sid,
            user_id=user.id if user else None,
            data={"history": []},
        )
        db.add(db_session)
        db.commit()
    return sid, db_session


def _seeded_prefs(db: Session, user: User | None) -> dict | None:
    """An authed user's saved travel defaults, mapped to UserPreferences field names, so the
    interviewer can seed them and stop re-asking. None for anonymous users."""
    if not user:
        return None
    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        return None
    mapping = {
        "budget": pref.default_budget,
        "interests": pref.default_interests,
        "num_travelers": pref.num_travelers,
        "age_range": pref.age_range,
        "trip_type": pref.trip_type,
        "start_location": pref.start_location,
        "constraints": pref.constraints,
    }
    out = {k: v for k, v in mapping.items() if v}
    return out or None


def _latest_trip(db: Session, session_id: str) -> Trip | None:
    """The session's most recently created trip, matching the latest delivered plan."""
    return db.query(Trip).filter(Trip.session_id == session_id).order_by(Trip.created_at.desc()).first()


def _is_trip_update(is_edit: bool, existing_trip: Trip | None) -> bool:
    """An edit updates the session's existing trip in place; a fresh plan, or an edit with no prior
    trip to update, inserts a new one."""
    return bool(is_edit and existing_trip is not None)


def _merge_geo(existing_geo: dict | None, new_geo: dict | None) -> dict | None:
    """Keep the prior map when an edit carries no fresh coordinates (an in-place text edit doesn't
    re-geocode); otherwise take the new payload."""
    return new_geo if new_geo is not None else existing_geo


def _upsert_trip(
    db: Session,
    session_id: str,
    user: User | None,
    user_details: dict,
    itinerary_text: str,
    is_edit: bool,
    geo: dict | None = None,
) -> None:
    """Save a delivered plan: update the existing trip in place for an edit, otherwise insert a new
    one. Does not commit; the caller owns the transaction."""
    existing = _latest_trip(db, session_id) if is_edit else None
    if _is_trip_update(is_edit, existing):
        existing.itinerary_text = itinerary_text
        existing.geo = _merge_geo(existing.geo, geo)
        logger.info(f"Updated trip {existing.id} for session {session_id}")
        return
    if is_edit:
        logger.warning(f"Edit for session {session_id} had no existing trip; inserting a new one")
    db.add(
        Trip(
            session_id=session_id,
            user_id=user.id if user else None,
            destination=str(user_details.get("destination", "Unknown")),
            duration=str(user_details.get("duration", "Unknown")),
            budget=str(user_details.get("budget", "Unknown")),
            interests=str(user_details.get("interests", "Unknown")),
            itinerary_text=itinerary_text,
            geo=geo,
        )
    )
    logger.info(f"Saved trip for session {session_id}")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    chat_message: ChatMessage,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Standard non-streaming chat endpoint. Works for both anonymous and authenticated users."""
    session_id, db_session = get_or_create_session(db, chat_message.session_id, user)
    history = db_session.data.get("history", [])
    user_text = chat_message.message.strip()

    try:
        response_text, updated_history, _, user_details, is_itinerary, is_edit = await orchestrator.chat(
            user_text, history, _seeded_prefs(db, user)
        )

        db_session.data["history"] = updated_history
        if not db_session.title or db_session.title == "New Chat":
            db_session.title = user_text[:60]
        flag_modified(db_session, "data")
        db.commit()

        if is_itinerary:
            try:
                _upsert_trip(db, session_id, user, user_details, response_text, is_edit)
                db.commit()
            except Exception as e:
                logger.error(f"Failed to save trip: {e}")

            return ChatResponse(
                session_id=session_id, message="Here is your trip plan!", state="completed", itinerary=response_text
            )

        return ChatResponse(session_id=session_id, message=response_text, state="chatting")

    except Exception as e:
        logger.error(f"Orchestrator Error: {e}")
        return ChatResponse(session_id=session_id, message="Something went wrong. Please try again.", state="error")


@router.post("/chat/stream")
async def chat_stream(
    chat_message: ChatMessage,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Streaming chat endpoint with guaranteed persistence. Supports anonymous and authenticated."""
    session_id, db_session = get_or_create_session(db, chat_message.session_id, user)
    history = db_session.data.get("history", [])
    user_text = chat_message.message.strip()
    prefs = _seeded_prefs(db, user)

    if not db_session.title or db_session.title == "New Chat":
        db_session.title = user_text[:60]
        db.commit()

    async def event_generator():
        accumulated_data = {"itinerary": "", "completed": False, "start_time": datetime.now(UTC)}
        is_itinerary = False
        cancelled = False

        try:
            # Tell the client its session id up front so it can resend it next turn
            # (this is what gives the web UI cross-turn memory).
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            async for event in orchestrator.stream_chat(user_text, history, prefs):
                if event["type"] == "reset":
                    accumulated_data["itinerary"] = ""
                elif event["type"] == "token":
                    accumulated_data["itinerary"] += event["content"]
                elif event["type"] == "end":
                    accumulated_data["completed"] = True
                    is_itinerary = event.get("is_itinerary", False)
                    accumulated_data["user_details"] = event.get("user_details", {})
                    accumulated_data["is_edit"] = event.get("is_edit", False)
                    accumulated_data["geo"] = event.get("geo")

                yield f"data: {json.dumps(event)}\n\n"

        except asyncio.CancelledError:
            cancelled = True
            logger.warning(f"Stream cancelled for session {session_id}")
            raise
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f'data: {json.dumps({"type": "error", "content": "An internal error occurred."})}\n\n'
        finally:
            # On client cancel we discard the partial so a stopped turn leaves no ghost in history.
            if not cancelled and accumulated_data["itinerary"].strip():
                persist_db = SessionLocal()
                try:
                    new_history = list(history)
                    new_history.append({"role": "user", "content": user_text})
                    new_history.append({"role": "model", "content": accumulated_data["itinerary"]})

                    active_session = persist_db.query(ChatSession).filter(ChatSession.session_id == session_id).first()

                    if active_session:
                        active_session.data["history"] = new_history
                        flag_modified(active_session, "data")

                        if is_itinerary:
                            _upsert_trip(
                                persist_db,
                                session_id,
                                user,
                                accumulated_data.get("user_details", {}),
                                accumulated_data["itinerary"],
                                accumulated_data.get("is_edit", False),
                                geo=accumulated_data.get("geo"),
                            )

                        persist_db.commit()
                        logger.info(f"Stream data persisted for session {session_id}")
                except Exception as save_err:
                    logger.error(f"Final persistence failed: {save_err}")
                finally:
                    persist_db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
