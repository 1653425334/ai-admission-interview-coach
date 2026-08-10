"""Page-preserving text extraction for already validated PDF bytes."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


class PdfTextExtractionError(ValueError):
    code = "PDF_PARSE_FAILED"


class EmptyExtractedTextError(PdfTextExtractionError):
    code = "EMPTY_EXTRACTED_TEXT"


@dataclass(frozen=True, slots=True)
class ExtractedPdfPage:
    """The raw and canonical variants of one extracted PDF page."""

    page_number: int
    raw_text: str
    normalized_text: str


def normalize_extracted_text(text: str) -> str:
    """Produce canonical text while retaining deterministic evidence offsets.

    Only line endings, NUL characters and horizontal whitespace are normalized.
    Offsets used by M2 evidence always refer to this exact canonical string, not
    the PDF byte stream or a later model-generated rewrite.
    """

    normalized_lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").split("\n"):
        normalized_lines.append(" ".join(line.replace("\t", " ").split()))
    return "\n".join(normalized_lines).strip()


def extract_pdf_pages(content: bytes) -> tuple[ExtractedPdfPage, ...]:
    """Extract all pages without losing their original page numbers."""

    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise PdfTextExtractionError("Encrypted PDFs cannot be extracted")
        extracted_pages: list[ExtractedPdfPage] = []
        for index, page in enumerate(reader.pages, start=1):
            raw_text = page.extract_text() or ""
            extracted_pages.append(
                ExtractedPdfPage(
                    page_number=index,
                    raw_text=raw_text,
                    normalized_text=normalize_extracted_text(raw_text),
                )
            )
        pages = tuple(extracted_pages)
    except PdfTextExtractionError:
        raise
    except Exception as error:
        raise PdfTextExtractionError("The PDF text could not be extracted") from error

    if not pages or not any(page.normalized_text for page in pages):
        raise EmptyExtractedTextError("The PDF contains no extractable text")
    return pages
