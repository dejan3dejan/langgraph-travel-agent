"""Unit tests for shared-itinerary helpers (title, ids, expiry, revoke auth). Pure, no DB."""

from datetime import UTC, datetime, timedelta

from api.share import can_revoke, expires_after, extract_title, is_expired, new_share_id


def test_extract_title_uses_the_markdown_heading():
    assert extract_title("# Trip to Rome\n## Day 1") == "Trip to Rome"


def test_extract_title_takes_the_first_heading_only():
    assert extract_title("intro\n# Lisbon long weekend\n# later heading") == "Lisbon long weekend"


def test_extract_title_falls_back_when_there_is_no_heading():
    assert extract_title("no heading here") == "Shared itinerary"
    assert extract_title("") == "Shared itinerary"


def test_extract_title_ignores_non_h1_headings():
    assert extract_title("## Day 1\n### morning") == "Shared itinerary"


def test_new_share_id_is_urlsafe_and_unguessably_long():
    sid = new_share_id()
    assert len(sid) >= 16
    assert all(c.isalnum() or c in "-_" for c in sid)


def test_new_share_id_is_unique_across_calls():
    assert len({new_share_id() for _ in range(100)}) == 100


# expiry


def test_expires_after_is_the_ttl_past_creation():
    created = datetime(2026, 6, 20, tzinfo=UTC)
    assert expires_after(created, days=30) == created + timedelta(days=30)


def test_is_expired_is_false_before_and_true_after_the_deadline():
    now = datetime(2026, 7, 1, tzinfo=UTC)
    assert is_expired(now + timedelta(seconds=1), now) is False
    assert is_expired(now - timedelta(seconds=1), now) is True


def test_is_expired_treats_a_missing_deadline_as_never_expiring():
    # legacy rows created before the column existed have no deadline
    assert is_expired(None, datetime.now(UTC)) is False


# revoke authorization


def test_can_revoke_only_with_the_exact_owner_token():
    assert can_revoke("secret-token", "secret-token") is True
    assert can_revoke("secret-token", "wrong") is False


def test_can_revoke_rejects_missing_tokens():
    assert can_revoke("secret-token", None) is False
    assert can_revoke(None, "anything") is False
    assert can_revoke(None, None) is False
