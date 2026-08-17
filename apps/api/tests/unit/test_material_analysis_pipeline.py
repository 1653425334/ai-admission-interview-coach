from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import UUID

import pytest

from app.ai.fake_interview_map import FakeInterviewMapLLM
from app.ai.deepseek_interview_map import (
    _build_evidence_catalog,
    _ground_evidence_to_source_pages,
    _include_referenced_catalog_evidence,
    _normalise_model_payload,
    _parse_model_json,
    _replace_catalog_evidence,
)
from app.parsers.pdf_text import EmptyExtractedTextError, PdfTextExtractionError, extract_pdf_pages
from app.schemas.interview_map import DocumentType, SourceLocation
from app.services.document_extraction import (
    AnalysisDocumentInput,
    DocumentExtractionService,
    DocumentReadError,
    InMemoryDocumentReader,
)
from app.services.evidence_validation import EvidenceValidationError, validate_evidence_against_documents
from app.services.material_analysis import MaterialAnalysisPipeline
from tests.pdf_factory import build_pdf


FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "milestone_two"
RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
CV_ID = UUID("22222222-2222-4222-8222-222222222222")
PS_ID = UUID("33333333-3333-4333-8333-333333333333")


def fixture_line(filename: str, prefix: str) -> str:
    for line in (FIXTURE_DIRECTORY / filename).read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"Fixture {filename} has no line beginning with {prefix!r}")


def analysis_inputs() -> tuple[list[AnalysisDocumentInput], InMemoryDocumentReader]:
    cv_text = fixture_line("attention_robustness_cv.txt", "Developed an attention-based")
    ps_text = fixture_line("attention_robustness_ps.txt", "I want to study reliable")
    cv_bytes = build_pdf(text=cv_text)
    ps_bytes = build_pdf(text=ps_text)
    inputs = [
        AnalysisDocumentInput(
            document_id=CV_ID,
            document_type=DocumentType.CV,
            sha256=sha256(cv_bytes).hexdigest(),
        ),
        AnalysisDocumentInput(
            document_id=PS_ID,
            document_type=DocumentType.PS,
            sha256=sha256(ps_bytes).hexdigest(),
        ),
    ]
    return inputs, InMemoryDocumentReader({CV_ID: cv_bytes, PS_ID: ps_bytes})


def test_extract_pdf_pages_preserves_page_boundaries_and_canonical_text() -> None:
    pages = extract_pdf_pages(build_pdf(pages=2, text="Evidence line"))

    assert [page.page_number for page in pages] == [1, 2]
    assert [page.normalized_text for page in pages] == ["Evidence line", "Evidence line"]
    assert all(page.raw_text == "Evidence line" for page in pages)


def test_extract_pdf_pages_rejects_empty_pdf() -> None:
    with pytest.raises(EmptyExtractedTextError) as error:
        extract_pdf_pages(build_pdf(text=None))

    assert error.value.code == "EMPTY_EXTRACTED_TEXT"


def test_extract_pdf_pages_rejects_damaged_pdf() -> None:
    with pytest.raises(PdfTextExtractionError) as error:
        extract_pdf_pages(b"%PDF-not-a-readable-document")

    assert error.value.code == "PDF_PARSE_FAILED"


def test_document_extraction_surfaces_reader_failure() -> None:
    class FailingReader:
        def read(self, _document: AnalysisDocumentInput) -> bytes:
            raise RuntimeError("storage is unavailable")

    inputs, _reader = analysis_inputs()
    with pytest.raises(DocumentReadError) as error:
        DocumentExtractionService().extract(inputs[0], FailingReader())

    assert error.value.code == "DOCUMENT_READ_FAILED"


def test_fake_pipeline_is_deterministic_and_returns_a_validated_interview_map() -> None:
    inputs, reader = analysis_inputs()
    pipeline = MaterialAnalysisPipeline(
        extraction_service=DocumentExtractionService(),
        llm=FakeInterviewMapLLM(),
    )

    first = pipeline.analyze(inputs, reader, RUN_ID)
    second = pipeline.analyze(inputs, reader, RUN_ID)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.risks[0].evidence_ids == ["ev-001"]
    assert first.risks[0].verification_status == "UNVERIFIED"


