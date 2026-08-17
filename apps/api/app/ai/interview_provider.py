"""Runtime provider boundary for M3 question generation and answer evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol
from uuid import UUID

from app.core.config import get_settings
from app.schemas.interview import AnswerEvaluation, InterviewQuestion
from app.schemas.interview_map import InterviewMap


class InterviewProvider(Protocol):
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
    ) -> InterviewQuestion: ...

    def evaluate_answer(
        self,
        *,
        question: InterviewQuestion,
        answer_text: str,
        interview_map: InterviewMap,
        history: Sequence[dict[str, object]] = (),
    ) -> AnswerEvaluation: ...


@lru_cache
def get_interview_provider() -> InterviewProvider:
    settings = get_settings()
    if settings.llm_mode == "deepseek":
        if not settings.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required when LLM_MODE=deepseek")
        from app.ai.deepseek_interview import DeepSeekInterviewProvider

        return DeepSeekInterviewProvider(
            api_key=settings.deepseek_api_key,
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
        )
    from app.ai.fake_interview import FakeInterviewProvider

    return FakeInterviewProvider()
