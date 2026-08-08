from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.core import request_limits
from app.core.request_limits import DocumentUploadRequestLimitMiddleware


def _upload_scope(*, headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/api/v1/applications/{uuid4()}/documents",
        "raw_path": b"/api/v1/applications/test/documents",
        "query_string": b"",
        "headers": headers or [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }


def _run_asgi(
    app: Callable[[Scope, Receive, Send], Awaitable[None]],
    scope: Scope,
    messages: list[Message],
) -> tuple[list[Message], int]:
    sent: list[Message] = []
    receive_calls = 0

    async def receive() -> Message:
        nonlocal receive_calls
        receive_calls += 1
        if not messages:
            raise AssertionError("middleware read past the bounded test stream")
        return messages.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent, receive_calls


def _error_body(sent: list[Message]) -> dict[str, object]:
    import json

    return json.loads(next(message["body"] for message in sent if message["type"] == "http.response.body"))


def test_content_length_limit_rejects_before_downstream_or_receive() -> None:
    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        raise AssertionError("oversized Content-Length reached downstream")

    request_id = str(uuid4())
    scope = _upload_scope(
        headers=[
            (b"content-length", str(request_limits.MAX_DOCUMENT_UPLOAD_REQUEST_BYTES + 1).encode()),
            (b"x-request-id", request_id.encode()),
        ]
    )
    sent, receive_calls = _run_asgi(
        DocumentUploadRequestLimitMiddleware(downstream), scope, []
    )

    assert receive_calls == 0
    assert sent[0]["status"] == 413
    assert dict(sent[0]["headers"])[b"x-request-id"] == request_id.encode()
    assert _error_body(sent) == {
        "error": {
            "code": "FILE_TOO_LARGE",
            "message": "The PDF must be 10 MB or smaller.",
            "request_id": request_id,
        }
    }


def test_chunked_upload_stops_after_crossing_bounded_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(request_limits, "MAX_DOCUMENT_UPLOAD_REQUEST_BYTES", 16)

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if not message.get("more_body", False):
                return

    sent, receive_calls = _run_asgi(
        DocumentUploadRequestLimitMiddleware(downstream),
        _upload_scope(),
        [
            {"type": "http.request", "body": b"12345678", "more_body": True},
            {"type": "http.request", "body": b"abcdefgh", "more_body": True},
            {"type": "http.request", "body": b"!", "more_body": True},
            {"type": "http.request", "body": b"must-not-be-read", "more_body": False},
        ],
    )

    assert receive_calls == 3
    assert sent[0]["status"] == 413
    assert _error_body(sent)["error"]["code"] == "FILE_TOO_LARGE"
