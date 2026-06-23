"""User authentication, preferences, and trip management endpoints."""

import os
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from core import email as email_boundary
from core.database import AuthToken, ChatSession, Trip, TripMember, User, UserPreference, get_db
from core.logger import get_logger
from core.ratelimit import within_limit
from core.schemas import IntakePrefs, TravelConstraints, intake_to_preference_columns
from core.tokens import generate_token, hash_token, is_token_usable, token_expires_at

from .auth import create_access_token, hash_password, require_user, verify_password
from .authz import OWNER, role_can_read, session_access, trip_access

logger = get_logger(__name__)
router = APIRouter()

PURPOSE_VERIFY = "email_verify"
PURPOSE_RESET = "password_reset"

EMAIL_VERIFY_TTL = timedelta(hours=int(os.getenv("EMAIL_VERIFY_TTL_HOURS", "24")))
PASSWORD_RESET_TTL = timedelta(minutes=int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "30")))

# Per-email cap on the endpoints that send mail, so neither can be used to flood an inbox. This is
# in-process (resets on restart, not shared across workers); the global per-IP limiter in api/main
# is the other layer. Keyed by purpose+identifier.
EMAIL_SEND_MAX = int(os.getenv("EMAIL_SEND_MAX", "3"))
EMAIL_SEND_WINDOW = int(os.getenv("EMAIL_SEND_WINDOW", "3600"))
_email_send_hits: dict[str, list[float]] = {}


def _allow_email_send(key: str) -> bool:
    """Sliding-window gate for an email-sending action, keyed by purpose+email. Returns False once
    the cap is hit within the window."""
    allowed, _email_send_hits[key] = within_limit(
        _email_send_hits.get(key, []), time.time(), EMAIL_SEND_WINDOW, EMAIL_SEND_MAX
    )
    return allowed


def prune_expired_tokens(db: Session, now: datetime | None = None) -> int:
    """Delete used or expired auth-token rows and return the count removed. Shared by the admin
    endpoint and the periodic sweep. Caller commits."""
    now = now or datetime.now(UTC)
    return (
        db.query(AuthToken)
        .filter(or_(AuthToken.used_at.isnot(None), AuthToken.expires_at < now))
        .delete(synchronize_session=False)
    )


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
    # The viewer's role on this trip ('owner'|'editor'|'viewer'), so the client knows whether to
    # offer edit controls.
    role: str = OWNER


class SharedTripSummary(TripSummary):
    # A trip shared with the current user: who owns it and what role they were granted.
    role: str
    owner: str


class MemberInfo(BaseModel):
    user_id: str
    username: str
    email: str
    role: str


class InviteMemberRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    role: Literal["viewer", "editor"] = "viewer"


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
    logger.info(f"New user registered: {user.id}")

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
    logger.info(f"User logged in: {user.id}")

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
    logger.info(f"Profile updated for {user.id}")

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
    logger.info(f"Password changed for {user.id}")


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(req: AccountDeleteRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Delete the account and everything tied to it. Requires the password as a confirmation. This
    is also the privacy 'delete my account' path, so the erasure is complete."""
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=403, detail="Password is incorrect")

    # Explicit cascade in one transaction: the trips/sessions/preferences FKs carry no ondelete, so
    # remove the user's rows directly rather than relying on the database.
    user_id = user.id
    db.query(Trip).filter(Trip.user_id == user.id).delete(synchronize_session=False)
    db.query(ChatSession).filter(ChatSession.user_id == user.id).delete(synchronize_session=False)
    db.query(UserPreference).filter(UserPreference.user_id == user.id).delete(synchronize_session=False)
    db.query(AuthToken).filter(AuthToken.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    logger.info(f"Account deleted: {user_id}")


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

    if not _allow_email_send(f"{PURPOSE_VERIFY}:{user.id}"):
        raise HTTPException(status_code=429, detail="Too many verification emails. Please wait a while and try again.")

    verify_raw = _issue_token(db, user.id, PURPOSE_VERIFY, EMAIL_VERIFY_TTL)
    db.commit()
    background_tasks.add_task(_send_verification_email, user.email, verify_raw)
    return {"status": "sent"}


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(req: ForgotPasswordRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Begin a password reset. Always returns the same response so the endpoint cannot be used to
    discover which emails have accounts."""
    # Gate the send by email so a flood of requests cannot bomb an inbox. Over-limit requests still
    # return the same 202 with no send, keeping the no-enumeration guarantee intact.
    email = req.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if user and user.is_active and _allow_email_send(f"{PURPOSE_RESET}:{email}"):
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
    logger.info(f"Password reset for {user.id}")
    return {"status": "reset"}


@router.get("/me/export")
async def export_my_data(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Return everything stored about the signed-in user as one JSON payload. Read-only; the password
    hash and internal token rows are deliberately excluded. Rounds out the privacy story alongside
    account deletion."""
    prefs = db.query(UserPreference).filter(UserPreference.user_id == user.id).first()
    trips = db.query(Trip).filter(Trip.user_id == user.id).order_by(Trip.created_at.desc()).all()
    sessions = (
        db.query(ChatSession).filter(ChatSession.user_id == user.id).order_by(ChatSession.updated_at.desc()).all()
    )

    return {
        "account": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "email_verified": user.email_verified,
            "created_at": user.created_at.isoformat(),
        },
        "preferences": (
            None
            if not prefs
            else {
                "default_budget": prefs.default_budget,
                "default_interests": prefs.default_interests,
                "num_travelers": prefs.num_travelers,
                "age_range": prefs.age_range,
                "trip_type": prefs.trip_type,
                "start_location": prefs.start_location,
                "constraints": prefs.travel_constraints,
            }
        ),
        "trips": [
            {
                "id": t.id,
                "destination": t.destination,
                "duration": t.duration,
                "budget": t.budget,
                "interests": t.interests,
                "itinerary_text": t.itinerary_text,
                "geo": t.geo,
                "session_id": t.session_id,
                "created_at": t.created_at.isoformat(),
            }
            for t in trips
        ],
        "sessions": [
            {
                "session_id": s.session_id,
                "title": s.title or "New Chat",
                "created_at": s.created_at.isoformat(),
                "updated_at": s.updated_at.isoformat(),
                "history": s.data.get("history", []) if s.data else [],
            }
            for s in sessions
        ],
    }


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
    logger.info(f"Preferences updated for {user.id}: {list(update_data.keys())}")

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


@router.get("/trips/shared", response_model=list[SharedTripSummary])
async def list_shared_trips(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Trips that other users have shared with the current user, with the granted role and the
    owner's username so the sidebar can show them apart from owned trips."""
    rows = (
        db.query(Trip, TripMember.role, User.username)
        .join(TripMember, TripMember.trip_id == Trip.id)
        .join(User, User.id == Trip.user_id)
        .filter(TripMember.user_id == user.id)
        .order_by(Trip.created_at.desc())
        .all()
    )

    return [
        SharedTripSummary(
            id=trip.id,
            destination=trip.destination,
            duration=trip.duration,
            budget=trip.budget,
            created_at=trip.created_at.isoformat(),
            role=role,
            owner=owner_username,
        )
        for trip, role, owner_username in rows
    ]


@router.get("/trips/{trip_id}", response_model=TripDetail)
async def get_trip(trip_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Get a specific saved trip with full itinerary. Readable by the owner and any member."""
    role = trip_access(db, trip_id, user)
    if not role_can_read(role):
        raise HTTPException(status_code=404, detail="Trip not found")

    trip = db.query(Trip).filter(Trip.id == trip_id).first()
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
        role=role,
    )


@router.delete("/trips/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(trip_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Delete a saved trip."""
    trip = db.query(Trip).filter(Trip.id == trip_id, Trip.user_id == user.id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    db.delete(trip)
    db.commit()
    logger.info(f"Trip {trip_id} deleted by {user.id}")


# Trip collaboration (members)


def _require_trip_role(db: Session, trip_id: str, user: User, *, owner_only: bool) -> str:
    """Resolve the user's role on a trip or raise. 404 when they have no access at all (so a
    non-member cannot tell whether the trip exists); 403 when access exists but is below what the
    action needs."""
    role = trip_access(db, trip_id, user)
    if not role_can_read(role):
        raise HTTPException(status_code=404, detail="Trip not found")
    if owner_only and role != OWNER:
        raise HTTPException(status_code=403, detail="Only the trip owner can do that")
    return role


@router.get("/trips/{trip_id}/members", response_model=list[MemberInfo])
async def list_members(trip_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """List a trip's collaborators. Visible to the owner and any member."""
    _require_trip_role(db, trip_id, user, owner_only=False)
    rows = (
        db.query(TripMember, User).join(User, User.id == TripMember.user_id).filter(TripMember.trip_id == trip_id).all()
    )
    return [
        MemberInfo(user_id=member.user_id, username=u.username, email=u.email, role=member.role) for member, u in rows
    ]


@router.post("/trips/{trip_id}/members", response_model=MemberInfo, status_code=status.HTTP_201_CREATED)
async def add_member(
    trip_id: str, req: InviteMemberRequest, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Invite a registered user to a trip by email with a role. Owner only. Re-inviting an existing
    member updates their role."""
    _require_trip_role(db, trip_id, user, owner_only=True)

    invitee = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not invitee:
        raise HTTPException(status_code=404, detail="No registered user with that email")
    if invitee.id == user.id:
        raise HTTPException(status_code=400, detail="You already own this trip")

    member = db.query(TripMember).filter(TripMember.trip_id == trip_id, TripMember.user_id == invitee.id).first()
    if member:
        member.role = req.role
    else:
        member = TripMember(trip_id=trip_id, user_id=invitee.id, role=req.role, invited_by=user.id)
        db.add(member)
    db.commit()
    logger.info(f"Trip {trip_id}: {invitee.id} granted {req.role} by {user.id}")

    return MemberInfo(user_id=invitee.id, username=invitee.username, email=invitee.email, role=req.role)


@router.delete("/trips/{trip_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    trip_id: str, member_user_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)
):
    """Remove a collaborator. The owner can remove anyone; a member can remove only themselves."""
    role = _require_trip_role(db, trip_id, user, owner_only=False)
    if role != OWNER and member_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the trip owner can remove other members")

    member = db.query(TripMember).filter(TripMember.trip_id == trip_id, TripMember.user_id == member_user_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    db.delete(member)
    db.commit()
    logger.info(f"Trip {trip_id}: member {member_user_id} removed by {user.id}")


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
    """Get a chat session's full history so the client can resume the conversation. Readable by the
    session owner and any member of a trip under it."""
    if not role_can_read(session_access(db, session_id, user)):
        raise HTTPException(status_code=404, detail="Session not found")
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()

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
    logger.info(f"Session {session_id} deleted by {user.id}")
