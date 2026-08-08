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
from app.core.errors import ApiError
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
        web_origin="https://web.example",
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
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/api/v1/test-auth")
    def test_auth(principal: AuthPrincipal = Depends(get_current_principal)) -> dict[str, str | None]:
        return {"user_id": str(principal.user_id), "email": principal.email}

    return TestClient(app)


def make_token(
    signing_key: rsa.RSAPrivateKey,
    settings: Settings,
    user_id: str,
    kid: str = "test-key",
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
    return jwt.encode(payload, signing_key, algorithm="RS256", headers={"kid": kid})


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_production_app_does_not_expose_test_auth_route() -> None:
    assert TestClient(create_app()).get("/api/v1/test-auth").status_code == 404


def test_app_factory_uses_validated_settings_for_cors() -> None:
    client = TestClient(create_app())
    allowed = client.options(
        "/api/v1/health",
        headers={"Origin": "https://web.example", "Access-Control-Request-Method": "GET"},
    )
    denied = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers["access-control-allow-origin"] == "https://web.example"
    assert "access-control-allow-origin" not in denied.headers


def test_app_factory_does_not_mask_settings_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    def missing_settings() -> Settings:
        raise RuntimeError("configuration missing")

    monkeypatch.setattr(main_module, "get_settings", missing_settings)
    with pytest.raises(RuntimeError, match="configuration missing"):
        main_module.create_app()


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
            "Origin": "https://web.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization, content-type, idempotency-key, x-request-id",
        },
    )
    denied = client.options(
        "/api/v1/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )

    assert allowed.headers["access-control-allow-origin"] == "https://web.example"
    assert set(allowed.headers["access-control-allow-headers"].lower().split(", ")) >= {
        "authorization",
        "content-type",
        "idempotency-key",
        "x-request-id",
    }
    assert "access-control-allow-origin" not in denied.headers


class _JwksResponse:
    def __init__(self, document: object) -> None:
        self.document = document

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        if isinstance(self.document, Exception):
            raise self.document
        return self.document


def test_jwks_network_and_json_failures_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import security

    security.get_jwks.cache_clear()

    def network_failure(url: str, *, timeout: float) -> _JwksResponse:
        raise security.httpx.ConnectError("provider host unavailable")

    monkeypatch.setattr(security.httpx, "get", network_failure)
    with pytest.raises(ApiError) as network_error:
        security.get_jwks("https://project.supabase.co/auth/v1/.well-known/jwks.json")
    assert network_error.value.status_code == 503
    assert network_error.value.code == "AUTH_UNAVAILABLE"
    assert "host unavailable" not in network_error.value.message

    security.get_jwks.cache_clear()
    monkeypatch.setattr(security.httpx, "get", lambda url, *, timeout: _JwksResponse(ValueError("bad json")))
    with pytest.raises(ApiError) as json_error:
        security.get_jwks("https://project.supabase.co/auth/v1/.well-known/jwks.json")
    assert json_error.value.status_code == 503
    assert json_error.value.code == "AUTH_UNAVAILABLE"

    security.get_jwks.cache_clear()
    monkeypatch.setattr(security.httpx, "get", lambda url, *, timeout: _JwksResponse({"keys": "invalid"}))
    with pytest.raises(ApiError) as malformed_error:
        security.get_jwks("https://project.supabase.co/auth/v1/.well-known/jwks.json")
    assert malformed_error.value.status_code == 503
    assert malformed_error.value.code == "AUTH_UNAVAILABLE"


def test_jwks_response_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import security

    calls = 0
    document: dict[str, object] = {"keys": []}
    security.get_jwks.cache_clear()

    def fetch(url: str, *, timeout: float) -> _JwksResponse:
        nonlocal calls
        calls += 1
        return _JwksResponse(document)

    monkeypatch.setattr(security.httpx, "get", fetch)

    assert security.get_jwks("https://project.supabase.co/auth/v1/.well-known/jwks.json") == document
    assert security.get_jwks("https://project.supabase.co/auth/v1/.well-known/jwks.json") == document
    assert calls == 1


def _jwks_for_key(signing_key: rsa.RSAPrivateKey, kid: str) -> dict[str, object]:
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public_jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [public_jwk]}


def test_jwks_cache_refreshes_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import security

    security.clear_jwks_cache()
    now = 100.0
    calls = 0
    documents = [{"keys": [{"kid": "first"}]}, {"keys": [{"kid": "second"}]}]

    def clock() -> float:
        return now

    def fetch(url: str, *, timeout: float) -> _JwksResponse:
        nonlocal calls
        response = _JwksResponse(documents[calls])
        calls += 1
        return response

    monkeypatch.setattr(security.time, "monotonic", clock)
    monkeypatch.setattr(security.httpx, "get", fetch)
    url = "https://project.supabase.co/auth/v1/.well-known/jwks.json"

    assert security.get_jwks(url) == documents[0]
    assert security.get_jwks(url) == documents[0]
    now += security.JWKS_CACHE_TTL_SECONDS + 0.1
    assert security.get_jwks(url) == documents[1]
    assert calls == 2


def test_unknown_kid_forces_one_refresh_and_accepts_rotated_key(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    user_id: UUID,
) -> None:
    from app.core import security
    from fastapi.security import HTTPAuthorizationCredentials

    old_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    documents = [_jwks_for_key(old_key, "old"), _jwks_for_key(new_key, "new")]
    calls = 0
    security.clear_jwks_cache()

    def fetch(url: str, *, timeout: float) -> _JwksResponse:
        nonlocal calls
        response = _JwksResponse(documents[calls])
        calls += 1
        return response

    monkeypatch.setattr(security.httpx, "get", fetch)
    principal = security.get_current_principal(
        credentials=HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=make_token(new_key, settings, str(user_id), kid="new"),
        ),
        settings=settings,
    )

    assert principal.user_id == user_id
    assert calls == 2


def test_unknown_kid_after_one_refresh_is_stable_401(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    user_id: UUID,
) -> None:
    from app.core import security
    from fastapi.security import HTTPAuthorizationCredentials

    cached_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    unknown_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    document = _jwks_for_key(cached_key, "cached")
    calls = 0
    security.clear_jwks_cache()

    def fetch(url: str, *, timeout: float) -> _JwksResponse:
        nonlocal calls
        calls += 1
        return _JwksResponse(document)

    monkeypatch.setattr(security.httpx, "get", fetch)
    with pytest.raises(ApiError) as error:
        security.get_current_principal(
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=make_token(unknown_key, settings, str(user_id), kid="missing"),
            ),
            settings=settings,
        )

    assert error.value.status_code == 401
    assert error.value.code == "AUTH_INVALID_TOKEN"
    assert calls == 2


def test_unknown_kid_refresh_network_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    user_id: UUID,
) -> None:
    from app.core import security
    from fastapi.security import HTTPAuthorizationCredentials

    cached_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    unknown_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    security.clear_jwks_cache()
    calls = 0

    def fetch(url: str, *, timeout: float) -> _JwksResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return _JwksResponse(_jwks_for_key(cached_key, "cached"))
        raise security.httpx.ConnectError("provider host unavailable")

    monkeypatch.setattr(security.httpx, "get", fetch)
    with pytest.raises(ApiError) as error:
        security.get_current_principal(
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer",
                credentials=make_token(unknown_key, settings, str(user_id), kid="missing"),
            ),
            settings=settings,
        )

    assert error.value.status_code == 503
    assert error.value.code == "AUTH_UNAVAILABLE"
    assert "host unavailable" not in error.value.message
