"""Unit tests for _resolve_secret_key — pure fail-loud check, no env/IO."""

import pytest

from api.auth import _DEV_SECRET_DEFAULT, _resolve_secret_key


def test_dev_allows_unset_default():
    assert _resolve_secret_key(None, "development") == _DEV_SECRET_DEFAULT
    assert _resolve_secret_key("", "development") == _DEV_SECRET_DEFAULT


def test_dev_keeps_custom_secret():
    assert _resolve_secret_key("a-real-secret", "development") == "a-real-secret"


def test_production_keeps_custom_secret():
    assert _resolve_secret_key("a-real-secret", "production") == "a-real-secret"


@pytest.mark.parametrize("secret", [None, "", _DEV_SECRET_DEFAULT])
def test_production_rejects_missing_or_default(secret):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        _resolve_secret_key(secret, "production")


def test_environment_is_case_insensitive():
    with pytest.raises(RuntimeError):
        _resolve_secret_key(_DEV_SECRET_DEFAULT, "Production")
