"""Transactional email boundary.

All network I/O for sending mail lives here. The rest of the app builds a link and a message and
hands them to send_email; whether a provider is configured, and which one, is decided by env. With
no provider key set the send degrades to a logged no-op so signup and reset still work in dev.

Tokens are a capability: the raw token rides inside the link and must never be logged. Nothing here
logs the link, the message body, or the provider response body. EMAIL_DEV_ECHO is the one, opt-in
exception for local testing.
"""

import os

import httpx

from .logger import get_logger

logger = get_logger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
SEND_TIMEOUT_SECONDS = 10.0


def _config() -> dict:
    """Read email config at call time so tests and a reloaded env see current values."""
    return {
        "provider": (os.getenv("EMAIL_PROVIDER") or "resend").strip().lower(),
        "resend_api_key": os.getenv("RESEND_API_KEY", "").strip(),
        "postmark_api_key": os.getenv("POSTMARK_API_KEY", "").strip(),
        "from_addr": os.getenv("EMAIL_FROM", "Atlas <onboarding@resend.dev>").strip(),
        "dev_echo": os.getenv("EMAIL_DEV_ECHO", "").strip().lower() in ("1", "true", "yes"),
    }


def app_base_url() -> str:
    """The public origin used to build email links. Trailing slash trimmed so link building is
    consistent."""
    return os.getenv("APP_BASE_URL", "http://localhost:5173").rstrip("/")


def build_verify_link(base_url: str, raw_token: str) -> str:
    """The email-verification link. The frontend reads ?verify=<token> on load (see main.jsx)."""
    return f"{base_url.rstrip('/')}/?verify={raw_token}"


def build_reset_link(base_url: str, raw_token: str) -> str:
    """The password-reset link. The frontend reads ?reset=<token> on load (see main.jsx)."""
    return f"{base_url.rstrip('/')}/?reset={raw_token}"


def verification_email(link: str) -> tuple[str, str, str]:
    """Subject, html, and text for the signup verification mail. Sentence-case copy."""
    subject = "Verify your Atlas email"
    html = (
        "<p>Welcome to Atlas.</p>"
        f'<p>Confirm this is your email by opening <a href="{link}">this link</a>. '
        "It expires in 24 hours.</p>"
        "<p>If you did not create an Atlas account, you can ignore this message.</p>"
    )
    text = f"Welcome to Atlas. Verify your email: {link}\nThis link expires in 24 hours."
    return subject, html, text


def password_reset_email(link: str) -> tuple[str, str, str]:
    """Subject, html, and text for the password-reset mail. Sentence-case copy."""
    subject = "Reset your Atlas password"
    html = (
        "<p>We received a request to reset your Atlas password.</p>"
        f'<p>Choose a new one with <a href="{link}">this link</a>. It expires in 30 minutes and can '
        "be used once.</p>"
        "<p>If you did not request this, you can ignore this message and your password stays the same.</p>"
    )
    text = f"Reset your Atlas password: {link}\nThis link expires in 30 minutes and can be used once."
    return subject, html, text


async def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    """Send one transactional email. Returns True if a provider accepted it, False if it degraded to
    a no-op or the provider rejected it. Never raises into the caller: a failed send must not fail
    the request that triggered it."""
    cfg = _config()

    if cfg["provider"] == "resend" and cfg["resend_api_key"]:
        return await _send_resend(cfg, to, subject, html, text)

    # No usable provider: degrade to a no-op. Log the recipient and subject only, never the body or
    # any link (the link carries the token).
    logger.warning(f"Email provider not configured; skipping send to {to} (subject: {subject!r})")
    if cfg["dev_echo"]:
        # Opt-in local affordance: surfaces the link so a developer can complete the flow without a
        # provider. Off by default so tokens never reach logs in any shared environment.
        logger.info(f"[EMAIL_DEV_ECHO] body for {to}: {text or html}")
    return False


async def _send_resend(cfg: dict, to: str, subject: str, html: str, text: str | None) -> bool:
    payload = {"from": cfg["from_addr"], "to": [to], "subject": subject, "html": html}
    if text:
        payload["text"] = text
    try:
        async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {cfg['resend_api_key']}"},
                json=payload,
            )
    except httpx.HTTPError as e:
        # Network/timeout failure. Log the class only; the request body holds the link.
        logger.error(f"Email send to {to} failed: {type(e).__name__}")
        return False

    if resp.status_code >= 400:
        # Status only. The response body can echo the rejected payload, which includes the link.
        logger.error(f"Email send to {to} rejected by provider (status {resp.status_code})")
        return False

    logger.info(f"Verification/reset email sent to {to}")
    return True
