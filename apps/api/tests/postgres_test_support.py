"""PostgreSQL-only coordination for tests that recreate the shared test schema."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.core.config import ENV_FILE
from app.db.migrations import validated_test_database_url


# A stable key reserved for admission_coach_test schema migration coordination.
ADMISSION_COACH_TEST_SCHEMA_LOCK_KEY = 5_698_346_596_182_293_115


class TestDatabaseSettings(BaseSettings):
    """Test-only settings that use the same repository-root env file as the API."""

    test_database_url: str

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")


def get_test_database_url() -> str:
    """Read and validate the dedicated database used by integration tests."""
    try:
        database_url = TestDatabaseSettings().test_database_url
    except ValidationError as error:
        raise ValueError(
            "TEST_DATABASE_URL must point to the dedicated migration test database"
        ) from error
    return validated_test_database_url(database_url)


@dataclass
class TestSchemaLock:
    """A session-scoped PostgreSQL advisory lock retained until explicit release."""

    engine: Engine
    connection: Connection

    def release(self) -> None:
        try:
            self.connection.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": ADMISSION_COACH_TEST_SCHEMA_LOCK_KEY},
            )
        finally:
            self.connection.close()
            self.engine.dispose()


def acquire_test_schema_lock(database_url: str) -> TestSchemaLock:
    """Block until this test process exclusively owns the shared schema lock."""
    engine = create_engine(database_url, pool_pre_ping=True)
    connection = engine.connect()
    try:
        connection.execute(
            text("SELECT pg_advisory_lock(:lock_key)"),
            {"lock_key": ADMISSION_COACH_TEST_SCHEMA_LOCK_KEY},
        )
    except Exception:
        connection.close()
        engine.dispose()
        raise
    return TestSchemaLock(engine=engine, connection=connection)


def try_acquire_test_schema_lock(database_url: str) -> TestSchemaLock | None:
    """Attempt a non-blocking lock acquisition for focused mutual-exclusion tests."""
    engine = create_engine(database_url, pool_pre_ping=True)
    connection = engine.connect()
    try:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": ADMISSION_COACH_TEST_SCHEMA_LOCK_KEY},
        )
        if acquired:
            return TestSchemaLock(engine=engine, connection=connection)
    except Exception:
        connection.close()
        engine.dispose()
        raise
    connection.close()
    engine.dispose()
    return None
