# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Tests for Phase 7 — graceful MCP process shutdown.

Validates that ``safe_remove_own_intent`` enforces zero-trust path
safety, and that ``CodeCloneMCPService.shutdown_cleanup`` removes only
files owned by the current process.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intents import (
    WorkspaceIntentRecord,
    _is_safe_intent_path,
    intent_path,
    registry_dir,
    safe_remove_own_intent,
    write_workspace_intent,
)
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.surfaces.mcp.session import MCPAnalysisRequest

if TYPE_CHECKING:
    from codeclone.surfaces.mcp._shutdown import ShutdownCoordinator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    intent_id: str = "intent-abcdef12-001",
    pid: int | None = None,
    start_epoch: int = 100,
) -> WorkspaceIntentRecord:
    declared_at = workspace_intents.utc_now()
    scope_payload: dict[str, object] = {
        "allowed_files": ["pkg/a.py"],
        "allowed_related": ["tests/test_a.py"],
        "forbidden": [
            ".cache/codeclone/**",
            ".codeclone/**",
            "codeclone.baseline.json",
        ],
    }
    return WorkspaceIntentRecord(
        intent_id=intent_id,
        agent_pid=pid or os.getpid(),
        agent_start_epoch=start_epoch,
        agent_label="test-agent",
        run_id="abcdef1234567890",
        declared_at_utc=workspace_intents.format_utc(declared_at),
        expires_at_utc=workspace_intents.format_utc(declared_at + timedelta(hours=1)),
        ttl_seconds=3600,
        status="active",
        intent="test intent",
        scope=scope_payload,
        scope_digest=workspace_intents.compute_scope_digest(scope_payload),
        blast_radius_summary={"radius_level": "low"},
        lease_renewed_at_utc=workspace_intents.format_utc(declared_at),
        lease_seconds=workspace_intents.DEFAULT_LEASE_SECONDS,
        report_digest="digest-a",
    )


def _svc() -> CodeCloneMCPService:
    return CodeCloneMCPService(history_limit=5)


def _analysis_request(root: str) -> MCPAnalysisRequest:
    return MCPAnalysisRequest(root=root)


class _ClosingWriter:
    def __init__(self) -> None:
        self.closed = 0

    def emit(self, _event: object) -> None:
        return None

    def close(self) -> None:
        self.closed += 1


# ---------------------------------------------------------------------------
# _is_safe_intent_path
# ---------------------------------------------------------------------------


