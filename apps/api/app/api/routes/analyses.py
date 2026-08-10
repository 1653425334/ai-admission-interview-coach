"""Owned endpoints for creating and observing durable material analysis."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import AuthPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.analysis import AnalysisRunResponse, analysis_run_response
from app.services.analysis_runs import (
    AnalysisDocumentsRequiredError,
    create_or_reuse_analysis_run,
    get_latest_current_analysis_run,
    get_owned_analysis_run,
)
from app.services.applications import get_owned_application


router = APIRouter(tags=["analyses"])


@router.post(
    "/applications/{application_id}/analyses",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_analysis_run(
    application_id: UUID,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AnalysisRunResponse:
    get_owned_application(db, application_id, principal.user_id)
    try:
        result = create_or_reuse_analysis_run(
            db, application_id=application_id, idempotency_key=idempotency_key
        )
    except AnalysisDocumentsRequiredError:
        raise ApiError(
            422,
            "ANALYSIS_DOCUMENTS_REQUIRED",
            "Upload one CV and one personal statement before starting analysis.",
        ) from None
    return analysis_run_response(result.analysis_run)


@router.get("/analysis-runs/{analysis_run_id}", response_model=AnalysisRunResponse)
def get_analysis_run(
    analysis_run_id: UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AnalysisRunResponse:
    return analysis_run_response(get_owned_analysis_run(db, analysis_run_id, principal.user_id))


@router.get(
    "/applications/{application_id}/latest-analysis", response_model=AnalysisRunResponse
)
def get_latest_analysis(
    application_id: UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> AnalysisRunResponse:
    get_owned_application(db, application_id, principal.user_id)
    analysis_run = get_latest_current_analysis_run(db, application_id)
    if analysis_run is None:
        raise ApiError(404, "ANALYSIS_NOT_FOUND", "No current completed analysis was found.")
    return analysis_run_response(analysis_run)
