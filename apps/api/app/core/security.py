"""Supabase JWT validation dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.errors import ApiError

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: UUID
    email: str | None


def _jwks_url(settings: Settings) -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


@lru_cache(maxsize=8)
def get_jwks(url: str) -> dict[str, Any]:
    """Fetch and cache a provider JWKS document without retaining any JWTs."""
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


def _verification_key(token: str, jwks: dict[str, Any]) -> Any:
    try:
        header = jwt.get_unverified_header(token)
        key_id = header.get("kid")
    except jwt.PyJWTError:
        raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.") from None

    if not isinstance(key_id, str):
        raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.")

    for key_data in jwks["keys"]:
        if isinstance(key_data, dict) and key_data.get("kid") == key_id:
            try:
                return jwt.PyJWK.from_dict(key_data).key
            except (jwt.PyJWTError, ValueError, TypeError):
                break
    raise ApiError(401, "AUTH_INVALID_TOKEN", "Invalid authentication token.")


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthPrincipal:
    """Validate a signed Supabase RS256 access token and return its principal."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "AUTH_REQUIRED", "A bearer token is required.")

    try:
        key = _verification_key(credentials.credentials, get_jwks(_jwks_url(settings)))
        claims = jwt.decode(
            credentials.credentials,
            key=key,
            algorithms=["RS256"],
            audience=settings.supabase_jwt_audience,
            issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
            options={"require": ["exp", "sub"]},
        )
    except ApiError:
        raise
    except jwt.PyJWTError:
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
