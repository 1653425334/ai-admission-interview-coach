"""Client-safe HTTP contracts for the text interview loop."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.models.interview_evaluation import InterviewEvaluation
from app.db.models.interview_session import InterviewSession
from app.schemas.interview import (
    AnswerEvaluation,
    DerivedInterviewState,
    FinalInterviewReport,
    InterviewSessionStatus,
    InterviewTurnStatus,
)
from app.schemas.interview_map import SuggestedQuestionType
from app.services.interviews import derive_persisted_session_state


class InterviewStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_budget: Annotated[int, Field(ge=5, le=8)] = 6


class InterviewAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: UUID
    answer_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)
    ]


class InterviewTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    sequence_number: int
    risk_id: str
    objective_id: str
    question_type: SuggestedQuestionType
    target_condition_ids: list[str]
    question_text: str
    followup_index: int
    parent_turn_id: UUID | None
    answer_text: str | None
    status: InterviewTurnStatus
    evaluation: AnswerEvaluation | None
    asked_at: datetime
    answered_at: datetime | None

    @field_serializer("asked_at", "answered_at")
    def serialize_utc_timestamp(self, value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value is not None else None


class InterviewSessionResponse(BaseModel):
    """Does not expose the source map, materials, provider prompts, or storage metadata."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    application_id: UUID
    analysis_run_id: UUID
    status: InterviewSessionStatus
    question_budget: int
    questions_asked: int
    current_turn_id: UUID | None
    turns: list[InterviewTurnResponse]
    derived_state: DerivedInterviewState
    final_report: FinalInterviewReport | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    @field_serializer("started_at", "completed_at", "created_at")
    def serialize_utc_timestamp(self, value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value is not None else None


def interview_session_response(
    db: Session, interview_session: InterviewSession
) -> InterviewSessionResponse:
    turns = sorted(interview_session.turns, key=lambda item: item.sequence_number)
    evaluations = {
        event.turn_id: event
        for event in db.scalars(
            select(InterviewEvaluation).where(
                InterviewEvaluation.session_id == interview_session.id
            )
        )
    }
    return InterviewSessionResponse(
        id=interview_session.id,
        application_id=interview_session.application_id,
        analysis_run_id=interview_session.analysis_run_id,
        status=interview_session.status,
        question_budget=interview_session.question_budget,
        questions_asked=interview_session.questions_asked,
        current_turn_id=interview_session.current_turn_id,
        turns=[
            InterviewTurnResponse(
                id=turn.id,
                sequence_number=turn.sequence_number,
                risk_id=turn.risk_id,
                objective_id=turn.objective_id,
                question_type=turn.question_type,
                target_condition_ids=turn.target_condition_ids_json,
                question_text=turn.question_text,
                followup_index=turn.followup_index,
                parent_turn_id=turn.parent_turn_id,
                answer_text=turn.answer_text,
                status=turn.status,
                evaluation=(
                    AnswerEvaluation.model_validate(evaluations[turn.id].evaluation_json)
                    if turn.id in evaluations
                    else None
                ),
                asked_at=turn.asked_at,
                answered_at=turn.answered_at,
            )
            for turn in turns
        ],
        derived_state=derive_persisted_session_state(db, interview_session),
        final_report=(
            FinalInterviewReport.model_validate(interview_session.final_report_json)
            if interview_session.final_report_json is not None
            else None
        ),
        started_at=interview_session.started_at,
        completed_at=interview_session.completed_at,
        created_at=interview_session.created_at,
    )
