"""User authentication, preferences, and trip management endpoints."""

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core import email as email_boundary
from core.database import AuthToken, ChatSession, Trip, User, UserPreference, get_db
from core.logger import get_logger
from core.schemas import IntakePrefs, TravelConstraints, intake_to_preference_columns
from core.tokens import generate_token, hash_token, is_token_usable, token_expires_at

from .auth import create_access_token, hash_password, require_user, verify_password

logger = get_logger(__name__)
router = APIRouter()

PURPOSE_VERIFY = "email_verify"
PURPOSE_RESET = "password_reset"

EMAIL_VERIFY_TTL = timedelta(hours=int(os.getenv("EMAIL_VERIFY_TTL_HOURS", "24")))
PASSWORD_RESET_TTL = timedelta(minutes=int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "30")))


def _issue_token(db: Session, user_id: str, purpose: str, ttl: timedelta) -> str:
    """Create a single-use token row and return the raw token. Only its hash is stored; the raw
    value travels only in the email link. Caller commits."""
    raw = generate_token()
    now = datetime.now(UTC)
    db.add(
        AuthToken(
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_token(raw),
            expires_at=token_expires_at(now, ttl),
        )
    )
    return raw


def _consume_token(db: Session, raw: str, purpose: str) -> AuthToken | None:
    """Look up a usable token by hash for the given purpose and mark it used. Returns the row, or
    None when no live, unused, matching token exists. Caller commits."""
    now = datetime.now(UTC)
    row = db.query(AuthToken).filter(AuthToken.token_hash == hash_token(raw), AuthToken.purpose == purpose).first()
    if not row:
        return None
    # The DB returns naive datetimes; pin them to UTC before comparing.
    expires = row.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if not is_token_usable(row.token_hash, raw, expires, row.used_at, now):
        return None
    row.used_at = now
    return row


async def _send_verification_email(to: str, raw: str) -> None:
    link = email_boundary.build_verify_link(email_boundary.app_base_url(), raw)
    subject, html, text = email_boundary.verification_email(link)
    await email_boundary.send_email(to, subject, html, text)


async def _send_reset_email(to: str, raw: str) -> None:
    link = email_boundary.build_reset_link(email_boundary.app_base_url(), raw)
    subject, html, text = email_boundary.password_reset_email(link)
    await email_boundary.send_email(to, subject, html, text)


# Request/Response schemas


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    session_id: str | None = None
    # Anonymous intake prefs carried over from localStorage, seeded onto the new profile so the
    # frictionless anon-to-registered handoff keeps what the user already told us.
    preferences: IntakePrefs | None = None


class LoginRequest(BaseModel):
    email: str
    password: str
    session_id: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    email_verified: bool
    created_at: str


class ProfileUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=50)
    email: str | None = Field(default=None, min_length=3, max_length=255)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6, max_length=128)


class AccountDeleteRequest(BaseModel):
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=6, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str


class PreferencesRequest(BaseModel):
    default_budget: str | None = None
    default_interests: str | None = None
    num_travelers: int | None = None
    age_range: str | None = None
    trip_type: str | None = None
    start_location: str | None = None
    constraints: TravelConstraints | None = None


class PreferencesResponse(BaseModel):
    default_budget: str
    default_interests: str
    num_travelers: int
    age_range: str
    trip_type: str | None
    start_location: str | None
    constraints: TravelConstraints | None


class TripSummary(BaseModel):
    id: str
    destination: str | None
    duration: str | None
    budget: str | None
    created_at: str


class TripDetail(TripSummary):
    interests: str | None
    itinerary_text: str | None
    session_id: str | None
    geo: dict | None = None


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class SessionDetail(BaseModel):
    session_id: str
    title: str
    history: list[dict]


# Auth endpoints


