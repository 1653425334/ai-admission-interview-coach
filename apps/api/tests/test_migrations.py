from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from app.db.migrations import validated_test_database_url
from app.db.alembic_config import configparser_safe_url


def test_migration_fixture_rejects_non_test_database_before_alembic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def should_not_run(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/admission_coach",
    )
    monkeypatch.setattr(command, "upgrade", should_not_run)

    dependency = migrated_database_url.__wrapped__(monkeypatch)
    with pytest.raises(pytest.fail.Exception, match="admission_coach_test"):
        next(dependency)

    assert called is False


@pytest.fixture
def migrated_database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Apply the Alembic head revision to the dedicated integration database."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL must point to the dedicated migration test database")
    try:
        database_url = validated_test_database_url(database_url)
    except ValueError as error:
        pytest.fail(str(error))

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    from app.core.config import get_settings

    get_settings.cache_clear()

    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", configparser_safe_url(database_url))
    command.upgrade(config, "head")
    try:
        yield database_url
    finally:
        command.downgrade(config, "base")
        get_settings.cache_clear()


@pytest.fixture
def migrated_engine(migrated_database_url: str) -> Iterator[Engine]:
    engine = create_engine(migrated_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def test_head_migration_creates_milestone_one_schema(migrated_engine: Engine) -> None:
    inspector = inspect(migrated_engine)

    assert {"profiles", "applications", "documents"} <= set(inspector.get_table_names())

    profile_columns = {column["name"]: column for column in inspector.get_columns("profiles")}
    assert profile_columns["id"]["type"].__class__.__name__ == "UUID"
    assert {"id", "display_name", "created_at"} <= profile_columns.keys()

    application_columns = {column["name"]: column for column in inspector.get_columns("applications")}
    assert {
        "id",
        "user_id",
        "target_school",
        "target_program",
        "degree_type",
        "status",
        "created_at",
        "updated_at",
    } <= application_columns.keys()
    assert any(
        foreign_key["constrained_columns"] == ["user_id"]
        and foreign_key["referred_table"] == "profiles"
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in inspector.get_foreign_keys("applications")
    )

    document_columns = {column["name"]: column for column in inspector.get_columns("documents")}
    assert {
        "id",
        "application_id",
        "document_type",
        "original_filename",
        "storage_key",
        "mime_type",
        "size_bytes",
        "sha256",
        "parse_status",
        "extracted_text",
        "parse_error",
        "created_at",
    } <= document_columns.keys()
    assert any(
        foreign_key["constrained_columns"] == ["application_id"]
        and foreign_key["referred_table"] == "applications"
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in inspector.get_foreign_keys("documents")
    )

    checks = {constraint["name"]: constraint["sqltext"] for constraint in inspector.get_check_constraints("documents")}
    assert "ck_documents_document_type" in checks
    assert "CV" in checks["ck_documents_document_type"]
    assert "PS" in checks["ck_documents_document_type"]
    assert "ck_documents_parse_status" in checks
    parse_status_literals = set(
        re.findall(r"'((?:''|[^'])*)'", checks["ck_documents_parse_status"])
    )
    assert parse_status_literals == {"UPLOADED", "PARSING", "PARSED", "FAILED"}

    unique_constraints = inspector.get_unique_constraints("documents")
    assert any(constraint["column_names"] == ["application_id", "document_type"] for constraint in unique_constraints)

    with migrated_engine.connect() as connection:
        index_definition = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'applications' "
                "AND indexname = 'ix_applications_user_created'"
            )
        ).scalar_one()
    assert "(user_id, created_at DESC)" in index_definition
