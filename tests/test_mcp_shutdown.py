"""Tests for Phase 7 — graceful MCP process shutdown.

Validates that ``safe_remove_own_intent`` enforces zero-trust path
safety, and that ``CodeCloneMCPService.shutdown_cleanup`` removes only
files owned by the current process.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

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
        "forbidden": [".cache/codeclone/**", "codeclone.baseline.json"],
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


# ---------------------------------------------------------------------------
# _is_safe_intent_path
# ---------------------------------------------------------------------------


def test_safe_path_accepts_valid_intent_path(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    expected = intent_path(
        root=tmp_path,
        pid=123,
        start_epoch=456,
        intent_id="intent-aaa-001",
    )
    assert _is_safe_intent_path(expected, registry) is True


def test_safe_path_rejects_relative(tmp_path: Path) -> None:
    registry = registry_dir(tmp_path)
    assert (
        _is_safe_intent_path(
            Path("relative/123-456-intent-aaa-001.json"),
            registry,
        )
        is False
    )


@pytest.mark.parametrize(
    "target_relative_to",
    ["outside", "inside"],
    ids=["symlink-outside-registry", "symlink-inside-registry"],
)
def test_safe_path_rejects_symlink(
    tmp_path: Path,
    target_relative_to: str,
) -> None:
    registry = registry_dir(tmp_path)
    registry.mkdir(parents=True, exist_ok=True)
    parent = tmp_path if target_relative_to == "outside" else registry
    target = parent / "real-target.json"
    target.write_text("{}")
    symlink = registry / "123-456-intent-aaa-001.json"
    symlink.symlink_to(target)
    assert _is_safe_intent_path(symlink, registry) is False


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


def test_shutdown_cleanup_skips_on_run_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _svc()
    run_id = str(svc.analyze_repository(_analysis_request(str(tmp_path)))["run_id"])
    svc.manage_change_intent(
        action="declare",
        run_id=run_id,
        root=str(tmp_path),
        scope={"allowed_files": ["pkg/c.py"], "allowed_related": [], "forbidden": []},
        intent="error test",
    )
    monkeypatch.setattr(
        svc._runs,
        "get",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    svc.shutdown_cleanup()  # must not raise


# ---------------------------------------------------------------------------
# SIGTERM handler
# ---------------------------------------------------------------------------


def test_sigterm_handler_raises_system_exit() -> None:
    import signal

    from codeclone.surfaces.mcp.server import _install_sigterm_handler

    old = signal.getsignal(signal.SIGTERM)
    try:
        _install_sigterm_handler()
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not signal.SIG_DFL
        with pytest.raises(SystemExit) as exc_info:
            handler(signal.SIGTERM, None)  # type: ignore[misc,operator]
        assert exc_info.value.code == 0
    finally:
        signal.signal(signal.SIGTERM, old)
