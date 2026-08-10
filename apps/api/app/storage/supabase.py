"""Private Supabase Storage HTTP adapter."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.storage.base import ObjectStorage

_REQUEST_TIMEOUT_SECONDS = 15.0


class SupabaseObjectStorage:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self._base_url = settings.supabase_url.rstrip("/")
        self._bucket = settings.supabase_storage_bucket
        storage_admin_key = settings.supabase_service_role_key
        self._headers = {"apikey": storage_admin_key}
        # New sb_secret_* keys are opaque API keys, not JWTs, and must not be
        # sent as bearer tokens. Keep legacy service_role JWT compatibility
        # while projects migrate to Supabase's current key format.
        if not storage_admin_key.startswith("sb_secret_"):
            self._headers["Authorization"] = f"Bearer {storage_admin_key}"
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers=self._headers,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        )

    def put(self, key: str, content: bytes, content_type: str) -> None:
        _validate_object_key(key)
        bucket = quote(self._bucket, safe="")
        object_key = quote(key, safe="/")
        url = f"{self._base_url}/storage/v1/object/{bucket}/{object_key}"
        try:
            with self._client() as client:
                response = client.post(
                    url,
                    content=content,
                    headers={"Content-Type": content_type, "x-upsert": "false"},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            raise _storage_unavailable() from None

    def get(self, key: str) -> bytes:
        _validate_object_key(key)
        bucket = quote(self._bucket, safe="")
        object_key = quote(key, safe="/")
        url = f"{self._base_url}/storage/v1/object/{bucket}/{object_key}"
        try:
            with self._client() as client:
                response = client.get(url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPError:
            raise _storage_unavailable() from None

    def delete(self, key: str) -> None:
        _validate_object_key(key)
        bucket = quote(self._bucket, safe="")
        url = f"{self._base_url}/storage/v1/object/{bucket}"
        try:
            with self._client() as client:
                response = client.request("DELETE", url, json={"prefixes": [key]})
                if response.status_code == 404:
                    return
                response.raise_for_status()
        except httpx.HTTPError:
            raise _storage_unavailable() from None


def _storage_unavailable() -> ApiError:
    return ApiError(
        status_code=503,
        code="STORAGE_UNAVAILABLE",
        message="Document storage is temporarily unavailable.",
    )


def _validate_object_key(key: str) -> None:
    """Reject non-canonical relative keys before constructing a provider URL."""
    if not key or key.startswith("/") or key.endswith("/") or "\\" in key:
        raise ValueError("Object key must be a canonical relative path")
    segments = key.split("/")
    if any(not segment or segment in {".", ".."} for segment in segments):
        raise ValueError("Object key must be a canonical relative path")


@lru_cache
def get_object_storage() -> ObjectStorage:
    """Return the process-wide storage adapter used by document operations."""
    return SupabaseObjectStorage(get_settings())
