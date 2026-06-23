"""Endpoint tests for trip collaboration authorization, on a real SQLite schema.

The security boundary is the point: a non-member must not read or edit a shared trip or its session,
a viewer must not edit, and only the owner manages members. These run on an in-memory SQLite DB with
the auth and orchestrator boundaries overridden, so no network or LLM is touched.
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api import chat as chat_module
from api.auth import get_current_user, require_user
from api.chat import router as chat_router
from api.users import router as users_router
from core.database import Base, ChatSession, Trip, TripMember, User, get_db

# Only the tables collaboration touches; this skips the pgvector columns on SemanticCache, which
# SQLite cannot create.
_TABLES = [
    t
    for t in Base.metadata.sorted_tables
    if t.name in {"users", "user_preferences", "chat_sessions", "trips", "trip_members"}
]


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=_TABLES)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def seeded(db_session):
    """An owner with a trip + session, plus an editor, a viewer, and an outsider with no access."""
    owner = User(id="owner", email="owner@x.com", username="owner", hashed_password="x")
    editor = User(id="editor", email="editor@x.com", username="editor", hashed_password="x")
    viewer = User(id="viewer", email="viewer@x.com", username="viewer", hashed_password="x")
    outsider = User(id="outsider", email="outsider@x.com", username="outsider", hashed_password="x")
    db_session.add_all([owner, editor, viewer, outsider])

    session = ChatSession(session_id="sess-1", user_id="owner", data={"history": [{"role": "user", "content": "hi"}]})
    trip = Trip(id="trip-1", session_id="sess-1", user_id="owner", destination="Rome", itinerary_text="# Rome")
    db_session.add_all([session, trip])
    db_session.add(TripMember(id=str(uuid.uuid4()), trip_id="trip-1", user_id="editor", role="editor"))
    db_session.add(TripMember(id=str(uuid.uuid4()), trip_id="trip-1", user_id="viewer", role="viewer"))
    db_session.commit()
    return {"owner": owner, "editor": editor, "viewer": viewer, "outsider": outsider}


@pytest.fixture
def client(db_session, seeded):
    """A client whose acting user is set per-request via client.act_as(user)."""
    app = FastAPI()
    app.include_router(users_router, prefix="/api/users")
    app.include_router(chat_router, prefix="/api")

    acting = {"user": None}
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: acting["user"]

    def _require():
        if acting["user"] is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")
        return acting["user"]

    app.dependency_overrides[require_user] = _require

    c = TestClient(app)
    c.act_as = lambda user: acting.__setitem__("user", user)
    return c


# reading a trip


def test_owner_can_read_trip(client, seeded):
    client.act_as(seeded["owner"])
    res = client.get("/api/users/trips/trip-1")
    assert res.status_code == 200
    assert res.json()["role"] == "owner"


def test_viewer_can_read_trip(client, seeded):
    client.act_as(seeded["viewer"])
    res = client.get("/api/users/trips/trip-1")
    assert res.status_code == 200
    assert res.json()["role"] == "viewer"


def test_outsider_cannot_read_trip(client, seeded):
    client.act_as(seeded["outsider"])
    assert client.get("/api/users/trips/trip-1").status_code == 404


# reading a session


def test_editor_can_read_session(client, seeded):
    client.act_as(seeded["editor"])
    assert client.get("/api/users/sessions/sess-1").status_code == 200


def test_outsider_cannot_read_session(client, seeded):
    client.act_as(seeded["outsider"])
    assert client.get("/api/users/sessions/sess-1").status_code == 404


# editing via chat (the gate runs before the orchestrator, so a block needs no LLM)


def test_outsider_cannot_edit_session(client, seeded):
    client.act_as(seeded["outsider"])
    res = client.post("/api/chat", json={"session_id": "sess-1", "message": "change day 2"})
    assert res.status_code == 403


def test_viewer_cannot_edit_session(client, seeded):
    client.act_as(seeded["viewer"])
    res = client.post("/api/chat", json={"session_id": "sess-1", "message": "change day 2"})
    assert res.status_code == 403


def test_anonymous_cannot_edit_owned_session(client, seeded):
    client.act_as(None)
    res = client.post("/api/chat", json={"session_id": "sess-1", "message": "change day 2"})
    assert res.status_code == 403


def test_editor_is_allowed_to_edit_session(client, seeded, monkeypatch):
    async def fake_chat(user_text, history, prefs):
        return ("reply", history, None, {}, False, False)

    monkeypatch.setattr(chat_module.orchestrator, "chat", fake_chat)
    client.act_as(seeded["editor"])
    res = client.post("/api/chat", json={"session_id": "sess-1", "message": "tweak it"})
    assert res.status_code == 200


# managing members


def test_owner_can_invite_a_registered_user(client, seeded):
    client.act_as(seeded["owner"])
    res = client.post("/api/users/trips/trip-1/members", json={"email": "outsider@x.com", "role": "editor"})
    assert res.status_code == 201
    assert res.json() == {"user_id": "outsider", "username": "outsider", "email": "outsider@x.com", "role": "editor"}


def test_inviting_an_unknown_email_is_404(client, seeded):
    client.act_as(seeded["owner"])
    res = client.post("/api/users/trips/trip-1/members", json={"email": "nobody@x.com", "role": "viewer"})
    assert res.status_code == 404


def test_a_member_cannot_invite_others(client, seeded):
    client.act_as(seeded["editor"])
    res = client.post("/api/users/trips/trip-1/members", json={"email": "outsider@x.com", "role": "viewer"})
    assert res.status_code == 403


def test_outsider_cannot_list_members(client, seeded):
    client.act_as(seeded["outsider"])
    assert client.get("/api/users/trips/trip-1/members").status_code == 404


def test_a_member_can_remove_themselves_but_not_others(client, seeded):
    client.act_as(seeded["viewer"])
    assert client.delete("/api/users/trips/trip-1/members/editor").status_code == 403
    assert client.delete("/api/users/trips/trip-1/members/viewer").status_code == 204


# shared-trips listing


def test_shared_trips_lists_only_trips_shared_with_me(client, seeded):
    client.act_as(seeded["editor"])
    res = client.get("/api/users/trips/shared")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["id"] == "trip-1"
    assert body[0]["role"] == "editor"
    assert body[0]["owner"] == "owner"


def test_owner_sees_no_shared_trips(client, seeded):
    client.act_as(seeded["owner"])
    assert client.get("/api/users/trips/shared").json() == []
