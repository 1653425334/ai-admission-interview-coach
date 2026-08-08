from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import ApiError
from app.core.security import AuthPrincipal, get_current_principal
from app.core.config import get_settings
from app.db.alembic_config import configparser_safe_url
from app.db.models.document import Document
from app.db.session import get_db
from app.main import create_app
from app.services.documents import _best_effort_delete
from app.services.pdf_validation import MAX_PDF_BYTES
from app.storage.supabase import get_object_storage


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.delete_calls: list[str] = []
        self.put_error: ApiError | None = None
        self.delete_error: Exception | None = None

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.put_calls.append((key, content, content_type))
        if self.put_error is not None:
            raise self.put_error
        self.objects[key] = content

    def delete(self, key: str) -> None:
        self.delete_calls.append(key)
        if self.delete_error is not None:
            raise self.delete_error
        self.objects.pop(key, None)


@pytest.fixture
def integration_engine(
    monkeypatch: pytest.MonkeyPatch, locked_test_database_url: str
) -> Iterator[Engine]:
    database_url = locked_test_database_url
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", configparser_safe_url(database_url))
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        get_settings.cache_clear()


@pytest.fixture
def fake_storage() -> Iterator[FakeStorage]:
    get_object_storage.cache_clear()
    storage = FakeStorage()
    try:
        yield storage
    finally:
        get_object_storage.cache_clear()


@pytest.fixture
def client_for_user(
    integration_engine: Engine, fake_storage: FakeStorage
) -> Iterator[Callable[[str], TestClient]]:
    factory = sessionmaker(bind=integration_engine, autoflush=False, expire_on_commit=False)
    apps = []

    def client_for(name: str) -> TestClient:
        app = create_app()
        apps.append(app)
        user_id = uuid5(NAMESPACE_URL, f"test-user:{name}")

        def override_principal() -> AuthPrincipal:
            return AuthPrincipal(user_id=user_id, email=f"{name}@example.test")

        def override_db() -> Iterator[Session]:
            session = factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        app.dependency_overrides[get_current_principal] = override_principal
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_object_storage] = lambda: fake_storage
        return TestClient(app, raise_server_exceptions=False)

    yield client_for
    for app in apps:
        app.dependency_overrides.clear()


