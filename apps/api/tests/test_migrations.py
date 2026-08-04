from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine


@pytest.fixture
def migrated_database_url() -> Iterator[str]:
    """Apply the Alembic head revision to the dedicated integration database."""
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL must point to the dedicated migration test database")

    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    try:
        yield database_url
    finally:
        command.downgrade(config, "base")


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
    assert {"UPLOADED", "PARSING", "PARSED", "FAILED"} <= set(checks["ck_documents_parse_status"].replace("'", "").replace(",", " ").replace("(", " ").replace(")", " ").split())

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
