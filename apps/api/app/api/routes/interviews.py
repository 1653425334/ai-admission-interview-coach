"""Authenticated endpoints for the minimal stateful mock interview loop."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.ai.deepseek_interview import DeepSeekInterviewError
from app.ai.interview_provider import InterviewProvider, get_interview_provider
from app.core.security import AuthPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.interview_api import (
    InterviewAnswerRequest,
    InterviewSessionResponse,
    InterviewStartRequest,
    interview_session_response,
)
from app.schemas.interview import FinalInterviewReport
from app.services.applications import get_owned_application
from app.services.interview_runtime import (
    start_or_resume_interview,
    submit_answer_and_advance_interview,
)
from app.services.interviews import (
    InterviewMapRequiredError,
    InterviewSessionStateError,
    InterviewTurnStateError,
    get_owned_interview_session,
)


router = APIRouter(tags=["interviews"])
logger = logging.getLogger(__name__)


@router.post(
    "/applications/{application_id}/interviews",
    response_model=InterviewSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_interview(
    application_id: UUID,
    payload: InterviewStartRequest = InterviewStartRequest(),
    provider: InterviewProvider = Depends(get_interview_provider),
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> InterviewSessionResponse:
    get_owned_application(db, application_id, principal.user_id)
    try:
        interview_session = start_or_resume_interview(
            db,
            application_id=application_id,
            question_budget=payload.question_budget,
            provider=provider,
        )
    except InterviewMapRequiredError:
        raise ApiError(
            409,
            "INTERVIEW_MAP_REQUIRED",
            "Complete a current material analysis with interview risks before starting.",
        ) from None
    except DeepSeekInterviewError as error:
        logger.warning("interview question generation failed error_type=%s", type(error).__name__)
        raise ApiError(
            502,
            "INTERVIEW_MODEL_UNAVAILABLE",
            "The interview model could not generate a question. Please try again.",
        ) from None
    return interview_session_response(db, interview_session)


@router.get("/interviews/{session_id}", response_model=InterviewSessionResponse)
def get_interview(
    session_id: UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> InterviewSessionResponse:
    return interview_session_response(
        db, get_owned_interview_session(db, session_id, principal.user_id)
    )


@router.post(
    "/interviews/{session_id}/turns",
    response_model=InterviewSessionResponse,
)
def submit_interview_answer(
    session_id: UUID,
    payload: InterviewAnswerRequest,
    provider: InterviewProvider = Depends(get_interview_provider),
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> InterviewSessionResponse:
    interview_session = get_owned_interview_session(db, session_id, principal.user_id)
    try:
        interview_session = submit_answer_and_advance_interview(
            db,
            interview_session=interview_session,
            turn_id=payload.turn_id,
            answer_text=payload.answer_text,
            provider=provider,
        )
    except (InterviewSessionStateError, InterviewTurnStateError):
        raise ApiError(
            409,
            "INTERVIEW_TURN_CONFLICT",
            "This interview turn is no longer available for that answer.",
        ) from None
    except DeepSeekInterviewError as error:
        logger.warning("interview answer evaluation failed error_type=%s", type(error).__name__)
        raise ApiError(
            502,
            "INTERVIEW_MODEL_UNAVAILABLE",
            "The interview model could not evaluate this answer. Please try again.",
        ) from None
    return interview_session_response(db, interview_session)


@router.get("/interviews/{session_id}/report", response_model=FinalInterviewReport)
def get_interview_report(
    session_id: UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> FinalInterviewReport:
    interview_session = get_owned_interview_session(db, session_id, principal.user_id)
    if interview_session.status != "COMPLETED" or interview_session.final_report_json is None:
        raise ApiError(409, "INTERVIEW_REPORT_NOT_READY", "The interview report is not ready.")
    return FinalInterviewReport.model_validate(interview_session.final_report_json)
