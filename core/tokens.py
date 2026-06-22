"""Single-use, expiring auth tokens for email verification and password reset.

The raw token is the capability handed to the user (in an email link); only its SHA-256 hash is
ever stored, so a database read cannot reveal a live token. Tokens are high-entropy CSPRNG values,
so a fast hash is the right primitive here (bcrypt is for low-entropy passwords). Pure and I/O-free:
generation, hashing, expiry, and usability are decided here; the DB row and the clock live at the
boundary.
"""

import hashlib
import secrets
from datetime import datetime, timedelta


def generate_token() -> str:
    """A URL-safe CSPRNG token. This raw value travels only in the email link, never to the DB."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """The SHA-256 hex digest stored in place of the raw token. Deterministic so lookups by hash
    work; one-way so a leaked row cannot reconstruct the token."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_token(stored_hash: str | None, provided_raw: str | None) -> bool:
    """Whether the provided raw token hashes to the stored hash. Constant-time compare; missing
    values never match."""
    if not stored_hash or not provided_raw:
        return False
    return secrets.compare_digest(stored_hash, hash_token(provided_raw))


def token_expires_at(created: datetime, ttl: timedelta) -> datetime:
    """The deadline past which a token stops being honored."""
    return created + ttl


def is_token_expired(expires_at: datetime | None, now: datetime) -> bool:
    """Whether the deadline has passed. A missing deadline is treated as expired: a token we cannot
    bound in time is unsafe to honor."""
    if expires_at is None:
        return True
    return expires_at <= now


def is_token_usable(
    stored_hash: str | None,
    provided_raw: str | None,
    expires_at: datetime | None,
    used_at: datetime | None,
    now: datetime,
) -> bool:
    """A token is usable only if it matches, has not expired, and has not already been consumed."""
    if used_at is not None:
        return False
    if is_token_expired(expires_at, now):
        return False
    return verify_token(stored_hash, provided_raw)


def is_token_prunable(expires_at: datetime | None, used_at: datetime | None, now: datetime) -> bool:
    """A token row is safe to delete once it has been consumed or has expired. Used and expired
    tokens are already refused by is_token_usable; pruning just keeps the table from growing."""
    if used_at is not None:
        return True
    return is_token_expired(expires_at, now)
