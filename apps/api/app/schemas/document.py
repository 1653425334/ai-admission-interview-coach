"""Safe document metadata exposed by application responses."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer


class DocumentType(StrEnum):
    CV = "CV"
    PS = "PS"


class ParseStatus(StrEnum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    FAILED = "FAILED"


class DocumentResponse(BaseModel):
    """Only non-sensitive document metadata is serialized to API clients."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    document_type: DocumentType
    original_filename: str
    mime_type: str
    size_bytes: int
    parse_status: ParseStatus
    created_at: datetime

    @field_serializer("created_at")
    def serialize_utc_timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()
