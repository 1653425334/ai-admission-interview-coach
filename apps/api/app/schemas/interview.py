"""Versioned runtime contracts for Milestone 3 adaptive interviews.

These models consume an immutable M2 InterviewMap.  They deliberately keep
evaluation events separate from derived verification state: a model can judge
coverage, but only deterministic application code transitions a risk state.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.schemas.interview_map import DomainModel, Identifier, MediumText, RiskCategory, SuggestedQuestionType, VerificationStatus


AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
EvaluationText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
AnswerExcerpt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class InterviewSessionStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class InterviewTurnStatus(StrEnum):
    ASKED = "ASKED"
    ANSWERED = "ANSWERED"
    EVALUATED = "EVALUATED"


class CoverageResult(StrEnum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    UNCLEAR = "UNCLEAR"


class NextAction(StrEnum):
    FOLLOW_UP_CURRENT_OBJECTIVE = "FOLLOW_UP_CURRENT_OBJECTIVE"
    MOVE_TO_NEXT_OBJECTIVE = "MOVE_TO_NEXT_OBJECTIVE"
    MOVE_TO_NEXT_RISK = "MOVE_TO_NEXT_RISK"
    END_INTERVIEW = "END_INTERVIEW"


class InterviewQuestion(DomainModel):
    question_id: UUID
    session_id: UUID
    risk_id: Identifier
    objective_id: Identifier
    question_type: SuggestedQuestionType
    target_condition_ids: Annotated[list[Identifier], Field(min_length=1)]
    text: MediumText
    followup_index: Annotated[int, Field(ge=0, le=2)]
    parent_question_id: UUID | None = None
    sequence_number: Annotated[int, Field(ge=1)]


class ConditionEvaluation(DomainModel):
    condition_id: Identifier
    result: CoverageResult
    answer_excerpt: AnswerExcerpt | None = None
    reason: EvaluationText

    @model_validator(mode="after")
    def met_or_not_met_requires_evidence(self) -> "ConditionEvaluation":
        if self.result is not CoverageResult.UNCLEAR and self.answer_excerpt is None:
            raise ValueError("MET and NOT_MET evaluations must quote the answer")
        return self


class CommunicationFeedback(DomainModel):
    grammar: EvaluationText | None = None
    vocabulary: EvaluationText | None = None
    clarity: EvaluationText | None = None
    structure: EvaluationText | None = None
    conciseness: EvaluationText | None = None


class AnswerEvaluation(DomainModel):
    question_id: UUID
    risk_id: Identifier
    objective_id: Identifier
    condition_results: Annotated[list[ConditionEvaluation], Field(min_length=1)]
    unmet_required_condition_ids: list[Identifier] = Field(default_factory=list)
    strengths: list[EvaluationText] = Field(default_factory=list)
    missing_points: list[EvaluationText] = Field(default_factory=list)
    unsupported_claims: list[EvaluationText] = Field(default_factory=list)
    communication_feedback: CommunicationFeedback | None = None


class ConditionState(DomainModel):
    condition_id: Identifier
    latest_result: CoverageResult | None = None
    last_question_id: UUID | None = None


class ObjectiveState(DomainModel):
    objective_id: Identifier
    condition_states: list[ConditionState]
    followups_used: Annotated[int, Field(ge=0, le=2)]
    all_required_conditions_met: bool
    unresolved_required_condition_ids: list[Identifier]


class RiskState(DomainModel):
    risk_id: Identifier
    verification_status: VerificationStatus
    objective_states: list[ObjectiveState]


class DerivedInterviewState(DomainModel):
    risk_states: list[RiskState]


class FinalInterviewReport(DomainModel):
    overall_summary: MediumText
    strong_answers: list[MediumText] = Field(default_factory=list)
    unresolved_risks: list[MediumText] = Field(default_factory=list)
    preparation_recommendations: list[MediumText] = Field(default_factory=list)
    english_communication_feedback: CommunicationFeedback | None = None
