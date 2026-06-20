"""Itinerary PDF export.

The client posts the same self-contained HTML document it would otherwise print, and we render it to
a PDF download server-side (see core.pdf). This gives a one-click, crisp file on every device instead
of leaning on the browser print dialog, which is awkward on mobile.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.logger import get_logger
from core.pdf import PdfRendererUnavailable, render_pdf, sanitize_pdf_filename

logger = get_logger(__name__)
router = APIRouter()


class ExportRequest(BaseModel):
    # The fully assembled export document. Capped so a single request can't hand the renderer an
    # unbounded payload; the real document is a few tens of KB.
    html: str = Field(..., min_length=1, max_length=1_000_000)
    filename: str | None = Field(default=None, max_length=200)


@router.post("/pdf")
async def export_pdf(req: ExportRequest) -> Response:
    """Render the posted itinerary document to a PDF download."""
    name = sanitize_pdf_filename(req.filename)
    try:
        pdf = await render_pdf(req.html)
    except PdfRendererUnavailable:
        logger.error("PDF export requested but the renderer is unavailable")
        raise HTTPException(status_code=503, detail="PDF export is unavailable.") from None
    except Exception as e:
        logger.error(f"PDF render failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to render the PDF.") from None

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )
