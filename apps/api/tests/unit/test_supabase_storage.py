from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.storage import supabase
from app.storage.supabase import SupabaseObjectStorage


def _settings() -> Settings:
    return Settings(
        database_url="postgresql://test:test@localhost/test",
        supabase_url="https://project.supabase.co/",
        supabase_storage_bucket="private-documents",
        supabase_service_role_key="super-secret-role-key",
    )


def _settings_with_new_secret_key() -> Settings:
    return Settings(
        database_url="postgresql://test:test@localhost/test",
        supabase_url="https://project.supabase.co/",
        supabase_storage_bucket="private-documents",
        supabase_service_role_key="sb_secret_server-only",
    )


def test_new_secret_key_uses_apikey_header_without_bearer_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"Key": "object"})

    storage = SupabaseObjectStorage(
        _settings_with_new_secret_key(), transport=httpx.MockTransport(handler)
    )

    storage.put("user/app/cv.pdf", b"pdf bytes", "application/pdf")

    request = requests[0]
    assert request.headers["apikey"] == "sb_secret_server-only"
    assert "authorization" not in request.headers


def test_put_uploads_private_object_without_upsert() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"Key": "object"})

    storage = SupabaseObjectStorage(_settings(), transport=httpx.MockTransport(handler))

    storage.put("user/app/cv file.pdf", b"pdf bytes", "application/pdf")

    request = requests[0]
    assert request.method == "POST"
    assert request.url == (
        "https://project.supabase.co/storage/v1/object/"
        "private-documents/user/app/cv%20file.pdf"
    )
    assert request.headers["authorization"] == "Bearer super-secret-role-key"
    assert request.headers["x-upsert"] == "false"
    assert request.headers["content-type"] == "application/pdf"
    assert request.content == b"pdf bytes"


@pytest.mark.parametrize(
    "key",
    [
        "",
        "../escape.pdf",
        "user/app/../../../escape.pdf",
        "/user/app/cv.pdf",
        "user//app/cv.pdf",
        "user/app/cv.pdf/",
        r"user\app\cv.pdf",
    ],
)
@pytest.mark.parametrize("operation", ["get", "put", "delete"])
def test_rejects_non_canonical_object_key_before_network(operation: str, key: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    storage = SupabaseObjectStorage(_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(ValueError, match="canonical relative path"):
        if operation == "get":
            storage.get(key)
        elif operation == "put":
            storage.put(key, b"pdf", "application/pdf")
        else:
            storage.delete(key)

    assert requests == []


def test_delete_calls_private_object_delete_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"message": "Successfully deleted"})

    storage = SupabaseObjectStorage(_settings(), transport=httpx.MockTransport(handler))

    storage.delete("user/app/cv.pdf")

    request = requests[0]
    assert request.method == "DELETE"
    assert request.url == "https://project.supabase.co/storage/v1/object/private-documents"
    assert request.headers["authorization"] == "Bearer super-secret-role-key"
    assert request.headers["content-type"] == "application/json"
    assert request.content == b'{"prefixes":["user/app/cv.pdf"]}'


def test_get_reads_private_object_bytes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"private pdf bytes")

    storage = SupabaseObjectStorage(_settings(), transport=httpx.MockTransport(handler))

    assert storage.get("user/app/cv file.pdf") == b"private pdf bytes"
    request = requests[0]
    assert request.method == "GET"
    assert request.url == (
        "https://project.supabase.co/storage/v1/object/"
        "private-documents/user/app/cv%20file.pdf"
    )


def test_delete_treats_missing_object_as_already_deleted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    storage = SupabaseObjectStorage(_settings(), transport=httpx.MockTransport(handler))

    storage.delete("already-gone.pdf")


@pytest.mark.parametrize("operation", ["get", "put", "delete"])
def test_provider_error_is_mapped_without_disclosing_response_or_key(operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="provider secret response")

    storage = SupabaseObjectStorage(_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(ApiError) as error:
        if operation == "get":
            storage.get("private.pdf")
        elif operation == "put":
            storage.put("private.pdf", b"pdf", "application/pdf")
        else:
            storage.delete("private.pdf")

    assert error.value.code == "STORAGE_UNAVAILABLE"
    assert "provider secret response" not in error.value.message
    assert "super-secret-role-key" not in error.value.message


def test_network_error_is_mapped_to_storage_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("service role key should not appear", request=request)

    storage = SupabaseObjectStorage(_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(ApiError) as error:
        storage.put("private.pdf", b"pdf", "application/pdf")

    assert error.value.code == "STORAGE_UNAVAILABLE"
    assert error.value.status_code == 503


def test_object_storage_dependency_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    supabase.get_object_storage.cache_clear()
    monkeypatch.setattr(supabase, "get_settings", _settings)
    try:
        first = supabase.get_object_storage()
        second = supabase.get_object_storage()
    finally:
        supabase.get_object_storage.cache_clear()

    assert first is second