def _claim_session(db: Session, session_id: str | None, user_id: str) -> None:
    """Assign an anonymous session (and its trips) to a user. Never touches a session that is
    already owned by someone else."""
    if not session_id:
        return
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id, ChatSession.user_id.is_(None)).first()
    if not session:
        return
    session.user_id = user_id
    db.query(Trip).filter(Trip.session_id == session_id, Trip.user_id.is_(None)).update({"user_id": user_id})


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Create a new user account and send a verification email."""
    if db.query(User).filter(User.email == req.email.lower().strip()).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        email=req.email.lower().strip(),
        username=req.username.strip(),
        hashed_password=hash_password(req.password),
    )
    db.add(user)
    db.flush()

    prefs = UserPreference(user_id=user.id, **intake_to_preference_columns(req.preferences))
    db.add(prefs)

    _claim_session(db, req.session_id, user.id)

    verify_raw = _issue_token(db, user.id, PURPOSE_VERIFY, EMAIL_VERIFY_TTL)

    db.commit()
    db.refresh(user)

    # Send after commit so a slow or failed provider never blocks or rolls back signup.
    background_tasks.add_task(_send_verification_email, user.email, verify_raw)

    token = create_access_token(user.id)
    logger.info(f"New user registered: {user.username}")

    return TokenResponse(
        access_token=token,
        user={
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "email_verified": user.email_verified,
        },
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and get a JWT token."""
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    _claim_session(db, req.session_id, user.id)
    db.commit()

    token = create_access_token(user.id)
    logger.info(f"User logged in: {user.username}")

    return TokenResponse(
        access_token=token,
        user={
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "email_verified": user.email_verified,
        },
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(require_user)):
    """Get current user profile."""
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        email_verified=user.email_verified,
        created_at=user.created_at.isoformat(),
    )


