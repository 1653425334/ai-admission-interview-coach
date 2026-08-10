from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.workers import run_analysis_worker


def test_once_mode_starts_a_worker_and_processes_one_available_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = Mock()
    worker.run_once.return_value = True
    monkeypatch.setattr(run_analysis_worker, "build_analysis_worker", lambda: worker)

    assert run_analysis_worker.main(["--once"]) == 0
    worker.run_once.assert_called_once_with()


def test_once_mode_exits_cleanly_when_no_job_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = Mock()
    worker.run_once.return_value = False
    monkeypatch.setattr(run_analysis_worker, "build_analysis_worker", lambda: worker)

    assert run_analysis_worker.main(["--once"]) == 0
    worker.run_once.assert_called_once_with()


def test_rejects_a_non_positive_poll_interval() -> None:
    with pytest.raises(SystemExit):
        run_analysis_worker.parse_args(["--poll-interval-seconds", "0"])
