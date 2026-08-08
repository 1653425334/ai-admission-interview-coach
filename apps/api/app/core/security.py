"""Supabase JWT validation dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
import time
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import ApiError

_bearer_scheme = HTTPBearer(auto_error=False)
JWKS_CACHE_TTL_SECONDS = 300.0
_ALLOWED_JWT_ALGORITHMS = {"RS256": "RSA", "ES256": "EC"}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache_lock = Lock()


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: UUID
    email: str | None


def _jwks_url(settings: Settings) -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _fetch_jwks(url: str) -> dict[str, Any]:
    """Fetch one provider JWKS document without retaining JWTs or error bodies."""
    try:
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        document = response.json()
    except (httpx.HTTPError, ValueError):
        # Provider response bodies can include data that should not be surfaced.
        raise ApiError(503, "AUTH_UNAVAILABLE", "Authentication is temporarily unavailable.") from None

    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise ApiError(503, "AUTH_UNAVAILABLE", "Authentication is temporarily unavailable.")
    return document


def clear_jwks_cache() -> None:
    """Clear cached public keys; exposed for deterministic tests and process control."""
    with _jwks_cache_lock:
        _jwks_cache.clear()


def get_jwks(
    url: str,
    *,
    force_refresh: bool = False,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a bounded-TTL JWKS cache, refreshing an unknown key ID at most once.

    Holding the small lock during a network fetch prevents concurrent requests that
    saw the same old key set from stampeding the identity provider during rotation.
    """
    with _jwks_cache_lock:
        now = time.monotonic()
        cached = _jwks_cache.get(url)
        if cached is not None:
            cached_at, document = cached
            if not force_refresh and now - cached_at < JWKS_CACHE_TTL_SECONDS:
                return document
            if force_refresh and previous is not None and document is not previous:
                return document

        document = _fetch_jwks(url)
        _jwks_cache[url] = (now, document)
        return document


# Keep the former cache-clearing test seam while using an explicit TTL cache.
get_jwks.cache_clear = clear_jwks_cache  # type: ignore[attr-defined]


class _UnknownKeyId(Exception):
    """A syntactically valid token named a key absent from the current JWKS."""


def _verification_key(token: str, jwks: dict[str, Any]) -> tuple[Any, str]:
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
        algorithm = header.get("alg")
    except jwt.PyJWTError:
        raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.") from None

    if not isinstance(key_id, str) or algorithm not in _ALLOWED_JWT_ALGORITHMS:
        raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.")

    for key_data in jwks["keys"]:
        if isinstance(key_data, dict) and key_data.get("kid") == key_id:
            if (
                key_data.get("kty") != _ALLOWED_JWT_ALGORITHMS[algorithm]
                or key_data.get("alg") not in {None, algorithm}
                or key_data.get("use") not in {None, "sig"}
            ):
                raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.")
            try:
                return jwt.PyJWK.from_dict(key_data, algorithm=algorithm).key, algorithm
            except (jwt.PyJWTError, ValueError, TypeError):
                raise ApiError(
                    401, "AUTH_INVALID_TOKEN", "Invalid authentication token."
                ) from None
    raise _UnknownKeyId


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthPrincipal:
    """Validate a signed Supabase RS256/ES256 access token and return its principal."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "AUTH_REQUIRED", "A bearer token is required.")

    try:
        jwks_url = _jwks_url(settings)
        current_jwks = get_jwks(jwks_url)
        try:
            key, algorithm = _verification_key(credentials.credentials, current_jwks)
        except _UnknownKeyId:
            # A rotated key may not yet be in the TTL cache.  Refresh once only;
            # a still-unknown key is an invalid token rather than a retry loop.
            key, algorithm = _verification_key(
                credentials.credentials,
                get_jwks(jwks_url, force_refresh=True, previous=current_jwks),
            )
        claims = jwt.decode(
            credentials.credentials,
            key=key,
            algorithms=[algorithm],
            audience=settings.supabase_jwt_audience,
            issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
            options={"require": ["exp", "sub"]},
        )
    except ApiError:
        raise
    except (_UnknownKeyId, jwt.PyJWTError):
        raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.") from None

    subject = claims.get("sub")
    if not isinstance(subject, str):
        raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.")
    try:
        user_id = UUID(subject)
    except ValueError:
        raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.") from None

    email = claims.get("email")
    return AuthPrincipal(user_id=user_id, email=email if isinstance(email, str) else None)
