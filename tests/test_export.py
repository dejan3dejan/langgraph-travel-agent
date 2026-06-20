"""Tests for the PDF export endpoint and its filename helper. The Playwright renderer is stubbed, so
these run without a browser; the real render is exercised separately."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import export as export_module
from api.export import router
from core.pdf import PdfRendererUnavailable, sanitize_pdf_filename


def make_client(monkeypatch, render):
    monkeypatch.setattr(export_module, "render_pdf", render)
    app = FastAPI()
    app.include_router(router, prefix="/api/export")
    return TestClient(app)


# filename helper


def test_sanitize_keeps_a_readable_basename():
    assert sanitize_pdf_filename("3 days Trip to Rome") == "3 days Trip to Rome"


def test_sanitize_strips_path_and_header_breaking_characters():
    assert sanitize_pdf_filename("../../etc/passwd") == "etcpasswd"
    assert sanitize_pdf_filename('a"b\r\nc') == "abc"


def test_sanitize_falls_back_when_nothing_usable_remains():
    assert sanitize_pdf_filename("") == "itinerary"
    assert sanitize_pdf_filename(None) == "itinerary"
    assert sanitize_pdf_filename("///") == "itinerary"


def test_sanitize_caps_length():
    assert len(sanitize_pdf_filename("x" * 500)) == 80


# endpoint


def test_export_returns_the_rendered_pdf_as_an_attachment(monkeypatch):
    seen = {}

    async def fake_render(html):
        seen["html"] = html
        return b"%PDF-1.4 fake bytes"

    client = make_client(monkeypatch, fake_render)
    res = client.post("/api/export/pdf", json={"html": "<h1>Rome</h1>", "filename": "Trip to Rome"})

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"] == 'attachment; filename="Trip to Rome.pdf"'
    assert res.content == b"%PDF-1.4 fake bytes"
    assert seen["html"] == "<h1>Rome</h1>"


def test_export_rejects_an_empty_document(monkeypatch):
    async def fake_render(html):
        return b"%PDF"

    client = make_client(monkeypatch, fake_render)
    assert client.post("/api/export/pdf", json={"html": ""}).status_code == 422


def test_export_answers_503_when_the_renderer_is_unavailable(monkeypatch):
    async def fake_render(html):
        raise PdfRendererUnavailable("no chromium")

    client = make_client(monkeypatch, fake_render)
    assert client.post("/api/export/pdf", json={"html": "<p>x</p>"}).status_code == 503


def test_export_answers_500_when_a_render_fails(monkeypatch):
    async def fake_render(html):
        raise RuntimeError("boom")

    client = make_client(monkeypatch, fake_render)
    res = client.post("/api/export/pdf", json={"html": "<p>x</p>"})
    assert res.status_code == 500
    # The failure is reported, not papered over with an empty-but-200 body.
    assert res.content != b""
