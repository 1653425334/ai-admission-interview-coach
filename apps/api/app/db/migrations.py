from sqlalchemy.engine import make_url


TEST_DATABASE_NAME = "admission_coach_test"


def validated_test_database_url(database_url: str) -> str:
    """Return a test URL only when it targets the isolated integration database."""
    try:
        parsed_url = make_url(database_url)
    except Exception as error:
        raise ValueError("TEST_DATABASE_URL must be a valid SQLAlchemy database URL") from error

    if parsed_url.database != TEST_DATABASE_NAME:
        raise ValueError(
            f"TEST_DATABASE_URL must target the dedicated {TEST_DATABASE_NAME} database"
        )
    return database_url
