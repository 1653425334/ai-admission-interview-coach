"""Milestone 1 acceptance journey against the dedicated PostgreSQL test database."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import AuthPrincipal, get_current_principal
from app.db.alembic_config import configparser_safe_url
from app.db.session import get_db
from app.main import create_app
from app.storage.supabase import get_object_storage


class FakeStorage:
    """Private in-memory object storage used only by the acceptance test."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.delete_calls: list[str] = []

    def put(self, key: str, content: bytes, content_type: str) -> None:
        assert content_type == "application/pdf"
        self.objects[key] = content

    def delete(self, key: str) -> None:
        self.delete_calls.append(key)
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
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def client_for_user(
    integration_engine: Engine, fake_storage: FakeStorage
) -> Iterator[Callable[[str], TestClient]]:
    factory = sessionmaker(bind=integration_engine, autoflush=False, expire_on_commit=False)
    apps = []

    def build_client(name: str) -> TestClient:
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

    yield build_client
    for app in apps:
        app.dependency_overrides.clear()


def test_milestone_one_journey(
    client_for_user: Callable[[str], TestClient],
    text_pdf_bytes: bytes,
    fake_storage: FakeStorage,
) -> None:
    user_a = client_for_user("a")
    application_response = user_a.post(
        "/api/v1/applications",
        json={"target_school": "CUHK-Shenzhen", "target_program": "MSc AI"},
    )
    assert application_response.status_code == 201
    application_id = application_response.json()["id"]

    uploaded_documents = []
    for document_type, filename in (("CV", "cv.pdf"), ("PS", "ps.pdf")):
        response = user_a.post(
            f"/api/v1/applications/{application_id}/documents",
            data={"document_type": document_type},
            files={"file": (filename, text_pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 201
        uploaded_documents.append(response.json())

    # A fresh client simulates a page refresh: document state comes from PostgreSQL.
    refreshed = client_for_user("a").get(f"/api/v1/applications/{application_id}")
    assert refreshed.status_code == 200
    assert [item["document_type"] for item in refreshed.json()["documents"]] == ["CV", "PS"]
    forbidden_fields = {"storage_key", "public_url", "extracted_text"}
    for document in refreshed.json()["documents"]:
        assert forbidden_fields.isdisjoint(document)

    user_b = client_for_user("b")
    hidden_application = user_b.get(f"/api/v1/applications/{application_id}")
    assert hidden_application.status_code == 404
    assert hidden_application.json()["error"]["code"] == "APPLICATION_NOT_FOUND"

    for document in uploaded_documents:
        denied = user_b.delete(f"/api/v1/documents/{document['id']}")
        assert denied.status_code == 404
        assert denied.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert fake_storage.delete_calls == []

    assert len(fake_storage.objects) == 2
    for document in uploaded_documents:
        deleted = user_a.delete(f"/api/v1/documents/{document['id']}")
        assert deleted.status_code == 204
    assert fake_storage.objects == {}
    assert client_for_user("a").get(
        f"/api/v1/applications/{application_id}"
    ).json()["documents"] == []
