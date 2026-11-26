"""Tests for ``python -m tracelens``: the uvicorn arguments and the store lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

from tracelens import __main__ as entry


class _RecordedRun:
    """Stand-in for ``uvicorn.run`` that records the call instead of serving."""

    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.kwargs: dict[str, Any] = {}

    def __call__(self, app: FastAPI, **kwargs: Any) -> None:
        self.app = app
        self.kwargs = kwargs


@pytest.fixture
def recorded_run(monkeypatch: pytest.MonkeyPatch) -> _RecordedRun:
    run = _RecordedRun()
    monkeypatch.setattr(uvicorn, "run", run)
    return run


def test_defaults_bind_loopback_port_4318(
    monkeypatch: pytest.MonkeyPatch, recorded_run: _RecordedRun, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("HOST", "PORT", "DB_PATH"):
        monkeypatch.delenv(name, raising=False)

    entry.main()

    assert recorded_run.kwargs["host"] == "127.0.0.1"
    assert recorded_run.kwargs["port"] == 4318
    assert (tmp_path / "trace-lens.db").exists()


def test_server_options_bound_keep_alive_and_concurrency(
    monkeypatch: pytest.MonkeyPatch, recorded_run: _RecordedRun, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "spans.db"))

    entry.main()

    assert recorded_run.kwargs == {
        "host": "0.0.0.0",
        "port": 8080,
        "timeout_keep_alive": 5,
        "limit_concurrency": 64,
    }
    assert isinstance(recorded_run.app, FastAPI)


def test_store_is_closed_after_the_server_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    closed: list[bool] = []

    class _ClosingStore:
        def __init__(self, path: str) -> None:
            self.path = path

        def close(self) -> None:
            closed.append(True)

    def failing_run(app: FastAPI, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setenv("DB_PATH", str(tmp_path / "spans.db"))
    monkeypatch.setattr(entry, "Store", _ClosingStore)
    monkeypatch.setattr(uvicorn, "run", failing_run)

    with pytest.raises(KeyboardInterrupt):
        entry.main()

    assert closed == [True]


def test_invalid_port_stops_before_the_store_is_opened(
    monkeypatch: pytest.MonkeyPatch, recorded_run: _RecordedRun
) -> None:
    monkeypatch.setenv("PORT", "70000")

    with pytest.raises(ValueError, match="PORT"):
        entry.main()

    assert recorded_run.app is None
