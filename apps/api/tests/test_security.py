from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.security import AuthPrincipal, get_current_principal
from app.main import create_app


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://unused",
        supabase_url="https://project.supabase.co",
        supabase_service_role_key="unused",
        web_origin="http://localhost:3000",
    )


@pytest.fixture
def jwks(signing_key: rsa.RSAPrivateKey) -> dict[str, object]:
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    return {"keys": [public_jwk]}


@pytest.fixture
def client(settings: Settings, jwks: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.core import security

    monkeypatch.setattr(security, "get_jwks", lambda _: jwks)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/api/v1/test-auth")
    def test_auth(principal: AuthPrincipal = Depends(get_current_principal)) -> dict[str, str | None]:
        return {"user_id": str(principal.user_id), "email": principal.email}

    return TestClient(app)


def make_token(
    signing_key: rsa.RSAPrivateKey,
    settings: Settings,
    user_id: str,
    **claims: object,
) -> str:
    payload: dict[str, object] = {
        "sub": user_id,
        "email": "applicant@example.com",
        "aud": settings.supabase_jwt_audience,
        "iss": f"{settings.supabase_url}/auth/v1",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    payload.update(claims)
    return jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": "test-key"})


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_production_app_does_not_expose_test_auth_route() -> None:
    assert TestClient(create_app()).get("/api/v1/test-auth").status_code == 404


def test_missing_bearer_token_is_401(client: TestClient) -> None:
    response = client.get("/api/v1/test-auth")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert UUID(response.json()["error"]["request_id"])


def test_wrong_authorization_scheme_is_401(client: TestClient) -> None:
    response = client.get("/api/v1/test-auth", headers={"Authorization": "Basic abc"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_expired_token_is_rejected(client: TestClient, signing_key: rsa.RSAPrivateKey, settings: Settings, user_id: UUID) -> None:
    token = make_token(signing_key, settings, str(user_id), exp=datetime.now(UTC) - timedelta(seconds=1))

    response = client.get("/api/v1/test-auth", headers=auth_headers(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_TOKEN"


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "wrong-audience"},
        {"iss": "https://other.supabase.co/auth/v1"},
        {"sub": "not-a-uuid"},
    ],
)
def test_invalid_token_claims_are_rejected(
    client: TestClient,
    signing_key: rsa.RSAPrivateKey,
    settings: Settings,
    user_id: UUID,
    claims: dict[str, object],
) -> None:
    token = make_token(signing_key, settings, str(user_id), **claims)

    response = client.get("/api/v1/test-auth", headers=auth_headers(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_TOKEN"


def test_valid_token_returns_principal(client: TestClient, signing_key: rsa.RSAPrivateKey, settings: Settings, user_id: UUID) -> None:
    token = make_token(signing_key, settings, str(user_id))

    response = client.get("/api/v1/test-auth", headers=auth_headers(token))

    assert response.status_code == 200
    assert response.json() == {"user_id": str(user_id), "email": "applicant@example.com"}


def test_token_with_an_invalid_signature_is_rejected(
    client: TestClient, settings: Settings, user_id: UUID
) -> None:
    another_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(another_key, settings, str(user_id))

    response = client.get("/api/v1/test-auth", headers=auth_headers(token))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_INVALID_TOKEN"


def test_cors_allows_only_configured_web_origin(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization, content-type, idempotency-key, x-request-id",
        },
    )
    denied = client.options(
        "/api/v1/health",
        headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert set(allowed.headers["access-control-allow-headers"].lower().split(", ")) >= {
        "authorization",
        "content-type",
        "idempotency-key",
        "x-request-id",
    }
    assert "access-control-allow-origin" not in denied.headers
