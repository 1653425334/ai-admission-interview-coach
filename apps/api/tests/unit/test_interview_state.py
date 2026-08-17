from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from app.ai.fake_interview import FakeInterviewProvider
from app.schemas.interview import ConditionEvaluation, CoverageResult, InterviewQuestion
from app.schemas.interview_map import CoverageConditionType, InterviewMap, SuggestedQuestionType, VerificationStatus
from app.services.interview_state import (
    InterviewRuntimeValidationError,
    decide_next_action,
    derive_interview_state,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
SESSION_ID = UUID("99999999-9999-4999-8999-999999999999")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "milestone_two"


def interview_map() -> InterviewMap:
    payload = json.loads((FIXTURES / "attention_robustness_interview_map.json").read_text())
    payload["analysis_run_id"] = str(RUN_ID)
    return InterviewMap.model_validate(payload)


def first_question() -> InterviewQuestion:
    model = interview_map()
    provider = FakeInterviewProvider()
    objective = model.risks[0].objectives[0]
    return provider.generate_question(
        session_id=SESSION_ID,
        interview_map=model,
        risk_id=model.risks[0].risk_id,
        objective_id=objective.objective_id,
        target_condition_ids=[item.condition_id for item in objective.coverage_conditions],
        followup_index=0,
        sequence_number=1,
    )


def test_partial_answer_drives_targeted_follow_up_and_partially_verified_risk() -> None:
    model = interview_map()
    provider = FakeInterviewProvider()
    question = first_question()
    evaluation = provider.evaluate_answer(
        question=question,
        answer_text="We tested Gaussian noise at multiple perturbation levels.",
        interview_map=model,
    )

    state = derive_interview_state(model, [question], [evaluation])
    objective_state = state.risk_states[0].objective_states[0]

    assert objective_state.unresolved_required_condition_ids == ["cond-002", "cond-003"]
    assert state.risk_states[0].verification_status is VerificationStatus.PARTIALLY_VERIFIED
    assert decide_next_action(model, state, question, questions_asked=1, question_budget=6).value == "FOLLOW_UP_CURRENT_OBJECTIVE"


def test_full_follow_up_verifies_risk_without_reasking_met_condition() -> None:
    model = interview_map()
    provider = FakeInterviewProvider()
    first = first_question()
    first_evaluation = provider.evaluate_answer(
        question=first,
        answer_text="We tested Gaussian noise at multiple perturbation levels.",
        interview_map=model,
    )
    follow_up = provider.generate_question(
        session_id=SESSION_ID,
        interview_map=model,
        risk_id=first.risk_id,
        objective_id=first.objective_id,
        target_condition_ids=["cond-002", "cond-003"],
        followup_index=1,
        sequence_number=2,
        parent_question_id=first.question_id,
    )
    second_evaluation = provider.evaluate_answer(
        question=follow_up,
        answer_text="Compared with the baseline, accuracy improved by 10%.",
        interview_map=model,
    )

    state = derive_interview_state(model, [first, follow_up], [first_evaluation, second_evaluation])

    assert follow_up.target_condition_ids == ["cond-002", "cond-003"]
    assert state.risk_states[0].verification_status is VerificationStatus.VERIFIED
    assert decide_next_action(model, state, follow_up, questions_asked=2, question_budget=6).value == "END_INTERVIEW"


def test_explicit_missing_detail_after_followup_budget_confirms_risk() -> None:
    model = interview_map()
    question = first_question()
    evaluations = []
    questions = [question]
    for index in range(1, 3):
        follow_up = InterviewQuestion(
            question_id=UUID(f"00000000-0000-4000-8000-00000000000{index}"),
            session_id=SESSION_ID,
            risk_id=question.risk_id,
            objective_id=question.objective_id,
            question_type=SuggestedQuestionType.EVIDENCE_PROBE,
            target_condition_ids=["cond-002"],
            text="Name the baseline.",
            followup_index=index,
            parent_question_id=question.question_id,
            sequence_number=index + 1,
        )
        questions.append(follow_up)
        evaluations.append(
            FakeInterviewProvider().evaluate_answer(
                question=follow_up,
                answer_text="I did not use a baseline.",
                interview_map=model,
            )
        )

    state = derive_interview_state(model, questions, evaluations)

    assert state.risk_states[0].verification_status is VerificationStatus.CONFIRMED_RISK


def test_evaluation_cannot_reference_condition_outside_question_objective() -> None:
    model = interview_map()
    question = first_question()
    invalid = FakeInterviewProvider().evaluate_answer(
        question=question,
        answer_text="We tested Gaussian noise.",
        interview_map=model,
    ).model_copy(
        update={
            "condition_results": [
                ConditionEvaluation(
                    condition_id="unknown-condition",
                    result=CoverageResult.UNCLEAR,
                    reason="Not in the objective.",
                )
            ]
        }
    )

    with pytest.raises(InterviewRuntimeValidationError, match="condition outside"):
        derive_interview_state(model, [question], [invalid])


def test_question_budget_ends_interview_before_any_new_follow_up() -> None:
    model = interview_map()
    question = first_question()
    evaluation = FakeInterviewProvider().evaluate_answer(
        question=question,
        answer_text="We tested Gaussian noise.",
        interview_map=model,
    )
    state = derive_interview_state(model, [question], [evaluation])

    assert decide_next_action(model, state, question, questions_asked=6, question_budget=6).value == "END_INTERVIEW"


def test_fake_question_converts_declarative_conditions_to_natural_prompt() -> None:
    model = interview_map()
    risk = model.risks[0]
    objective = risk.objectives[0].model_copy(
        update={
            "coverage_conditions": [
                risk.objectives[0].coverage_conditions[0].model_copy(
                    update={
                        "description": "Candidate explains the confidence estimation method and threshold selection."
                    }
                ),
                risk.objectives[0].coverage_conditions[1].model_copy(
                    update={
                        "description": "Candidate describes how the attention branch is dynamically activated."
                    }
                ),
            ]
        }
    )
    updated_risk = risk.model_copy(update={"objectives": [objective]})
    updated_map = model.model_copy(update={"risks": [updated_risk]})

    question = FakeInterviewProvider().generate_question(
        session_id=SESSION_ID,
        interview_map=updated_map,
        risk_id=updated_risk.risk_id,
        objective_id=objective.objective_id,
        target_condition_ids=[item.condition_id for item in objective.coverage_conditions],
        followup_index=0,
        sequence_number=1,
    )

    assert question.text == (
        "Please address these points. (1) What robustness or perturbation test did you use? "
        "(2) What baseline did you compare against, and why?"
    )
    assert "Candidate" not in question.text


def test_fake_ownership_question_does_not_repeat_third_person_condition_text() -> None:
    model = interview_map()
    risk = model.risks[0]
    condition = risk.objectives[0].coverage_conditions[0].model_copy(
        update={
            "type": CoverageConditionType.DISTINGUISHES_OWNERSHIP,
            "description": "Candidate clearly states their individual tasks and responsibilities in the project.",
        }
    )
    objective = risk.objectives[0].model_copy(update={"coverage_conditions": [condition]})
    updated_map = model.model_copy(
        update={"risks": [risk.model_copy(update={"objectives": [objective]})]}
    )

    question = FakeInterviewProvider().generate_question(
        session_id=SESSION_ID,
        interview_map=updated_map,
        risk_id=risk.risk_id,
        objective_id=objective.objective_id,
        target_condition_ids=[condition.condition_id],
        followup_index=0,
        sequence_number=1,
    )

    assert question.text == "What were your individual tasks and responsibilities in the project?"
