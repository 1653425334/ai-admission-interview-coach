"""Pure deterministic state derivation for an M3 interview session."""

from __future__ import annotations

from collections.abc import Iterable

from app.schemas.interview import (
    AnswerEvaluation,
    CoverageResult,
    DerivedInterviewState,
    InterviewQuestion,
    NextAction,
    ObjectiveState,
    RiskState,
    ConditionState,
)
from app.schemas.interview_map import InterviewMap, VerificationStatus


class InterviewRuntimeValidationError(ValueError):
    """A question or evaluation does not bind to the immutable InterviewMap."""


def derive_interview_state(
    interview_map: InterviewMap,
    questions: Iterable[InterviewQuestion],
    evaluations: Iterable[AnswerEvaluation],
) -> DerivedInterviewState:
    """Replay immutable events into condition, objective and risk state."""

    question_by_id = {question.question_id: question for question in questions}
    results_by_condition: dict[str, tuple[CoverageResult, object]] = {}
    for evaluation in evaluations:
        question = question_by_id.get(evaluation.question_id)
        if question is None:
            raise InterviewRuntimeValidationError("evaluation references an unknown question")
        risk, objective = _map_objective(interview_map, evaluation.risk_id, evaluation.objective_id)
        if question.risk_id != risk.risk_id or question.objective_id != objective.objective_id:
            raise InterviewRuntimeValidationError("evaluation does not match its question binding")
        valid_condition_ids = {condition.condition_id for condition in objective.coverage_conditions}
        for result in evaluation.condition_results:
            if result.condition_id not in valid_condition_ids:
                raise InterviewRuntimeValidationError("evaluation references a condition outside its objective")
            results_by_condition[result.condition_id] = (result.result, question.question_id)

    states: list[RiskState] = []
    question_list = list(question_by_id.values())
    for risk in interview_map.risks:
        objective_states: list[ObjectiveState] = []
        for objective in risk.objectives:
            condition_states = [
                ConditionState(
                    condition_id=condition.condition_id,
                    latest_result=(results_by_condition.get(condition.condition_id) or (None, None))[0],
                    last_question_id=(results_by_condition.get(condition.condition_id) or (None, None))[1],
                )
                for condition in objective.coverage_conditions
            ]
            required_ids = {
                condition.condition_id for condition in objective.coverage_conditions if condition.required
            }
            unresolved = [
                state.condition_id
                for state in condition_states
                if state.condition_id in required_ids and state.latest_result is not CoverageResult.MET
            ]
            followups_used = sum(
                1
                for question in question_list
                if question.risk_id == risk.risk_id
                and question.objective_id == objective.objective_id
                and question.followup_index > 0
            )
            objective_states.append(
                ObjectiveState(
                    objective_id=objective.objective_id,
                    condition_states=condition_states,
                    followups_used=followups_used,
                    all_required_conditions_met=not unresolved,
                    unresolved_required_condition_ids=unresolved,
                )
            )
        states.append(
            RiskState(
                risk_id=risk.risk_id,
                verification_status=_risk_status(risk.max_followups, objective_states),
                objective_states=objective_states,
            )
        )
    return DerivedInterviewState(risk_states=states)


def decide_next_action(
    interview_map: InterviewMap,
    state: DerivedInterviewState,
    current_question: InterviewQuestion,
    *,
    questions_asked: int,
    question_budget: int,
) -> NextAction:
    """Choose flow control without asking a model to mutate interview state."""

    if questions_asked >= question_budget:
        return NextAction.END_INTERVIEW
    risk, objective = _map_objective(interview_map, current_question.risk_id, current_question.objective_id)
    risk_state = next(item for item in state.risk_states if item.risk_id == risk.risk_id)
    objective_state = next(
        item for item in risk_state.objective_states if item.objective_id == objective.objective_id
    )
    if objective_state.all_required_conditions_met:
        return (
            NextAction.MOVE_TO_NEXT_OBJECTIVE
            if _has_next_objective(risk, objective.objective_id)
            else _next_risk_action(interview_map, state, risk.risk_id)
        )
    if objective_state.followups_used < risk.max_followups:
        return NextAction.FOLLOW_UP_CURRENT_OBJECTIVE
    return (
        NextAction.MOVE_TO_NEXT_OBJECTIVE
        if _has_next_objective(risk, objective.objective_id)
        else _next_risk_action(interview_map, state, risk.risk_id)
    )


def _risk_status(max_followups: int, objective_states: list[ObjectiveState]) -> VerificationStatus:
    if all(item.all_required_conditions_met for item in objective_states):
        return VerificationStatus.VERIFIED
    exhausted_not_met = any(
        item.followups_used >= max_followups
        and any(condition.latest_result is CoverageResult.NOT_MET for condition in item.condition_states)
        for item in objective_states
    )
    if exhausted_not_met:
        return VerificationStatus.CONFIRMED_RISK
    if any(
        condition.latest_result is CoverageResult.MET
        for item in objective_states
        for condition in item.condition_states
    ):
        return VerificationStatus.PARTIALLY_VERIFIED
    return VerificationStatus.UNVERIFIED


def _map_objective(interview_map: InterviewMap, risk_id: str, objective_id: str):
    for risk in interview_map.risks:
        if risk.risk_id == risk_id:
            for objective in risk.objectives:
                if objective.objective_id == objective_id:
                    return risk, objective
    raise InterviewRuntimeValidationError("risk/objective does not exist in InterviewMap")


def _has_next_objective(risk, objective_id: str) -> bool:
    objective_ids = [objective.objective_id for objective in risk.objectives]
    return objective_ids.index(objective_id) < len(objective_ids) - 1


def _next_risk_action(
    interview_map: InterviewMap, state: DerivedInterviewState, current_risk_id: str
) -> NextAction:
    ordered_ids = [
        *interview_map.priority_risk_ids,
        *(risk.risk_id for risk in interview_map.risks if risk.risk_id not in interview_map.priority_risk_ids),
    ]
    current_index = ordered_ids.index(current_risk_id)
    remaining_ids = set(ordered_ids[current_index + 1 :])
    if any(
        item.risk_id in remaining_ids and item.verification_status is not VerificationStatus.VERIFIED
        for item in state.risk_states
    ):
        return NextAction.MOVE_TO_NEXT_RISK
    return NextAction.END_INTERVIEW
