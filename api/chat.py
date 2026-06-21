"""DB-backed chat router with standard and streaming endpoints."""

import asyncio
import json
import uuid

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
    compare: bool = False  # opt-in: produce two itinerary variants (A/B) for a fresh plan


class KeepVariant(BaseModel):
    session_id: str
    variant: str = Field(..., pattern="^[AB]$")


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
        "constraints": _seeded_constraints(pref),
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


# Compare mode: per-variant stream accumulation and keep-variant selection


def _new_variant_buckets() -> dict:
    """Empty A/B buckets the stream folds tokens and geo into. Untagged (single-itinerary) events
    fold into bucket A, so this also backs the normal flow."""
    return {"A": {"text": "", "geo": None}, "B": {"text": "", "geo": None}}


def _new_variant_meta() -> dict:
    """Variant-A metadata captured from its end event, used to persist (or stage) after the stream."""
    return {"is_itinerary": False, "is_edit": False, "user_details": {}}


def _apply_stream_event(variants: dict, meta: dict, event: dict) -> None:
    """Fold one stream event into the per-variant buckets and the variant-A meta, so the stream's
    finally block can persist or stage without re-deriving anything. Untagged events (the
    single-itinerary flow) fold into bucket A."""
    variant = event.get("variant") or "A"
    if variant not in variants:
        return
    etype = event.get("type")
    if etype == "reset":
        variants[variant]["text"] = ""
    elif etype == "token":
        variants[variant]["text"] += event.get("content", "")
    elif etype == "end":
        variants[variant]["geo"] = event.get("geo")
        if variant == "A":
            meta["is_itinerary"] = event.get("is_itinerary", False)
            meta["is_edit"] = event.get("is_edit", False)
            meta["user_details"] = event.get("user_details", {})


def _should_stage(variants: dict) -> bool:
    """True when a second variant was actually produced (B has streamed text), so the two are staged
    for the user to choose. Otherwise the turn is a single result and persists normally."""
    return bool(variants["B"]["text"].strip())


def _select_variant(pending: dict | None, variant: str) -> dict | None:
    """The staged {text, geo} for the chosen tag, or None when nothing is staged or the tag is
    unknown. Guards the keep endpoint against a stale or malformed selection."""
    if not pending or variant not in ("A", "B"):
        return None
    return pending.get(variant)


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


