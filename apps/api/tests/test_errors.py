from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ApiError
from app.main import create_app


def make_client() -> TestClient:
    app: FastAPI = create_app()

    @app.get("/api/v1/known-error")
    def known_error() -> None:
        raise ApiError(409, "CONFLICT", "A safe conflict message.")

    @app.get("/api/v1/unexpected-error")
    def unexpected_error() -> None:
        raise RuntimeError("database password is definitely not safe to expose")

    return TestClient(app, raise_server_exceptions=False)


def test_request_id_reuses_valid_uuid_and_replaces_invalid_values() -> None:
    client = make_client()
    supplied = str(uuid4())

    reused = client.get("/api/v1/health", headers={"X-Request-ID": supplied})
    replaced = client.get("/api/v1/health", headers={"X-Request-ID": "not-a-uuid"})

    assert reused.headers["x-request-id"] == supplied
    assert UUID(replaced.headers["x-request-id"])
    assert replaced.headers["x-request-id"] != "not-a-uuid"


def test_api_error_uses_safe_envelope_and_request_id() -> None:
    client = make_client()
    request_id = str(uuid4())

    response = client.get("/api/v1/known-error", headers={"X-Request-ID": request_id})

    assert response.status_code == 409
    assert response.headers["x-request-id"] == request_id
    assert response.json() == {
        "error": {"code": "CONFLICT", "message": "A safe conflict message.", "request_id": request_id}
    }


def test_unknown_error_does_not_leak_exception_text() -> None:
    response = make_client().get("/api/v1/unexpected-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["message"] == "An unexpected error occurred."
    assert UUID(response.json()["error"]["request_id"])
    assert "password" not in response.text
