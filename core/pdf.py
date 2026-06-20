"""Server-side PDF rendering for itinerary exports.

The client builds a self-contained, branded HTML document (inline CSS and an inline SVG route map)
and posts it here; we render it with headless Chromium so the download is crisp vector text on every
device, including mobile where the browser print dialog is clumsy.

Rendering arbitrary client HTML in a browser is only safe because the document needs neither scripts
nor network: JavaScript is disabled and every external http(s) request is aborted, which closes the
SSRF and exfiltration paths a poisoned itinerary could otherwise open. Concurrency is bounded and
each render is time-boxed so the endpoint can't be used to exhaust the box.
"""

import asyncio
import os
import re

from core.logger import get_logger

logger = get_logger(__name__)

_MAX_CONCURRENT = int(os.getenv("PDF_MAX_CONCURRENT", "2"))
_RENDER_TIMEOUT_S = float(os.getenv("PDF_RENDER_TIMEOUT_S", "20"))
_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9 _-]+")
_WHITESPACE = re.compile(r"\s+")


class PdfRendererUnavailable(RuntimeError):
    """Chromium (or Playwright itself) isn't installed, so no PDF can be produced. Distinct from a
    render that fails on the document, so the API can answer 503 rather than 500."""


def sanitize_pdf_filename(name: str | None, default: str = "itinerary") -> str:
    """A safe, header-injection-proof basename (no extension) for the download. Strips anything that
    isn't alphanumeric, space, dash, or underscore, collapses whitespace, and caps the length."""
    base = _UNSAFE_FILENAME.sub("", name or "").strip()
    base = _WHITESPACE.sub(" ", base)
    return (base or default)[:80]


def _render_sync(html: str) -> bytes:
    # Playwright's sync API drives the browser over its own thread, so it doesn't need the calling
    # event loop to support subprocesses. The async API does, which uvicorn's loop on Windows does
    # not (it raises a bare NotImplementedError on launch). render_pdf runs this in a worker thread.
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise PdfRendererUnavailable("Playwright is not installed") from e

    def _block_external(route):
        # The document is self-contained; any http(s) fetch is an injected resource, so refuse it.
        # data:, blob:, and about:blank carry the inline content and must pass through.
        if route.request.url.startswith(("http://", "https://")):
            route.abort()
        else:
            route.continue_()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            try:
                context = browser.new_context(java_script_enabled=False)
                page = context.new_page()
                page.set_default_timeout(_RENDER_TIMEOUT_S * 1000)
                page.route("**/*", _block_external)
                page.set_content(html, wait_until="load")
                return page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
            finally:
                browser.close()
    except PdfRendererUnavailable:
        raise
    except Exception as e:
        logger.error(f"Chromium render error: {e}")
        # A missing browser binary surfaces here (launch fails), not as ImportError above.
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            raise PdfRendererUnavailable("Chromium is not installed for Playwright") from e
        raise


async def render_pdf(html: str) -> bytes:
    """Render an HTML document to PDF bytes. The blocking render runs in a worker thread so it never
    stalls the event loop; bounded concurrency and a hard timeout keep a burst of exports from piling
    up browser processes."""
    async with _semaphore:
        try:
            return await asyncio.wait_for(asyncio.to_thread(_render_sync, html), timeout=_RENDER_TIMEOUT_S)
        except TimeoutError as e:
            logger.error("PDF render timed out after %ss", _RENDER_TIMEOUT_S)
            raise RuntimeError("PDF render timed out") from e
