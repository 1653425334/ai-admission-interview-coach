from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
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

    @app.get("/api/v1/http-unauthorized")
    def http_unauthorized() -> None:
        raise HTTPException(status_code=401, detail="not safe to expose")

    @app.get("/api/v1/validation-error")
    def validation_error(required_number: int) -> dict[str, int]:
        return {"required_number": required_number}

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
    request_id = str(uuid4())
    response = make_client().get("/api/v1/unexpected-error", headers={"X-Request-ID": request_id})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert response.json()["error"]["message"] == "An unexpected error occurred."
    assert response.headers["x-request-id"] == request_id
    assert response.json()["error"]["request_id"] == request_id
    assert "password" not in response.text


def test_validation_error_has_matching_request_id_in_header_and_envelope() -> None:
    request_id = str(uuid4())
    response = make_client().get("/api/v1/validation-error", headers={"X-Request-ID": request_id})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.headers["x-request-id"] == request_id
    assert response.json()["error"]["request_id"] == request_id


def test_framework_401_has_bearer_challenge_and_safe_envelope() -> None:
    request_id = str(uuid4())
    response = make_client().get("/api/v1/http-unauthorized", headers={"X-Request-ID": request_id})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["x-request-id"] == request_id
    assert response.json()["error"]["request_id"] == request_id
