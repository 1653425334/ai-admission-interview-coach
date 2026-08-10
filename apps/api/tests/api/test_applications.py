from __future__ import annotations

from collections.abc import Callable, Iterator
import json
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
from app.db.models.analysis_run import AnalysisRun
from app.db.models.document import Document
from app.db.models.job import Job
from app.db.models.profile import Profile
from app.db.session import get_db
from app.main import create_app


M2_FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "fixtures" / "milestone_two"
M2_CV_ID = UUID("22222222-2222-4222-8222-222222222222")
M2_PS_ID = UUID("33333333-3333-4333-8333-333333333333")
M2_CV_SHA256 = "a" * 64
M2_PS_SHA256 = "b" * 64


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


def _seed_analysis_ready_application(
    integration_engine: Engine, *, user_name: str = "a"
) -> UUID:
    user_id = uuid5(NAMESPACE_URL, f"test-user:{user_name}")
    application_id = uuid4()
    with Session(integration_engine) as session:
        session.add(Profile(id=user_id))
        session.add(
            Application(
                id=application_id,
                user_id=user_id,
                target_school="Example University",
                target_program="MSc AI",
                status="ACTIVE",
            )
        )
        session.add_all(
            [
                Document(
                    id=M2_CV_ID,
                    application_id=application_id,
                    document_type="CV",
                    original_filename="cv.pdf",
                    storage_key="private/cv.pdf",
                    mime_type="application/pdf",
                    size_bytes=100,
                    sha256=M2_CV_SHA256,
                    parse_status="UPLOADED",
                ),
                Document(
                    id=M2_PS_ID,
                    application_id=application_id,
                    document_type="PS",
                    original_filename="ps.pdf",
                    storage_key="private/ps.pdf",
                    mime_type="application/pdf",
                    size_bytes=100,
                    sha256=M2_PS_SHA256,
                    parse_status="UPLOADED",
                ),
            ]
        )
        session.commit()
    return application_id


def test_owned_user_can_create_analysis_without_leaking_input_metadata(
    client_for_user: Callable[[str], TestClient], integration_engine: Engine
) -> None:
    application_id = _seed_analysis_ready_application(integration_engine)

    client = client_for_user("a")
    response = client.post(f"/api/v1/applications/{application_id}/analyses")

    assert response.status_code == 202
    payload = response.json()
    assert payload["application_id"] == str(application_id)
    assert payload["status"] == "PENDING"
    assert payload["stage"] == "QUEUED"
    assert payload["interview_map"] is None
    assert {"input_manifest", "storage_key", "sha256", "extracted_text"}.isdisjoint(payload)

    observed = client.get(f"/api/v1/analysis-runs/{payload['id']}")
    assert observed.status_code == 200
    assert observed.json()["id"] == payload["id"]
    assert observed.json()["interview_map"] is None


def test_analysis_requires_both_current_documents(
    client_for_user: Callable[[str], TestClient]
) -> None:
    application = client_for_user("a").post(
        "/api/v1/applications", json={"target_school": "CUHK", "target_program": "MSc AI"}
    ).json()

    response = client_for_user("a").post(f"/api/v1/applications/{application['id']}/analyses")

    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "ANALYSIS_DOCUMENTS_REQUIRED",
        "message": "Upload one CV and one personal statement before starting analysis.",
        "request_id": response.headers["x-request-id"],
    }


def test_duplicate_analysis_requests_reuse_one_run_and_job(
    client_for_user: Callable[[str], TestClient], integration_engine: Engine
) -> None:
    application_id = _seed_analysis_ready_application(integration_engine)
    client = client_for_user("a")

    first = client.post(
        f"/api/v1/applications/{application_id}/analyses", headers={"Idempotency-Key": "analysis-1"}
    )
    second = client.post(
        f"/api/v1/applications/{application_id}/analyses", headers={"Idempotency-Key": "analysis-1"}
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    with Session(integration_engine) as session:
        assert session.query(AnalysisRun).count() == 1
        assert session.query(Job).count() == 1


def test_other_user_cannot_read_analysis_run_or_latest_analysis(
    client_for_user: Callable[[str], TestClient], integration_engine: Engine
) -> None:
    application_id = _seed_analysis_ready_application(integration_engine, user_name="a")
    created = client_for_user("a").post(f"/api/v1/applications/{application_id}/analyses")
    analysis_run_id = created.json()["id"]

    hidden_run = client_for_user("b").get(f"/api/v1/analysis-runs/{analysis_run_id}")
    hidden_latest = client_for_user("b").get(
        f"/api/v1/applications/{application_id}/latest-analysis"
    )

    assert hidden_run.status_code == 404
    assert hidden_run.json()["error"]["code"] == "ANALYSIS_RUN_NOT_FOUND"
    assert hidden_latest.status_code == 404
    assert hidden_latest.json()["error"]["code"] == "APPLICATION_NOT_FOUND"


def test_latest_analysis_returns_only_current_completed_interview_map(
    client_for_user: Callable[[str], TestClient], integration_engine: Engine
) -> None:
    application_id = _seed_analysis_ready_application(integration_engine)
    client = client_for_user("a")
    created = client.post(f"/api/v1/applications/{application_id}/analyses")
    analysis_run_id = UUID(created.json()["id"])
    interview_map = json.loads(
        (M2_FIXTURE_DIRECTORY / "attention_robustness_interview_map.json").read_text(
            encoding="utf-8"
        )
    )
    interview_map["analysis_run_id"] = str(analysis_run_id)
    with Session(integration_engine) as session:
        analysis_run = session.get(AnalysisRun, analysis_run_id)
        assert analysis_run is not None
        analysis_run.status = "COMPLETED"
        analysis_run.stage = "COMPLETED"
        analysis_run.interview_map_json = interview_map
        session.commit()

    response = client.get(f"/api/v1/applications/{application_id}/latest-analysis")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(analysis_run_id)
    assert payload["interview_map"]["schema_version"] == "interview-map-v1"
    assert payload["interview_map"]["risks"][0]["verification_status"] == "UNVERIFIED"
    serialized = json.dumps(payload)
    assert "private/cv.pdf" not in serialized
    assert "private/ps.pdf" not in serialized
    assert "input_manifest_json" not in serialized
    assert "extracted_text" not in serialized
