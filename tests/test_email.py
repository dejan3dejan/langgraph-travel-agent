"""Tests for the email boundary's pure helpers and its safe-degrade behavior. No network."""

from core.email import build_reset_link, build_verify_link, password_reset_email, send_email, verification_email


def test_build_verify_link_uses_the_verify_query_param():
    assert build_verify_link("https://atlas.app", "tok123") == "https://atlas.app/?verify=tok123"


def test_build_reset_link_uses_the_reset_query_param():
    assert build_reset_link("https://atlas.app", "tok123") == "https://atlas.app/?reset=tok123"


def test_link_builders_trim_a_trailing_slash_on_the_base():
    assert build_verify_link("https://atlas.app/", "t") == "https://atlas.app/?verify=t"
    assert build_reset_link("https://atlas.app/", "t") == "https://atlas.app/?reset=t"


def test_message_bodies_carry_the_link_and_avoid_em_dashes():
    for link, (subject, html, text) in (
        ("https://atlas.app/?verify=t", verification_email("https://atlas.app/?verify=t")),
        ("https://atlas.app/?reset=t", password_reset_email("https://atlas.app/?reset=t")),
    ):
        assert subject
        assert link in html
        assert link in text
        assert "—" not in html and "—" not in text


async def test_send_email_degrades_to_a_noop_when_no_provider_is_configured(monkeypatch):
    # With no provider key the send must not raise and must report it did not send, so the caller
    # (signup, reset) still succeeds in dev.
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    sent = await send_email("a@b.com", "hi", "<p>body</p>", "body")
    assert sent is False
