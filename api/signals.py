"""Client-emitted interaction signals.

Only a small allowlist of event types may be reported by the client; everything else is denied by
default. Forgeable signals (a "keep", an "edit") are recorded server-side from the actual save paths,
never trusted from the client. A trip-open carries only a trip id; the server resolves the trip and
derives the descriptors itself, so the client cannot inject arbitrary payloads.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.database import Trip, User, get_db
from core.logger import get_logger
from core.signal_store import record_signal
from core.signals import TRIP_OPENED

from .auth import require_user
from .authz import role_can_read, trip_access

logger = get_logger(__name__)
router = APIRouter()

# Event types a client is allowed to report. Keep this narrow: anything that grants preference weight
# to a plan (kept/edited/variant) is recorded from the trusted server save paths instead.
_CLIENT_EVENTS = {TRIP_OPENED}


class SignalRequest(BaseModel):
    event_type: str
    trip_id: str


@router.post("")
async def report_signal(
    payload: SignalRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Record a client-reported interaction signal. Currently only trip-open, gated on read access to
    the trip so a user cannot log activity against a trip they cannot see."""
    if payload.event_type not in _CLIENT_EVENTS:
        raise HTTPException(status_code=422, detail="Unsupported signal type.")
    if not role_can_read(trip_access(db, payload.trip_id, user)):
        raise HTTPException(status_code=404, detail="Trip not found")

    trip = db.query(Trip).filter(Trip.id == payload.trip_id).first()
    descriptors = {
        k: v
        for k, v in {
            "destination": trip.destination,
            "budget": trip.budget,
            "interests": trip.interests,
            "duration": trip.duration,
        }.items()
        if v
    }
    record_signal(
        event_type=payload.event_type,
        user_id=user.id,
        session_id=trip.session_id,
        trip_id=trip.id,
        payload=descriptors,
    )
    return {"ok": True}
