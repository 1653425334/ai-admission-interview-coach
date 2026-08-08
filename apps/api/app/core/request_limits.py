"""ASGI ingress limits for multipart document uploads.

The transport limit includes multipart framing, so it is deliberately a little
larger than the 10 MiB business limit for one PDF.  The route still enforces
the exact file-size limit after multipart parsing.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.pdf_validation import MAX_PDF_BYTES

MULTIPART_TRANSPORT_OVERHEAD_BYTES = 64 * 1024
MAX_DOCUMENT_UPLOAD_REQUEST_BYTES = MAX_PDF_BYTES + MULTIPART_TRANSPORT_OVERHEAD_BYTES

_HTTP_REQUEST = "http.request"


class _RequestBodyTooLarge(Exception):
    """Stop downstream multipart parsing as soon as the bounded total is exceeded."""


def _request_id(scope: Scope) -> str:
    """Use the same UUID validation rules as the request-ID middleware."""
    supplied = next(
        (value.decode("latin-1") for name, value in scope["headers"] if name == b"x-request-id"),
        None,
    )
    try:
        request_id = str(UUID(supplied)) if supplied else str(uuid4())
    except ValueError:
        request_id = str(uuid4())
    scope.setdefault("state", {})["request_id"] = request_id
    return request_id


def _is_document_upload(scope: Scope) -> bool:
    if scope["type"] != "http" or scope["method"] != "POST":
        return False
    parts = scope["path"].split("/")
    if len(parts) != 6 or parts[:4] != ["", "api", "v1", "applications"] or parts[-1] != "documents":
        return False
    try:
        UUID(parts[4])
    except ValueError:
        return False
    return True


def _content_length_exceeds_limit(scope: Scope) -> bool:
    values = [value for name, value in scope["headers"] if name == b"content-length"]
    if len(values) != 1:
        return False
    try:
        return int(values[0]) > MAX_DOCUMENT_UPLOAD_REQUEST_BYTES
    except ValueError:
        return False


async def _send_too_large(send: Send, request_id: str) -> None:
    body = json.dumps(
        {
            "error": {
                "code": "FILE_TOO_LARGE",
                "message": "The PDF must be 10 MB or smaller.",
                "request_id": request_id,
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"x-request-id", request_id.encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class DocumentUploadRequestLimitMiddleware:
    """Reject oversized document-upload bodies before Starlette spools multipart data."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not _is_document_upload(scope):
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)
        if _content_length_exceeds_limit(scope):
            await _send_too_large(send, request_id)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == _HTTP_REQUEST:
                received += len(message.get("body", b""))
                if received > MAX_DOCUMENT_UPLOAD_REQUEST_BYTES:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            # Multipart parsing occurs before the endpoint can start a response.
            # Do not risk a second response if a future route changes that behavior.
            if not response_started:
                await _send_too_large(send, request_id)


class RequestIdMiddleware:
    """Assign a request ID without BaseHTTPMiddleware task groups around ASGI bodies."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(scope)

        async def add_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(name.lower() == b"x-request-id" for name, _ in headers):
                    headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, add_request_id)
