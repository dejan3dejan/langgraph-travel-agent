"""Boundary for interaction signals: record events, and load a user's recent ones into a
planning-context block.

The pure aggregation lives in core/signals.py; this module owns the DB I/O and the clock.
Recording is best-effort: a failed signal write is logged, never raised, so it can never
break the user-facing planning flow. Reading folds in the existing explicit `feedback`
ratings (rating only, never the free-text note) so the two layers complement each other.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from .database import Feedback, InteractionSignal, SessionLocal, Trip
from .logger import get_logger
from .signals import EVENT_TYPES, THUMB_DOWN, THUMB_UP, aggregate_signals, classify_edit_intent, render_learned_context

logger = get_logger(__name__)

_DESCRIPTOR_KEYS = ("destination", "trip_type", "budget", "interests", "duration")
_MAX_EDIT_INSTRUCTION = 500
_RECENT_LIMIT = 100
_RECENT_DAYS = 120


def descriptors_from(user_details: dict | None) -> dict:
    """The small, non-PII trip descriptor snapshot stored on a signal payload."""
    ud = user_details or {}
    return {k: ud[k] for k in _DESCRIPTOR_KEYS if ud.get(k)}


def edited_payload(user_details: dict | None, edit_instruction: str | None) -> dict:
    """Payload for an edit signal: descriptors plus the (bounded) raw instruction and its
    pre-classified intents. The raw text is stored for later analysis only; aggregation feeds
    back the enums, never the text."""
    payload = descriptors_from(user_details)
    text = (edit_instruction or "")[:_MAX_EDIT_INSTRUCTION]
    if text:
        payload["edit_instruction"] = text
        payload["edit_intents"] = classify_edit_intent(text)
    return payload


def record_signal(
    *,
    event_type: str,
    user_id: str | None,
    session_id: str | None,
    trip_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Persist one interaction signal on its own short transaction. Best-effort: an unknown
    event type or any DB error is logged and swallowed so the caller's flow is never affected."""
    if event_type not in EVENT_TYPES:
        logger.warning(f"Ignoring unknown signal event_type: {event_type}")
        return
    db = SessionLocal()
    try:
        db.add(
            InteractionSignal(
                id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                trip_id=trip_id,
                event_type=event_type,
                payload=payload or {},
            )
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to record signal {event_type}: {e}")
        db.rollback()
    finally:
        db.close()


def _session_descriptors(db: Session, session_ids: set[str]) -> dict[str, dict]:
    """Map each session id to its most recent trip's descriptors, in one query, so explicit
    feedback rows (which carry no descriptors) can be tied back to what was planned."""
    if not session_ids:
        return {}
    out: dict[str, dict] = {}
    trips = db.query(Trip).filter(Trip.session_id.in_(session_ids)).order_by(Trip.created_at.asc()).all()
    # Ascending order means the last write per session wins (the latest trip).
    for t in trips:
        out[t.session_id] = {
            "destination": t.destination,
            "trip_type": None,
            "budget": t.budget,
            "interests": t.interests,
            "duration": t.duration,
        }
    return out


def _feedback_signals(db: Session, user_id: str, cutoff: datetime) -> list[dict]:
    """Translate explicit star ratings into implicit-signal shape: rating >= 4 is positive,
    <= 2 negative, 3 is neutral and skipped. Descriptors come from the rated session's trip;
    the note is never read."""
    rows = (
        db.query(Feedback)
        .filter(
            Feedback.user_id == user_id,
            Feedback.kind.in_(("plan", "compare")),
            Feedback.rating.isnot(None),
            Feedback.created_at >= cutoff,
        )
        .all()
    )
    if not rows:
        return []
    desc = _session_descriptors(db, {r.session_id for r in rows if r.session_id})
    signals: list[dict] = []
    for r in rows:
        if r.rating >= 4:
            event = THUMB_UP
        elif r.rating <= 2:
            event = THUMB_DOWN
        else:
            continue
        payload = {k: v for k, v in desc.get(r.session_id, {}).items() if v}
        signals.append({"event_type": event, "payload": payload, "created_at": r.created_at})
    return signals


def _recent_signals(db: Session, user_id: str | None, session_id: str | None, cutoff: datetime) -> list[dict]:
    """The user's recent interaction signals (by account when signed in, else by session),
    plus their explicit ratings folded into the same shape."""
    query = db.query(InteractionSignal).filter(InteractionSignal.created_at >= cutoff)
    if user_id:
        query = query.filter(InteractionSignal.user_id == user_id)
    elif session_id:
        query = query.filter(InteractionSignal.session_id == session_id)
    else:
        return []
    rows = query.order_by(InteractionSignal.created_at.desc()).limit(_RECENT_LIMIT).all()
    signals = [{"event_type": r.event_type, "payload": r.payload or {}, "created_at": r.created_at} for r in rows]
    if user_id:
        signals.extend(_feedback_signals(db, user_id, cutoff))
    return signals


def planning_context(db: Session, user_id: str | None, session_id: str | None, profile: dict | None) -> str | None:
    """Load recent signals, aggregate them with the profile, and render the advisory block for
    the compiler. Returns None when nothing has been learned. Fail-soft: any error degrades to
    no personalization rather than blocking a plan."""
    try:
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=_RECENT_DAYS)
        signals = _recent_signals(db, user_id, session_id, cutoff)
        if not signals:
            return None
        portrait = aggregate_signals(signals, profile or {}, now=now, recency_days=_RECENT_DAYS)
        return render_learned_context(portrait)
    except Exception as e:
        logger.warning(f"Could not build planning context from signals: {e}")
        return None
