from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from app.ai.deepseek_interview import (
    DeepSeekInterviewInvalidResponseError,
    DeepSeekInterviewProvider,
)
from app.schemas.interview_map import InterviewMap


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "milestone_two"
SESSION_ID = UUID("99999999-9999-4999-8999-999999999999")


class FakeResponse:
    def __init__(self, content: dict[str, object]) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": json.dumps(self._content)},
                }
            ]
        }


def interview_map() -> InterviewMap:
    payload = json.loads(
        (FIXTURES / "attention_robustness_interview_map.json").read_text(
            encoding="utf-8"
        )
    )
    return InterviewMap.model_validate(payload)


def provider() -> DeepSeekInterviewProvider:
    return DeepSeekInterviewProvider(
        api_key="test-key", model="deepseek-test", base_url="https://api.example"
    )


def test_deepseek_generates_only_text_while_code_binds_runtime_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def post(url: str, **kwargs: object) -> FakeResponse:
        captured.update(url=url, **kwargs)
        return FakeResponse(
            {"text": "How did you measure robustness, and what baseline did you use?"}
        )

    monkeypatch.setattr(httpx, "post", post)
    model = interview_map()
    risk = model.risks[0]
    objective = risk.objectives[0]
    question = provider().generate_question(
        session_id=SESSION_ID,
        interview_map=model,
        risk_id=risk.risk_id,
        objective_id=objective.objective_id,
        target_condition_ids=[item.condition_id for item in objective.coverage_conditions],
        followup_index=0,
        sequence_number=1,
    )

    assert question.text == "How did you measure robustness, and what baseline did you use?"
    assert question.risk_id == risk.risk_id
    assert question.objective_id == objective.objective_id
    assert question.question_id.version == 5
    assert captured["url"] == "https://api.example/chat/completions"
    request = captured["json"]
    assert isinstance(request, dict)
    assert request["response_format"] == {"type": "json_object"}
    prompt = json.loads(request["messages"][1]["content"])
    assert "verification_goal" in prompt
    assert "verification_status" not in prompt["output_schema"].get("properties", {})


def test_deepseek_evaluation_is_condition_bound_and_unmet_ids_are_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = interview_map()
    risk = model.risks[0]
    objective = risk.objectives[0]
    target_ids = [item.condition_id for item in objective.coverage_conditions]
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {
                "text": "unused"
            }
        ),
    )
    question = provider().generate_question(
        session_id=SESSION_ID,
        interview_map=model,
        risk_id=risk.risk_id,
        objective_id=objective.objective_id,
        target_condition_ids=target_ids,
        followup_index=0,
        sequence_number=1,
    )
    answer = "We tested Gaussian noise, but I do not remember the baseline result."
    evaluation_payload = {
        "condition_results": [
            {
                "condition_id": target_ids[0],
                "result": "MET",
                "answer_excerpt": "We tested Gaussian noise",
                "reason": "Names a perturbation test.",
            },
            *[
                {
                    "condition_id": condition_id,
                    "result": "UNCLEAR",
                    "answer_excerpt": None,
                    "reason": "No concrete detail was provided.",
                }
                for condition_id in target_ids[1:]
            ],
        ],
        "strengths": ["Names a concrete noise test."],
        "missing_points": ["Give the baseline and result."],
        "unsupported_claims": [],
        "communication_feedback": {"clarity": "State the comparison directly."},
    }
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(evaluation_payload),
    )

    evaluation = provider().evaluate_answer(
        question=question,
        answer_text=answer,
        interview_map=model,
    )

    assert evaluation.question_id == question.question_id
    assert evaluation.unmet_required_condition_ids == target_ids[1:]
    assert [item.result.value for item in evaluation.condition_results] == [
        "MET",
        *(["UNCLEAR"] * (len(target_ids) - 1)),
    ]


def test_deepseek_evaluation_rejects_an_excerpt_not_in_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = interview_map()
    risk = model.risks[0]
    objective = risk.objectives[0]
    condition = objective.coverage_conditions[0]
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse({"text": "What test did you use?"}),
    )
    question = provider().generate_question(
        session_id=SESSION_ID,
        interview_map=model,
        risk_id=risk.risk_id,
        objective_id=objective.objective_id,
        target_condition_ids=[condition.condition_id],
        followup_index=0,
        sequence_number=1,
    )
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(
            {
                "condition_results": [
                    {
                        "condition_id": condition.condition_id,
                        "result": "MET",
                        "answer_excerpt": "an invented quote",
                        "reason": "Claims detail.",
                    }
                ],
                "strengths": [],
                "missing_points": [],
                "unsupported_claims": [],
                "communication_feedback": None,
            }
        ),
    )

    with pytest.raises(DeepSeekInterviewInvalidResponseError, match="excerpt"):
        provider().evaluate_answer(
            question=question,
            answer_text="I tested Gaussian noise.",
            interview_map=model,
        )
