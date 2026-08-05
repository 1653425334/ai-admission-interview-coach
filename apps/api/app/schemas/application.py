"""Request and response schemas for owned applications."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_serializer, field_validator

from app.schemas.document import DocumentResponse


class ApplicationCreate(BaseModel):
    target_school: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    target_program: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    degree_type: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=100)] = None

    @field_validator("degree_type")
    @classmethod
    def degree_type_must_not_be_blank(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("degree_type must not be blank when provided")
        return value


class ApplicationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    target_school: str
    target_program: str
    degree_type: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_utc_timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


class ApplicationDetailResponse(ApplicationSummaryResponse):
    documents: list[DocumentResponse]


class ApplicationListResponse(BaseModel):
    items: list[ApplicationSummaryResponse]
