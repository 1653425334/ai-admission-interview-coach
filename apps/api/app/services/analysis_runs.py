"""Create immutable input snapshots and durable analysis jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.analysis_run import AnalysisRun
from app.db.models.application import Application
from app.db.models.document import Document
from app.db.models.job import Job

ANALYSIS_INPUT_SCHEMA_VERSION = "analysis-input-v1"
INTERVIEW_MAP_SCHEMA_VERSION = "interview-map-v1"
PARSER_VERSION = "pdf-text-v1"
FAKE_PROVIDER = "fake"
FAKE_MODEL = "fake-interview-map-v1"
FAKE_PROMPT_VERSION = "fake-interview-map-v1"
ACTIVE_ANALYSIS_STATUSES = ("PENDING", "RUNNING")


class AnalysisDocumentsRequiredError(ValueError):
    code = "ANALYSIS_DOCUMENTS_REQUIRED"


@dataclass(frozen=True, slots=True)
class AnalysisRunResult:
    analysis_run: AnalysisRun
    created: bool


def create_or_reuse_analysis_run(
    db: Session,
    *,
    application_id: UUID,
    idempotency_key: str | None = None,
    provider: str = FAKE_PROVIDER,
    model: str = FAKE_MODEL,
    prompt_version: str = FAKE_PROMPT_VERSION,
) -> AnalysisRunResult:
    """Create one durable fake-analysis job, or safely reuse an equivalent run.

    This service does not commit the caller's transaction. The partial unique
    index is the final race-condition guard; Phase 4 will translate any unique
    violation into a safe API response.
    """

    if idempotency_key is not None:
        existing_by_key = db.scalar(
            select(AnalysisRun).where(
                AnalysisRun.application_id == application_id,
                AnalysisRun.idempotency_key == idempotency_key,
            )
        )
        if existing_by_key is not None:
            return AnalysisRunResult(existing_by_key, created=False)

    manifest = build_input_manifest(db, application_id)
    active_run = db.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.application_id == application_id,
            AnalysisRun.status.in_(ACTIVE_ANALYSIS_STATUSES),
        )
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
    )
    if active_run is not None:
        return AnalysisRunResult(active_run, created=False)

    completed_runs = db.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.application_id == application_id,
            AnalysisRun.status == "COMPLETED",
        )
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
    )
    for completed_run in completed_runs:
        if completed_run.input_manifest_json == manifest:
            return AnalysisRunResult(completed_run, created=False)

    analysis_run = AnalysisRun(
        application_id=application_id,
        status="PENDING",
        stage="QUEUED",
        input_manifest_json=manifest,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        schema_version=INTERVIEW_MAP_SCHEMA_VERSION,
        idempotency_key=idempotency_key,
    )
    db.add(analysis_run)
    db.flush()
    db.add(Job(job_type="ANALYZE_APPLICATION", entity_id=analysis_run.id, status="PENDING"))
    db.flush()
    return AnalysisRunResult(analysis_run, created=True)


def build_input_manifest(db: Session, application_id: UUID) -> dict[str, Any]:
    """Snapshot exactly one current CV and PS without retaining storage keys."""

    documents = list(
        db.scalars(
            select(Document)
            .where(Document.application_id == application_id)
            .order_by(Document.document_type.asc())
        )
    )
    by_type = {document.document_type: document for document in documents}
    if set(by_type) != {"CV", "PS"} or len(documents) != 2:
        raise AnalysisDocumentsRequiredError("A current CV and PS are required for analysis")
    application = db.get(Application, application_id)
    if application is None:
        raise ValueError("Application no longer exists")
    return {
        "schema_version": ANALYSIS_INPUT_SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
        "interview_map_schema_version": INTERVIEW_MAP_SCHEMA_VERSION,
        "application_context": {
            "target_school": application.target_school,
            "target_program": application.target_program,
            "program_url": application.program_url,
            "program_description": application.program_description,
        },
        "documents": [
            {
                "document_id": str(by_type[document_type].id),
                "document_type": document_type,
                "sha256": by_type[document_type].sha256,
            }
            for document_type in ("CV", "PS")
        ],
    }


def input_manifest_matches_current_documents(db: Session, analysis_run: AnalysisRun) -> bool:
    """Return true only while source IDs, types and hashes still match exactly."""

    try:
        return analysis_run.input_manifest_json == build_input_manifest(db, analysis_run.application_id)
    except AnalysisDocumentsRequiredError:
        return False


def delete_analysis_runs_for_application(db: Session, application_id: UUID) -> None:
    """Remove maps containing source excerpts before one source document is deleted."""

    db.execute(delete(AnalysisRun).where(AnalysisRun.application_id == application_id))


def get_owned_analysis_run(db: Session, analysis_run_id: UUID, user_id: UUID) -> AnalysisRun:
    """Hide existence of an analysis run that belongs to another user."""

    analysis_run = db.scalar(
        select(AnalysisRun)
        .join(Application, AnalysisRun.application_id == Application.id)
        .where(AnalysisRun.id == analysis_run_id, Application.user_id == user_id)
    )
    if analysis_run is None:
        raise ApiError(404, "ANALYSIS_RUN_NOT_FOUND", "Analysis run not found.")
    return analysis_run


def get_latest_current_analysis_run(db: Session, application_id: UUID) -> AnalysisRun | None:
    """Return only a completed map that still matches current source material."""

    completed_runs = db.scalars(
        select(AnalysisRun)
        .where(
            AnalysisRun.application_id == application_id,
            AnalysisRun.status == "COMPLETED",
        )
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc())
    )
    for analysis_run in completed_runs:
        if input_manifest_matches_current_documents(db, analysis_run):
            return analysis_run
    return None
