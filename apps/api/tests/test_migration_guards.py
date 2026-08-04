from __future__ import annotations

import pytest

from app.db.migrations import TEST_DATABASE_NAME, validated_test_database_url
from app.db.alembic_config import configparser_safe_url


def test_alembic_database_url_is_safe_for_configparser_interpolation() -> None:
    assert configparser_safe_url("postgresql://user:p%40ss@localhost/admission_coach") == (
        "postgresql://user:p%%40ss@localhost/admission_coach"
    )


def test_test_database_url_accepts_only_the_dedicated_database() -> None:
    accepted = "postgresql+psycopg://postgres:postgres@localhost:5432/admission_coach_test"

    assert validated_test_database_url(accepted) == accepted


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://postgres:postgres@localhost:5432/admission_coach",
        "postgresql+psycopg://postgres:postgres@localhost:5432/postgres",
        "postgresql+psycopg://postgres:postgres@localhost:5432/other_test",
    ],
)
def test_test_database_url_rejects_any_non_dedicated_database(database_url: str) -> None:
    with pytest.raises(ValueError, match=TEST_DATABASE_NAME):
        validated_test_database_url(database_url)
