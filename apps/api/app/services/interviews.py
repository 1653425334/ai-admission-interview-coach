"""Transactional persistence for M3 interview sessions.

The InterviewMap remains immutable and authoritative. Questions and evaluations
are persisted as events; verification state is rebuilt deterministically by
replaying those events through ``interview_state``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.analysis_run import AnalysisRun
from app.db.models.interview_evaluation import InterviewEvaluation
from app.db.models.interview_session import InterviewSession
from app.db.models.interview_turn import InterviewTurn
from app.db.models.application import Application
from app.core.errors import ApiError
from app.schemas.interview import (
    AnswerEvaluation,
    DerivedInterviewState,
    FinalInterviewReport,
    InterviewQuestion,
)
from app.schemas.interview_map import InterviewMap
from app.services.analysis_runs import get_latest_current_analysis_run
from app.services.interview_state import derive_interview_state


ACTIVE_SESSION_STATUSES = ("PENDING", "ACTIVE")


class InterviewMapRequiredError(ValueError):
    """No current, completed, risk-bearing InterviewMap can start an interview."""


class InterviewSessionStateError(ValueError):
    """The requested operation is invalid for the current session state."""


class InterviewTurnStateError(ValueError):
    """The requested operation is invalid for the current turn state."""


@dataclass(frozen=True, slots=True)
class InterviewSessionResult:
    interview_session: InterviewSession
    created: bool


def create_or_reuse_interview_session(
    db: Session,
    *,
    application_id: UUID,
    question_budget: int = 6,
) -> InterviewSessionResult:
    """Create one session bound to the latest current M2 map, or resume active work."""

    if not 5 <= question_budget <= 8:
        raise ValueError("question_budget must be between 5 and 8")
    active = db.scalar(
        select(InterviewSession)
        .where(
            InterviewSession.application_id == application_id,
            InterviewSession.status.in_(ACTIVE_SESSION_STATUSES),
        )
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
    )
    if active is not None:
        return InterviewSessionResult(active, created=False)

    analysis_run = get_latest_current_analysis_run(db, application_id)
    interview_map = _validated_map(analysis_run)
    if not interview_map.risks:
        raise InterviewMapRequiredError("InterviewMap contains no risks to verify")

    interview_session = InterviewSession(
        application_id=application_id,
        analysis_run_id=analysis_run.id,
        interview_map_schema_version=interview_map.schema_version,
        status="PENDING",
        question_budget=question_budget,
        questions_asked=0,
    )
    db.add(interview_session)
    db.flush()
    return InterviewSessionResult(interview_session, created=True)


def record_question(
    db: Session,
    *,
    session_id: UUID,
    question: InterviewQuestion,
) -> InterviewTurn:
    """Persist one map-bound question while enforcing one open turn per session."""

    interview_session = _locked_session(db, session_id)
    if interview_session.status not in ACTIVE_SESSION_STATUSES:
        raise InterviewSessionStateError("interview session cannot accept another question")
    if interview_session.current_turn_id is not None:
        raise InterviewSessionStateError("the current question must be answered first")
    if interview_session.questions_asked >= interview_session.question_budget:
        raise InterviewSessionStateError("interview question budget is exhausted")
    if question.session_id != interview_session.id:
        raise InterviewTurnStateError("question belongs to another interview session")
    expected_sequence = interview_session.questions_asked + 1
    if question.sequence_number != expected_sequence:
        raise InterviewTurnStateError("question sequence is not the next session sequence")

    interview_map = _session_map(interview_session)
    _validate_question_binding(interview_map, question)
    if question.parent_question_id is not None:
        parent = db.get(InterviewTurn, question.parent_question_id)
        if parent is None or parent.session_id != interview_session.id:
            raise InterviewTurnStateError("parent question does not belong to the session")

    turn = InterviewTurn(
        id=question.question_id,
        session=interview_session,
        sequence_number=question.sequence_number,
        risk_id=question.risk_id,
        objective_id=question.objective_id,
        question_type=question.question_type.value,
        target_condition_ids_json=list(question.target_condition_ids),
        question_text=question.text,
        followup_index=question.followup_index,
        parent_turn_id=question.parent_question_id,
        status="ASKED",
    )
    db.add(turn)
    interview_session.current_turn_id = turn.id
    interview_session.questions_asked = expected_sequence
    if interview_session.status == "PENDING":
        interview_session.status = "ACTIVE"
        interview_session.started_at = datetime.now(timezone.utc)
    db.flush()
    return turn


def submit_answer(
    db: Session,
    *,
    session_id: UUID,
    turn_id: UUID,
    answer_text: str,
) -> InterviewTurn:
    """Attach exactly one non-empty answer to the current open question."""

    interview_session = _locked_session(db, session_id)
    turn = db.get(InterviewTurn, turn_id)
    if turn is None or turn.session_id != interview_session.id:
        raise InterviewTurnStateError("interview turn was not found in the session")
    if interview_session.status != "ACTIVE" or interview_session.current_turn_id != turn.id:
        raise InterviewTurnStateError("only the current active turn can be answered")
    if turn.status != "ASKED" or turn.answer_text is not None:
        raise InterviewTurnStateError("interview turn has already been answered")
    normalized_answer = answer_text.strip()
    if not normalized_answer or len(normalized_answer) > 8_000:
        raise ValueError("answer_text must contain between 1 and 8000 characters")

    turn.answer_text = normalized_answer
    turn.status = "ANSWERED"
    turn.answered_at = datetime.now(timezone.utc)
    db.flush()
    return turn


def record_evaluation(
    db: Session,
    *,
    session_id: UUID,
    turn_id: UUID,
    evaluation: AnswerEvaluation,
) -> InterviewEvaluation:
    """Persist one validated evaluation event and close the current turn."""

    interview_session = _locked_session(db, session_id)
    turn = db.get(InterviewTurn, turn_id)
    if turn is None or turn.session_id != interview_session.id:
        raise InterviewTurnStateError("interview turn was not found in the session")
    if interview_session.status != "ACTIVE" or interview_session.current_turn_id != turn.id:
        raise InterviewTurnStateError("only the current active turn can be evaluated")
    if turn.status != "ANSWERED" or turn.answer_text is None:
        raise InterviewTurnStateError("the turn must have an answer before evaluation")
    if turn.evaluation is not None:
        raise InterviewTurnStateError("interview turn has already been evaluated")

    question = _question_from_turn(turn)
    interview_map = _session_map(interview_session)
    _validate_evaluation_binding(interview_map, question, turn.answer_text, evaluation)
    existing_questions, existing_evaluations = _session_events(db, interview_session.id)
    derive_interview_state(
        interview_map,
        existing_questions,
        [*existing_evaluations, evaluation],
    )

    event = InterviewEvaluation(
        session_id=interview_session.id,
        turn_id=turn.id,
        evaluation_json=evaluation.model_dump(mode="json"),
    )
    db.add(event)
    turn.status = "EVALUATED"
    interview_session.current_turn_id = None
    db.flush()
    return event


def derive_persisted_session_state(
    db: Session, interview_session: InterviewSession
) -> DerivedInterviewState:
    interview_map = _session_map(interview_session)
    questions, evaluations = _session_events(db, interview_session.id)
    return derive_interview_state(interview_map, questions, evaluations)


def complete_interview_session(
    db: Session,
    *,
    session_id: UUID,
    final_report: FinalInterviewReport | None = None,
) -> InterviewSession:
    interview_session = _locked_session(db, session_id)
    if interview_session.status not in ACTIVE_SESSION_STATUSES:
        raise InterviewSessionStateError("interview session is already terminal")
    if interview_session.current_turn_id is not None:
        raise InterviewSessionStateError("the current turn must be evaluated before completion")
    interview_session.status = "COMPLETED"
    interview_session.completed_at = datetime.now(timezone.utc)
    interview_session.final_report_json = (
        final_report.model_dump(mode="json") if final_report is not None else None
    )
    db.flush()
    return interview_session


def get_owned_interview_session(
    db: Session, session_id: UUID, user_id: UUID
) -> InterviewSession:
    """Hide absent and other-user interview sessions behind one safe 404."""

    interview_session = db.scalar(
        select(InterviewSession)
        .join(Application, InterviewSession.application_id == Application.id)
        .where(InterviewSession.id == session_id, Application.user_id == user_id)
    )
    if interview_session is None:
        raise ApiError(404, "INTERVIEW_NOT_FOUND", "Interview session not found.")
    return interview_session


def interview_map_for_session(interview_session: InterviewSession) -> InterviewMap:
    """Return the validated immutable map bound when the session was created."""

    return _session_map(interview_session)


def _locked_session(db: Session, session_id: UUID) -> InterviewSession:
    interview_session = db.scalar(
        select(InterviewSession).where(InterviewSession.id == session_id).with_for_update()
    )
    if interview_session is None:
        raise InterviewSessionStateError("interview session was not found")
    return interview_session


def _validated_map(analysis_run: AnalysisRun | None) -> InterviewMap:
    if analysis_run is None or analysis_run.interview_map_json is None:
        raise InterviewMapRequiredError("a current completed InterviewMap is required")
    try:
        return InterviewMap.model_validate(analysis_run.interview_map_json)
    except ValueError as exc:
        raise InterviewMapRequiredError("the current InterviewMap is invalid") from exc


def _session_map(interview_session: InterviewSession) -> InterviewMap:
    interview_map = _validated_map(interview_session.analysis_run)
    if interview_map.schema_version != interview_session.interview_map_schema_version:
        raise InterviewMapRequiredError("interview session schema version does not match its map")
    return interview_map


def _validate_question_binding(interview_map: InterviewMap, question: InterviewQuestion) -> None:
    for risk in interview_map.risks:
        if risk.risk_id != question.risk_id:
            continue
        for objective in risk.objectives:
            if objective.objective_id != question.objective_id:
                continue
            valid_ids = {item.condition_id for item in objective.coverage_conditions}
            if not set(question.target_condition_ids).issubset(valid_ids):
                raise InterviewTurnStateError("question targets conditions outside its objective")
            if question.followup_index > risk.max_followups:
                raise InterviewTurnStateError("question exceeds the risk follow-up limit")
            return
    raise InterviewTurnStateError("question risk/objective does not exist in InterviewMap")


def _validate_evaluation_binding(
    interview_map: InterviewMap,
    question: InterviewQuestion,
    answer_text: str,
    evaluation: AnswerEvaluation,
) -> None:
    if (
        evaluation.question_id != question.question_id
        or evaluation.risk_id != question.risk_id
        or evaluation.objective_id != question.objective_id
    ):
        raise InterviewTurnStateError("evaluation does not match its question binding")
    result_ids = [item.condition_id for item in evaluation.condition_results]
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(question.target_condition_ids):
        raise InterviewTurnStateError("evaluation must cover exactly the question target conditions")
    required_ids: set[str] = set()
    for risk in interview_map.risks:
        if risk.risk_id == question.risk_id:
            objective = next(
                item for item in risk.objectives if item.objective_id == question.objective_id
            )
            required_ids = {
                item.condition_id for item in objective.coverage_conditions if item.required
            }
            break
    unmet_required_ids = {
        item.condition_id
        for item in evaluation.condition_results
        if item.condition_id in required_ids and item.result.value != "MET"
    }
    if set(evaluation.unmet_required_condition_ids) != unmet_required_ids:
        raise InterviewTurnStateError("evaluation unmet conditions do not match condition results")
    for result in evaluation.condition_results:
        if result.answer_excerpt is not None and result.answer_excerpt not in answer_text:
            raise InterviewTurnStateError("evaluation excerpt is not present in the submitted answer")


def _question_from_turn(turn: InterviewTurn) -> InterviewQuestion:
    return InterviewQuestion(
        question_id=turn.id,
        session_id=turn.session_id,
        risk_id=turn.risk_id,
        objective_id=turn.objective_id,
        question_type=turn.question_type,
        target_condition_ids=turn.target_condition_ids_json,
        text=turn.question_text,
        followup_index=turn.followup_index,
        parent_question_id=turn.parent_turn_id,
        sequence_number=turn.sequence_number,
    )


def _session_events(
    db: Session, session_id: UUID
) -> tuple[list[InterviewQuestion], list[AnswerEvaluation]]:
    turns = list(
        db.scalars(
            select(InterviewTurn)
            .where(InterviewTurn.session_id == session_id)
            .order_by(InterviewTurn.sequence_number.asc())
        )
    )
    questions = [_question_from_turn(turn) for turn in turns]
    evaluation_events = list(
        db.scalars(
            select(InterviewEvaluation)
            .join(InterviewTurn, InterviewEvaluation.turn_id == InterviewTurn.id)
            .where(InterviewEvaluation.session_id == session_id)
            .order_by(InterviewTurn.sequence_number.asc())
        )
    )
    evaluations = [
        AnswerEvaluation.model_validate(event.evaluation_json) for event in evaluation_events
    ]
    return questions, evaluations
