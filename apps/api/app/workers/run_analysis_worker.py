"""Minimal process entry point for durable fake material-analysis jobs.

Run locally with ``python -m app.workers.run_analysis_worker`` after the API
has created an analysis job. This process intentionally owns no HTTP routes
and uses PostgreSQL's existing job table for coordination.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from time import sleep

from sqlalchemy.orm import Session, sessionmaker

from app.ai.fake_interview_map import FakeInterviewMapLLM
from app.ai.deepseek_interview_map import DeepSeekInterviewMapLLM
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.services.document_extraction import DocumentExtractionService
from app.services.material_analysis import InterviewMapGenerator, MaterialAnalysisPipeline
from app.storage.base import ObjectStorage
from app.storage.supabase import get_object_storage
from app.workers.analysis_worker import DurableAnalysisWorker


DEFAULT_POLL_INTERVAL_SECONDS = 1.0
logger = logging.getLogger(__name__)


def build_analysis_worker(
    *,
    session_factory: sessionmaker[Session] | None = None,
    storage: ObjectStorage | None = None,
    llm: InterviewMapGenerator | None = None,
) -> DurableAnalysisWorker:
    """Compose the existing local runtime dependencies for one worker process."""

    if llm is None:
        settings = get_settings()
        if settings.llm_mode == "deepseek":
            if not settings.deepseek_api_key:
                raise RuntimeError("DEEPSEEK_API_KEY is required when LLM_MODE=deepseek")
            llm = DeepSeekInterviewMapLLM(
                api_key=settings.deepseek_api_key,
                model=settings.deepseek_model,
                base_url=settings.deepseek_base_url,
            )
        else:
            llm = FakeInterviewMapLLM()
    return DurableAnalysisWorker(
        session_factory=session_factory or get_session_factory(),
        storage=storage or get_object_storage(),
        pipeline=MaterialAnalysisPipeline(
            extraction_service=DocumentExtractionService(),
            llm=llm,
        ),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run durable material-analysis jobs.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Claim and process at most one ready job, then exit.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="Idle wait between job checks when not using --once (default: 1).",
    )
    args = parser.parse_args(argv)
    if args.poll_interval_seconds <= 0:
        parser.error("--poll-interval-seconds must be greater than zero")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    worker = build_analysis_worker()

    if args.once:
        worker.run_once()
        return 0

    logger.info("analysis worker started")
    try:
        while True:
            if not worker.run_once():
                sleep(args.poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("analysis worker stopped")
        return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main().
    raise SystemExit(main())
