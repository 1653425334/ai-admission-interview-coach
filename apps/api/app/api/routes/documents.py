"""Secure owned document upload and deletion endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import AuthPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.document import DocumentResponse, DocumentType
from app.services.applications import get_owned_application
from app.services.documents import create_document, delete_owned_document
from app.services.pdf_validation import MAX_PDF_BYTES, validate_pdf
from app.storage.base import ObjectStorage
from app.storage.supabase import get_object_storage

router = APIRouter(tags=["documents"])


@router.post(
    "/applications/{application_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    application_id: UUID,
    request: Request,
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_object_storage),
) -> DocumentResponse:
    # Check ownership before spending work reading and parsing an untrusted file.
    get_owned_application(db, application_id, principal.user_id)
    content = await file.read(MAX_PDF_BYTES + 1)
    if len(content) > MAX_PDF_BYTES:
        raise ApiError(413, "FILE_TOO_LARGE", "The PDF must be 10 MB or smaller.")
    validated_pdf = validate_pdf(content, file.content_type)
    document = create_document(
        db,
        storage,
        application_id=application_id,
        user_id=principal.user_id,
        document_type=document_type,
        original_filename=file.filename,
        validated_pdf=validated_pdf,
        request_id=str(request.state.request_id),
    )
    return DocumentResponse.model_validate(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: UUID,
    principal: AuthPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_object_storage),
) -> Response:
    delete_owned_document(
        db,
        storage,
        document_id=document_id,
        user_id=principal.user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
