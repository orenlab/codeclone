from __future__ import annotations

import io
import types
from pathlib import Path

import pytest

from codeclone.utils import file_lock


def test_advisory_file_lock_timeout_and_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock_path = tmp_path / ".locks" / "memory.lock"
    attempts = {"count": 0}

    def _acquire(_handle: object) -> None:
        attempts["count"] += 1
        raise BlockingIOError("busy")

    monkeypatch.setattr(file_lock, "_acquire_exclusive_lock", _acquire)
    monkeypatch.setattr("codeclone.utils.file_lock.time.sleep", lambda _seconds: None)
    timeline = iter([0.0, 1.0, 2.0])
    monkeypatch.setattr(
        "codeclone.utils.file_lock.time.monotonic",
        lambda: next(timeline),
    )
    with (
        pytest.raises(TimeoutError),
        file_lock.advisory_file_lock(
            lock_path,
            timeout_seconds=0.5,
            timeout_error=lambda _path: TimeoutError("timed out"),
        ),
    ):
        raise AssertionError("should not enter")
    assert attempts["count"] >= 1


def test_file_lock_windows_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, calls=[])

    def _locking(fileno: int, mode: int, size: int) -> None:
        fake_msvcrt.calls.append((fileno, mode, size))

    fake_msvcrt.locking = _locking
    monkeypatch.setitem(__import__("sys").modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr("codeclone.utils.file_lock.sys.platform", "win32")

    class _Handle(io.BytesIO):
        def fileno(self) -> int:
            return 7

    handle = _Handle(b"x")
    file_lock._acquire_exclusive_lock(handle)
    file_lock._release_exclusive_lock(handle)
    assert fake_msvcrt.calls == [(7, 1, 1), (7, 2, 1)]