@router.patch("/me", response_model=UserResponse)
async def update_me(
    req: ProfileUpdateRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Edit profile basics. Changing the email resets verification and sends a fresh link."""
    if req.username is not None and req.username.strip() != user.username:
        new_username = req.username.strip()
        if db.query(User).filter(User.username == new_username, User.id != user.id).first():
            raise HTTPException(status_code=409, detail="Username already taken")
        user.username = new_username

    email_changed = False
    if req.email is not None and req.email.lower().strip() != user.email:
        new_email = req.email.lower().strip()
        if db.query(User).filter(User.email == new_email, User.id != user.id).first():
            raise HTTPException(status_code=409, detail="Email already registered")
        user.email = new_email
        user.email_verified = False
        email_changed = True

    verify_raw = _issue_token(db, user.id, PURPOSE_VERIFY, EMAIL_VERIFY_TTL) if email_changed else None

    db.commit()
    db.refresh(user)

    if verify_raw:
        background_tasks.add_task(_send_verification_email, user.email, verify_raw)
    logger.info(f"Profile updated for {user.username}")

    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        email_verified=user.email_verified,
        created_at=user.created_at.isoformat(),
    )


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    req: PasswordChangeRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Change the password. Requires the current password."""
    if not verify_password(req.current_password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Current password is incorrect")

    user.hashed_password = hash_password(req.new_password)
    db.commit()
    logger.info(f"Password changed for {user.username}")


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(req: AccountDeleteRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Delete the account and everything tied to it. Requires the password as a confirmation. This
    is also the privacy 'delete my account' path, so the erasure is complete."""
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Password is incorrect")

    # Explicit cascade in one transaction: the trips/sessions/preferences FKs carry no ondelete, so
    # remove the user's rows directly rather than relying on the database.
    username = user.username
    db.query(Trip).filter(Trip.user_id == user.id).delete(synchronize_session=False)
    db.query(ChatSession).filter(ChatSession.user_id == user.id).delete(synchronize_session=False)
    db.query(UserPreference).filter(UserPreference.user_id == user.id).delete(synchronize_session=False)
    db.query(AuthToken).filter(AuthToken.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    logger.info(f"Account deleted: {username}")


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(req: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Confirm an email from a verification link. Idempotent only within the token's single use."""
    row = _consume_token(db, req.token, PURPOSE_VERIFY)
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")

    user = db.query(User).filter(User.id == row.user_id).first()
    if user:
        user.email_verified = True
    db.commit()
    return {"status": "verified"}


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    background_tasks: BackgroundTasks, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Send a fresh verification link to the signed-in user's current email."""
    if user.email_verified:
        return {"status": "already_verified"}

    verify_raw = _issue_token(db, user.id, PURPOSE_VERIFY, EMAIL_VERIFY_TTL)
    db.commit()
    background_tasks.add_task(_send_verification_email, user.email, verify_raw)
    return {"status": "sent"}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(req: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Begin a password reset. Always returns the same response so the endpoint cannot be used to
    discover which emails have accounts."""
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if user and user.is_active:
        reset_raw = _issue_token(db, user.id, PURPOSE_RESET, PASSWORD_RESET_TTL)
        db.commit()
        background_tasks.add_task(_send_reset_email, user.email, reset_raw)
    return {"status": "sent"}


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Set a new password from a reset link, then invalidate any other outstanding reset tokens."""
    row = _consume_token(db, req.token, PURPOSE_RESET)
    if not row:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    user.hashed_password = hash_password(req.new_password)
    db.query(AuthToken).filter(
        AuthToken.user_id == user.id,
        AuthToken.purpose == PURPOSE_RESET,
        AuthToken.used_at.is_(None),
    ).update({"used_at": datetime.now(UTC)}, synchronize_session=False)
    db.commit()
    logger.info(f"Password reset for {user.username}")
    return {"status": "reset"}


# Preferences endpoints


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get user's saved travel preferences."""
    prefs = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()

    if not prefs:
        prefs = UserPreference(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)

    return PreferencesResponse(
        default_budget=prefs.default_budget,
        default_interests=prefs.default_interests,
        num_travelers=prefs.num_travelers,
        age_range=prefs.age_range,
        trip_type=prefs.trip_type,
        start_location=prefs.start_location,
        constraints=prefs.travel_constraints,
    )


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    req: PreferencesRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Update user's saved travel preferences. Only provided fields are updated."""
    prefs = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()

    if not prefs:
        prefs = UserPreference(user_id=user.id)
        db.add(prefs)

    update_data = req.model_dump(exclude_none=True)
    # constraints maps to the structured travel_constraints column, not the generic setattr loop
    # (which would write the legacy string column).
    constraints = update_data.pop("constraints", None)
    for field, value in update_data.items():
        setattr(prefs, field, value)
    if constraints is not None:
        prefs.travel_constraints = constraints

    db.commit()
    db.refresh(prefs)
    logger.info(f"Preferences updated for {user.username}: {list(update_data.keys())}")

    return PreferencesResponse(
        default_budget=prefs.default_budget,
        default_interests=prefs.default_interests,
        num_travelers=prefs.num_travelers,
        age_range=prefs.age_range,
        trip_type=prefs.trip_type,
        start_location=prefs.start_location,
        constraints=prefs.travel_constraints,
    )


# Trip management


@router.get("/trips", response_model=list[TripSummary])
async def list_trips(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """List all saved trips for the current user."""
    trips = db.query(Trip).filter(Trip.user_id == user.id).order_by(Trip.created_at.desc()).all()

    return [
        TripSummary(
            id=t.id,
            destination=t.destination,
            duration=t.duration,
            budget=t.budget,
            created_at=t.created_at.isoformat(),
        )
        for t in trips
    ]


@router.get("/trips/{trip_id}", response_model=TripDetail)
async def get_trip(trip_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get a specific saved trip with full itinerary."""
    trip = db.query(Trip).filter(Trip.id == trip_id, Trip.user_id == user.id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    return TripDetail(
        id=trip.id,
        destination=trip.destination,
        duration=trip.duration,
        budget=trip.budget,
        interests=trip.interests,
        itinerary_text=trip.itinerary_text,
        session_id=trip.session_id,
        geo=trip.geo,
        created_at=trip.created_at.isoformat(),
    )


@router.delete("/trips/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(trip_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Delete a saved trip."""
    trip = db.query(Trip).filter(Trip.id == trip_id, Trip.user_id == user.id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    db.delete(trip)
    db.commit()
    logger.info(f"Trip {trip_id} deleted by {user.username}")


# Chat session management


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """List all chat sessions for the current user."""
    sessions = (
        db.query(ChatSession).filter(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc()).all()
    )

    return [
        SessionSummary(
            session_id=s.session_id,
            title=s.title or "New Chat",
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
            message_count=len(s.data.get("history", [])) if s.data else 0,
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get a chat session's full history so the client can resume the conversation."""
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id, ChatSession.user_id == user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionDetail(
        session_id=session.session_id,
        title=session.title or "New Chat",
        history=session.data.get("history", []) if session.data else [],
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Delete a chat session and its associated trips."""
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id, ChatSession.user_id == user.id).first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    db.query(Trip).filter(Trip.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    logger.info(f"Session {session_id} deleted by {user.username}")