def _dedupe(items: list[str]) -> list[str]:
    """Case-insensitive de-dupe preserving order; drops blanks."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = (item or "").strip()
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def _merge_constraints(saved: dict | None, learned: dict | None) -> dict:
    """Union two structured constraint sets ({hard, soft}), de-duped case-insensitively and saved
    first, so remembering allergies/dietary needs across trips never piles up duplicates."""
    saved = saved or {}
    learned = learned or {}
    return {
        "hard": _dedupe((saved.get("hard") or []) + (learned.get("hard") or [])),
        "soft": _dedupe((saved.get("soft") or []) + (learned.get("soft") or [])),
    }


def _seeded_constraints(pref: UserPreference) -> dict | None:
    """The user's saved constraints to seed into the interview: the structured value, or the legacy
    free-text column treated as a single soft entry. None when nothing is saved."""
    structured = pref.travel_constraints
    if structured and (structured.get("hard") or structured.get("soft")):
        return structured
    legacy = (pref.constraints or "").strip()
    return {"hard": [], "soft": [legacy]} if legacy else None


def _remember_user_prefs(db: Session, user: User | None, user_details: dict) -> None:
    """Persist durable, chat-learned constraints (allergies, dietary, accessibility) to a signed-in
    user's saved profile, so a later trip seeds them and Atlas does not re-ask. Anonymous users have
    no profile to update. Merge-only: learned constraints extend what is saved, never wipe it. Does
    not commit; the caller owns the transaction."""
    if not user:
        return
    learned = user_details.get("constraints") or {}
    if not (learned.get("hard") or learned.get("soft")):
        return
    pref = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    if not pref:
        pref = UserPreference(user_id=user.id)
        db.add(pref)
    merged = _merge_constraints(pref.travel_constraints, learned)
    if merged != (pref.travel_constraints or {"hard": [], "soft": []}):
        pref.travel_constraints = merged
        logger.info(f"Remembered constraints for user {user.id}")


def _persist_single_turn(
    session_id: str, history: list, user_text: str, bucket: dict, meta: dict, user: User | None
) -> None:
    """Commit a single delivered turn: append the user message and the model reply to history, and for
    an itinerary upsert the trip and remember durable prefs. Owns its own DB session because the
    request's session is gone by the time the stream's finally runs."""
    persist_db = SessionLocal()
    try:
        active = persist_db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not active:
            return
        new_history = list(history)
        new_history.append({"role": "user", "content": user_text})
        new_history.append({"role": "model", "content": bucket["text"]})
        active.data["history"] = new_history
        flag_modified(active, "data")
        if meta.get("is_itinerary"):
            _upsert_trip(
                persist_db,
                session_id,
                user,
                meta.get("user_details", {}),
                bucket["text"],
                meta.get("is_edit", False),
                geo=bucket.get("geo"),
            )
            _remember_user_prefs(persist_db, user, meta.get("user_details", {}))
        persist_db.commit()
        logger.info(f"Stream data persisted for session {session_id}")
    except Exception as save_err:
        logger.error(f"Final persistence failed: {save_err}")
    finally:
        persist_db.close()


def _stage_pending_variants(session_id: str, variants: dict, user_details: dict, user_text: str) -> None:
    """Stash both unsaved itinerary variants on the session so a later keep-variant call can commit the
    chosen one. Nothing reaches history or the trips list until the user keeps a variant."""
    persist_db = SessionLocal()
    try:
        active = persist_db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
        if not active:
            return
        active.data["pending_variants"] = {
            "A": {"text": variants["A"]["text"], "geo": variants["A"]["geo"]},
            "B": {"text": variants["B"]["text"], "geo": variants["B"]["geo"]},
            "user_details": user_details,
            "message": user_text,
        }
        flag_modified(active, "data")
        persist_db.commit()
        logger.info(f"Staged two itinerary variants for session {session_id}")
    except Exception as save_err:
        logger.error(f"Staging variants failed: {save_err}")
    finally:
        persist_db.close()


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
                _remember_user_prefs(db, user, user_details)
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
        variants = _new_variant_buckets()
        meta = _new_variant_meta()
        cancelled = False

        try:
            # Tell the client its session id up front so it can resend it next turn
            # (this is what gives the web UI cross-turn memory).
            yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

            async for event in orchestrator.stream_chat(user_text, history, prefs, compare=chat_message.compare):
                _apply_stream_event(variants, meta, event)
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
            if cancelled:
                pass
            elif _should_stage(variants):
                # Two variants were produced: stage them and commit nothing until the user keeps one.
                _stage_pending_variants(session_id, variants, meta.get("user_details", {}), user_text)
            elif variants["A"]["text"].strip():
                _persist_single_turn(session_id, history, user_text, variants["A"], meta, user)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/keep-variant", response_model=ChatResponse)
async def keep_variant(
    payload: KeepVariant,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Commit the variant the user chose from an A/B compare. Appends the original request and the
    chosen itinerary to history, upserts the trip, clears the staged variants, and collapses the
    session back to the single-itinerary flow."""
    db_session = db.query(ChatSession).filter(ChatSession.session_id == payload.session_id).first()
    if not db_session:
        return ChatResponse(session_id=payload.session_id, message="Session not found.", state="error")

    pending = (db_session.data or {}).get("pending_variants")
    chosen = _select_variant(pending, payload.variant)
    if not chosen or not (chosen.get("text") or "").strip():
        return ChatResponse(session_id=payload.session_id, message="No variant to keep.", state="error")

    try:
        history = db_session.data.get("history", [])
        history.append({"role": "user", "content": pending["message"]})
        history.append({"role": "model", "content": chosen["text"]})
        db_session.data["history"] = history
        db_session.data.pop("pending_variants", None)
        flag_modified(db_session, "data")

        _upsert_trip(
            db,
            payload.session_id,
            user,
            pending.get("user_details", {}),
            chosen["text"],
            is_edit=False,
            geo=chosen.get("geo"),
        )
        _remember_user_prefs(db, user, pending.get("user_details", {}))
        db.commit()
        logger.info(f"Kept variant {payload.variant} for session {payload.session_id}")
    except Exception as e:
        logger.error(f"Failed to keep variant: {e}")
        return ChatResponse(session_id=payload.session_id, message="Could not save your choice.", state="error")

    return ChatResponse(
        session_id=payload.session_id,
        message="Saved your selected itinerary!",
        state="completed",
        itinerary=chosen["text"],
    )
