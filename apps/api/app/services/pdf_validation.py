"""Validation for uploaded, text-based PDF application documents."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.core.errors import ApiError

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 30


@dataclass(frozen=True, slots=True)
class ValidatedPdf:
    content: bytes
    sha256: str
    page_count: int


def _validation_error(*, status_code: int, code: str, message: str) -> ApiError:
    return ApiError(status_code=status_code, code=code, message=message)


def validate_pdf(content: bytes, content_type: str | None) -> ValidatedPdf:
    """Validate one PDF in a fixed, cheap-to-expensive order."""
    if content_type is None or content_type.strip().lower() != "application/pdf":
        raise _validation_error(
            status_code=422,
            code="INVALID_CONTENT_TYPE",
            message="The uploaded file must be a PDF.",
        )

    if len(content) > MAX_PDF_BYTES:
        raise _validation_error(
            status_code=413,
            code="FILE_TOO_LARGE",
            message="The PDF must be 10 MB or smaller.",
        )

    if not content.startswith(b"%PDF-"):
        raise _validation_error(
            status_code=422,
            code="INVALID_PDF_SIGNATURE",
            message="The uploaded file is not a valid PDF.",
        )

    content_sha256 = sha256(content).hexdigest()

    try:
        reader = PdfReader(BytesIO(content), strict=True)
    except (PyPdfError, ValueError, TypeError, OSError, KeyError, AttributeError, IndexError):
        raise _validation_error(
            status_code=422,
            code="INVALID_PDF",
            message="The PDF could not be read.",
        ) from None

    if reader.is_encrypted:
        raise _validation_error(
            status_code=422,
            code="ENCRYPTED_PDF_UNSUPPORTED",
            message="Encrypted PDFs are not supported.",
        )

    try:
        page_count = len(reader.pages)
    except (PyPdfError, ValueError, TypeError, OSError, KeyError, AttributeError, IndexError):
        raise _validation_error(
            status_code=422,
            code="INVALID_PDF",
            message="The PDF could not be read.",
        ) from None

    if page_count > MAX_PDF_PAGES:
        raise _validation_error(
            status_code=422,
            code="PDF_TOO_LONG",
            message="The PDF must contain no more than 30 pages.",
        )

    try:
        has_text = any((page.extract_text() or "").strip() for page in reader.pages)
    except (
        PyPdfError,
        ValueError,
        TypeError,
        OSError,
        UnicodeError,
        KeyError,
        AttributeError,
        IndexError,
    ):
        raise _validation_error(
            status_code=422,
            code="INVALID_PDF",
            message="The PDF text layer could not be read.",
        ) from None

    if not has_text:
        raise _validation_error(
            status_code=422,
            code="SCANNED_PDF_UNSUPPORTED",
            message="The PDF must contain extractable text.",
        )

    return ValidatedPdf(content=content, sha256=content_sha256, page_count=page_count)
