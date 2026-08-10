"""PostgreSQL integration tests for the Phase 3 durable fake-analysis worker."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.fake_interview_map import FakeInterviewMapLLM
from app.core.config import get_settings
from app.db.alembic_config import configparser_safe_url
from app.db.models.analysis_run import AnalysisRun
from app.db.models.application import Application
from app.db.models.document import Document
from app.db.models.job import Job
from app.db.models.llm_run import LlmRun
from app.db.models.profile import Profile
from app.schemas.document import DocumentType
from app.schemas.interview_map import InterviewMap
from app.services.analysis_runs import create_or_reuse_analysis_run
from app.services.document_extraction import DocumentExtractionService
from app.services.documents import delete_owned_document
from app.services.material_analysis import MaterialAnalysisPipeline
from app.workers.analysis_worker import DurableAnalysisWorker
from app.workers.run_analysis_worker import build_analysis_worker
from tests.pdf_factory import build_pdf


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
CV_TEXT = "Developed an attention-based model to improve robustness under noisy inputs."
PS_TEXT = "I want to study reliable machine learning systems for healthcare."


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = dict(objects)

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class TemporarilyUnavailableStorage(FakeStorage):
    def get(self, key: str) -> bytes:
        raise RuntimeError(f"temporary read failure for {key}")


class InvalidEvidenceGenerator:
    def generate(self, documents: list[object], analysis_run_id: UUID) -> InterviewMap:
        interview_map = FakeInterviewMapLLM().generate(documents, analysis_run_id)  # type: ignore[arg-type]
        invalid_evidence = interview_map.evidence[0].model_copy(
            update={"original_text": "Evidence absent from the source PDF."}
        )
        return interview_map.model_copy(update={"evidence": [invalid_evidence]})


@pytest.fixture
def analysis_engine(
    monkeypatch: pytest.MonkeyPatch, locked_test_database_url: str
) -> Iterator[Engine]:
    monkeypatch.setenv("DATABASE_URL", locked_test_database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", configparser_safe_url(locked_test_database_url))
    command.upgrade(config, "head")
    engine = create_engine(locked_test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        get_settings.cache_clear()


@pytest.fixture
def session_factory(analysis_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=analysis_engine, autoflush=False, expire_on_commit=False)


def _seed_application(
    factory: sessionmaker[Session],
) -> tuple[UUID, UUID, UUID, UUID, FakeStorage]:
    user_id = uuid4()
    application_id = uuid4()
    cv_id = uuid4()
    ps_id = uuid4()
    cv_bytes = build_pdf(text=CV_TEXT)
    ps_bytes = build_pdf(text=PS_TEXT)
    storage = FakeStorage({"private/cv.pdf": cv_bytes, "private/ps.pdf": ps_bytes})
    with factory() as db:
        db.add(Profile(id=user_id))
        db.add(
            Application(
                id=application_id,
                user_id=user_id,
                target_school="Example University",
                target_program="MSc AI",
                status="ACTIVE",
            )
        )
        db.add_all(
            [
                Document(
                    id=cv_id,
                    application_id=application_id,
                    document_type="CV",
                    original_filename="cv.pdf",
                    storage_key="private/cv.pdf",
                    mime_type="application/pdf",
                    size_bytes=len(cv_bytes),
                    sha256=sha256(cv_bytes).hexdigest(),
                    parse_status="UPLOADED",
                ),
                Document(
                    id=ps_id,
                    application_id=application_id,
                    document_type="PS",
                    original_filename="ps.pdf",
                    storage_key="private/ps.pdf",
                    mime_type="application/pdf",
                    size_bytes=len(ps_bytes),
                    sha256=sha256(ps_bytes).hexdigest(),
                    parse_status="UPLOADED",
                ),
            ]
        )
        db.commit()
    return user_id, application_id, cv_id, ps_id, storage


def _create_run(factory: sessionmaker[Session], application_id: UUID) -> UUID:
    with factory() as db:
        result = create_or_reuse_analysis_run(db, application_id=application_id)
        db.commit()
        return result.analysis_run.id


def _worker(factory: sessionmaker[Session], storage: FakeStorage, **kwargs: object) -> DurableAnalysisWorker:
    return DurableAnalysisWorker(
        session_factory=factory,
        storage=storage,
        pipeline=MaterialAnalysisPipeline(
            extraction_service=DocumentExtractionService(), llm=FakeInterviewMapLLM()
        ),
        **kwargs,
    )


def test_same_input_reuses_analysis_run_and_job(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, _cv_id, _ps_id, _storage = _seed_application(session_factory)
    with session_factory() as db:
        first = create_or_reuse_analysis_run(db, application_id=application_id)
        second = create_or_reuse_analysis_run(db, application_id=application_id)
        db.commit()
        assert first.created is True
        assert second.created is False
        assert first.analysis_run.id == second.analysis_run.id
        assert db.scalar(select(Job).where(Job.entity_id == first.analysis_run.id)) is not None
        assert first.analysis_run.input_manifest_json["parser_version"] == "pdf-text-v1"
        assert first.analysis_run.schema_version == "interview-map-v1"


def test_runtime_factory_consumes_a_job_with_the_fake_pipeline(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, _cv_id, _ps_id, storage = _seed_application(session_factory)
    analysis_run_id = _create_run(session_factory, application_id)

    assert build_analysis_worker(session_factory=session_factory, storage=storage).run_once() is True

    with session_factory() as db:
        run = db.get(AnalysisRun, analysis_run_id)
        assert run is not None
        assert run.status == "COMPLETED"
        assert run.interview_map_json is not None


def test_claiming_prevents_two_workers_from_processing_same_job(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, _cv_id, _ps_id, storage = _seed_application(session_factory)
    _create_run(session_factory, application_id)
    first_worker = _worker(session_factory, storage)
    second_worker = _worker(session_factory, storage)

    first_claim = first_worker._claim_next_job()
    second_claim = second_worker._claim_next_job()

    assert first_claim is not None
    assert second_claim is None


def test_stale_running_job_is_recovered_after_worker_restart(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, _cv_id, _ps_id, storage = _seed_application(session_factory)
    analysis_run_id = _create_run(session_factory, application_id)
    with session_factory() as db:
        run = db.get(AnalysisRun, analysis_run_id)
        job = db.scalar(select(Job).where(Job.entity_id == analysis_run_id))
        assert run is not None and job is not None
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        run.status = "RUNNING"
        job.status = "RUNNING"
        job.attempts = 1
        job.locked_at = stale_time
        db.commit()

    assert _worker(session_factory, storage, lock_timeout=timedelta(seconds=0)).run_once() is True
    with session_factory() as db:
        run = db.get(AnalysisRun, analysis_run_id)
        job = db.scalar(select(Job).where(Job.entity_id == analysis_run_id))
        assert run is not None and job is not None
        assert run.status == "COMPLETED"
        assert job.status == "COMPLETED"
        assert job.attempts == 2


def test_input_change_cannot_persist_an_old_interview_map(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, cv_id, _ps_id, storage = _seed_application(session_factory)
    analysis_run_id = _create_run(session_factory, application_id)
    with session_factory() as db:
        document = db.get(Document, cv_id)
        assert document is not None
        document.sha256 = "c" * 64
        db.commit()

    assert _worker(session_factory, storage).run_once() is True
    with session_factory() as db:
        run = db.get(AnalysisRun, analysis_run_id)
        assert run is not None
        assert run.status == "FAILED"
        assert run.error_code == "ANALYSIS_INPUT_CHANGED"
        assert run.interview_map_json is None


def test_deleting_source_document_removes_analysis_map_jobs_and_llm_metadata(
    session_factory: sessionmaker[Session],
) -> None:
    user_id, application_id, cv_id, _ps_id, storage = _seed_application(session_factory)
    analysis_run_id = _create_run(session_factory, application_id)
    assert _worker(session_factory, storage).run_once() is True

    with session_factory() as db:
        delete_owned_document(db, storage, document_id=cv_id, user_id=user_id)

    with session_factory() as db:
        assert db.get(AnalysisRun, analysis_run_id) is None
        assert db.scalar(select(Job).where(Job.entity_id == analysis_run_id)) is None
        assert db.scalar(select(LlmRun).where(LlmRun.entity_id == analysis_run_id)) is None
        assert db.get(Document, cv_id) is None
        assert db.get(Application, application_id) is not None


def test_llm_runs_store_metadata_without_material_content(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, _cv_id, _ps_id, storage = _seed_application(session_factory)
    analysis_run_id = _create_run(session_factory, application_id)
    assert _worker(session_factory, storage).run_once() is True

    with session_factory() as db:
        llm_run = db.scalar(select(LlmRun).where(LlmRun.entity_id == analysis_run_id))
        assert llm_run is not None
        assert llm_run.operation == "BUILD_INTERVIEW_MAP"
        assert llm_run.input_tokens == 0
        assert llm_run.output_tokens == 0
        assert llm_run.estimated_cost_usd == 0
        assert not hasattr(llm_run, "input_json")
        assert not hasattr(llm_run, "output_json")
        assert CV_TEXT not in str(llm_run.__dict__)
        assert PS_TEXT not in str(llm_run.__dict__)


def test_temporary_document_read_failure_is_requeued_safely(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, _cv_id, _ps_id, storage = _seed_application(session_factory)
    analysis_run_id = _create_run(session_factory, application_id)

    assert _worker(session_factory, TemporarilyUnavailableStorage(storage.objects)).run_once() is True
    with session_factory() as db:
        run = db.get(AnalysisRun, analysis_run_id)
        job = db.scalar(select(Job).where(Job.entity_id == analysis_run_id))
        assert run is not None and job is not None
        assert run.status == "PENDING"
        assert run.stage == "QUEUED"
        assert run.error_code == "DOCUMENT_READ_FAILED"
        assert job.status == "PENDING"
        assert job.attempts == 1


def test_invalid_generated_evidence_is_a_non_retryable_failure(
    session_factory: sessionmaker[Session],
) -> None:
    _user_id, application_id, _cv_id, _ps_id, storage = _seed_application(session_factory)
    analysis_run_id = _create_run(session_factory, application_id)
    worker = DurableAnalysisWorker(
        session_factory=session_factory,
        storage=storage,
        pipeline=MaterialAnalysisPipeline(
            extraction_service=DocumentExtractionService(), llm=InvalidEvidenceGenerator()
        ),
    )

    assert worker.run_once() is True
    with session_factory() as db:
        run = db.get(AnalysisRun, analysis_run_id)
        job = db.scalar(select(Job).where(Job.entity_id == analysis_run_id))
        assert run is not None and job is not None
        assert run.status == "FAILED"
        assert run.error_code == "EVIDENCE_VALIDATION_FAILED"
        assert job.status == "FAILED"
        assert job.attempts == 1
