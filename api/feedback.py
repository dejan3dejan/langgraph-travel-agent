"""User feedback: optional star rating and/or free-text note, for a plan, an A/B choice, or the app.

Both fields are optional but a submission must carry at least one. Feedback may be anonymous; it is
attributed to a user only when one is signed in. The note is stored as inert data (no LLM ever reads
it) and length-capped."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import Feedback, User, get_db
from core.logger import get_logger

from .auth import get_current_user

logger = get_logger(__name__)
router = APIRouter()

ALLOWED_KINDS = {"plan", "compare", "app"}
MAX_MESSAGE = 4000


class FeedbackRequest(BaseModel):
    kind: str
    rating: int | None = Field(default=None, ge=1, le=5)
    message: str | None = Field(default=None, max_length=MAX_MESSAGE)
    session_id: str | None = None
    context: dict | None = None


class FeedbackResponse(BaseModel):
    ok: bool


def _valid_kind(kind: str) -> bool:
    """Whether the feedback context is one we accept. Deny-by-default for anything else."""
    return kind in ALLOWED_KINDS


def _has_content(rating: int | None, message: str | None) -> bool:
    """A submission must carry a rating or a non-blank note; an empty one is rejected, not stored."""
    return rating is not None or bool((message or "").strip())


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    payload: FeedbackRequest,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a feedback submission. Anonymous and authenticated users both allowed."""
    if not _valid_kind(payload.kind):
        raise HTTPException(status_code=422, detail="Unknown feedback kind.")
    if not _has_content(payload.rating, payload.message):
        raise HTTPException(status_code=422, detail="Add a rating or a note before sending.")

    note = (payload.message or "").strip() or None
    try:
        db.add(
            Feedback(
                id=str(uuid.uuid4()),
                kind=payload.kind,
                rating=payload.rating,
                message=note,
                session_id=payload.session_id,
                user_id=user.id if user else None,
                context=payload.context,
            )
        )
        db.commit()
    except Exception as e:
        logger.error(f"Failed to save feedback: {e}")
        raise HTTPException(status_code=500, detail="Could not save your feedback.") from None

    logger.info(f"Feedback received (kind={payload.kind}, rating={payload.rating}, user={user.id if user else 'anon'})")
    return FeedbackResponse(ok=True)
