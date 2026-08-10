"""Minimal durable worker for persisted fake material-analysis jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Callable
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db.models.analysis_run import AnalysisRun
from app.db.models.document import Document
from app.db.models.job import Job
from app.db.models.llm_run import LlmRun
from app.parsers.pdf_text import PdfTextExtractionError
from app.schemas.interview_map import DocumentType, InterviewMap
from app.services.analysis_runs import input_manifest_matches_current_documents
from app.services.document_extraction import (
    AnalysisDocumentInput,
    DocumentIntegrityError,
    DocumentReadError,
    DocumentReader,
)
from app.services.evidence_validation import EvidenceValidationError
from app.services.interview_map_validation import InterviewMapValidationError
from app.services.material_analysis import MaterialAnalysisPipeline
from app.storage.base import ObjectStorage

MAX_JOB_ATTEMPTS = 3
DEFAULT_LOCK_TIMEOUT = timedelta(minutes=5)


class InputChangedError(ValueError):
    code = "ANALYSIS_INPUT_CHANGED"


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: UUID
    analysis_run_id: UUID


@dataclass(frozen=True, slots=True)
class PreparedWork:
    analysis_run_id: UUID
    inputs: list[AnalysisDocumentInput]
    storage_keys: dict[UUID, str]


class StorageDocumentReader(DocumentReader):
    """Adapt owned storage keys into the Phase 2 document-reader contract."""

    def __init__(self, storage: ObjectStorage, storage_keys: dict[UUID, str]) -> None:
        self._storage = storage
        self._storage_keys = dict(storage_keys)

    def read(self, document: AnalysisDocumentInput) -> bytes:
        try:
            storage_key = self._storage_keys[document.document_id]
        except KeyError as error:
            raise DocumentReadError("A snapshot document is no longer available") from error
        return self._storage.get(storage_key)


class DurableAnalysisWorker:
    """Claim, execute and settle one durable analysis job at a time."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        storage: ObjectStorage,
        pipeline: MaterialAnalysisPipeline,
        lock_timeout: timedelta = DEFAULT_LOCK_TIMEOUT,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._pipeline = pipeline
        self._lock_timeout = lock_timeout
        self._now = now or (lambda: datetime.now(timezone.utc))

    def run_once(self) -> bool:
        """Claim and settle at most one job; return false when no work is ready."""

        claimed = self._claim_next_job()
        if claimed is None:
            return False
        try:
            prepared = self._prepare_work(claimed)
            reader = StorageDocumentReader(self._storage, prepared.storage_keys)
            extracted_documents = self._pipeline.extract_documents(prepared.inputs, reader)
            self._mark_building_map(claimed.analysis_run_id)
            started = perf_counter()
            interview_map = self._pipeline.generate_validated_map(
                extracted_documents, claimed.analysis_run_id
            )
            latency_ms = int((perf_counter() - started) * 1000)
            self._persist_success(claimed, extracted_documents, interview_map, latency_ms)
        except Exception as error:
            self._record_failure(claimed, error)
        return True

    def _claim_next_job(self) -> ClaimedJob | None:
        now = self._now()
        stale_before = now - self._lock_timeout
        with self._session_factory() as db:
            with db.begin():
                job = db.scalar(
                    select(Job)
                    .where(
                        or_(
                            and_(Job.status == "PENDING", Job.available_at <= now),
                            and_(Job.status == "RUNNING", Job.locked_at < stale_before),
                        )
                    )
                    .order_by(Job.available_at.asc(), Job.created_at.asc(), Job.id.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if job is None:
                    return None
                analysis_run = db.get(AnalysisRun, job.entity_id)
                if analysis_run is None:
                    job.status = "FAILED"
                    job.error_code = "ANALYSIS_NOT_FOUND"
                    job.error_message = "The analysis run no longer exists."
                    job.completed_at = now
                    return None
                if job.attempts >= MAX_JOB_ATTEMPTS:
                    self._mark_terminal_failure(
                        analysis_run,
                        job,
                        code="ANALYSIS_FAILED",
                        message="The analysis exhausted its retry limit.",
                    )
                    return None
                job.status = "RUNNING"
                job.attempts += 1
                job.locked_at = now
                job.error_code = None
                job.error_message = None
                analysis_run.status = "RUNNING"
                analysis_run.started_at = analysis_run.started_at or now
                analysis_run.error_code = None
                analysis_run.error_message = None
                return ClaimedJob(job_id=job.id, analysis_run_id=analysis_run.id)

    def _prepare_work(self, claimed: ClaimedJob) -> PreparedWork:
        with self._session_factory() as db:
            with db.begin():
                analysis_run = _required_analysis_run(db, claimed.analysis_run_id)
                _required_running_job(db, claimed.job_id)
                if not input_manifest_matches_current_documents(db, analysis_run):
                    raise InputChangedError("The source documents changed before analysis started")
                documents = _current_documents(db, analysis_run.application_id)
                document_by_id = {document.id: document for document in documents}
                snapshot_documents = analysis_run.input_manifest_json["documents"]
                inputs = [
                    AnalysisDocumentInput(
                        document_id=UUID(snapshot["document_id"]),
                        document_type=DocumentType(snapshot["document_type"]),
                        sha256=snapshot["sha256"],
                    )
                    for snapshot in snapshot_documents
                ]
                for document in documents:
                    document.parse_status = "PARSING"
                    document.parse_error = None
                analysis_run.stage = "PARSE_DOCUMENTS"
                return PreparedWork(
                    analysis_run_id=analysis_run.id,
                    inputs=inputs,
                    storage_keys={item.document_id: document_by_id[item.document_id].storage_key for item in inputs},
                )

    def _mark_building_map(self, analysis_run_id: UUID) -> None:
        with self._session_factory() as db:
            with db.begin():
                analysis_run = _required_analysis_run(db, analysis_run_id)
                if not input_manifest_matches_current_documents(db, analysis_run):
                    raise InputChangedError("The source documents changed during parsing")
                analysis_run.stage = "BUILD_INTERVIEW_MAP"

    def _persist_success(
        self,
        claimed: ClaimedJob,
        extracted_documents: list[object],
        interview_map: InterviewMap,
        latency_ms: int,
    ) -> None:
        with self._session_factory() as db:
            with db.begin():
                analysis_run = _required_analysis_run(db, claimed.analysis_run_id)
                job = _required_running_job(db, claimed.job_id)
                if not input_manifest_matches_current_documents(db, analysis_run):
                    raise InputChangedError("The source documents changed before map persistence")
                documents = {document.id: document for document in _current_documents(db, analysis_run.application_id)}
                for extracted_document in extracted_documents:
                    manifest = extracted_document.manifest  # type: ignore[attr-defined]
                    document = documents[manifest.document_id]
                    document.parse_status = "PARSED"
                    document.extracted_text = extracted_document.canonical_text  # type: ignore[attr-defined]
                    document.parse_error = None
                    document.parser_version = analysis_run.input_manifest_json["parser_version"]
                    document.page_count = manifest.page_count
                    document.parsed_at = self._now()
                now = self._now()
                analysis_run.interview_map_json = interview_map.model_dump(mode="json")
                analysis_run.status = "COMPLETED"
                analysis_run.stage = "COMPLETED"
                analysis_run.completed_at = now
                job.status = "COMPLETED"
                job.completed_at = now
                job.locked_at = None
                db.add(
                    LlmRun(
                        operation="BUILD_INTERVIEW_MAP",
                        entity_id=analysis_run.id,
                        provider=analysis_run.provider,
                        model=analysis_run.model,
                        prompt_version=analysis_run.prompt_version,
                        schema_version=analysis_run.schema_version,
                        status="COMPLETED",
                        input_tokens=0,
                        output_tokens=0,
                        latency_ms=latency_ms,
                        estimated_cost_usd=0,
                    )
                )

    def _record_failure(self, claimed: ClaimedJob, error: Exception) -> None:
        code, message, retryable = _classify_error(error)
        with self._session_factory() as db:
            with db.begin():
                job = db.get(Job, claimed.job_id)
                analysis_run = db.get(AnalysisRun, claimed.analysis_run_id)
                if job is None or analysis_run is None or job.status != "RUNNING":
                    return
                if retryable and job.attempts < MAX_JOB_ATTEMPTS:
                    job.status = "PENDING"
                    job.available_at = self._now() + timedelta(seconds=5 * job.attempts)
                    job.locked_at = None
                    job.error_code = code
                    job.error_message = message
                    analysis_run.status = "PENDING"
                    analysis_run.stage = "QUEUED"
                    analysis_run.error_code = code
                    analysis_run.error_message = message
                    return
                self._mark_terminal_failure(analysis_run, job, code=code, message=message)
                if code in {"PDF_PARSE_FAILED", "EMPTY_EXTRACTED_TEXT"}:
                    for document in _current_documents(db, analysis_run.application_id):
                        if document.parse_status == "PARSING":
                            document.parse_status = "FAILED"
                            document.parse_error = code

    def _mark_terminal_failure(
        self, analysis_run: AnalysisRun, job: Job, *, code: str, message: str
    ) -> None:
        now = self._now()
        job.status = "FAILED"
        job.locked_at = None
        job.completed_at = now
        job.error_code = code
        job.error_message = message
        analysis_run.status = "FAILED"
        analysis_run.stage = "FAILED"
        analysis_run.completed_at = now
        analysis_run.error_code = code
        analysis_run.error_message = message


def _required_analysis_run(db: Session, analysis_run_id: UUID) -> AnalysisRun:
    analysis_run = db.get(AnalysisRun, analysis_run_id)
    if analysis_run is None:
        raise InputChangedError("The analysis run no longer exists")
    return analysis_run


def _required_running_job(db: Session, job_id: UUID) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.status != "RUNNING":
        raise InputChangedError("The analysis job is no longer running")
    return job


def _current_documents(db: Session, application_id: UUID) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(Document.application_id == application_id)
            .order_by(Document.document_type.asc())
        )
    )


def _classify_error(error: Exception) -> tuple[str, str, bool]:
    if isinstance(error, InputChangedError):
        return error.code, "The source documents changed during analysis.", False
    if isinstance(error, DocumentIntegrityError):
        return "ANALYSIS_INPUT_CHANGED", "The source document no longer matches its snapshot.", False
    if isinstance(error, DocumentReadError):
        return error.code, "The private document could not be read. Retrying is safe.", True
    if isinstance(error, PdfTextExtractionError):
        return error.code, "The source PDF could not be parsed.", False
    if isinstance(error, (InterviewMapValidationError, EvidenceValidationError)):
        return "EVIDENCE_VALIDATION_FAILED", "The generated interview map failed validation.", False
    return "ANALYSIS_FAILED", "The analysis failed temporarily and can be retried.", True
