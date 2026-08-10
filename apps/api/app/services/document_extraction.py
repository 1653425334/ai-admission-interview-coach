"""In-memory document extraction boundary for the Phase 2 analysis pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from app.parsers.pdf_text import ExtractedPdfPage, extract_pdf_pages
from app.schemas.interview_map import DocumentType, InputDocumentManifest


class DocumentReadError(ValueError):
    code = "DOCUMENT_READ_FAILED"


class DocumentIntegrityError(ValueError):
    code = "DOCUMENT_CONTENT_MISMATCH"


@dataclass(frozen=True, slots=True)
class AnalysisDocumentInput:
    document_id: UUID
    document_type: DocumentType
    sha256: str


class DocumentReader(Protocol):
    def read(self, document: AnalysisDocumentInput) -> bytes:
        """Return private PDF bytes for an already authorized document."""


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    manifest: InputDocumentManifest
    pages: tuple[ExtractedPdfPage, ...]

    def page(self, page_number: int) -> ExtractedPdfPage:
        for page in self.pages:
            if page.page_number == page_number:
                return page
        raise KeyError(f"No extracted page {page_number}")

    @property
    def canonical_text(self) -> str:
        return "\n\n".join(
            f"<<<PAGE:{page.page_number}>>>\n{page.normalized_text}" for page in self.pages
        )


class InMemoryDocumentReader:
    """Test-only private reader; deliberately has no I/O or network behavior."""

    def __init__(self, objects: dict[UUID, bytes]) -> None:
        self._objects = dict(objects)

    def read(self, document: AnalysisDocumentInput) -> bytes:
        try:
            return self._objects[document.document_id]
        except KeyError as error:
            raise DocumentReadError("Document bytes are unavailable") from error


class DocumentExtractionService:
    """Build an evidence-addressable document from private bytes and metadata."""

    def extract(
        self, document: AnalysisDocumentInput, reader: DocumentReader
    ) -> ExtractedDocument:
        try:
            content = reader.read(document)
        except DocumentReadError:
            raise
        except Exception as error:
            raise DocumentReadError("The private document could not be read") from error

        if not isinstance(content, bytes):
            raise DocumentReadError("The private document reader returned invalid content")
        if sha256(content).hexdigest() != document.sha256:
            raise DocumentIntegrityError("Document bytes do not match the input manifest")

        pages = extract_pdf_pages(content)
        return ExtractedDocument(
            manifest=InputDocumentManifest(
                document_id=document.document_id,
                document_type=document.document_type,
                sha256=document.sha256,
                page_count=len(pages),
            ),
            pages=pages,
        )
