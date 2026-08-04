from __future__ import annotations

import pytest

from app.db import session as session_module


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_get_db_commits_and_closes_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    monkeypatch.setattr(session_module, "get_session_factory", lambda: lambda: db)

    dependency = session_module.get_db()
    assert next(dependency) is db
    with pytest.raises(StopIteration):
        next(dependency)

    assert (db.commits, db.rollbacks, db.closes) == (1, 0, 1)


def test_get_db_rolls_back_and_closes_after_error(monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeSession()
    monkeypatch.setattr(session_module, "get_session_factory", lambda: lambda: db)

    dependency = session_module.get_db()
    next(dependency)
    with pytest.raises(RuntimeError, match="route failed"):
        dependency.throw(RuntimeError("route failed"))

    assert (db.commits, db.rollbacks, db.closes) == (0, 1, 1)
