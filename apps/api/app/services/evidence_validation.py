"""Validate InterviewMap evidence against actual extracted document text."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.interview_map import InterviewMap
from app.services.document_extraction import ExtractedDocument
from app.services.interview_map_validation import validate_interview_map


class EvidenceValidationError(ValueError):
    """Raised when a map cites text absent from its extracted input documents."""


def validate_evidence_against_documents(
    interview_map: InterviewMap, documents: Iterable[ExtractedDocument]
) -> None:
    """Require every Evidence citation to exist exactly in its declared page."""

    validate_interview_map(interview_map)
    extracted_by_document_id = {document.manifest.document_id: document for document in documents}
    expected_manifest = {
        document.document_id: (document.document_type, document.sha256, document.page_count)
        for document in interview_map.input_manifest
    }
    actual_manifest = {
        document_id: (
            document.manifest.document_type,
            document.manifest.sha256,
            document.manifest.page_count,
        )
        for document_id, document in extracted_by_document_id.items()
    }
    if actual_manifest != expected_manifest:
        raise EvidenceValidationError("Extracted documents do not match the InterviewMap input manifest")

    for evidence in interview_map.evidence:
        document = extracted_by_document_id[evidence.document_id]
        page = document.page(evidence.location.page_number)
        start_offset = evidence.location.start_offset
        end_offset = evidence.location.end_offset
        if start_offset is None:
            if evidence.original_text not in page.normalized_text:
                raise EvidenceValidationError(
                    f"evidence {evidence.evidence_id} text is not present in its declared page"
                )
            continue
        if page.normalized_text[start_offset:end_offset] != evidence.original_text:
            raise EvidenceValidationError(
                f"evidence {evidence.evidence_id} offsets do not locate its original text"
            )