def test_evidence_validation_rejects_text_not_present_in_extracted_page() -> None:
    inputs, reader = analysis_inputs()
    extraction_service = DocumentExtractionService()
    documents = [extraction_service.extract(item, reader) for item in inputs]
    interview_map = FakeInterviewMapLLM().generate(documents, RUN_ID)
    invalid_evidence = interview_map.evidence[0].model_copy(
        update={
            "original_text": "Invented evidence that is not in the PDF.",
            "location": SourceLocation(page_number=1),
        }
    )
    invalid_map = interview_map.model_copy(update={"evidence": [invalid_evidence]})

    with pytest.raises(EvidenceValidationError, match="not present"):
        validate_evidence_against_documents(invalid_map, documents)


def test_deepseek_payload_normalisation_removes_only_invalid_optional_offsets() -> None:
    payload = {
        "evidence": [
            {"location": {"page_number": 1, "start_offset": 0, "end_offset": 0}},
            {"location": {"page_number": 2, "start_offset": 3, "end_offset": 9}},
        ]
    }

    normalised = _normalise_model_payload(payload)

    assert normalised == {
        "evidence": [
            {"location": {"page_number": 1, "start_offset": None, "end_offset": None}},
            {"location": {"page_number": 2, "start_offset": 3, "end_offset": 9}},
        ]
    }


def test_deepseek_payload_normalisation_repairs_model_only_contract_fields() -> None:
    payload = {
        "evidence": [
            {
                "original_text": "a" * 301,
                "location": {"page_number": 1, "start_offset": None, "end_offset": None},
            }
        ],
        "risks": [
            {
                "category": "EVIDENCE_GAP",
                "verification_status": "VERIFIED",
                "objectives": [
                    {"coverage_conditions": [{"type": "REFLECTION_PROBE"}]}
                ],
            }
        ],
    }

    normalised = _normalise_model_payload(payload)

    assert normalised == {
        "evidence": [
            {
                "original_text": "a" * 300,
                "location": {"page_number": 1, "start_offset": None, "end_offset": None},
            }
        ],
        "risks": [
            {
                "category": "EVIDENCE_GAP",
                "verification_status": "UNVERIFIED",
                "objectives": [
                    {"coverage_conditions": [{"type": "PROVIDES_RESULT"}]}
                ],
            }
        ],
    }


def test_deepseek_evidence_grounding_replaces_a_close_paraphrase_with_pdf_text() -> None:
    inputs, reader = analysis_inputs()
    extraction_service = DocumentExtractionService()
    documents = [extraction_service.extract(item, reader) for item in inputs]
    payload = {
        "evidence": [
            {
                "document_id": str(CV_ID),
                "location": {"page_number": 1},
                "original_text": "Developed an attention-based model that improved robustness under noisy inputs.",
            }
        ]
    }

    grounded = _ground_evidence_to_source_pages(payload, documents)
    evidence = grounded["evidence"][0]

    assert evidence["original_text"] == fixture_line(
        "attention_robustness_cv.txt", "Developed an attention-based"
    )
    assert evidence["location"]["start_offset"] == 0


def test_deepseek_catalog_selection_replaces_model_copied_evidence_fields() -> None:
    inputs, reader = analysis_inputs()
    extraction_service = DocumentExtractionService()
    documents = [extraction_service.extract(item, reader) for item in inputs]
    catalog = _build_evidence_catalog(documents)
    selected = catalog[0]
    payload = {"evidence": [{"evidence_id": selected["evidence_id"], "original_text": "paraphrase"}]}

    resolved = _replace_catalog_evidence(payload, catalog)

    assert resolved == {"evidence": [selected]}


def test_deepseek_catalog_restores_an_omitted_but_referenced_evidence_entry() -> None:
    inputs, reader = analysis_inputs()
    extraction_service = DocumentExtractionService()
    catalog = _build_evidence_catalog(
        [extraction_service.extract(item, reader) for item in inputs]
    )
    selected = catalog[0]
    payload = {
        "evidence": [],
        "claims": [{"evidence_ids": [selected["evidence_id"]]}],
        "risks": [],
    }

    resolved = _include_referenced_catalog_evidence(payload, catalog)

    assert resolved == {"evidence": [selected], "claims": payload["claims"], "risks": []}


def test_deepseek_json_parser_accepts_a_fenced_object() -> None:
    assert _parse_model_json("```json\n{\"schema_version\": \"interview-map-v1\"}\n```") == {
        "schema_version": "interview-map-v1"
    }
