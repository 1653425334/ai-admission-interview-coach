"""Versioned, evidence-grounded material-analysis contracts for Milestone 2.

The map is immutable analysis output. Runtime interview questions, answers, and
evaluations intentionally do not belong in this module; they are Milestone 3
contracts which consume this map.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
MediumText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]


class DomainModel(BaseModel):
    """Reject unversioned or undeclared fields in persisted AI output."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocumentType(StrEnum):
    CV = "CV"
    PS = "PS"


class EvidenceSourceType(StrEnum):
    APPLICATION_DOCUMENT = "APPLICATION_DOCUMENT"


class ClaimCategory(StrEnum):
    TECHNICAL_CHOICE = "TECHNICAL_CHOICE"
    PROJECT_CONTRIBUTION = "PROJECT_CONTRIBUTION"
    METHOD_INNOVATION = "METHOD_INNOVATION"
    PERFORMANCE_IMPROVEMENT = "PERFORMANCE_IMPROVEMENT"
    RESEARCH_CONCLUSION = "RESEARCH_CONCLUSION"
    PERSONAL_OWNERSHIP = "PERSONAL_OWNERSHIP"
    MOTIVATION = "MOTIVATION"


class AssertionStrength(StrEnum):
    EXPLICIT = "EXPLICIT"
    IMPLIED = "IMPLIED"
    CONFLICTING = "CONFLICTING"


class InterviewValue(StrEnum):
    HIGH = "HIGH"


class CoverageConditionType(StrEnum):
    NAMES_TEST = "NAMES_TEST"
    EXPLAINS_BASELINE = "EXPLAINS_BASELINE"
    PROVIDES_RESULT = "PROVIDES_RESULT"
    EXPLAINS_MECHANISM = "EXPLAINS_MECHANISM"
    JUSTIFIES_CHOICE = "JUSTIFIES_CHOICE"
    DISTINGUISHES_OWNERSHIP = "DISTINGUISHES_OWNERSHIP"
    RESOLVES_INCONSISTENCY = "RESOLVES_INCONSISTENCY"
    CONNECTS_MOTIVATION_TO_EXPERIENCE = "CONNECTS_MOTIVATION_TO_EXPERIENCE"


class RiskCategory(StrEnum):
    TECHNICAL_UNDERSTANDING = "TECHNICAL_UNDERSTANDING"
    OWNERSHIP = "OWNERSHIP"
    EVIDENCE_GAP = "EVIDENCE_GAP"
    CONSISTENCY = "CONSISTENCY"
    MOTIVATION_DEPTH = "MOTIVATION_DEPTH"


class SuggestedQuestionType(StrEnum):
    EVIDENCE_PROBE = "EVIDENCE_PROBE"
    OWNERSHIP_PROBE = "OWNERSHIP_PROBE"
    TECHNICAL_DEPTH_PROBE = "TECHNICAL_DEPTH_PROBE"
    CONSISTENCY_PROBE = "CONSISTENCY_PROBE"
    MOTIVATION_PROBE = "MOTIVATION_PROBE"
    TRADEOFF_PROBE = "TRADEOFF_PROBE"
    REFLECTION_PROBE = "REFLECTION_PROBE"


class VerificationStatus(StrEnum):
    """Stable M2→M3 risk state vocabulary.

    M2 only produces UNVERIFIED. M3 owns all later state transitions.
    """

    UNVERIFIED = "UNVERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    VERIFIED = "VERIFIED"
    CONFIRMED_RISK = "CONFIRMED_RISK"


class SourceLocation(DomainModel):
    page_number: Annotated[int, Field(ge=1)]
    section: Annotated[str | None, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)] = None
    start_offset: Annotated[int | None, Field(ge=0)] = None
    end_offset: Annotated[int | None, Field(ge=0)] = None

    @model_validator(mode="after")
    def offsets_are_complete_and_ordered(self) -> "SourceLocation":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("start_offset and end_offset must be supplied together")
        if self.start_offset is not None and self.end_offset is not None:
            if self.end_offset <= self.start_offset:
                raise ValueError("end_offset must be greater than start_offset")
        return self


class Evidence(DomainModel):
    evidence_id: Identifier
    source_type: Literal[EvidenceSourceType.APPLICATION_DOCUMENT]
    document_id: UUID
    document_type: DocumentType
    location: SourceLocation
    original_text: ShortText


class CandidateClaim(DomainModel):
    claim_id: Identifier
    category: ClaimCategory
    statement: MediumText
    assertion_strength: AssertionStrength
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    interview_value: Literal[InterviewValue.HIGH]


class CoverageCondition(DomainModel):
    condition_id: Identifier
    type: CoverageConditionType
    description: MediumText
    required: bool


class VerificationObjective(DomainModel):
    objective_id: Identifier
    risk_id: Identifier
    target_claim_id: Identifier
    verification_goal: MediumText
    coverage_conditions: Annotated[list[CoverageCondition], Field(min_length=1)]

    @model_validator(mode="after")
    def includes_required_coverage_condition(self) -> "VerificationObjective":
        if not any(condition.required for condition in self.coverage_conditions):
            raise ValueError("at least one coverage condition must be required")
        return self


class InterviewRisk(DomainModel):
    risk_id: Identifier
    category: RiskCategory
    title: ShortText
    severity: Annotated[int, Field(ge=1, le=5)]
    evidence_ids: Annotated[list[Identifier], Field(min_length=1)]
    claim_id: Identifier
    reason: MediumText
    objectives: Annotated[list[VerificationObjective], Field(min_length=1)]
    suggested_question_types: Annotated[list[SuggestedQuestionType], Field(min_length=1)]
    max_followups: Annotated[int, Field(ge=0, le=2)]
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class CandidateProfile(DomainModel):
    """A display-oriented view whose factual anchors are Claim IDs.

    Profile prose is never an independently trusted source of fact. Consumers
    must use ``high_value_claim_ids`` to trace it back to validated claims and
    evidence; any new candidate fact belongs in CandidateClaim first.
    """

    overview: MediumText
    research_interests: list[ShortText] = Field(default_factory=list)
    high_value_claim_ids: list[Identifier] = Field(default_factory=list)
    missing_or_uncertain_information: list[ShortText] = Field(default_factory=list)


class InputDocumentManifest(DomainModel):
    document_id: UUID
    document_type: DocumentType
    sha256: Sha256
    page_count: Annotated[int, Field(ge=1)]


class InterviewMap(DomainModel):
    schema_version: Literal["interview-map-v1"]
    analysis_run_id: UUID
    input_manifest: Annotated[list[InputDocumentManifest], Field(min_length=2, max_length=2)]
    candidate_profile: CandidateProfile
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[CandidateClaim] = Field(default_factory=list)
    risks: list[InterviewRisk] = Field(default_factory=list)
    priority_risk_ids: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def requires_one_cv_and_one_ps(self) -> "InterviewMap":
        document_types = {document.document_type for document in self.input_manifest}
        if document_types != {DocumentType.CV, DocumentType.PS}:
            raise ValueError("input_manifest must contain exactly one CV and one PS")
        if len({document.document_id for document in self.input_manifest}) != 2:
            raise ValueError("input_manifest document IDs must be unique")
        return self
