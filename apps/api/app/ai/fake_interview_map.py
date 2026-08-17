"""Deterministic, offline InterviewMap generator used by Phase 2 tests."""

from __future__ import annotations

from uuid import UUID

from app.schemas.interview_map import (
    AssertionStrength,
    CandidateClaim,
    CandidateProfile,
    ApplicationContext,
    ClaimCategory,
    CoverageCondition,
    CoverageConditionType,
    DocumentType,
    Evidence,
    EvidenceSourceType,
    InterviewMap,
    InterviewRisk,
    InterviewValue,
    RiskCategory,
    SourceLocation,
    SuggestedQuestionType,
    VerificationObjective,
)
from app.services.document_extraction import ExtractedDocument


_ROBUSTNESS_EVIDENCE = (
    "Developed an attention-based model to improve robustness under noisy inputs."
)


class FakeInterviewMapLLM:
    """Return fixture-oriented maps without network access or model calls.

    The fake deliberately creates evidence only after locating a known literal in
    extracted CV text. This makes it unsuitable for production but valuable for
    deterministic tests of the evidence-to-map contract.
    """

    def generate(
        self,
        documents: list[ExtractedDocument],
        analysis_run_id: UUID,
        application_context: ApplicationContext | None = None,
    ) -> InterviewMap:
        documents_by_type = {document.manifest.document_type: document for document in documents}
        cv_document = documents_by_type[DocumentType.CV]
        ps_document = documents_by_type[DocumentType.PS]
        evidence = self._robustness_evidence(cv_document)

        if evidence is None:
            return InterviewMap(
                schema_version="interview-map-v1",
                analysis_run_id=analysis_run_id,
                input_manifest=[cv_document.manifest, ps_document.manifest],
                candidate_profile=CandidateProfile(
                    overview="No high-value fixture claim was found in the supplied materials."
                ),
            )

        claim = CandidateClaim(
            claim_id="claim-001",
            category=ClaimCategory.PERFORMANCE_IMPROVEMENT,
            statement="The proposed attention-based method improved robustness.",
            assertion_strength=AssertionStrength.EXPLICIT,
            evidence_ids=[evidence.evidence_id],
            interview_value=InterviewValue.HIGH,
        )
        objective = VerificationObjective(
            objective_id="obj-001",
            risk_id="risk-001",
            target_claim_id=claim.claim_id,
            verification_goal=(
                "Verify whether the candidate can explain the robustness definition, "
                "evaluation method, baseline, and concrete result."
            ),
            coverage_conditions=[
                CoverageCondition(
                    condition_id="cond-001",
                    type=CoverageConditionType.NAMES_TEST,
                    description="Names the robustness or perturbation test used.",
                    required=True,
                ),
                CoverageCondition(
                    condition_id="cond-002",
                    type=CoverageConditionType.EXPLAINS_BASELINE,
                    description="Explains the baseline used for comparison.",
                    required=True,
                ),
                CoverageCondition(
                    condition_id="cond-003",
                    type=CoverageConditionType.PROVIDES_RESULT,
                    description="Provides a concrete comparison or result.",
                    required=True,
                ),
            ],
        )
        risk = InterviewRisk(
            risk_id="risk-001",
            category=RiskCategory.EVIDENCE_GAP,
            title="Robustness improvement lacks evaluation evidence",
            severity=4,
            evidence_ids=[evidence.evidence_id],
            claim_id=claim.claim_id,
            reason=(
                "The material claims improved robustness but does not provide a test, "
                "baseline, or result."
            ),
            objectives=[objective],
            suggested_question_types=[
                SuggestedQuestionType.EVIDENCE_PROBE,
                SuggestedQuestionType.TECHNICAL_DEPTH_PROBE,
            ],
            max_followups=2,
        )
        return InterviewMap(
            schema_version="interview-map-v1",
            analysis_run_id=analysis_run_id,
            input_manifest=[cv_document.manifest, ps_document.manifest],
            candidate_profile=CandidateProfile(
                overview="The candidate reports an attention-based robustness project.",
                research_interests=["reliable machine learning"],
                high_value_claim_ids=[claim.claim_id],
                missing_or_uncertain_information=[
                    "The evaluation baseline and numerical result are not stated."
                ],
            ),
            evidence=[evidence],
            claims=[claim],
            risks=[risk],
            priority_risk_ids=[risk.risk_id],
        )

    @staticmethod
    def _robustness_evidence(document: ExtractedDocument) -> Evidence | None:
        for page in document.pages:
            start_offset = page.normalized_text.find(_ROBUSTNESS_EVIDENCE)
            if start_offset >= 0:
                return Evidence(
                    evidence_id="ev-001",
                    source_type=EvidenceSourceType.APPLICATION_DOCUMENT,
                    document_id=document.manifest.document_id,
                    document_type=document.manifest.document_type,
                    location=SourceLocation(
                        page_number=page.page_number,
                        start_offset=start_offset,
                        end_offset=start_offset + len(_ROBUSTNESS_EVIDENCE),
                    ),
                    original_text=_ROBUSTNESS_EVIDENCE,
                )
        return None
