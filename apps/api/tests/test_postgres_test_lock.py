from __future__ import annotations

from time import monotonic

from tests.postgres_test_support import (
    acquire_test_schema_lock,
    get_test_database_url,
    try_acquire_test_schema_lock,
)


def test_test_database_schema_lock_is_mutually_exclusive() -> None:
    """A second independent connection cannot take the lock until release."""
    database_url = get_test_database_url()
    first_lock = acquire_test_schema_lock(database_url)
    try:
        # pg_try_advisory_lock is non-blocking, so this has a bounded duration
        # even if a lock holder fails to release it.
        started_at = monotonic()
        assert try_acquire_test_schema_lock(database_url) is None
        assert monotonic() - started_at < 2.0
    finally:
        first_lock.release()

    second_lock = try_acquire_test_schema_lock(database_url)
    assert second_lock is not None
    second_lock.release()
