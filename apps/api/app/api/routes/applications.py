"""Owned application endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.security import AuthPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.application import (
    ApplicationCreate,
    ApplicationDetailResponse,
    ApplicationListResponse,
    ApplicationSummaryResponse,
    ProgramContextUpdate,
)
from app.services.applications import (
    create_application,
    get_owned_application,
    list_owned_applications,
    update_program_context,
)


router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationSummaryResponse, status_code=status.HTTP_201_CREATED)
def create_owned_application(
    payload: ApplicationCreate,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ApplicationSummaryResponse:
    return ApplicationSummaryResponse.model_validate(create_application(db, principal.user_id, payload))


@router.get("", response_model=ApplicationListResponse)
def list_applications(
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ApplicationListResponse:
    return ApplicationListResponse(
        items=[ApplicationSummaryResponse.model_validate(item) for item in list_owned_applications(db, principal.user_id)]
    )


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
def get_application(
    application_id: UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ApplicationDetailResponse:
    return ApplicationDetailResponse.model_validate(
        get_owned_application(db, application_id, principal.user_id)
    )


@router.patch("/{application_id}/program-context", response_model=ApplicationDetailResponse)
def update_owned_program_context(
    application_id: UUID,
    payload: ProgramContextUpdate,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> ApplicationDetailResponse:
    return ApplicationDetailResponse.model_validate(
        update_program_context(
            db, application_id=application_id, user_id=principal.user_id, payload=payload
        )
    )
