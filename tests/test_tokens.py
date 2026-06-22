"""Unit tests for auth-token helpers (generation, hashing, expiry, single-use). Pure, no DB."""

from datetime import UTC, datetime, timedelta

from core.tokens import (
    generate_token,
    hash_token,
    is_token_expired,
    is_token_prunable,
    is_token_usable,
    token_expires_at,
    verify_token,
)

# generation


def test_generate_token_is_urlsafe_and_high_entropy():
    raw = generate_token()
    # secrets.token_urlsafe(32) yields ~43 chars; long enough to be unguessable.
    assert len(raw) >= 32
    assert all(c.isalnum() or c in "-_" for c in raw)


def test_generate_token_is_unique_across_calls():
    assert len({generate_token() for _ in range(100)}) == 100


# hashing


def test_hash_token_is_deterministic():
    raw = generate_token()
    assert hash_token(raw) == hash_token(raw)


def test_hash_token_never_equals_the_raw_token():
    raw = generate_token()
    assert hash_token(raw) != raw


def test_hash_token_differs_for_different_inputs():
    assert hash_token("a") != hash_token("b")


def test_hash_token_is_hex_sha256():
    digest = hash_token("anything")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


# verification (constant-time hash compare)


def test_verify_token_matches_the_hash_of_the_raw_value():
    raw = generate_token()
    assert verify_token(hash_token(raw), raw) is True


def test_verify_token_rejects_a_wrong_value():
    raw = generate_token()
    assert verify_token(hash_token(raw), "not-the-token") is False


def test_verify_token_rejects_missing_inputs():
    assert verify_token(None, "x") is False
    assert verify_token("deadbeef", None) is False
    assert verify_token(None, None) is False


# expiry


def test_token_expires_at_is_the_ttl_past_creation():
    created = datetime(2026, 6, 22, tzinfo=UTC)
    assert token_expires_at(created, timedelta(minutes=30)) == created + timedelta(minutes=30)


def test_is_token_expired_is_false_before_and_true_after_the_deadline():
    now = datetime(2026, 6, 22, tzinfo=UTC)
    assert is_token_expired(now + timedelta(seconds=1), now) is False
    assert is_token_expired(now - timedelta(seconds=1), now) is True


def test_is_token_expired_treats_a_missing_deadline_as_expired():
    # A token with no recorded deadline is unsafe to honor, so treat it as expired.
    assert is_token_expired(None, datetime.now(UTC)) is True


# single-use composition


def test_is_token_usable_requires_match_unexpired_and_unused():
    raw = generate_token()
    stored = hash_token(raw)
    now = datetime(2026, 6, 22, tzinfo=UTC)
    expires = now + timedelta(minutes=10)
    assert is_token_usable(stored, raw, expires, used_at=None, now=now) is True


def test_is_token_usable_is_false_when_the_hash_does_not_match():
    raw = generate_token()
    now = datetime(2026, 6, 22, tzinfo=UTC)
    expires = now + timedelta(minutes=10)
    assert is_token_usable(hash_token(raw), "wrong", expires, used_at=None, now=now) is False


def test_is_token_usable_is_false_when_expired():
    raw = generate_token()
    stored = hash_token(raw)
    now = datetime(2026, 6, 22, tzinfo=UTC)
    expires = now - timedelta(seconds=1)
    assert is_token_usable(stored, raw, expires, used_at=None, now=now) is False


def test_is_token_usable_is_false_when_already_used():
    raw = generate_token()
    stored = hash_token(raw)
    now = datetime(2026, 6, 22, tzinfo=UTC)
    expires = now + timedelta(minutes=10)
    used = now - timedelta(minutes=1)
    assert is_token_usable(stored, raw, expires, used_at=used, now=now) is False


# prunable (cleanup job)


def test_is_token_prunable_when_used_even_if_unexpired():
    now = datetime(2026, 6, 22, tzinfo=UTC)
    assert is_token_prunable(now + timedelta(minutes=10), used_at=now, now=now) is True


def test_is_token_prunable_when_expired_even_if_unused():
    now = datetime(2026, 6, 22, tzinfo=UTC)
    assert is_token_prunable(now - timedelta(seconds=1), used_at=None, now=now) is True


def test_is_token_not_prunable_when_live_and_unused():
    now = datetime(2026, 6, 22, tzinfo=UTC)
    assert is_token_prunable(now + timedelta(minutes=10), used_at=None, now=now) is False
