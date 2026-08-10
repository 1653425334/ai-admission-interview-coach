"""Pure in-memory Phase 2 material-analysis pipeline."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.schemas.interview_map import InterviewMap
from app.services.document_extraction import (
    AnalysisDocumentInput,
    DocumentExtractionService,
    DocumentReader,
    ExtractedDocument,
)
from app.services.evidence_validation import validate_evidence_against_documents
from app.services.interview_map_validation import validate_interview_map


class InterviewMapGenerator(Protocol):
    def generate(
        self, documents: list[ExtractedDocument], analysis_run_id: UUID
    ) -> InterviewMap:
        """Generate a schema-shaped map from canonical extracted document text."""


class MaterialAnalysisPipeline:
    """Compose extraction, deterministic generation, and complete validation."""

    def __init__(
        self, *, extraction_service: DocumentExtractionService, llm: InterviewMapGenerator
    ) -> None:
        self._extraction_service = extraction_service
        self._llm = llm

    def analyze(
        self,
        inputs: list[AnalysisDocumentInput],
        reader: DocumentReader,
        analysis_run_id: UUID,
    ) -> InterviewMap:
        documents = self.extract_documents(inputs, reader)
        return self.generate_validated_map(documents, analysis_run_id)

    def extract_documents(
        self, inputs: list[AnalysisDocumentInput], reader: DocumentReader
    ) -> list[ExtractedDocument]:
        return [self._extraction_service.extract(document, reader) for document in inputs]

    def generate_validated_map(
        self, documents: list[ExtractedDocument], analysis_run_id: UUID
    ) -> InterviewMap:
        interview_map = self._llm.generate(documents, analysis_run_id)
        validate_interview_map(interview_map)
        validate_evidence_against_documents(interview_map, documents)
        return interview_map
