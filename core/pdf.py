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


async def _render(html: str) -> bytes:
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise PdfRendererUnavailable("Playwright is not installed") from e

    async def _block_external(route):
        # The document is self-contained; any http(s) fetch is an injected resource, so refuse it.
        # data:, blob:, and about:blank carry the inline content and must pass through.
        if route.request.url.startswith(("http://", "https://")):
            await route.abort()
        else:
            await route.continue_()

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            try:
                context = await browser.new_context(java_script_enabled=False)
                page = await context.new_page()
                await page.route("**/*", _block_external)
                await page.set_content(html, wait_until="load")
                return await page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
            finally:
                await browser.close()
    except PdfRendererUnavailable:
        raise
    except Exception as e:
        # A missing browser binary surfaces here (launch fails), not as ImportError above.
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            raise PdfRendererUnavailable("Chromium is not installed for Playwright") from e
        raise


async def render_pdf(html: str) -> bytes:
    """Render an HTML document to PDF bytes. Bounded concurrency and a hard timeout keep a burst of
    exports from starving the event loop or piling up browser processes."""
    async with _semaphore:
        try:
            return await asyncio.wait_for(_render(html), timeout=_RENDER_TIMEOUT_S)
        except TimeoutError as e:
            logger.error("PDF render timed out after %ss", _RENDER_TIMEOUT_S)
            raise RuntimeError("PDF render timed out") from e
