from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Callable
from uuid import uuid4

from pypdf import PdfReader
from pypdf.errors import PdfReadError


@dataclass(frozen=True, slots=True)
class PageMetadata:
    doc_id: str
    page_number: int
    text: str
    extraction_status: str
    section_title: str | None = None


class PdfIngestionError(ValueError):
    """Actionable error while reading an uploaded PDF."""


def extract_pdf_pages(
    content: bytes,
    doc_id: str | None = None,
    reader_factory: Callable[..., object] = PdfReader,
) -> list[PageMetadata]:
    if not content:
        raise PdfIngestionError("The uploaded PDF is empty.")
    document_id = doc_id or str(uuid4())
    try:
        reader = reader_factory(BytesIO(content), strict=False)
        if getattr(reader, "is_encrypted", False):
            try:
                unlocked = reader.decrypt("")
            except Exception as exc:
                raise PdfIngestionError("The PDF is password protected.") from exc
            if not unlocked:
                raise PdfIngestionError("The PDF is password protected.")
        if not reader.pages:
            raise PdfIngestionError("The PDF contains no pages.")
        pages: list[PageMetadata] = []
        for number, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            status = "success" if text else "ocr_required"
            pages.append(PageMetadata(document_id, number, text, status))
        if not any(page.text for page in pages):
            raise PdfIngestionError(
                "No extractable text was found in the PDF; scanned pages require OCR before upload."
            )
        return pages
    except PdfIngestionError:
        raise
    except Exception as exc:
        raise PdfIngestionError("The PDF is corrupted or could not be parsed.") from exc
