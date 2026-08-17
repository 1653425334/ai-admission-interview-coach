from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.fake_interview import FakeInterviewProvider
from app.core.config import get_settings
from app.db.alembic_config import configparser_safe_url
from app.db.models.analysis_run import AnalysisRun
from app.db.models.application import Application
from app.db.models.document import Document
from app.db.models.interview_session import InterviewSession
from app.db.models.interview_turn import InterviewTurn
from app.db.models.profile import Profile
from app.schemas.interview_map import InterviewMap
from app.services.analysis_runs import build_input_manifest
from app.services.interviews import (
    InterviewMapRequiredError,
    InterviewSessionStateError,
    InterviewTurnStateError,
    complete_interview_session,
    create_or_reuse_interview_session,
    derive_persisted_session_state,
    record_evaluation,
    record_question,
    submit_answer,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "milestone_two"


@pytest.fixture
def interview_engine(
    monkeypatch: pytest.MonkeyPatch, locked_test_database_url: str
) -> Iterator[Engine]:
    monkeypatch.setenv("DATABASE_URL", locked_test_database_url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", configparser_safe_url(locked_test_database_url))
    command.upgrade(config, "head")
    engine = create_engine(locked_test_database_url)
    try:
        yield engine
    finally:
        engine.dispose()
        command.downgrade(config, "base")
        get_settings.cache_clear()


@pytest.fixture
def interview_factory(interview_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=interview_engine, autoflush=False, expire_on_commit=False)


def _seed_completed_map(factory: sessionmaker[Session]) -> tuple[UUID, InterviewMap]:
    user_id = uuid4()
    application_id = uuid4()
    cv_id = uuid4()
    ps_id = uuid4()
    run_id = uuid4()
    with factory() as db:
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
        payload = json.loads(
            (FIXTURES / "attention_robustness_interview_map.json").read_text(encoding="utf-8")
        )
        payload["analysis_run_id"] = str(run_id)
        for item in payload["input_manifest"]:
            if item["document_type"] == "CV":
                item.update(document_id=str(cv_id), sha256="a" * 64)
            else:
                item.update(document_id=str(ps_id), sha256="b" * 64)
        for evidence in payload["evidence"]:
            evidence["document_id"] = str(cv_id if evidence["document_type"] == "CV" else ps_id)
        interview_map = InterviewMap.model_validate(payload)
        analysis_run = AnalysisRun(
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
        db.add(analysis_run)
        db.commit()
    return application_id, interview_map


def _first_question(session_id: UUID, interview_map: InterviewMap):
    risk = interview_map.risks[0]
    objective = risk.objectives[0]
    return FakeInterviewProvider().generate_question(
        session_id=session_id,
        interview_map=interview_map,
        risk_id=risk.risk_id,
        objective_id=objective.objective_id,
        target_condition_ids=[item.condition_id for item in objective.coverage_conditions],
        followup_index=0,
        sequence_number=1,
    )


def test_migration_creates_m3_tables(interview_engine: Engine) -> None:
    assert {
        "interview_sessions",
        "interview_turns",
        "interview_evaluations",
    }.issubset(set(inspect(interview_engine).get_table_names()))


def test_active_session_is_idempotent_and_bound_to_completed_analysis(
    interview_factory: sessionmaker[Session],
) -> None:
    application_id, _interview_map = _seed_completed_map(interview_factory)
    with interview_factory() as db:
        first = create_or_reuse_interview_session(db, application_id=application_id)
        second = create_or_reuse_interview_session(db, application_id=application_id)
        db.commit()

        assert first.created is True
        assert second.created is False
        assert second.interview_session.id == first.interview_session.id
        assert first.interview_session.analysis_run.status == "COMPLETED"
        assert first.interview_session.interview_map_schema_version == "interview-map-v1"


def test_question_answer_evaluation_survive_a_new_database_session(
    interview_factory: sessionmaker[Session],
) -> None:
    application_id, interview_map = _seed_completed_map(interview_factory)
    with interview_factory() as db:
        interview_session = create_or_reuse_interview_session(
            db, application_id=application_id
        ).interview_session
        session_id = interview_session.id
        question = _first_question(session_id, interview_map)
        record_question(db, session_id=session_id, question=question)
        db.commit()

    with interview_factory() as db:
        recovered = db.get(InterviewSession, session_id)
        turn = db.get(InterviewTurn, question.question_id)
        assert recovered is not None and turn is not None
        assert recovered.status == "ACTIVE"
        assert recovered.current_turn_id == turn.id
        assert turn.question_text == question.text

        answer = "We tested Gaussian noise against a ResNet baseline and accuracy improved by 10%."
        submit_answer(db, session_id=session_id, turn_id=turn.id, answer_text=answer)
        evaluation = FakeInterviewProvider().evaluate_answer(
            question=question, answer_text=answer, interview_map=interview_map
        )
        record_evaluation(
            db,
            session_id=session_id,
            turn_id=turn.id,
            evaluation=evaluation,
        )
        state = derive_persisted_session_state(db, recovered)
        db.commit()

        assert recovered.current_turn_id is None
        assert turn.status == "EVALUATED"
        assert state.risk_states[0].verification_status.value == "VERIFIED"


def test_duplicate_answer_and_duplicate_evaluation_are_rejected(
    interview_factory: sessionmaker[Session],
) -> None:
    application_id, interview_map = _seed_completed_map(interview_factory)
    with interview_factory() as db:
        interview_session = create_or_reuse_interview_session(
            db, application_id=application_id
        ).interview_session
        question = _first_question(interview_session.id, interview_map)
        turn = record_question(db, session_id=interview_session.id, question=question)
        answer = "We tested Gaussian noise against a baseline and accuracy improved by 10%."
        submit_answer(db, session_id=interview_session.id, turn_id=turn.id, answer_text=answer)
        with pytest.raises(InterviewTurnStateError, match="already been answered"):
            submit_answer(db, session_id=interview_session.id, turn_id=turn.id, answer_text=answer)
        evaluation = FakeInterviewProvider().evaluate_answer(
            question=question, answer_text=answer, interview_map=interview_map
        )
        record_evaluation(
            db,
            session_id=interview_session.id,
            turn_id=turn.id,
            evaluation=evaluation,
        )
        with pytest.raises(InterviewTurnStateError, match="current active turn"):
            record_evaluation(
                db,
                session_id=interview_session.id,
                turn_id=turn.id,
                evaluation=evaluation,
            )


def test_open_question_blocks_another_question(
    interview_factory: sessionmaker[Session],
) -> None:
    application_id, interview_map = _seed_completed_map(interview_factory)
    with interview_factory() as db:
        interview_session = create_or_reuse_interview_session(
            db, application_id=application_id
        ).interview_session
        question = _first_question(interview_session.id, interview_map)
        record_question(db, session_id=interview_session.id, question=question)
        second = question.model_copy(
            update={"question_id": uuid4(), "sequence_number": 2}
        )
        with pytest.raises(InterviewSessionStateError, match="answered first"):
            record_question(db, session_id=interview_session.id, question=second)


def test_changed_application_context_cannot_start_from_stale_analysis(
    interview_factory: sessionmaker[Session],
) -> None:
    application_id, _interview_map = _seed_completed_map(interview_factory)
    with interview_factory() as db:
        first = create_or_reuse_interview_session(db, application_id=application_id).interview_session
        complete_interview_session(db, session_id=first.id)
        application = db.get(Application, application_id)
        assert application is not None
        application.program_description = "A newly changed program description."
        db.flush()

        with pytest.raises(InterviewMapRequiredError, match="current completed"):
            create_or_reuse_interview_session(db, application_id=application_id)
