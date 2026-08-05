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
        self._headers = {
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
        }
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            headers=self._headers,
            timeout=_REQUEST_TIMEOUT_SECONDS,
            transport=self._transport,
        )

    def put(self, key: str, content: bytes, content_type: str) -> None:
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

    def delete(self, key: str) -> None:
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


@lru_cache
def get_object_storage() -> ObjectStorage:
    """Return the process-wide storage adapter used by document operations."""
    return SupabaseObjectStorage(get_settings())
