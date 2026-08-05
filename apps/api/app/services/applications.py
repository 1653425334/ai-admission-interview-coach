"""Application ownership checks and database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError
from app.db.models.application import Application
from app.db.models.profile import Profile
from app.schemas.application import ApplicationCreate


def get_owned_application(db: Session, application_id: UUID, user_id: UUID) -> Application:
    """Return an application only when it belongs to the supplied user.

    A single not-found result intentionally covers both an absent application and
    one owned by a different user.
    """
    application = db.scalar(
        select(Application)
        .options(selectinload(Application.documents))
        .where(Application.id == application_id, Application.user_id == user_id)
    )
    if application is None:
        raise ApiError(404, "APPLICATION_NOT_FOUND", "Application not found.")
    application.documents.sort(key=lambda document: document.document_type)
    return application


def create_application(db: Session, user_id: UUID, payload: ApplicationCreate) -> Application:
    """Create an active application, provisioning the owned profile safely."""
    db.execute(
        insert(Profile)
        .values(id=user_id)
        .on_conflict_do_nothing(index_elements=[Profile.id])
    )
    application = Application(
        user_id=user_id,
        target_school=payload.target_school,
        target_program=payload.target_program,
        degree_type=payload.degree_type,
        status="ACTIVE",
    )
    db.add(application)
    db.flush()
    db.refresh(application)
    return application


def list_owned_applications(db: Session, user_id: UUID) -> list[Application]:
    """List current-user applications in deterministic newest-first order."""
    return list(
        db.scalars(
            select(Application)
            .where(Application.user_id == user_id)
            .order_by(Application.created_at.desc(), Application.id.desc())
        )
    )
