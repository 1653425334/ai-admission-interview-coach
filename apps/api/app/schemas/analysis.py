"""Safe HTTP representations of durable material-analysis runs."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.db.models.analysis_run import AnalysisRun
from app.schemas.interview_map import InterviewMap


class AnalysisRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalysisStage(StrEnum):
    QUEUED = "QUEUED"
    PARSE_DOCUMENTS = "PARSE_DOCUMENTS"
    BUILD_INTERVIEW_MAP = "BUILD_INTERVIEW_MAP"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalysisRunResponse(BaseModel):
    """Never exposes input manifests, storage keys, or raw provider output."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    application_id: UUID
    status: AnalysisRunStatus
    stage: AnalysisStage
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    interview_map: InterviewMap | None = None

    @field_serializer("created_at", "started_at", "completed_at")
    def serialize_utc_timestamp(self, value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value is not None else None


def analysis_run_response(analysis_run: AnalysisRun) -> AnalysisRunResponse:
    """Convert an owned run while exposing the map only after completion."""

    interview_map = None
    if analysis_run.status == AnalysisRunStatus.COMPLETED.value:
        if analysis_run.interview_map_json is None:
            raise ValueError("Completed analysis run is missing its InterviewMap")
        interview_map = InterviewMap.model_validate(analysis_run.interview_map_json)
    return AnalysisRunResponse(
        id=analysis_run.id,
        application_id=analysis_run.application_id,
        status=analysis_run.status,
        stage=analysis_run.stage,
        error_code=analysis_run.error_code,
        error_message=analysis_run.error_message,
        created_at=analysis_run.created_at,
        started_at=analysis_run.started_at,
        completed_at=analysis_run.completed_at,
        interview_map=interview_map,
    )
