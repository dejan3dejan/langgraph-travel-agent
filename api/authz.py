"""Authorization for trip collaboration.

Ownership lives on Trip.user_id; collaborators live in trip_members with a viewer (read) or editor
(read + edit) role. Access to a chat session is derived from membership of the trip that owns that
session_id, so the same rules cover both the saved trip and the conversation behind it.

The pure helpers decide access from already-fetched values, so the rules are testable without a DB.
The resolvers below do the lookups at the boundary and return None for both "no access" and "not
found" so callers can 404 uniformly without leaking whether a trip exists.
"""

from sqlalchemy.orm import Session

from core.database import ChatSession, Trip, TripMember, User

VIEWER = "viewer"
EDITOR = "editor"
OWNER = "owner"
_MEMBER_ROLES = (VIEWER, EDITOR)


def access_role(owner_id: str | None, member_role: str | None, user_id: str | None) -> str | None:
    """The effective role a user has: 'owner' if they own the trip, else their membership role
    ('editor'/'viewer'), else None. None means no access at all."""
    if user_id and owner_id and user_id == owner_id:
        return OWNER
    if member_role in _MEMBER_ROLES:
        return member_role
    return None


def role_can_edit(role: str | None) -> bool:
    """Owners and editors may edit; viewers and non-members may not."""
    return role in (OWNER, EDITOR)


def role_can_read(role: str | None) -> bool:
    """Any granted role may read; only None (no access) is denied."""
    return role is not None


def trip_access(db: Session, trip_id: str, user: User | None) -> str | None:
    """The user's effective role on a trip, or None if the trip is missing or they have no access."""
    if not user:
        return None
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        return None
    member = db.query(TripMember).filter(TripMember.trip_id == trip_id, TripMember.user_id == user.id).first()
    return access_role(trip.user_id, member.role if member else None, user.id)


def session_access(db: Session, session_id: str, user: User | None) -> str | None:
    """The user's effective role on a chat session, derived from the trip(s) under that session_id.
    The session owner has owner access even before any trip is saved."""
    if not user:
        return None
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if not session:
        return None
    if session.user_id and session.user_id == user.id:
        return OWNER
    member = (
        db.query(TripMember)
        .join(Trip, Trip.id == TripMember.trip_id)
        .filter(Trip.session_id == session_id, TripMember.user_id == user.id)
        .first()
    )
    return member.role if member else None


def can_edit_session(db: Session, session_id: str, user: User | None) -> bool:
    """Edit gate for the chat endpoints. A session that does not exist yet (fresh chat) or one with
    no owner (the anonymous flow) is open; an owned session requires the requester to be its owner or
    an editor member."""
    session = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
    if session is None or session.user_id is None:
        return True
    return role_can_edit(session_access(db, session_id, user))
