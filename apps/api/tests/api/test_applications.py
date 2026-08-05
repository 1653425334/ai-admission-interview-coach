from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import AuthPrincipal, get_current_principal
from app.core.config import get_settings
from app.db.alembic_config import configparser_safe_url
from app.db.migrations import validated_test_database_url
from app.db.models.application import Application
from app.db.models.document import Document
from app.db.models.profile import Profile
from app.db.session import get_db
from app.main import create_app


@pytest.fixture
def integration_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    env_file = Path(__file__).resolve().parents[4] / ".env"
    database_url = validated_test_database_url(
        env_file.read_text(encoding="utf-8").split("TEST_DATABASE_URL=", 1)[1].splitlines()[0]
    )
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
def client_for_user(integration_engine: Engine) -> Iterator[Callable[[str], TestClient]]:
    factory = sessionmaker(bind=integration_engine, autoflush=False, expire_on_commit=False)
    app = create_app()

    def client_for(name: str) -> TestClient:
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
        return TestClient(app)

    yield client_for
    app.dependency_overrides.clear()


def test_user_can_create_trim_and_list_application(client_for_user: Callable[[str], TestClient]) -> None:
    client = client_for_user("a")
    created = client.post(
        "/api/v1/applications",
        json={"target_school": "  CUHK-Shenzhen  ", "target_program": " MSc AI ", "degree_type": " Master \t"},
    )
    assert created.status_code == 201
    assert created.json()["target_school"] == "CUHK-Shenzhen"
    assert created.json()["target_program"] == "MSc AI"
    assert created.json()["degree_type"] == "Master"
    assert created.json()["status"] == "ACTIVE"
    assert created.json()["created_at"].endswith("+00:00")

    listed = client.get("/api/v1/applications")
    assert [item["id"] for item in listed.json()["items"]] == [created.json()["id"]]


@pytest.mark.parametrize(
    "payload",
    [
        {"target_school": " ", "target_program": "MSc AI"},
        {"target_school": "CUHK", "target_program": "\t"},
        {"target_school": "x" * 201, "target_program": "MSc AI"},
        {"target_school": "CUHK", "target_program": "MSc AI", "degree_type": " "},
        {"target_school": "CUHK", "target_program": "MSc AI", "degree_type": "x" * 101},
    ],
)
def test_application_create_validates_fields(client_for_user: Callable[[str], TestClient], payload: dict[str, str]) -> None:
    response = client_for_user("a").post("/api/v1/applications", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_creation_creates_profile(client_for_user: Callable[[str], TestClient], integration_engine: Engine) -> None:
    client_for_user("profile-user").post(
        "/api/v1/applications", json={"target_school": "CUHK", "target_program": "MSc AI"}
    )
    user_id = uuid5(NAMESPACE_URL, "test-user:profile-user")
    with Session(integration_engine) as session:
        assert session.get(Profile, user_id) is not None


def test_list_is_empty_isolated_and_stably_ordered(client_for_user: Callable[[str], TestClient], integration_engine: Engine) -> None:
    assert client_for_user("empty").get("/api/v1/applications").json() == {"items": []}
    user_id = uuid5(NAMESPACE_URL, "test-user:a")
    other_id = uuid5(NAMESPACE_URL, "test-user:b")
    first_id, second_id = uuid4(), uuid4()
    with Session(integration_engine) as session:
        session.add_all([Profile(id=user_id), Profile(id=other_id)])
        session.add_all([
            Application(id=first_id, user_id=user_id, target_school="First", target_program="P", status="ACTIVE"),
            Application(id=second_id, user_id=user_id, target_school="Second", target_program="P", status="ACTIVE"),
            Application(user_id=other_id, target_school="Hidden", target_program="P", status="ACTIVE"),
        ])
        session.commit()
        session.execute(
            update(Application)
            .where(Application.id.in_([first_id, second_id]))
            .values(created_at="2026-01-01T00:00:00+00:00")
        )
        session.commit()
    items = client_for_user("a").get("/api/v1/applications").json()["items"]
    assert [item["id"] for item in items] == [str(max(first_id, second_id)), str(min(first_id, second_id))]
    assert all(item["target_school"] != "Hidden" for item in items)


def test_detail_embeds_only_safe_documents_in_type_order(client_for_user: Callable[[str], TestClient], integration_engine: Engine) -> None:
    user_id, application_id = uuid5(NAMESPACE_URL, "test-user:a"), uuid4()
    with Session(integration_engine) as session:
        session.add(Profile(id=user_id))
        session.add(Application(id=application_id, user_id=user_id, target_school="CUHK", target_program="MSc", status="ACTIVE"))
        session.add_all([
            Document(id=uuid4(), application_id=application_id, document_type="PS", original_filename="ps.pdf", storage_key="secret-ps", mime_type="application/pdf", size_bytes=1, sha256="secret", parse_status="UPLOADED", extracted_text="private", parse_error="private"),
            Document(id=uuid4(), application_id=application_id, document_type="CV", original_filename="cv.pdf", storage_key="secret-cv", mime_type="application/pdf", size_bytes=2, sha256="secret", parse_status="PARSED", extracted_text="private", parse_error=None),
        ])
        session.commit()
    response = client_for_user("a").get(f"/api/v1/applications/{application_id}")
    assert response.status_code == 200
    assert [item["document_type"] for item in response.json()["documents"]] == ["CV", "PS"]
    forbidden = {"storage_key", "sha256", "extracted_text", "parse_error"}
    assert not forbidden.intersection(response.json()["documents"][0])


def test_other_user_and_missing_application_are_indistinguishable(client_for_user: Callable[[str], TestClient], integration_engine: Engine) -> None:
    user_id, application_id = uuid5(NAMESPACE_URL, "test-user:a"), uuid4()
    with Session(integration_engine) as session:
        session.add(Profile(id=user_id))
        session.add(Application(id=application_id, user_id=user_id, target_school="CUHK", target_program="MSc", status="ACTIVE"))
        session.commit()
    for application in (application_id, uuid4()):
        response = client_for_user("b").get(f"/api/v1/applications/{application}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "APPLICATION_NOT_FOUND"
