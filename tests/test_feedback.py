"""Unit tests for feedback validation. Pure, no DB."""

from api.feedback import ALLOWED_KINDS, _has_content, _valid_kind


def test_valid_kind_accepts_the_three_contexts():
    assert all(_valid_kind(k) for k in ("plan", "compare", "app"))


def test_valid_kind_rejects_unknown():
    assert _valid_kind("spam") is False
    assert _valid_kind("") is False


def test_has_content_true_with_rating_only():
    # rating without a note is fine; the message is optional
    assert _has_content(5, None) is True


def test_has_content_true_with_message_only():
    # a note without stars is fine; the rating is optional
    assert _has_content(None, "loved it") is True


def test_has_content_false_when_both_empty():
    assert _has_content(None, None) is False
    assert _has_content(None, "   ") is False


def test_allowed_kinds_is_the_full_set():
    assert ALLOWED_KINDS == {"plan", "compare", "app"}
