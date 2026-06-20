"""Public, read-only itinerary sharing.

A share is an immutable snapshot of a delivered plan (markdown text + the {hotel, days[]} geo
payload) stored under an unguessable id. The snapshot deliberately carries no user_id, session, or
profile data, so a public link cannot leak who made it or their saved constraints.
"""

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import SharedItinerary, get_db
from core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_DEFAULT_TITLE = "Shared itinerary"


def extract_title(markdown: str) -> str:
    """The itinerary's first level-1 heading, or a generic fallback. Mirrors the title the canvas
    derives client-side so the shared page reads the same."""
    match = _H1.search(markdown or "")
    return match.group(1).strip() if match else _DEFAULT_TITLE


def new_share_id() -> str:
    """A URL-safe, CSPRNG token. Unguessable is the only access control on a public snapshot."""
    return secrets.token_urlsafe(16)


class ShareRequest(BaseModel):
    # Only the rendered plan and its map travel into a public snapshot; nothing user-identifying.
    itinerary_text: str = Field(..., min_length=1, max_length=20000)
    geo: dict | None = None
    title: str | None = Field(default=None, max_length=200)


class ShareCreated(BaseModel):
    id: str


class SharedItineraryResponse(BaseModel):
    id: str
    title: str
    itinerary_text: str
    geo: dict | None
    created_at: str


@router.post("", response_model=ShareCreated, status_code=201)
async def create_share(req: ShareRequest, db: Session = Depends(get_db)):
    """Persist a public snapshot of an itinerary and return its unguessable id."""
    snapshot = SharedItinerary(
        id=new_share_id(),
        title=(req.title or extract_title(req.itinerary_text)),
        itinerary_text=req.itinerary_text,
        geo=req.geo,
    )
    db.add(snapshot)
    db.commit()
    logger.info(f"Created shared itinerary {snapshot.id}")
    return ShareCreated(id=snapshot.id)


@router.get("/{share_id}", response_model=SharedItineraryResponse)
async def get_share(share_id: str, db: Session = Depends(get_db)):
    """Fetch a public snapshot. No auth: the id is the capability."""
    snapshot = db.query(SharedItinerary).filter(SharedItinerary.id == share_id).first()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Shared itinerary not found")

    return SharedItineraryResponse(
        id=snapshot.id,
        title=snapshot.title,
        itinerary_text=snapshot.itinerary_text,
        geo=snapshot.geo,
        created_at=snapshot.created_at.isoformat(),
    )
