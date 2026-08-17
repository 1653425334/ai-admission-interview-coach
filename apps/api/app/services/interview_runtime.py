"""Small deterministic adaptive loop using the offline Fake provider."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.interview_provider import InterviewProvider
from app.db.models.interview_session import InterviewSession
from app.db.models.interview_turn import InterviewTurn
from app.schemas.interview import (
    FinalInterviewReport,
    InterviewQuestion,
    NextAction,
)
from app.schemas.interview_map import InterviewMap, VerificationStatus
from app.services.interview_state import decide_next_action
from app.services.interviews import (
    InterviewTurnStateError,
    complete_interview_session,
    create_or_reuse_interview_session,
    derive_persisted_session_state,
    interview_map_for_session,
    record_evaluation,
    record_question,
    submit_answer,
)


def start_or_resume_interview(
    db: Session,
    *,
    application_id: UUID,
    question_budget: int = 6,
    provider: InterviewProvider,
) -> InterviewSession:
    result = create_or_reuse_interview_session(
        db, application_id=application_id, question_budget=question_budget
    )
    interview_session = result.interview_session
    if interview_session.status == "PENDING" and interview_session.questions_asked == 0:
        interview_map = interview_map_for_session(interview_session)
        risk = _ordered_risks(interview_map)[0]
        objective = risk.objectives[0]
        target_ids = [
            item.condition_id for item in objective.coverage_conditions if item.required
        ][:1]
        question = provider.generate_question(
            session_id=interview_session.id,
            interview_map=interview_map,
            risk_id=risk.risk_id,
            objective_id=objective.objective_id,
            target_condition_ids=target_ids,
            followup_index=0,
            sequence_number=1,
            history=(),
        )
        record_question(db, session_id=interview_session.id, question=question)
    return interview_session


def submit_answer_and_advance_interview(
    db: Session,
    *,
    interview_session: InterviewSession,
    turn_id: UUID,
    answer_text: str,
    provider: InterviewProvider,
) -> InterviewSession:
    """Evaluate one answer and synchronously produce the next visible state."""

    turn = db.get(InterviewTurn, turn_id)
    if turn is None or turn.session_id != interview_session.id:
        raise InterviewTurnStateError("interview turn was not found in the session")
    normalized_answer = answer_text.strip()
    if turn.status == "EVALUATED":
        if turn.answer_text == normalized_answer:
            return interview_session
        raise InterviewTurnStateError("interview turn has already been evaluated")

    question = _question_from_turn(turn)
    interview_map = interview_map_for_session(interview_session)
    submit_answer(
        db,
        session_id=interview_session.id,
        turn_id=turn.id,
        answer_text=normalized_answer,
    )
    history = _history(interview_session)
    evaluation = provider.evaluate_answer(
        question=question,
        answer_text=normalized_answer,
        interview_map=interview_map,
        history=history,
    )
    record_evaluation(
        db,
        session_id=interview_session.id,
        turn_id=turn.id,
        evaluation=evaluation,
    )
    state = derive_persisted_session_state(db, interview_session)
    action = decide_next_action(
        interview_map,
        state,
        question,
        questions_asked=interview_session.questions_asked,
        question_budget=interview_session.question_budget,
    )
    if action is NextAction.END_INTERVIEW:
        return _finish(db, interview_session, interview_map)

    next_target = _next_target(interview_map, state, question, action)
    if next_target is None:
        return _finish(db, interview_session, interview_map)
    risk_id, objective_id, condition_ids, followup_index, parent_id = next_target
    next_question = provider.generate_question(
        session_id=interview_session.id,
        interview_map=interview_map,
        risk_id=risk_id,
        objective_id=objective_id,
        target_condition_ids=condition_ids,
        followup_index=followup_index,
        sequence_number=interview_session.questions_asked + 1,
        parent_question_id=parent_id,
        history=_history(interview_session),
    )
    record_question(db, session_id=interview_session.id, question=next_question)
    return interview_session


def _next_target(interview_map, state, question, action):
    risk = next(item for item in interview_map.risks if item.risk_id == question.risk_id)
    if action is NextAction.FOLLOW_UP_CURRENT_OBJECTIVE:
        risk_state = next(item for item in state.risk_states if item.risk_id == risk.risk_id)
        objective_state = next(
            item
            for item in risk_state.objective_states
            if item.objective_id == question.objective_id
        )
        return (
            risk.risk_id,
            question.objective_id,
            objective_state.unresolved_required_condition_ids[:1],
            question.followup_index + 1,
            question.question_id,
        )
    if action is NextAction.MOVE_TO_NEXT_OBJECTIVE:
        objective_ids = [item.objective_id for item in risk.objectives]
        objective = risk.objectives[objective_ids.index(question.objective_id) + 1]
        return (
            risk.risk_id,
            objective.objective_id,
            [item.condition_id for item in objective.coverage_conditions if item.required],
            0,
            None,
        )
    ordered = _ordered_risks(interview_map)
    current_index = next(
        index for index, item in enumerate(ordered) if item.risk_id == question.risk_id
    )
    statuses = {item.risk_id: item.verification_status for item in state.risk_states}
    for next_risk in ordered[current_index + 1 :]:
        if statuses[next_risk.risk_id] is VerificationStatus.VERIFIED:
            continue
        objective = next_risk.objectives[0]
        return (
            next_risk.risk_id,
            objective.objective_id,
            [item.condition_id for item in objective.coverage_conditions if item.required],
            0,
            None,
        )
    return None


def _finish(
    db: Session, interview_session: InterviewSession, interview_map: InterviewMap
) -> InterviewSession:
    state = derive_persisted_session_state(db, interview_session)
    status_by_risk = {item.risk_id: item.verification_status for item in state.risk_states}
    verified = [
        f"Provided sufficient detail to resolve this interview concern: {risk.title}."
        for risk in interview_map.risks
        if status_by_risk[risk.risk_id] is VerificationStatus.VERIFIED
    ]
    unresolved = [
        f"{risk.title} ({status_by_risk[risk.risk_id].value})"
        for risk in interview_map.risks
        if status_by_risk[risk.risk_id] is not VerificationStatus.VERIFIED
    ]
    summary = (
        f"Interview completed after {interview_session.questions_asked} questions. "
        f"Verified {len(verified)} of {len(interview_map.risks)} interview risks."
    )
    report = FinalInterviewReport(
        overall_summary=summary,
        strong_answers=verified,
        unresolved_risks=unresolved,
        preparation_recommendations=[
            f"Prepare a concrete, evidence-backed explanation for: {item}"
            for item in unresolved
        ],
    )
    return complete_interview_session(
        db, session_id=interview_session.id, final_report=report
    )


def _ordered_risks(interview_map: InterviewMap):
    risk_by_id = {item.risk_id: item for item in interview_map.risks}
    return [
        *(risk_by_id[risk_id] for risk_id in interview_map.priority_risk_ids),
        *(
            risk
            for risk in interview_map.risks
            if risk.risk_id not in interview_map.priority_risk_ids
        ),
    ]


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


def _history(interview_session: InterviewSession) -> list[dict[str, object]]:
    return [
        {
            "sequence_number": turn.sequence_number,
            "question": turn.question_text,
            "answer": turn.answer_text,
        }
        for turn in sorted(interview_session.turns, key=lambda item: item.sequence_number)
    ]
