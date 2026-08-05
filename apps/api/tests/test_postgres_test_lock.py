from __future__ import annotations

import pytest

from app.core.config import ENV_FILE
from app.db.migrations import validated_test_database_url
from tests.postgres_test_support import (
    acquire_test_schema_lock,
    get_test_database_url,
    try_acquire_test_schema_lock,
)


def test_test_database_url_falls_back_to_the_root_env_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    expected = validated_test_database_url(
        ENV_FILE.read_text(encoding="utf-8").split("TEST_DATABASE_URL=", 1)[1].splitlines()[0]
    )

    assert get_test_database_url() == expected


def test_test_database_url_prefers_environment_and_rejects_unsafe_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override = "postgresql+psycopg://test:test@example.test:5432/admission_coach_test"
    monkeypatch.setenv("TEST_DATABASE_URL", override)
    assert get_test_database_url() == override

    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://test:test@example.test:5432/admission_coach",
    )
    with pytest.raises(ValueError, match="admission_coach_test"):
        get_test_database_url()


def test_test_database_schema_lock_is_mutually_exclusive() -> None:
    """A second independent connection cannot take the lock until release."""
    database_url = get_test_database_url()
    first_lock = acquire_test_schema_lock(database_url)
    try:
        # pg_try_advisory_lock never waits, so this request has a deterministic
        # non-blocking bound independent of connection setup duration.
        assert try_acquire_test_schema_lock(database_url) is None
    finally:
        first_lock.release()

    second_lock = try_acquire_test_schema_lock(database_url)
    assert second_lock is not None
    second_lock.release()
