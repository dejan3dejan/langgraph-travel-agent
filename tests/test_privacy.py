"""Privacy contract tests for data export and account deletion.

These pin the GDPR-ish guarantees on the already-shipped /me/export and DELETE /me endpoints: the
export carries everything tied to a user and nothing secret, and deletion leaves no orphaned rows
behind (nor touches another user's data). Runs on an isolated sqlite database holding only the
per-user tables, so it needs no Postgres and no pgvector.
"""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.auth import hash_password, require_user
from api.users import router
from core.database import AuthToken, ChatSession, Trip, User, UserPreference, get_db

# Only the per-user tables; this dodges the pgvector columns on the cache tables, which sqlite
# cannot emit DDL for and which hold no per-user data anyway.
_TABLES = [User.__table__, UserPreference.__table__, ChatSession.__table__, Trip.__table__, AuthToken.__table__]

_PER_USER_MODELS = [Trip, ChatSession, UserPreference, AuthToken]


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    for table in _TABLES:
        table.create(engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_user(db, email, username, with_data=True):
    """Create a user with a preference row, a session (with chat history), a trip, and an auth
    token. Returns the user."""
    user = User(
        email=email,
        username=username,
        hashed_password=hash_password("secret-pw"),
        email_verified=True,
        created_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()

    if with_data:
        db.add(
            UserPreference(user_id=user.id, default_budget="High", travel_constraints={"hard": ["vegan"], "soft": []})
        )
        session = ChatSession(
            session_id=f"sess-{username}",
            user_id=user.id,
            title="Trip to Rome",
            data={"history": [{"role": "user", "content": "plan Rome"}, {"role": "model", "content": "## Day 1"}]},
        )
        db.add(session)
        db.add(
            Trip(
                session_id=session.session_id,
                user_id=user.id,
                destination="Rome",
                duration="3 days",
                budget="High",
                interests="food",
                itinerary_text="## Day 1\nColosseum",
            )
        )
        db.add(
            AuthToken(
                user_id=user.id,
                purpose="email_verify",
                token_hash=f"hash-{username}",
                expires_at=datetime.now(UTC),
            )
        )
    db.commit()
    return user


def _client(db, user):
    app = FastAPI()
    app.include_router(router, prefix="/api/users")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_user] = lambda: user
    return TestClient(app)


# Export payload shape


def test_export_carries_account_preferences_trips_and_sessions(db_session):
    user = _seed_user(db_session, "rome@example.com", "romeo")
    res = _client(db_session, user).get("/api/users/me/export")

    assert res.status_code == 200
    payload = res.json()

    assert set(payload) == {"account", "preferences", "trips", "sessions"}
    assert payload["account"]["email"] == "rome@example.com"
    assert payload["account"]["username"] == "romeo"
    assert payload["preferences"]["constraints"] == {"hard": ["vegan"], "soft": []}

    assert len(payload["trips"]) == 1
    assert payload["trips"][0]["destination"] == "Rome"
    assert payload["trips"][0]["itinerary_text"].startswith("## Day 1")

    assert len(payload["sessions"]) == 1
    # The full chat history travels with the export, not just a summary.
    assert payload["sessions"][0]["history"] == [
        {"role": "user", "content": "plan Rome"},
        {"role": "model", "content": "## Day 1"},
    ]


def test_export_never_leaks_secrets(db_session):
    user = _seed_user(db_session, "secret@example.com", "keeper")
    payload = _client(db_session, user).get("/api/users/me/export").json()

    # The password hash and the internal token rows must never appear in a user-facing export.
    assert "hashed_password" not in payload["account"]
    blob = str(payload)
    assert "hash-keeper" not in blob
    assert hash_password("secret-pw") not in blob
    assert "auth_tokens" not in payload and "tokens" not in payload


# Deletion cascade (no orphaned rows, no collateral damage)


def test_delete_removes_every_row_tied_to_the_user(db_session):
    user = _seed_user(db_session, "gone@example.com", "ghost")
    client = _client(db_session, user)

    res = client.request("DELETE", "/api/users/me", json={"password": "secret-pw"})
    assert res.status_code == 204

    assert db_session.query(User).filter(User.id == user.id).count() == 0
    for model in _PER_USER_MODELS:
        leftover = db_session.query(model).filter(model.user_id == user.id).count()
        assert leftover == 0, f"orphaned rows left in {model.__tablename__}"


def test_delete_leaves_other_users_data_untouched(db_session):
    victim = _seed_user(db_session, "gone@example.com", "ghost")
    bystander = _seed_user(db_session, "stay@example.com", "keeper")

    _client(db_session, victim).request("DELETE", "/api/users/me", json={"password": "secret-pw"})

    assert db_session.query(User).filter(User.id == bystander.id).count() == 1
    for model in _PER_USER_MODELS:
        kept = db_session.query(model).filter(model.user_id == bystander.id).count()
        assert kept == 1, f"deletion wrongly removed {model.__tablename__} for another user"


def test_delete_rejects_a_wrong_password(db_session):
    user = _seed_user(db_session, "safe@example.com", "cautious")
    client = _client(db_session, user)

    res = client.request("DELETE", "/api/users/me", json={"password": "not-the-password"})
    assert res.status_code == 403
    # Nothing was removed on a failed confirmation.
    assert db_session.query(User).filter(User.id == user.id).count() == 1
