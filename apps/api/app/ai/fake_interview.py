"""Deterministic M3 provider for unit tests and offline development."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID, uuid5

from app.schemas.interview import (
    AnswerEvaluation,
    CommunicationFeedback,
    ConditionEvaluation,
    CoverageResult,
    InterviewQuestion,
)
from app.schemas.interview_map import InterviewMap, SuggestedQuestionType


class FakeInterviewProvider:
    def generate_question(
        self,
        *,
        session_id: UUID,
        interview_map: InterviewMap,
        risk_id: str,
        objective_id: str,
        target_condition_ids: list[str],
        followup_index: int,
        sequence_number: int,
        parent_question_id: UUID | None = None,
        history: Sequence[dict[str, object]] = (),
    ) -> InterviewQuestion:
        risk = next(item for item in interview_map.risks if item.risk_id == risk_id)
        objective = next(item for item in risk.objectives if item.objective_id == objective_id)
        conditions = [
            condition
            for condition in objective.coverage_conditions
            if condition.condition_id in target_condition_ids
        ]
        prompt = _question_prompt(
            [_QUESTION_BY_CONDITION_TYPE[condition.type.value] for condition in conditions],
            followup=followup_index > 0,
        )
        return InterviewQuestion(
            question_id=uuid5(session_id, f"question:{sequence_number}"),
            session_id=session_id,
            risk_id=risk_id,
            objective_id=objective_id,
            question_type=(
                risk.suggested_question_types[0]
                if followup_index == 0
                else SuggestedQuestionType.EVIDENCE_PROBE
            ),
            target_condition_ids=target_condition_ids,
            text=prompt,
            followup_index=followup_index,
            parent_question_id=parent_question_id,
            sequence_number=sequence_number,
        )

    def evaluate_answer(
        self,
        *,
        question: InterviewQuestion,
        answer_text: str,
        interview_map: InterviewMap,
        history: Sequence[dict[str, object]] = (),
    ) -> AnswerEvaluation:
        risk = next(item for item in interview_map.risks if item.risk_id == question.risk_id)
        objective = next(item for item in risk.objectives if item.objective_id == question.objective_id)
        results: list[ConditionEvaluation] = []
        lowered = answer_text.lower()
        for condition in objective.coverage_conditions:
            if condition.condition_id not in question.target_condition_ids:
                continue
            result, excerpt = _condition_result(condition.type.value, answer_text, lowered)
            results.append(
                ConditionEvaluation(
                    condition_id=condition.condition_id,
                    result=result,
                    answer_excerpt=excerpt,
                    reason=("The answer provides the requested detail." if result is CoverageResult.MET else "The answer does not provide enough detail."),
                )
            )
        required_ids = {
            item.condition_id for item in objective.coverage_conditions if item.required
        }
        unmet = [
            item.condition_id
            for item in results
            if item.condition_id in required_ids and item.result is not CoverageResult.MET
        ]
        return AnswerEvaluation(
            question_id=question.question_id,
            risk_id=question.risk_id,
            objective_id=question.objective_id,
            condition_results=results,
            unmet_required_condition_ids=unmet,
            strengths=["Gives a concrete answer."] if len(unmet) < len(results) else [],
            missing_points=["Address the remaining coverage conditions."] if unmet else [],
            communication_feedback=CommunicationFeedback(clarity="Use concise, concrete examples."),
        )


def _condition_result(condition_type: str, answer: str, lowered: str) -> tuple[CoverageResult, str | None]:
    if "not " in lowered or "did not" in lowered:
        return CoverageResult.NOT_MET, answer[:300]
    keywords = {
        "NAMES_TEST": ("noise", "perturb", "test", "gaussian"),
        "EXPLAINS_BASELINE": ("baseline", "compared", "resnet"),
        "PROVIDES_RESULT": ("%", "accuracy", "result", "improved"),
        "EXPLAINS_MECHANISM": ("because", "mechanism", "attention", "feature"),
        "JUSTIFIES_CHOICE": ("because", "trade", "choose"),
        "DISTINGUISHES_OWNERSHIP": ("i ", "my role", "implemented"),
        "RESOLVES_INCONSISTENCY": ("difference", "clarify", "because"),
        "CONNECTS_MOTIVATION_TO_EXPERIENCE": ("experience", "project", "worked"),
    }
    if any(token in lowered for token in keywords[condition_type]):
        return CoverageResult.MET, answer[:300]
    return CoverageResult.UNCLEAR, None


_QUESTION_BY_CONDITION_TYPE = {
    "NAMES_TEST": "What robustness or perturbation test did you use?",
    "EXPLAINS_BASELINE": "What baseline did you compare against, and why?",
    "PROVIDES_RESULT": "What concrete result did you observe?",
    "EXPLAINS_MECHANISM": "How does the method work in practice?",
    "JUSTIFIES_CHOICE": "Why did you choose this approach over the alternatives?",
    "DISTINGUISHES_OWNERSHIP": "What were your individual tasks and responsibilities in the project?",
    "RESOLVES_INCONSISTENCY": "How do you explain the difference between the descriptions in your materials?",
    "CONNECTS_MOTIVATION_TO_EXPERIENCE": "Which concrete experience led to this motivation?",
}


def _question_prompt(questions: list[str], *, followup: bool) -> str:
    if len(questions) == 1:
        return f"Could you clarify: {questions[0]}" if followup else questions[0]
    label = "Please clarify the remaining points." if followup else "Please address these points."
    points = " ".join(
        f"({index}) {question}" for index, question in enumerate(questions, start=1)
    )
    return f"{label} {points}"