def _create_application(client: TestClient) -> str:
    response = client.post(
        "/api/v1/applications",
        json={"target_school": "CUHK-Shenzhen", "target_program": "MSc AI"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _upload(
    client: TestClient,
    application_id: str,
    content: bytes,
    *,
    document_type: str = "CV",
    filename: str = "cv.pdf",
    content_type: str = "application/pdf",
):
    return client.post(
        f"/api/v1/applications/{application_id}/documents",
        data={"document_type": document_type},
        files={"file": (filename, content, content_type)},
    )


def _document_count(engine: Engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(Document)) or 0


def test_owner_can_upload_cv_with_safe_metadata_only(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)

    response = _upload(
        client,
        application_id,
        text_pdf_bytes,
        filename="../../resume final.pdf",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["document_type"] == "CV"
    assert body["parse_status"] == "UPLOADED"
    assert body["original_filename"] == "resume_final.pdf"
    assert set(body) == {
        "id", "application_id", "document_type", "original_filename",
        "mime_type", "size_bytes", "parse_status", "created_at",
    }
    key, stored, mime = fake_storage.put_calls[0]
    assert key == f"{uuid5(NAMESPACE_URL, 'test-user:a')}/{application_id}/{body['id']}/resume_final.pdf"
    assert stored == text_pdf_bytes
    assert mime == "application/pdf"
    assert fake_storage.objects[key] == text_pdf_bytes


def test_filename_is_always_nonempty_single_segment_pdf(
    client_for_user: Callable[[str], TestClient], text_pdf_bytes: bytes
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)
    response = _upload(client, application_id, text_pdf_bytes, filename="../..")
    assert response.status_code == 201
    assert response.json()["original_filename"] == "document.pdf"


def test_other_user_and_missing_application_cannot_upload(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    application_id = _create_application(client_for_user("a"))
    for target in (application_id, str(uuid4())):
        response = _upload(client_for_user("b"), target, text_pdf_bytes)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "APPLICATION_NOT_FOUND"
    assert fake_storage.put_calls == []


def test_invalid_document_type_is_rejected_before_storage(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    client = client_for_user("a")
    response = _upload(client, _create_application(client), text_pdf_bytes, document_type="TRANSCRIPT")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert fake_storage.put_calls == []


def test_validation_failure_does_not_write_storage(
    client_for_user: Callable[[str], TestClient], fake_storage: FakeStorage
) -> None:
    client = client_for_user("a")
    response = _upload(client, _create_application(client), b"not a pdf")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PDF_SIGNATURE"
    assert fake_storage.put_calls == []


def test_read_is_limited_and_oversize_does_not_write_storage(
    client_for_user: Callable[[str], TestClient],
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.datastructures import UploadFile

    read_sizes: list[int] = []
    original_read = UploadFile.read

    async def tracked_read(self: UploadFile, size: int = -1) -> bytes:
        read_sizes.append(size)
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", tracked_read)
    client = client_for_user("a")
    response = _upload(
        client,
        _create_application(client),
        b"%PDF-" + b"x" * MAX_PDF_BYTES,
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    # This is below the multipart transport cap, so the route applies the exact
    # file-size rule after parsing without reading beyond its 10 MiB + 1 bound.
    assert read_sizes == [MAX_PDF_BYTES + 1]
    assert fake_storage.put_calls == []


def test_exact_10_mib_pdf_multipart_reaches_route_and_succeeds(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    content = text_pdf_bytes + b"\x00" * (MAX_PDF_BYTES - len(text_pdf_bytes))
    client = client_for_user("a")

    response = _upload(client, _create_application(client), content)

    assert response.status_code == 201
    assert response.json()["size_bytes"] == MAX_PDF_BYTES
    assert fake_storage.put_calls[0][1] == content


def test_duplicate_type_is_stable_conflict_without_second_storage_write(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)
    assert _upload(client, application_id, text_pdf_bytes).status_code == 201
    response = _upload(client, application_id, text_pdf_bytes)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_TYPE_ALREADY_EXISTS"
    assert len(fake_storage.put_calls) == 1


def test_integrity_race_cleans_uploaded_object_and_returns_conflict(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)

    class Diagnostic:
        constraint_name = "uq_documents_application_document_type"

    class UniqueViolation(Exception):
        diag = Diagnostic()

    def fail_commit(self: Session) -> None:
        raise IntegrityError("duplicate", {}, UniqueViolation("unique violation"))

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        response = _upload(client, application_id, text_pdf_bytes)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_TYPE_ALREADY_EXISTS"
    assert len(fake_storage.put_calls) == 1
    assert fake_storage.delete_calls == [fake_storage.put_calls[0][0]]
    assert fake_storage.objects == {}


def test_storage_failure_leaves_no_database_row(
    client_for_user: Callable[[str], TestClient],
    integration_engine: Engine,
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    fake_storage.put_error = ApiError(503, "STORAGE_UNAVAILABLE", "Storage unavailable.")
    client = client_for_user("a")
    response = _upload(client, _create_application(client), text_pdf_bytes)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert _document_count(integration_engine) == 0


def test_database_failure_cleans_uploaded_object(
    client_for_user: Callable[[str], TestClient],
    integration_engine: Engine,
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)

    def fail_commit(self: Session) -> None:
        raise OperationalError("insert", {}, Exception("database down"))

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        response = _upload(client, application_id, text_pdf_bytes)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DOCUMENT_SAVE_FAILED"
    assert fake_storage.delete_calls == [fake_storage.put_calls[0][0]]
    assert fake_storage.objects == {}
    assert _document_count(integration_engine) == 0


def test_cleanup_warning_uses_storage_key_fingerprint_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    storage = FakeStorage()
    storage.delete_error = RuntimeError("storage cleanup unavailable")
    request_id = str(uuid4())
    storage_key = "private-user/application/document/resume-secret.pdf"
    documents_logger = logging.getLogger("app.services.documents")
    previous_level = documents_logger.level
    previous_disabled = documents_logger.disabled
    previous_disable_level = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    caplog.set_level(logging.WARNING, logger=documents_logger.name)
    documents_logger.disabled = False
    documents_logger.addHandler(caplog.handler)
    try:
        _best_effort_delete(storage, storage_key, request_id)
        log_text = caplog.text
    finally:
        documents_logger.removeHandler(caplog.handler)
        documents_logger.setLevel(previous_level)
        documents_logger.disabled = previous_disabled
        logging.disable(previous_disable_level)

    fingerprint = hashlib.sha256(storage_key.encode("utf-8")).hexdigest()[:16]
    assert storage.delete_calls == [storage_key]
    assert request_id in log_text
    assert f"storage_key_sha256={fingerprint}" in log_text
    assert storage_key not in log_text
    assert "resume-secret.pdf" not in log_text


@pytest.mark.parametrize("failing_operation", ["flush", "refresh"])
def test_precommit_database_failure_rolls_back_and_cleans_storage(
    failing_operation: str,
    client_for_user: Callable[[str], TestClient],
    integration_engine: Engine,
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)

    def fail(self: Session, *args: object, **kwargs: object) -> None:
        raise OperationalError(failing_operation, {}, Exception("database down"))

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, failing_operation, fail)
        response = _upload(client, application_id, text_pdf_bytes)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DOCUMENT_SAVE_FAILED"
    assert fake_storage.delete_calls == [fake_storage.put_calls[0][0]]
    assert fake_storage.objects == {}
    assert _document_count(integration_engine) == 0


def test_successful_commit_is_not_followed_by_document_refresh(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)
    original_commit = Session.commit
    original_refresh = Session.refresh
    commit_completed = False

    def tracked_commit(self: Session) -> None:
        nonlocal commit_completed
        original_commit(self)
        commit_completed = True

    def guarded_refresh(self: Session, instance: object, *args: object, **kwargs: object) -> None:
        if commit_completed and isinstance(instance, Document):
            raise AssertionError("Document refresh occurred after commit")
        original_refresh(self, instance, *args, **kwargs)

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", tracked_commit)
        patcher.setattr(Session, "refresh", guarded_refresh)
        response = _upload(client, application_id, text_pdf_bytes)
    assert response.status_code == 201


def test_non_duplicate_integrity_failure_is_not_reported_as_duplicate(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for_user("a")
    application_id = _create_application(client)

    def fail_commit(self: Session) -> None:
        raise IntegrityError("foreign key", {}, Exception("constraint failure"))

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        response = _upload(client, application_id, text_pdf_bytes)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "DOCUMENT_SAVE_FAILED"
    assert fake_storage.delete_calls == [fake_storage.put_calls[0][0]]


def test_owner_can_delete_and_other_user_cannot(
    client_for_user: Callable[[str], TestClient],
    integration_engine: Engine,
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    owner = client_for_user("a")
    uploaded = _upload(owner, _create_application(owner), text_pdf_bytes).json()
    key = fake_storage.put_calls[0][0]

    denied = client_for_user("b").delete(f"/api/v1/documents/{uploaded['id']}")
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert fake_storage.delete_calls == []
    assert _document_count(integration_engine) == 1

    deleted = owner.delete(f"/api/v1/documents/{uploaded['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert fake_storage.delete_calls == [key]
    assert fake_storage.objects == {}
    assert _document_count(integration_engine) == 0


def test_delete_storage_failure_preserves_database_row(
    client_for_user: Callable[[str], TestClient],
    integration_engine: Engine,
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    client = client_for_user("a")
    uploaded = _upload(client, _create_application(client), text_pdf_bytes).json()
    fake_storage.delete_error = ApiError(503, "STORAGE_UNAVAILABLE", "Storage unavailable.")
    response = client.delete(f"/api/v1/documents/{uploaded['id']}")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_DELETE_FAILED"
    assert _document_count(integration_engine) == 1


def test_non_api_storage_delete_failure_is_mapped_and_preserves_row(
    client_for_user: Callable[[str], TestClient],
    integration_engine: Engine,
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    client = client_for_user("a")
    uploaded = _upload(client, _create_application(client), text_pdf_bytes).json()
    fake_storage.delete_error = RuntimeError("provider response must stay private")
    response = client.delete(f"/api/v1/documents/{uploaded['id']}")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_DELETE_FAILED"
    assert "provider response" not in response.text
    assert _document_count(integration_engine) == 1


def test_delete_commit_failure_preserves_row_and_retry_converges(
    client_for_user: Callable[[str], TestClient],
    integration_engine: Engine,
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = client_for_user("a")
    uploaded = _upload(client, _create_application(client), text_pdf_bytes).json()
    storage_key = fake_storage.put_calls[0][0]

    def fail_commit(self: Session) -> None:
        raise OperationalError("delete", {}, Exception("database down"))

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        first = client.delete(f"/api/v1/documents/{uploaded['id']}")
    assert first.status_code == 500
    assert first.json()["error"]["code"] == "DOCUMENT_DELETE_FAILED"
    assert storage_key not in fake_storage.objects
    assert _document_count(integration_engine) == 1

    second = client.delete(f"/api/v1/documents/{uploaded['id']}")
    assert second.status_code == 204
    assert fake_storage.delete_calls == [storage_key, storage_key]
    assert _document_count(integration_engine) == 0


def test_missing_document_is_not_found_without_storage_call(
    client_for_user: Callable[[str], TestClient], fake_storage: FakeStorage
) -> None:
    response = client_for_user("a").delete(f"/api/v1/documents/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert fake_storage.delete_calls == []
