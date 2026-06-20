"""Public, read-only itinerary sharing.

A share is an immutable snapshot of a delivered plan (markdown text + the {hotel, days[]} geo
payload) stored under an unguessable id. The snapshot deliberately carries no user_id, session, or
profile data, so a public link cannot leak who made it or their saved constraints.
"""

import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import SharedItinerary, get_db
from core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_DEFAULT_TITLE = "Shared itinerary"
SHARE_TTL_DAYS = 30


def extract_title(markdown: str) -> str:
    """The itinerary's first level-1 heading, or a generic fallback. Mirrors the title the canvas
    derives client-side so the shared page reads the same."""
    match = _H1.search(markdown or "")
    return match.group(1).strip() if match else _DEFAULT_TITLE


def new_share_id() -> str:
    """A URL-safe, CSPRNG token. Unguessable is the only access control on a public snapshot."""
    return secrets.token_urlsafe(16)


def expires_after(created: datetime, days: int = SHARE_TTL_DAYS) -> datetime:
    """The deadline past which a snapshot stops resolving. Caps how long a leaked link stays live."""
    return created + timedelta(days=days)


def is_expired(expires_at: datetime | None, now: datetime) -> bool:
    """Whether a snapshot's deadline has passed. A null deadline (legacy rows) never expires."""
    return expires_at is not None and expires_at <= now


def can_revoke(stored_token: str | None, provided: str | None) -> bool:
    """Revoke only with the exact owner token. Constant-time compare; missing tokens never match."""
    if not stored_token or not provided:
        return False
    return secrets.compare_digest(stored_token, provided)


class ShareRequest(BaseModel):
    # Only the rendered plan and its map travel into a public snapshot; nothing user-identifying.
    itinerary_text: str = Field(..., min_length=1, max_length=20000)
    geo: dict | None = None
    title: str | None = Field(default=None, max_length=200)


class ShareCreated(BaseModel):
    # revoke_token is returned only here, never on GET, so only the creator can later revoke.
    id: str
    revoke_token: str


class RevokeRequest(BaseModel):
    revoke_token: str


class SharedItineraryResponse(BaseModel):
    id: str
    title: str
    itinerary_text: str
    geo: dict | None
    created_at: str


@router.post("", response_model=ShareCreated, status_code=201)
async def create_share(req: ShareRequest, db: Session = Depends(get_db)):
    """Persist a public snapshot of an itinerary and return its unguessable id and revoke token."""
    created = datetime.now(UTC)
    snapshot = SharedItinerary(
        id=new_share_id(),
        title=(req.title or extract_title(req.itinerary_text)),
        itinerary_text=req.itinerary_text,
        geo=req.geo,
        revoke_token=new_share_id(),
        expires_at=expires_after(created),
    )
    db.add(snapshot)
    db.commit()
    logger.info(f"Created shared itinerary {snapshot.id}")
    return ShareCreated(id=snapshot.id, revoke_token=snapshot.revoke_token)


@router.get("/{share_id}", response_model=SharedItineraryResponse)
async def get_share(share_id: str, response: Response, db: Session = Depends(get_db)):
    """Fetch a public snapshot. No auth: the id is the capability. Keep it out of search indexes."""
    response.headers["X-Robots-Tag"] = "noindex"
    snapshot = db.query(SharedItinerary).filter(SharedItinerary.id == share_id).first()
    # An expired snapshot is treated as gone, so a leaked link stops working after the TTL. The DB
    # returns naive datetimes, so pin them to UTC before comparing.
    deadline = snapshot.expires_at if snapshot else None
    if deadline is not None and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=UTC)
    if not snapshot or is_expired(deadline, datetime.now(UTC)):
        raise HTTPException(status_code=404, detail="Shared itinerary not found")

    return SharedItineraryResponse(
        id=snapshot.id,
        title=snapshot.title,
        itinerary_text=snapshot.itinerary_text,
        geo=snapshot.geo,
        created_at=snapshot.created_at.isoformat(),
    )


@router.delete("/{share_id}", status_code=204)
async def revoke_share(share_id: str, req: RevokeRequest, db: Session = Depends(get_db)):
    """Revoke a snapshot. Requires the owner token returned at creation, so a recipient who only
    has the view link cannot delete it."""
    snapshot = db.query(SharedItinerary).filter(SharedItinerary.id == share_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Shared itinerary not found")
    if not can_revoke(snapshot.revoke_token, req.revoke_token):
        raise HTTPException(status_code=403, detail="Invalid revoke token")

    db.delete(snapshot)
    db.commit()
    logger.info(f"Revoked shared itinerary {share_id}")