def _symlink_or_skip(link: Path, target: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not supported on this platform")
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not available in this environment")


# The safety property is resolved containment -- ``resolve(candidate)`` lands
# inside ``resolve(registry)`` -- and not ``candidate == resolve(candidate)``.
# The four tests below are the discriminating cases of exactly that property:
# they differ only in where the candidate resolves to, so a predicate that
# refuses every link fails the first, and a predicate that inspects the
# unresolved spelling fails the last two.


def test_safe_path_accepts_ordinary_path_inside_root(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    expected = intent_path(
        root=tmp_path,
        pid=123,
        start_epoch=456,
        intent_id="intent-aaa-001",
    )
    assert _is_safe_intent_path(expected, registry) is True


def _registry_holding_link_to(tmp_path: Path, target_parent: str) -> tuple[Path, Path]:
    """A registry plus one link in it named like an intent record.

    ``target_parent`` says where the link lands -- inside the registry, or out
    in the repository root -- because that is the single fact the containment
    property turns on. Everything else about the two cases is identical, and
    saying it twice would pin the shape of the setup rather than the property.
    """

    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    parent = registry if target_parent == "registry" else tmp_path
    target = parent / "real-target.json"
    target.write_text("{}", encoding="utf-8")
    link = registry / "123-456-intent-aaa-001.json"
    _symlink_or_skip(link, target)
    return registry, link


def test_safe_path_accepts_symlink_whose_target_is_inside_root(
    tmp_path: Path,
) -> None:
    registry, link = _registry_holding_link_to(tmp_path, "registry")

    assert _is_safe_intent_path(link, registry) is True


def test_safe_path_rejects_relative(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    assert (
        _is_safe_intent_path(
            Path("relative/123-456-intent-aaa-001.json"),
            registry,
        )
        is False
    )


def test_safe_path_refuses_symlink_whose_target_escapes_root(
    tmp_path: Path,
) -> None:
    registry, link = _registry_holding_link_to(tmp_path, "root")

    assert _is_safe_intent_path(link, registry) is False


def test_safe_path_refuses_dotdot_escape_after_normalization(
    tmp_path: Path,
) -> None:
    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    escape = registry / ".." / ".." / "123-456-intent-aaa-001.json"

    # Every non-containment check passes on this spelling: it is absolute, it
    # ends in .json and it carries two dashes. Containment is the only thing
    # standing between it and acceptance.
    assert _is_safe_intent_path(escape, registry) is False


def test_safe_path_rejects_directory(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "123-456-intent-aaa-001.json").mkdir()
    assert (
        _is_safe_intent_path(
            registry / "123-456-intent-aaa-001.json",
            registry,
        )
        is False
    )


def test_safe_path_rejects_outside_registry(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    outside = tmp_path / "123-456-intent-aaa-001.json"
    assert _is_safe_intent_path(outside, registry) is False


def test_safe_path_rejects_non_json_extension(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    assert _is_safe_intent_path(registry / "123-456-x.txt", registry) is False


def test_safe_path_rejects_filename_without_dashes(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    assert _is_safe_intent_path(registry / "nodashes.json", registry) is False


# ---------------------------------------------------------------------------
# safe_remove_own_intent
# ---------------------------------------------------------------------------


def test_safe_remove_own_file(tmp_path: Path) -> None:
    pid, epoch = os.getpid(), 100
    intent_id = "intent-abcdef12-001"
    record = _record(pid=pid, start_epoch=epoch, intent_id=intent_id)
    assert write_workspace_intent(root=tmp_path, record=record)
    path = intent_path(root=tmp_path, pid=pid, start_epoch=epoch, intent_id=intent_id)
    assert path.exists()
    assert safe_remove_own_intent(
        root=tmp_path,
        pid=pid,
        start_epoch=epoch,
        intent_id=intent_id,
    )
    assert not path.exists()


def test_safe_remove_missing_file_returns_true(tmp_path: Path) -> None:
    registry_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    assert safe_remove_own_intent(
        root=tmp_path,
        pid=1,
        start_epoch=1,
        intent_id="intent-gone-001",
    )


def test_safe_remove_does_not_touch_foreign_pid(tmp_path: Path) -> None:
    foreign_pid, own_pid = 999999, os.getpid()
    intent_id = "intent-foreign-001"
    record = _record(pid=foreign_pid, start_epoch=200, intent_id=intent_id)
    assert write_workspace_intent(root=tmp_path, record=record)
    foreign_path = intent_path(
        root=tmp_path,
        pid=foreign_pid,
        start_epoch=200,
        intent_id=intent_id,
    )
    assert foreign_path.exists()
    safe_remove_own_intent(
        root=tmp_path,
        pid=own_pid,
        start_epoch=200,
        intent_id=intent_id,
    )
    assert foreign_path.exists()


def test_safe_remove_does_not_touch_foreign_epoch(tmp_path: Path) -> None:
    pid = os.getpid()
    intent_id = "intent-epoch-001"
    record = _record(pid=pid, start_epoch=200, intent_id=intent_id)
    assert write_workspace_intent(root=tmp_path, record=record)
    real_path = intent_path(
        root=tmp_path,
        pid=pid,
        start_epoch=200,
        intent_id=intent_id,
    )
    assert real_path.exists()
    safe_remove_own_intent(
        root=tmp_path,
        pid=pid,
        start_epoch=999,
        intent_id=intent_id,
    )
    assert real_path.exists()


def test_safe_remove_rejects_relative_root() -> None:
    assert (
        safe_remove_own_intent(
            root=Path("relative/path"),
            pid=1,
            start_epoch=1,
            intent_id="intent-rel-001",
        )
        is False
    )


def test_safe_remove_rejects_symlink_escape(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-secret.json"
    outside.write_text("important data")
    pid, epoch = os.getpid(), 100
    intent_id = "intent-sym-001"
    symlink = intent_path(
        root=tmp_path, pid=pid, start_epoch=epoch, intent_id=intent_id
    )
    symlink.symlink_to(outside)
    assert (
        safe_remove_own_intent(
            root=tmp_path,
            pid=pid,
            start_epoch=epoch,
            intent_id=intent_id,
        )
        is False
    )
    assert outside.exists()
    assert symlink.is_symlink()


def test_safe_remove_rejects_directory_target(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    pid, epoch = os.getpid(), 100
    intent_id = "intent-dir-001"
    dir_path = intent_path(
        root=tmp_path,
        pid=pid,
        start_epoch=epoch,
        intent_id=intent_id,
    )
    dir_path.mkdir()
    assert (
        safe_remove_own_intent(
            root=tmp_path,
            pid=pid,
            start_epoch=epoch,
            intent_id=intent_id,
        )
        is False
    )
    assert dir_path.is_dir()


# ---------------------------------------------------------------------------
# shutdown_cleanup — integration
# ---------------------------------------------------------------------------


def test_shutdown_cleanup_removes_own_intents(tmp_path: Path) -> None:
    svc = _svc()
    run_id = str(svc.analyze_repository(_analysis_request(str(tmp_path)))["run_id"])
    decl = svc.manage_change_intent(
        action="declare",
        run_id=run_id,
        root=str(tmp_path),
        scope={"allowed_files": ["pkg/a.py"], "allowed_related": [], "forbidden": []},
        intent="test shutdown cleanup",
    )
    path = intent_path(
        root=tmp_path,
        pid=svc._agent_pid,
        start_epoch=svc._agent_start_epoch,
        intent_id=str(decl["intent_id"]),
    )
    assert path.exists()
    svc.shutdown_cleanup()
    assert not path.exists()


def test_shutdown_cleanup_noop_without_intents() -> None:
    _svc().shutdown_cleanup()  # must not raise


def test_shutdown_cleanup_is_idempotent(tmp_path: Path) -> None:
    svc = _svc()
    run_id = str(svc.analyze_repository(_analysis_request(str(tmp_path)))["run_id"])
    svc.manage_change_intent(
        action="declare",
        run_id=run_id,
        root=str(tmp_path),
        scope={"allowed_files": ["pkg/b.py"], "allowed_related": [], "forbidden": []},
        intent="idempotent test",
    )
    svc.shutdown_cleanup()
    svc.shutdown_cleanup()  # second call — no error


def test_shutdown_cleanup_survives_an_unavailable_run(tmp_path: Path) -> None:
    """Cleanup follows the intent's own root, not a run lookup.

    An intent whose run has aged out of session history still owns the
    registry file this process wrote, so cleanup must still reach it.
    """

    svc = _svc()
    run_id = str(svc.analyze_repository(_analysis_request(str(tmp_path)))["run_id"])
    svc.manage_change_intent(
        action="declare",
        run_id=run_id,
        root=str(tmp_path),
        scope={"allowed_files": ["pkg/c.py"], "allowed_related": [], "forbidden": []},
        intent="error test",
    )
    svc._runs.clear()
    svc.shutdown_cleanup()  # must not raise


def test_shutdown_cleanup_closes_audit_writers_and_store_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import codeclone.surfaces.mcp._workspace_intent_store as intent_store_mod

    svc = _svc()
    writer = _ClosingWriter()
    svc._audit_writers[tmp_path.resolve()] = writer
    cache_cleared: list[bool] = []
    monkeypatch.setattr(
        intent_store_mod,
        "clear_workspace_intent_store_cache",
        lambda: cache_cleared.append(True),
    )

    svc.shutdown_cleanup()

    assert writer.closed == 1
    assert cache_cleared == [True]


def test_clear_session_runs_handles_missing_intent_run(tmp_path: Path) -> None:
    svc = _svc()
    run_id = str(svc.analyze_repository(_analysis_request(str(tmp_path)))["run_id"])
    svc.manage_change_intent(
        action="declare",
        run_id=run_id,
        root=str(tmp_path),
        scope={"allowed_files": ["pkg/d.py"], "allowed_related": [], "forbidden": []},
        intent="missing run cleanup",
    )
    svc._runs.clear()

    result = svc.clear_session_runs()

    assert result["cleared_intents"] == 1


# ---------------------------------------------------------------------------
# SIGTERM handler
# ---------------------------------------------------------------------------


def _inert_coordinator(
    *,
    grace_seconds: float = 1.0,
    exits: list[int] | None = None,
    deadline: list[object] | None = None,
) -> ShutdownCoordinator:
    """A coordinator that can never end this pytest process.

    Extracted on CodeClone's own remediation for the block-clone group these
    unit tests introduced: the same four-line construction stood in each of
    them, and the real hard-exit default (``os._exit``) is exactly the kind of
    thing a copy is a bad place to keep.
    """

    from codeclone.surfaces.mcp._shutdown import ShutdownCoordinator

    return ShutdownCoordinator(
        grace_seconds=grace_seconds,
        hard_exit=(lambda _status: None) if exits is None else exits.append,
        arm_deadline=(
            (lambda _delay, _callback: None)
            if deadline is None
            else (lambda _delay, callback: deadline.append(callback))
        ),
    )


def test_the_installed_handler_arms_the_deadline_and_runs_the_teardown() -> None:
    """What the handler does, with a coordinator that cannot kill pytest.

    The previous version of this test asserted only that the handler raises
    ``SystemExit`` -- true, and green for as long as the server hung on every
    SIGTERM, because a process with no event loop and no worker threads cannot
    exhibit the defect.  It is kept, one assertion among several, rather than
    standing alone as the meaning of "SIGTERM works".
    """

    from codeclone.surfaces.mcp.server import _install_sigterm_handler

    armed: list[object] = []
    exits: list[int] = []
    ran: list[str] = []
    coordinator = _inert_coordinator(exits=exits, deadline=armed)
    coordinator.set_teardown(lambda: ran.append("teardown"))

    previous = signal.getsignal(signal.SIGTERM)
    try:
        _install_sigterm_handler(coordinator)
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not signal.SIG_DFL
        with pytest.raises(SystemExit) as exc_info:
            handler(signal.SIGTERM, None)  # type: ignore[misc,operator]
        assert exc_info.value.code == 0
    finally:
        signal.signal(signal.SIGTERM, previous)

    assert len(armed) == 1, "the deadline was not armed by the signal path"
    assert ran == ["teardown"], "the teardown the lifespan never reaches did not run"
    assert exits == [], "the graceful path must not hard-exit on the first signal"


def test_the_deadline_ends_a_shutdown_that_cannot_finish() -> None:
    """The fallback, isolated from the graceful path it backs up.

    The teardown here never returns, which is the real failure mode: the
    service state lock is held by an in-flight tool call and the handler runs
    on the main thread.  Arming before running is what makes this bounded.
    """

    exits: list[int] = []
    deadline: list[object] = []
    blocked = threading.Event()

    def _never_returns() -> None:
        blocked.set()
        raise KeyboardInterrupt  # a teardown that ends in the worst way

    coordinator = _inert_coordinator(grace_seconds=0.01, exits=exits, deadline=deadline)
    coordinator.set_teardown(_never_returns)

    with pytest.raises(KeyboardInterrupt):
        coordinator.request_shutdown(signal.SIGTERM)
    # Armed BEFORE the teardown, so a teardown that never returns cleanly is
    # still covered by it.
    assert blocked.is_set()
    assert len(deadline) == 1, "no deadline was armed before the teardown ran"
    assert exits == []
    callback = deadline[0]
    assert callable(callback)
    callback()
    assert exits == [128 + int(signal.SIGTERM)], exits


def test_a_second_signal_does_not_wait_for_the_grace_window() -> None:
    exits: list[int] = []
    coordinator = _inert_coordinator(grace_seconds=30.0, exits=exits)
    with pytest.raises(SystemExit):
        coordinator.request_shutdown(signal.SIGTERM)
    coordinator.request_shutdown(signal.SIGTERM)
    assert exits == [128 + int(signal.SIGTERM)]


def test_the_teardown_runs_once_per_registration_not_once_per_process() -> None:
    """Both doors reach one teardown; a new server re-arms its own.

    A latched guard would make the second server built in one process skip its
    own cleanup, which is the failure a naive ``once`` introduces.
    """

    first: list[str] = []
    coordinator = _inert_coordinator()
    coordinator.set_teardown(lambda: first.append("a"))
    coordinator.run_teardown_once()
    coordinator.run_teardown_once()
    assert first == ["a"]

    second: list[str] = []
    coordinator.set_teardown(lambda: second.append("b"))
    coordinator.run_teardown_once()
    assert second == ["b"]


def test_a_failing_teardown_does_not_stop_the_shutdown() -> None:
    """A cleanup that raises must neither escape nor be retried forever."""

    calls: list[str] = []
    coordinator = _inert_coordinator()

    def _boom() -> None:
        calls.append("attempt")
        raise RuntimeError("cleanup failed")

    coordinator.set_teardown(_boom)
    coordinator.run_teardown_once()
    coordinator.run_teardown_once()
    assert calls == ["attempt"]


def test_the_grace_window_is_clamped_and_total_over_its_input() -> None:
    from codeclone.surfaces.mcp._shutdown import (
        DEFAULT_SHUTDOWN_GRACE_SECONDS,
        MAX_SHUTDOWN_GRACE_SECONDS,
        MIN_SHUTDOWN_GRACE_SECONDS,
        resolved_shutdown_grace_seconds,
    )

    assert resolved_shutdown_grace_seconds() == DEFAULT_SHUTDOWN_GRACE_SECONDS
    assert resolved_shutdown_grace_seconds(env_value="2.5") == 2.5
    assert resolved_shutdown_grace_seconds(env_value="0") == MIN_SHUTDOWN_GRACE_SECONDS
    assert (
        resolved_shutdown_grace_seconds(env_value="900") == MAX_SHUTDOWN_GRACE_SECONDS
    )
    # A shutdown path must not fail to shut down over a typo.
    assert (
        resolved_shutdown_grace_seconds(env_value="soon")
        == DEFAULT_SHUTDOWN_GRACE_SECONDS
    )
    assert (
        resolved_shutdown_grace_seconds(env_value="nan")
        == DEFAULT_SHUTDOWN_GRACE_SECONDS
    )
    assert resolved_shutdown_grace_seconds(value=True) == DEFAULT_SHUTDOWN_GRACE_SECONDS


# ---------------------------------------------------------------------------
# Bounded shutdown: SIGTERM must end the process, and end it gracefully
# ---------------------------------------------------------------------------
#
# Measured 2026-09-05 on this build, python 3.14, stdio transport.  The handler
# below WAS installed and DID run -- and the process still had to be killed:
#
#   * ``_handler`` raises ``SystemExit`` from the signal context, which aborts
#     ``asyncio``'s ``run_forever`` mid-``select`` rather than asking it to
#     stop.  ``main()`` unwinds (measured: ``main() raised SystemExit: 0``).
#   * Because the loop was aborted, the FastMCP lifespan ``__aexit__`` never
#     runs, so ``service.shutdown_cleanup()`` -- the whole point of the
#     handler, per its own docstring -- was measured NEVER CALLED.
#   * Interpreter shutdown then blocks in ``threading._shutdown`` joining
#     anyio's non-daemon worker thread, whose ``stop()`` was a done-callback of
#     the task the abort skipped.  Measured main-thread stack while hung:
#     ``threading.py:_shutdown``.  SIGKILL was the only exit.
#
# ``test_sigterm_handler_raises_system_exit`` above was green throughout: it
# calls the handler in a process with no event loop and no worker threads, so
# it pins the implementation detail and cannot see the behaviour.  The two
# subprocess tests here reach the mechanism instead, and each proves it was
# reached (an ``initialize`` round-trip) before reading a shutdown outcome.

_SERVER_MAIN = "from codeclone.surfaces.mcp.server import main; main()"
_PROVENANCE = (
    "import pathlib, codeclone;"
    "_p = pathlib.Path(codeclone.__file__).resolve().parent.parent;"
    "assert _p == pathlib.Path({root!r}), f'wrong codeclone: {{_p}}';"
)
#: Long enough that a hang is unambiguous, short enough for a test suite.
_EXIT_BOUND_SECONDS = 20.0
_TEST_GRACE_SECONDS = "0.5"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _spawn_stdio_server(
    *,
    prelude: str = "",
    grace_seconds: str = _TEST_GRACE_SECONDS,
) -> subprocess.Popen[bytes]:
    """The real server on the real transport, in a fresh interpreter."""

    root = _repo_root()
    source = _PROVENANCE.format(root=str(root)) + prelude + _SERVER_MAIN
    env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "CODECLONE_MCP_SHUTDOWN_GRACE_SECONDS": grace_seconds,
    }
    return subprocess.Popen(
        [sys.executable, "-c", source],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(root),
        env=env,
    )


def _initialize(proc: subprocess.Popen[bytes]) -> None:
    """Probe validity: prove the server is serving before signalling it.

    A process that died at import would also "exit on SIGTERM".  The round
    trip below is what makes the later exit attributable to the signal.
    """

    assert proc.stdin is not None and proc.stdout is not None
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "shutdown-probe", "version": "1"},
        },
    }
    proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, "server produced no initialize response; it was never serving"
    payload = json.loads(line)
    assert payload.get("id") == 1 and "result" in payload, payload


def _terminate_and_wait(proc: subprocess.Popen[bytes]) -> int:
    proc.send_signal(signal.SIGTERM)
    try:
        return proc.wait(timeout=_EXIT_BOUND_SECONDS)
    except subprocess.TimeoutExpired:  # pragma: no cover - the defect's shape
        proc.kill()
        proc.wait(timeout=_EXIT_BOUND_SECONDS)
        raise AssertionError(
            f"server ignored SIGTERM for {_EXIT_BOUND_SECONDS}s; only SIGKILL ended it"
        ) from None
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics")
def test_sigterm_terminates_a_running_stdio_server() -> None:
    """The hard boundary: the process must end without SIGKILL."""

    proc = _spawn_stdio_server()
    try:
        _initialize(proc)
        _terminate_and_wait(proc)
    finally:
        if proc.poll() is None:  # pragma: no cover - only on assertion paths
            proc.kill()
            proc.wait(timeout=_EXIT_BOUND_SECONDS)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics")
def test_sigterm_runs_the_teardown_the_lifespan_never_reaches(
    tmp_path: Path,
) -> None:
    """The soft boundary: SIGKILL's cost is the cleanup it denies.

    Separate from the test above on purpose.  A watchdog that only hard-exits
    would satisfy termination while still leaving the sqlite handle and the
    workspace intent behind -- which is the state SIGKILL already produced.
    """

    marker = tmp_path / "teardown.marker"
    prelude = (
        "from codeclone.surfaces.mcp.service import CodeCloneMCPService as _S;"
        "_orig = _S.shutdown_cleanup;"
        f"_m = pathlib.Path({str(marker)!r});"
        "_S.shutdown_cleanup = lambda self: (_m.write_text('ran'), _orig(self))[1];"
    )
    proc = _spawn_stdio_server(prelude=prelude)
    try:
        _initialize(proc)
        _terminate_and_wait(proc)
    finally:
        if proc.poll() is None:  # pragma: no cover - only on assertion paths
            proc.kill()
            proc.wait(timeout=_EXIT_BOUND_SECONDS)
    assert marker.is_file(), (
        "SIGTERM ended the process without running the shutdown cleanup "
        "the handler exists to make possible"
    )


def test_the_real_deadline_timer_fires_and_never_blocks_interpreter_exit() -> None:
    """The production arming path, which every other test replaces.

    A deadline nobody ever arms for real is theatre: the whole fallback rests
    on this thread being (a) reached and (b) daemonic, and the injected
    ``arm_deadline`` in the tests above proves neither.
    """

    from codeclone.surfaces.mcp._shutdown import _spawn_deadline

    fired = threading.Event()
    daemonic: list[bool] = []

    def _on_deadline() -> None:
        daemonic.append(threading.current_thread().daemon)
        fired.set()

    _spawn_deadline(0.01, _on_deadline)
    assert fired.wait(timeout=5.0), "the production deadline timer never fired"
    assert daemonic == [True], (
        "a non-daemon watchdog would join the very shutdown queue it exists to break"
    )


def test_an_unconfigured_coordinator_reads_the_grace_window_at_signal_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Late configuration must still be honoured.

    The process-global coordinator is built at import; the environment that
    configures it is read by the operator's launcher, which may set it after.
    """

    from codeclone.surfaces.mcp._shutdown import (
        DEFAULT_SHUTDOWN_GRACE_SECONDS,
        SHUTDOWN_GRACE_ENV,
        ShutdownCoordinator,
    )

    coordinator = ShutdownCoordinator(
        hard_exit=lambda _status: None,
        arm_deadline=lambda _delay, _callback: None,
    )
    monkeypatch.delenv(SHUTDOWN_GRACE_ENV, raising=False)
    assert coordinator.grace_seconds() == DEFAULT_SHUTDOWN_GRACE_SECONDS
    monkeypatch.setenv(SHUTDOWN_GRACE_ENV, "1.25")
    assert coordinator.grace_seconds() == 1.25
