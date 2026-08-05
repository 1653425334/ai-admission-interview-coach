"""Owned document upload and deletion operations."""

from __future__ import annotations

import logging
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models.application import Application
from app.db.models.document import Document
from app.schemas.document import DocumentType
from app.services.applications import get_owned_application
from app.services.pdf_validation import ValidatedPdf
from app.storage.base import ObjectStorage

logger = logging.getLogger(__name__)

_UNSAFE_FILENAME_CHARACTER = re.compile(r"[^\w.-]+", flags=re.UNICODE)
_MAX_FILENAME_LENGTH = 120


def sanitize_pdf_filename(filename: str | None) -> str:
    """Return a non-empty, single-segment PDF filename safe for object keys."""
    candidate = unicodedata.normalize("NFKC", filename or "")
    candidate = candidate.replace("\\", "/").rsplit("/", 1)[-1]
    candidate = "".join(character for character in candidate if not unicodedata.category(character).startswith("C"))
    candidate = _UNSAFE_FILENAME_CHARACTER.sub("_", candidate).strip(" ._")

    if candidate.lower().endswith(".pdf"):
        stem = candidate[:-4].rstrip(" ._")
    else:
        stem = candidate.rsplit(".", 1)[0].rstrip(" ._") if "." in candidate else candidate
    stem = stem or "document"
    # Reserve four characters for the required extension.
    stem = stem[: _MAX_FILENAME_LENGTH - 4].rstrip(" ._") or "document"
    return f"{stem}.pdf"


def build_storage_key(
    *, user_id: UUID, application_id: UUID, document_id: UUID, filename: str
) -> str:
    return f"{user_id}/{application_id}/{document_id}/{sanitize_pdf_filename(filename)}"


def create_document(
    db: Session,
    storage: ObjectStorage,
    *,
    application_id: UUID,
    user_id: UUID,
    document_type: DocumentType,
    original_filename: str | None,
    validated_pdf: ValidatedPdf,
    request_id: str,
) -> Document:
    """Store validated bytes, then atomically persist their owned metadata."""
    get_owned_application(db, application_id, user_id)

    existing = db.scalar(
        select(Document.id).where(
            Document.application_id == application_id,
            Document.document_type == document_type.value,
        )
    )
    if existing is not None:
        raise _duplicate_document_error(document_type)

    document_id = uuid4()
    safe_filename = sanitize_pdf_filename(original_filename)
    storage_key = build_storage_key(
        user_id=user_id,
        application_id=application_id,
        document_id=document_id,
        filename=safe_filename,
    )
    storage.put(storage_key, validated_pdf.content, "application/pdf")

    document = Document(
        id=document_id,
        application_id=application_id,
        document_type=document_type.value,
        original_filename=safe_filename,
        storage_key=storage_key,
        mime_type="application/pdf",
        size_bytes=len(validated_pdf.content),
        sha256=validated_pdf.sha256,
        parse_status="UPLOADED",
    )
    try:
        db.add(document)
        db.flush()
        db.refresh(document)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        _best_effort_delete(storage, storage_key, request_id)
        if _is_duplicate_document_integrity_error(error):
            raise _duplicate_document_error(document_type) from None
        raise ApiError(
            500,
            "DOCUMENT_SAVE_FAILED",
            "The document metadata could not be saved.",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        _best_effort_delete(storage, storage_key, request_id)
        raise ApiError(
            500,
            "DOCUMENT_SAVE_FAILED",
            "The document metadata could not be saved.",
        ) from None
    return document


def delete_owned_document(
    db: Session,
    storage: ObjectStorage,
    *,
    document_id: UUID,
    user_id: UUID,
) -> None:
    """Delete an owned private object before removing its metadata row."""
    document = db.scalar(
        select(Document)
        .join(Application, Document.application_id == Application.id)
        .where(Document.id == document_id, Application.user_id == user_id)
    )
    if document is None:
        raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document not found.")

    try:
        storage.delete(document.storage_key)
    except Exception:
        raise ApiError(
            503,
            "STORAGE_DELETE_FAILED",
            "The document could not be deleted from storage.",
        ) from None

    db.delete(document)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise ApiError(
            500,
            "DOCUMENT_DELETE_FAILED",
            "The document metadata could not be deleted.",
        ) from None


def _duplicate_document_error(document_type: DocumentType) -> ApiError:
    return ApiError(
        409,
        "DOCUMENT_TYPE_ALREADY_EXISTS",
        f"A {document_type.value} document already exists for this application.",
    )


def _is_duplicate_document_integrity_error(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    return (
        getattr(diagnostic, "constraint_name", None)
        == "uq_documents_application_document_type"
    )


def _best_effort_delete(storage: ObjectStorage, storage_key: str, request_id: str) -> None:
    try:
        storage.delete(storage_key)
    except Exception:
        # Deliberately omit provider errors, file content, and credentials.
        logger.warning(
            "document_upload_cleanup_failed request_id=%s storage_key=%s",
            request_id,
            storage_key,
        )
