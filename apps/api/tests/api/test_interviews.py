from __future__ import annotations

from collections.abc import Callable, Iterator
import json
from pathlib import Path
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.ai.interview_provider import get_interview_provider
from app.core.security import AuthPrincipal, get_current_principal
from app.db.alembic_config import configparser_safe_url
from app.db.models.analysis_run import AnalysisRun
from app.db.models.application import Application
from app.db.models.document import Document
from app.db.models.interview_session import InterviewSession
from app.db.models.profile import Profile
from app.db.session import get_db
from app.main import create_app
from app.schemas.interview_map import InterviewMap
from app.services.analysis_runs import build_input_manifest


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "milestone_two"


@pytest.fixture
def interview_api_engine(
    monkeypatch: pytest.MonkeyPatch, locked_test_database_url: str
) -> Iterator[Engine]:
    monkeypatch.setenv("DATABASE_URL", locked_test_database_url)
    monkeypatch.setenv("LLM_MODE", "fake")
    get_settings.cache_clear()
    get_interview_provider.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", configparser_safe_url(locked_test_database_url))
    command.upgrade(config, "head")
    engine = create_engine(locked_test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        get_interview_provider.cache_clear()
        get_settings.cache_clear()


@pytest.fixture
def interview_client_for_user(
    interview_api_engine: Engine,
) -> Iterator[Callable[[str], TestClient]]:
    factory = sessionmaker(
        bind=interview_api_engine, autoflush=False, expire_on_commit=False
    )
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


def _seed_application(
    engine: Engine, *, user_name: str = "a", completed_map: bool = True
) -> UUID:
    user_id = uuid5(NAMESPACE_URL, f"test-user:{user_name}")
    application_id = uuid4()
    cv_id = uuid4()
    ps_id = uuid4()
    run_id = uuid4()
    with Session(engine) as db:
        db.add(Profile(id=user_id))
        db.add(
            Application(
                id=application_id,
                user_id=user_id,
                target_school="Example University",
                target_program="MSc AI",
                status="ACTIVE",
            )
        )
        db.add_all(
            [
                Document(
                    id=cv_id,
                    application_id=application_id,
                    document_type="CV",
                    original_filename="cv.pdf",
                    storage_key="private/cv.pdf",
                    mime_type="application/pdf",
                    size_bytes=10,
                    sha256="a" * 64,
                    parse_status="PARSED",
                ),
                Document(
                    id=ps_id,
                    application_id=application_id,
                    document_type="PS",
                    original_filename="ps.pdf",
                    storage_key="private/ps.pdf",
                    mime_type="application/pdf",
                    size_bytes=10,
                    sha256="b" * 64,
                    parse_status="PARSED",
                ),
            ]
        )
        db.flush()
        if completed_map:
            payload = json.loads(
                (FIXTURES / "attention_robustness_interview_map.json").read_text(
                    encoding="utf-8"
                )
            )
            payload["analysis_run_id"] = str(run_id)
            for item in payload["input_manifest"]:
                if item["document_type"] == "CV":
                    item.update(document_id=str(cv_id), sha256="a" * 64)
                else:
                    item.update(document_id=str(ps_id), sha256="b" * 64)
            for evidence in payload["evidence"]:
                evidence["document_id"] = str(
                    cv_id if evidence["document_type"] == "CV" else ps_id
                )
            interview_map = InterviewMap.model_validate(payload)
            db.add(
                AnalysisRun(
                    id=run_id,
                    application_id=application_id,
                    status="COMPLETED",
                    stage="COMPLETED",
                    input_manifest_json=build_input_manifest(db, application_id),
                    interview_map_json=interview_map.model_dump(mode="json"),
                    provider="fake",
                    model="fake-interview-map-v1",
                    prompt_version="fake-interview-map-v1",
                    schema_version="interview-map-v1",
                )
            )
        db.commit()
    return application_id


def test_start_creates_first_map_bound_question_and_refresh_recovers_it(
    interview_client_for_user: Callable[[str], TestClient],
    interview_api_engine: Engine,
) -> None:
    application_id = _seed_application(interview_api_engine)
    client = interview_client_for_user("a")

    started = client.post(
        f"/api/v1/applications/{application_id}/interviews",
        json={"question_budget": 6},
    )

    assert started.status_code == 201
    payload = started.json()
    assert payload["status"] == "ACTIVE"
    assert payload["questions_asked"] == 1
    assert payload["current_turn_id"] == payload["turns"][0]["id"]
    assert payload["turns"][0]["risk_id"] == "risk-001"
    assert payload["turns"][0]["status"] == "ASKED"
    assert payload["derived_state"]["risk_states"][0]["verification_status"] == "UNVERIFIED"
    serialized = json.dumps(payload)
    assert "private/cv.pdf" not in serialized
    assert "input_manifest" not in serialized

    recovered = client.get(f"/api/v1/interviews/{payload['id']}")
    assert recovered.status_code == 200
    assert recovered.json()["current_turn_id"] == payload["current_turn_id"]
    assert recovered.json()["turns"][0]["question_text"] == payload["turns"][0]["question_text"]


def test_start_requires_a_current_risk_bearing_interview_map(
    interview_client_for_user: Callable[[str], TestClient],
    interview_api_engine: Engine,
) -> None:
    application_id = _seed_application(interview_api_engine, completed_map=False)
    response = interview_client_for_user("a").post(
        f"/api/v1/applications/{application_id}/interviews", json={}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTERVIEW_MAP_REQUIRED"


def test_duplicate_start_reuses_active_session(
    interview_client_for_user: Callable[[str], TestClient],
    interview_api_engine: Engine,
) -> None:
    application_id = _seed_application(interview_api_engine)
    client = interview_client_for_user("a")
    first = client.post(f"/api/v1/applications/{application_id}/interviews", json={})
    second = client.post(f"/api/v1/applications/{application_id}/interviews", json={})

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["turns"][0]["id"] == second.json()["turns"][0]["id"]
    with Session(interview_api_engine) as db:
        assert db.query(InterviewSession).count() == 1


def test_partial_answer_is_evaluated_and_creates_targeted_followup(
    interview_client_for_user: Callable[[str], TestClient],
    interview_api_engine: Engine,
) -> None:
    application_id = _seed_application(interview_api_engine)
    client = interview_client_for_user("a")
    started = client.post(f"/api/v1/applications/{application_id}/interviews", json={}).json()
    first_turn = started["turns"][0]

    response = client.post(
        f"/api/v1/interviews/{started['id']}/turns",
        json={
            "turn_id": first_turn["id"],
            "answer_text": "We tested Gaussian noise at several perturbation levels.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ACTIVE"
    assert payload["questions_asked"] == 2
    assert payload["turns"][0]["status"] == "EVALUATED"
    assert payload["turns"][0]["evaluation"] is not None
    assert payload["turns"][1]["followup_index"] == 1
    assert payload["turns"][1]["target_condition_ids"] == ["cond-002"]
    assert payload["derived_state"]["risk_states"][0]["verification_status"] == "PARTIALLY_VERIFIED"


def test_complete_answer_finishes_session_and_report_is_available(
    interview_client_for_user: Callable[[str], TestClient],
    interview_api_engine: Engine,
) -> None:
    application_id = _seed_application(interview_api_engine)
    client = interview_client_for_user("a")
    started = client.post(f"/api/v1/applications/{application_id}/interviews", json={}).json()
    answer = "We tested Gaussian noise against a ResNet baseline and accuracy improved by 10%."
    current = started
    first_turn_id = started["current_turn_id"]
    completed = None
    for _index in range(3):
        completed = client.post(
            f"/api/v1/interviews/{started['id']}/turns",
            json={"turn_id": current["current_turn_id"], "answer_text": answer},
        )
        current = completed.json()

    assert completed is not None
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["current_turn_id"] is None
    assert completed.json()["derived_state"]["risk_states"][0]["verification_status"] == "VERIFIED"
    report = client.get(f"/api/v1/interviews/{started['id']}/report")
    assert report.status_code == 200
    assert "1 of 1" in report.json()["overall_summary"]

    duplicate = client.post(
        f"/api/v1/interviews/{started['id']}/turns",
        json={"turn_id": first_turn_id, "answer_text": answer},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["questions_asked"] == 3


def test_other_user_cannot_read_or_answer_interview(
    interview_client_for_user: Callable[[str], TestClient],
    interview_api_engine: Engine,
) -> None:
    application_id = _seed_application(interview_api_engine, user_name="a")
    owner = interview_client_for_user("a")
    started = owner.post(f"/api/v1/applications/{application_id}/interviews", json={}).json()
    other = interview_client_for_user("b")

    hidden = other.get(f"/api/v1/interviews/{started['id']}")
    answer = other.post(
        f"/api/v1/interviews/{started['id']}/turns",
        json={"turn_id": started["current_turn_id"], "answer_text": "hidden"},
    )

    assert hidden.status_code == answer.status_code == 404
    assert hidden.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"
    assert answer.json()["error"]["code"] == "INTERVIEW_NOT_FOUND"


def test_report_is_not_available_during_active_interview(
    interview_client_for_user: Callable[[str], TestClient],
    interview_api_engine: Engine,
) -> None:
    application_id = _seed_application(interview_api_engine)
    client = interview_client_for_user("a")
    started = client.post(f"/api/v1/applications/{application_id}/interviews", json={}).json()

    response = client.get(f"/api/v1/interviews/{started['id']}/report")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INTERVIEW_REPORT_NOT_READY"
