"""User authentication, preferences, and trip management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.database import ChatSession, Trip, User, UserPreference, get_db
from core.logger import get_logger

from .auth import create_access_token, hash_password, require_user, verify_password

logger = get_logger(__name__)
router = APIRouter()


# ── Request/Response schemas ────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    created_at: str


class PreferencesRequest(BaseModel):
    default_budget: str | None = None
    default_interests: str | None = None
    num_travelers: int | None = None
    age_range: str | None = None
    trip_type: str | None = None
    start_location: str | None = None
    constraints: str | None = None


class PreferencesResponse(BaseModel):
    default_budget: str
    default_interests: str
    num_travelers: int
    age_range: str
    trip_type: str | None
    start_location: str | None
    constraints: str | None


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


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


# ── Auth endpoints ──────────────────────────────────────────────────────────


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account."""
    if db.query(User).filter(User.email == req.email).first():
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

    prefs = UserPreference(user_id=user.id)
    db.add(prefs)

    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    logger.info(f"New user registered: {user.username}")

    return TokenResponse(
        access_token=token,
        user={"id": user.id, "email": user.email, "username": user.username},
    )


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and get a JWT token."""
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_access_token(user.id)
    logger.info(f"User logged in: {user.username}")

    return TokenResponse(
        access_token=token,
        user={"id": user.id, "email": user.email, "username": user.username},
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(require_user)):
    """Get current user profile."""
    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        created_at=user.created_at.isoformat(),
    )


# ── Preferences endpoints ──────────────────────────────────────────────────


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
        constraints=prefs.constraints,
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
    for field, value in update_data.items():
        setattr(prefs, field, value)

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
        constraints=prefs.constraints,
    )


# ── Trip management ─────────────────────────────────────────────────────────


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


# ── Chat session management ────────────────────────────────────────────────


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
