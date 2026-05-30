# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import io
import json
import os
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from rich.console import Console

import codeclone.surfaces.cli.session_stats as session_stats_mod
from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.session_stats import (
    _AgentSnapshot,
    _classify_workspace_health,
    _format_age,
    _format_duration,
    _has_scope_overlap,
    _IntentSnapshot,
    _is_pid_alive,
    _lease_remaining_seconds,
    _read_cached_report,
    render_session_stats,
)
from codeclone.surfaces.cli.types import PrinterLike
from codeclone.surfaces.mcp._workspace_intents import (
    MIN_LEASE_SECONDS,
    WorkspaceIntentRecord,
    compute_scope_digest,
    expires_at,
    format_utc,
    write_workspace_intent,
)


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _write_intent_file(
    intents_dir: Path,
    *,
    intent_id: str = "intent-aabb0011-001",
    pid: int = 99999,
    start_epoch: int | None = None,
    status: str = "active",
    label: str = "test-agent",
    allowed_files: list[str] | None = None,
    ttl_seconds: int = 3600,
    lease_seconds: int = 300,
) -> Path:
    """Write a synthetic workspace intent JSON file."""
    now_epoch = start_epoch or int(time.time())
    now_utc = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
    declared = format_utc(now_utc)
    scope_files = allowed_files or ["src/a.py"]
    scope: dict[str, object] = {
        "allowed_files": scope_files,
        "allowed_related": [],
        "forbidden": [],
    }
    root = intents_dir.parent.parent.parent
    record = WorkspaceIntentRecord(
        intent_id=intent_id,
        agent_pid=pid,
        agent_start_epoch=now_epoch,
        agent_label=label,
        run_id="a" * 64,
        declared_at_utc=declared,
        expires_at_utc=expires_at(declared_at=now_utc, ttl_seconds=ttl_seconds),
        ttl_seconds=ttl_seconds,
        status=status,
        intent="test intent",
        scope=scope,
        scope_digest=compute_scope_digest(scope),
        blast_radius_summary={},
        lease_renewed_at_utc=declared,
        lease_seconds=lease_seconds,
        report_digest="a" * 64,
    )
    assert write_workspace_intent(root=root, record=record)
    return intents_dir / f"{pid}-{now_epoch}-{intent_id}.json"


def _write_report(root: Path, *, health: int = 90, files: int = 10) -> Path:
    """Write a synthetic report.json."""
    report = {
        "integrity": {"digest": {"value": "abcdef01" + "0" * 56}},
        "inventory": {"file_registry": {"items": [f"f{i}.py" for i in range(files)]}},
        "metrics": {"families": {}},
        "health": {"score": health, "grade": "A"},
        "findings": {"total": 0},
    }
    report_dir = root / ".cache" / "codeclone"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(report))
    return report_path


def _write_report_payload(root: Path, payload: object) -> Path:
    report_dir = root / ".cache" / "codeclone"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(payload))
    return report_path


def _render_session_stats_text(root: Path, *, quiet: bool) -> str:
    printer = _RecordingPrinter()
    exit_code = render_session_stats(
        console=printer,
        root_path=root,
        quiet=quiet,
    )
    assert exit_code == int(ExitCode.SUCCESS)
    return printer.text


def _snapshot(
    *,
    agents: tuple[_AgentSnapshot, ...] = (),
    workspace_health: str = "idle",
    latest_run_id: str | None = None,
    latest_run_health: int | None = None,
    latest_run_findings: int | None = None,
    latest_run_files: int | None = None,
    latest_run_age_seconds: int | None = None,
    cache_present: bool = False,
    mcp_token_footprint: int | None = None,
    mcp_token_encoding: str | None = None,
    mcp_token_event_count: int = 0,
) -> session_stats_mod._SessionSnapshot:
    return session_stats_mod._SessionSnapshot(
        root=Path("/tmp/test"),
        agents=agents,
        stale_count=0,
        expired_count=0,
        recoverable_count=0,
        latest_run_id=latest_run_id,
        latest_run_health=latest_run_health,
        latest_run_findings=latest_run_findings,
        latest_run_files=latest_run_files,
        latest_run_age_seconds=latest_run_age_seconds,
        cache_present=cache_present,
        workspace_health=workspace_health,
        intent_registry_backend="file",
        intent_registry_storage=".cache/codeclone/intents",
        mcp_token_footprint=mcp_token_footprint,
        mcp_token_encoding=mcp_token_encoding,
        mcp_token_event_count=mcp_token_event_count,
    )


def _write_audit_pyproject(
    tmp_path: Path,
    *,
    enabled: bool = True,
    audit_path: str | None = None,
) -> None:
    lines = ["[tool.codeclone]"]
    if enabled:
        lines.append("audit_enabled = true")
    if audit_path is not None:
        lines.append(f'audit_path = "{audit_path}"')
    (tmp_path / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _snapshot_with_audit_and_run(
    *,
    health: int = 88,
    findings: int = 3,
    age_seconds: int = 12,
    files: int | None = None,
) -> session_stats_mod._SessionSnapshot:
    return replace(
        _snapshot(
            latest_run_id="run1234567890",
            latest_run_health=health,
            latest_run_findings=findings,
            latest_run_age_seconds=age_seconds,
            latest_run_files=files,
            cache_present=True,
        ),
        audit_enabled=True,
        audit_storage=".cache/codeclone/db/audit.sqlite3",
    )


# ── Quiet mode tests ──


def test_session_stats_idle_quiet(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "session-stats: idle" in printer.text
    assert "agents=0" in printer.text
    assert "intents=0" in printer.text
    assert "latest_run=none" in printer.text


def test_session_stats_active_quiet(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    current_pid = os.getpid()
    _write_intent_file(
        intents_dir,
        pid=current_pid,
        start_epoch=int(time.time()),
        status="active",
    )
    text = _render_session_stats_text(tmp_path, quiet=True)

    assert "session-stats: active" in text
    assert "agents=1" in text
    assert "intents=1" in text


def test_session_stats_with_cached_report(tmp_path: Path) -> None:
    _write_report(tmp_path, health=85, files=42)
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "latest_run=abcdef01" in printer.text
    assert "health=85" in printer.text


def test_session_stats_stale_quiet(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    _write_intent_file(
        intents_dir,
        pid=2,
        start_epoch=1000000,
        status="active",
        lease_seconds=1,
    )
    printer = _RecordingPrinter()

    with patch.object(session_stats_mod, "_is_pid_alive", return_value=False):
        exit_code = render_session_stats(
            console=printer,
            root_path=tmp_path,
            quiet=True,
        )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "stale=" in printer.text


# ── Verbose mode tests ──


def test_session_stats_idle_verbose(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert "Session Stats" in text
    assert "Active agents:   0" in text
    assert "Workspace health: idle" in text


def test_session_stats_active_verbose(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    current_pid = os.getpid()
    _write_intent_file(
        intents_dir,
        pid=current_pid,
        start_epoch=int(time.time()),
        status="active",
        allowed_files=["src/a.py", "src/b.py"],
    )
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert "Active agents:   1" in text
    assert f"PID {current_pid}" in text
    assert "src/a.py" in text
    assert "Workspace health: active" in text


def test_session_stats_verbose_with_report(tmp_path: Path) -> None:
    _write_report(tmp_path, health=92, files=100)
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert "abcdef01" in text
    assert "health=92" in text
    assert "100 files" in text


def test_session_stats_verbose_uses_rich_table(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    _write_intent_file(
        intents_dir,
        pid=os.getpid(),
        start_epoch=int(time.time()),
        allowed_files=["src/a.py"],
    )
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=100)

    exit_code = render_session_stats(
        console=cast(PrinterLike, console),
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = output.getvalue()
    assert "Session Stats" in text
    assert "Workspace intents" in text
    assert "src/a.py" in text


def test_session_stats_verbose_with_report_without_file_count(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / ".cache" / "codeclone"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text(
        json.dumps(
            {
                "integrity": {"digest": {"value": "12345678" + "0" * 56}},
                "metrics": {"families": {}},
                "health": {"score": 77},
                "findings": {"total": 3},
            }
        )
    )
    text = _render_session_stats_text(tmp_path, quiet=False)

    assert "12345678" in text
    assert "findings=3" in text
    assert "Cache:" not in text


def test_session_stats_verbose_truncates_allowed_files(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    _write_intent_file(
        intents_dir,
        pid=os.getpid(),
        start_epoch=int(time.time()),
        allowed_files=[f"src/{index}.py" for index in range(7)],
    )
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "and 2 more" in printer.text


def test_session_stats_verbose_handles_empty_allowed_files(tmp_path: Path) -> None:
    printer = _RecordingPrinter()
    snapshot = session_stats_mod._SessionSnapshot(
        root=tmp_path,
        agents=(
            _AgentSnapshot(
                pid=123,
                start_epoch=int(time.time()),
                label="agent",
                alive=True,
                intents=(
                    _IntentSnapshot(
                        intent_id="intent-empty-files",
                        status="active",
                        ownership="foreign_active",
                        scope_file_count=0,
                        allowed_files=(),
                        declared_at_utc="",
                        lease_remaining_seconds=0,
                    ),
                ),
            ),
        ),
        stale_count=0,
        expired_count=0,
        recoverable_count=0,
        latest_run_id=None,
        latest_run_health=None,
        latest_run_findings=None,
        latest_run_files=None,
        latest_run_age_seconds=None,
        cache_present=False,
        workspace_health="active",
        intent_registry_backend="file",
        intent_registry_storage=".cache/codeclone/intents",
    )

    exit_code = session_stats_mod._render_verbose(printer, snapshot)

    assert exit_code == int(ExitCode.SUCCESS)
    assert "scope: 0 files" in printer.text
    assert "lease: expired remaining" in printer.text
    assert "allowed:" not in printer.text


# ── Edge cases ──


def test_session_stats_no_cache_dir(tmp_path: Path) -> None:
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "idle" in printer.text


def test_session_stats_corrupt_intent_file(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    (intents_dir / "999-999-intent-bad.json").write_text("{corrupt json!!!")
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "idle" in printer.text


def test_session_stats_corrupt_report(tmp_path: Path) -> None:
    report_dir = tmp_path / ".cache" / "codeclone"
    report_dir.mkdir(parents=True)
    (report_dir / "report.json").write_text("NOT JSON")
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "latest_run=none" in printer.text


def test_session_stats_reader_failure_is_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_reader_error(*args: object, **kwargs: object) -> tuple[object, ...]:
        raise OSError("registry unavailable")

    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intents.list_workspace_intent_records_for_recovery",
        raise_reader_error,
    )
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "session-stats: idle" in printer.text


def test_session_stats_contract_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_collection_error(root_path: Path) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        session_stats_mod,
        "_collect_session_snapshot",
        raise_collection_error,
    )
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert "failed to read session state: boom" in printer.text


def test_collect_session_snapshot_tolerates_non_list_allowed_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    record = SimpleNamespace(
        agent_pid=os.getpid(),
        agent_start_epoch=100,
        agent_label="agent",
        intent_id="intent-bad-scope-001",
        status="active",
        declared_at_utc="2026-01-01T00:00:00Z",
        expires_at_utc="2099-01-01T00:00:00Z",
        lease_renewed_at_utc="2026-01-01T00:00:00Z",
        lease_seconds=3600,
        scope={"allowed_files": "pkg/a.py"},
    )
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intents.list_workspace_intent_records_for_recovery",
        lambda **_: (record,),
    )
    monkeypatch.setattr(session_stats_mod, "_process_start_epoch", lambda: 100)
    snapshot = session_stats_mod._collect_session_snapshot(tmp_path)
    assert len(snapshot.agents) == 1
    assert snapshot.agents[0].intents[0].allowed_files == ()


def test_session_stats_counts_expired_stale_and_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    own_start_epoch = int(time.time()) - MIN_LEASE_SECONDS - 10
    _write_intent_file(
        intents_dir,
        intent_id="intent-own-stale-001",
        pid=os.getpid(),
        start_epoch=own_start_epoch,
        lease_seconds=MIN_LEASE_SECONDS,
    )
    _write_intent_file(
        intents_dir,
        intent_id="intent-recoverable-001",
        pid=999999,
        start_epoch=own_start_epoch,
        lease_seconds=300,
    )
    _write_intent_file(
        intents_dir,
        intent_id="intent-expired-001",
        pid=999998,
        start_epoch=own_start_epoch - 4000,
    )

    monkeypatch.setattr(
        session_stats_mod, "_process_start_epoch", lambda: own_start_epoch
    )
    monkeypatch.setattr(
        session_stats_mod,
        "_is_pid_alive",
        lambda pid: pid == os.getpid(),
    )

    snapshot = session_stats_mod._collect_session_snapshot(tmp_path)

    assert snapshot.stale_count == 1
    assert snapshot.recoverable_count == 1
    assert snapshot.expired_count == 1


def test_session_stats_groups_multiple_intents_per_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intents_dir = tmp_path / ".cache" / "codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    start_epoch = int(time.time())
    for index in range(2):
        _write_intent_file(
            intents_dir,
            intent_id=f"intent-same-agent-{index:03d}",
            pid=os.getpid(),
            start_epoch=start_epoch,
            allowed_files=[f"src/{index}.py"],
        )

    monkeypatch.setattr(session_stats_mod, "_process_start_epoch", lambda: start_epoch)
    snapshot = session_stats_mod._collect_session_snapshot(tmp_path)

    assert len(snapshot.agents) == 1
    assert len(snapshot.agents[0].intents) == 2


# ── Data collection helpers ──


def test_read_cached_report_missing(tmp_path: Path) -> None:
    run_id, _health, _findings, _files, _age, present = _read_cached_report(tmp_path)
    assert run_id is None
    assert not present


def test_read_cached_report_valid(tmp_path: Path) -> None:
    _write_report(tmp_path, health=88, files=50)
    run_id, health, _findings, files, age, present = _read_cached_report(tmp_path)
    assert run_id == "abcdef01"
    assert health == 88
    assert files == 50
    assert present is True
    assert age is not None and age >= 0


def test_read_cached_report_non_object_payload(tmp_path: Path) -> None:
    _write_report_payload(tmp_path, [])

    run_id, _health, _findings, _files, age, present = _read_cached_report(tmp_path)

    assert (run_id, _health, _findings, _files) == (None, None, None, None)
    assert age is not None
    assert present is True


def test_read_cached_report_nested_type_mismatches(tmp_path: Path) -> None:
    _write_report_payload(
        tmp_path,
        {
            "integrity": {"digest": []},
            "inventory": {"file_registry": []},
            "metrics": {"families": []},
            "findings": [],
        },
    )

    run_id, _health, _findings, _files, age, present = _read_cached_report(tmp_path)

    assert (run_id, _health, _findings, _files) == (None, None, None, None)
    assert age is not None
    assert present is True


def test_read_cached_report_leaf_type_mismatches(tmp_path: Path) -> None:
    _write_report_payload(
        tmp_path,
        {
            "integrity": {"digest": {"value": 123}},
            "inventory": {"file_registry": {"items": "bad"}},
            "metrics": {"families": {}},
            "health": [],
            "findings": {"total": "bad"},
        },
    )

    run_id, _health, _findings, _files, age, present = _read_cached_report(tmp_path)

    assert (run_id, _health, _findings, _files) == (None, None, None, None)
    assert age is not None
    assert present is True


def test_read_cached_report_stat_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_report(tmp_path)

    def raise_stat_error(self: Path) -> object:
        raise OSError("stat failed")

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "stat", raise_stat_error)

    run_id, _health, _findings, _files, age, present = _read_cached_report(tmp_path)

    assert run_id == "abcdef01"
    assert age is None
    assert present is True


# ── Workspace health classification ──


def test_classify_idle_no_agents() -> None:
    assert (
        _classify_workspace_health(agents=[], stale_count=0, expired_count=0) == "idle"
    )


def test_classify_clean_no_active_intents() -> None:
    agent = _AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(
            _IntentSnapshot(
                intent_id="i",
                status="clean",
                ownership="own_active",
                scope_file_count=1,
                allowed_files=("x.py",),
                declared_at_utc="",
                lease_remaining_seconds=60,
            ),
        ),
    )
    assert (
        _classify_workspace_health(agents=[agent], stale_count=0, expired_count=0)
        == "clean"
    )


def test_classify_active_with_active_intent() -> None:
    agent = _AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(
            _IntentSnapshot(
                intent_id="i",
                status="active",
                ownership="own_active",
                scope_file_count=1,
                allowed_files=("x.py",),
                declared_at_utc="",
                lease_remaining_seconds=60,
            ),
        ),
    )
    assert (
        _classify_workspace_health(agents=[agent], stale_count=0, expired_count=0)
        == "active"
    )


def test_classify_contested_overlapping_scope() -> None:
    intent_a = _IntentSnapshot(
        intent_id="ia",
        status="active",
        ownership="own_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    intent_b = _IntentSnapshot(
        intent_id="ib",
        status="active",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agent_a = _AgentSnapshot(
        pid=1, start_epoch=1, label="a", alive=True, intents=(intent_a,)
    )
    agent_b = _AgentSnapshot(
        pid=2, start_epoch=2, label="b", alive=True, intents=(intent_b,)
    )
    result = _classify_workspace_health(
        agents=[agent_a, agent_b], stale_count=0, expired_count=0
    )
    assert result == "contested"


def test_classify_active_non_overlapping_agents() -> None:
    intent_a = _IntentSnapshot(
        intent_id="ia",
        status="active",
        ownership="own_active",
        scope_file_count=1,
        allowed_files=("a.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    intent_b = _IntentSnapshot(
        intent_id="ib",
        status="active",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("b.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agent_a = _AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(intent_a,),
    )
    agent_b = _AgentSnapshot(
        pid=2,
        start_epoch=2,
        label="b",
        alive=True,
        intents=(intent_b,),
    )

    assert (
        _classify_workspace_health(
            agents=[agent_a, agent_b],
            stale_count=0,
            expired_count=0,
        )
        == "active"
    )


def test_classify_ignores_inactive_empty_scopes() -> None:
    inactive = _IntentSnapshot(
        intent_id="ia",
        status="clean",
        ownership="own_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    empty_active = _IntentSnapshot(
        intent_id="ib",
        status="active",
        ownership="foreign_active",
        scope_file_count=0,
        allowed_files=(),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agent_a = _AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(inactive,),
    )
    agent_b = _AgentSnapshot(
        pid=2,
        start_epoch=2,
        label="b",
        alive=True,
        intents=(empty_active,),
    )

    assert (
        _classify_workspace_health(
            agents=[agent_a, agent_b],
            stale_count=0,
            expired_count=0,
        )
        == "active"
    )


# ── Formatting helpers ──


def test_format_age_seconds() -> None:
    assert _format_age(30) == "30s ago"


def test_format_age_minutes() -> None:
    assert _format_age(180) == "3m ago"


def test_format_age_hours() -> None:
    assert _format_age(3660) == "1h1m ago"


def test_format_age_exact_hours() -> None:
    assert _format_age(3600) == "1h ago"


def test_format_age_none() -> None:
    assert _format_age(None) == "unknown"


def test_format_duration_expired() -> None:
    assert _format_duration(0) == "expired"


def test_format_duration_seconds() -> None:
    assert _format_duration(45) == "45s"


def test_format_duration_minutes() -> None:
    assert _format_duration(125) == "2m5s"


def test_lease_remaining_handles_invalid_lease() -> None:
    scope: dict[str, object] = {
        "allowed_files": ["src/a.py"],
        "allowed_related": [],
        "forbidden": [],
    }
    now_epoch = int(time.time())
    now_utc = datetime.fromtimestamp(now_epoch, tz=timezone.utc)
    record = WorkspaceIntentRecord(
        intent_id="intent-invalid-lease-001",
        agent_pid=os.getpid(),
        agent_start_epoch=now_epoch,
        agent_label="test-agent",
        run_id="a" * 64,
        declared_at_utc=format_utc(now_utc),
        expires_at_utc=expires_at(declared_at=now_utc, ttl_seconds=3600),
        ttl_seconds=3600,
        status="active",
        intent="test intent",
        scope=scope,
        scope_digest=compute_scope_digest(scope),
        blast_radius_summary={},
        lease_renewed_at_utc="not-a-date",
        lease_seconds=300,
        report_digest="a" * 64,
    )

    assert _lease_remaining_seconds(record, now_utc) == 0


def test_is_pid_alive_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _is_pid_alive(0) is False

    def raise_process_lookup(pid: int, signal: int) -> None:
        raise ProcessLookupError

    def raise_permission(pid: int, signal: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", raise_process_lookup)
    assert _is_pid_alive(123) is False
    monkeypatch.setattr(os, "kill", raise_permission)
    assert _is_pid_alive(123) is True


# ── Token footprint in verbose plain mode ──


def test_session_stats_verbose_plain_with_token_footprint() -> None:
    """Exercise plain verbose path with mcp_token_footprint (lines 277-278)."""
    printer = _RecordingPrinter()
    snapshot = _snapshot(
        mcp_token_footprint=5000,
        mcp_token_encoding="o200k_base",
        mcp_token_event_count=10,
    )

    exit_code = session_stats_mod._render_verbose(printer, snapshot)

    assert exit_code == int(ExitCode.SUCCESS)
    assert "MCP payload footprint" in printer.text
    assert "5,000" in printer.text
    assert "o200k_base" in printer.text


# ── Rich verbose with cached report + file count ──


def test_session_stats_rich_with_cached_report_and_files(tmp_path: Path) -> None:
    """Exercise Rich path with latest_run_files (lines 298-301)."""
    _write_report(tmp_path, health=92, files=100)
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=120)

    exit_code = render_session_stats(
        console=cast(PrinterLike, console),
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = output.getvalue()
    assert "report.json present" in text
    assert "100 files" in text


# ── Rich verbose with token footprint ──


def test_session_stats_rich_with_token_footprint() -> None:
    """Exercise Rich path with mcp_token_footprint (lines 312-313)."""
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=120)
    snapshot = _snapshot(
        mcp_token_footprint=3000,
        mcp_token_encoding="o200k_base",
        mcp_token_event_count=7,
    )

    exit_code = session_stats_mod._render_verbose_rich(
        cast(PrinterLike, console), snapshot
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = output.getvalue()
    assert "MCP payload footprint" in text
    assert "3,000" in text


# ── Rich verbose with no live agents ──


def test_session_stats_rich_no_live_agents() -> None:
    """Exercise Rich path with dead agent only (lines 329-330)."""
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=120)
    snapshot = _snapshot(
        agents=(
            _AgentSnapshot(
                pid=999999,
                start_epoch=int(time.time()),
                label="dead-agent",
                alive=False,
                intents=(),
            ),
        ),
    )

    exit_code = session_stats_mod._render_verbose_rich(
        cast(PrinterLike, console), snapshot
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = output.getvalue()
    assert "No live workspace agents found" in text


# ── _latest_run_text with health and findings ──


def test_latest_run_text_with_health_and_findings() -> None:
    """Exercise _latest_run_text branches (lines 377-384)."""
    snapshot = _snapshot(
        latest_run_id="abc12345",
        latest_run_health=90,
        latest_run_findings=5,
        latest_run_files=100,
        latest_run_age_seconds=120,
        cache_present=True,
        workspace_health="clean",
    )

    result = session_stats_mod._latest_run_text(snapshot)

    assert "abc12345" in result
    assert "health=90" in result
    assert "findings=5" in result


# ── _allowed_files_label ──


def test_allowed_files_label_empty() -> None:
    """Exercise _allowed_files_label with empty tuple (line 389)."""
    assert session_stats_mod._allowed_files_label(()) == "-"


def test_allowed_files_label_many() -> None:
    """Exercise _allowed_files_label truncation (line 393)."""
    files = tuple(f"src/{i}.py" for i in range(7))
    result = session_stats_mod._allowed_files_label(files)
    assert "and 2 more" in result


# ── _ownership_style ──


def test_ownership_style_branches() -> None:
    """Exercise all _ownership_style branches (lines 409-415)."""
    assert session_stats_mod._ownership_style("own_active") == "green"
    assert session_stats_mod._ownership_style("own_stale") == "green"
    assert session_stats_mod._ownership_style("foreign_stale") == "yellow"
    assert session_stats_mod._ownership_style("foreign_active") == "cyan"
    assert session_stats_mod._ownership_style("recoverable") == "magenta"
    assert session_stats_mod._ownership_style("unknown") == "dim"


# ── _resolve_mcp_tokens ──


def test_read_audit_config_enabled_relative_path(tmp_path: Path) -> None:
    _write_audit_pyproject(
        tmp_path,
        audit_path=".cache/codeclone/db/audit.sqlite3",
    )
    enabled, storage = session_stats_mod._read_audit_config(tmp_path)
    assert enabled is True
    assert storage == ".cache/codeclone/db/audit.sqlite3"


def test_read_audit_config_config_validation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.config.pyproject_loader import ConfigValidationError

    monkeypatch.setattr(
        "codeclone.config.pyproject_loader.load_pyproject_config",
        lambda _root: (_ for _ in ()).throw(ConfigValidationError("bad")),
    )
    enabled, storage = session_stats_mod._read_audit_config(tmp_path)
    assert enabled is False
    assert storage is None


def test_read_audit_config_disabled(tmp_path: Path) -> None:
    enabled, storage = session_stats_mod._read_audit_config(tmp_path)
    assert enabled is False
    assert storage is None


def test_read_audit_config_enabled_with_absolute_path(tmp_path: Path) -> None:
    _write_audit_pyproject(tmp_path, audit_path="/tmp/audit.sqlite3")
    enabled, storage = session_stats_mod._read_audit_config(tmp_path)
    assert enabled is True
    assert storage is None


def test_read_audit_config_storage_falls_back_when_not_relative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = Path("/tmp/codeclone-audit-outside.sqlite3")
    _write_audit_pyproject(tmp_path, audit_path=".cache/codeclone/db/audit.sqlite3")
    monkeypatch.setattr(
        "codeclone.audit.validation.resolve_audit_path",
        lambda **_: outside,
    )
    enabled, storage = session_stats_mod._read_audit_config(tmp_path)
    assert enabled is True
    assert storage == str(outside)


def test_has_scope_overlap_ignores_non_active_intents() -> None:
    queued = _IntentSnapshot(
        intent_id="queued",
        status="queued",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    active = _IntentSnapshot(
        intent_id="active",
        status="active",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("other.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agents = (
        _AgentSnapshot(pid=1, start_epoch=1, label="a", alive=True, intents=(queued,)),
        _AgentSnapshot(pid=2, start_epoch=2, label="b", alive=True, intents=(active,)),
    )
    assert _has_scope_overlap(list(agents)) is False


@pytest.mark.parametrize(
    ("renderer", "include_health_marker"),
    [
        ("plain", True),
        ("rich", False),
    ],
)
def test_session_stats_verbose_includes_audit_and_run(
    renderer: str,
    include_health_marker: bool,
) -> None:
    snapshot = _snapshot_with_audit_and_run(
        health=90 if renderer == "rich" else 88,
        findings=2 if renderer == "rich" else 3,
        age_seconds=30 if renderer == "rich" else 12,
        files=5 if renderer == "rich" else None,
    )
    if renderer == "plain":
        printer = _RecordingPrinter()
        exit_code = session_stats_mod._render_verbose(printer, snapshot)
        text = printer.text
    else:
        output = io.StringIO()
        console = Console(
            file=output, force_terminal=True, color_system=None, width=100
        )
        exit_code = session_stats_mod._render_verbose_rich(
            cast(PrinterLike, console),
            snapshot,
        )
        text = output.getvalue()

    assert exit_code == int(ExitCode.SUCCESS)
    assert "audit.sqlite3" in text
    assert "run1234567890" in text
    if include_health_marker:
        assert "health=88" in text


def test_read_audit_token_footprint_handles_config_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "codeclone.config.pyproject_loader.load_pyproject_config",
        lambda _root: (_ for _ in ()).throw(OSError("boom")),
    )
    tokens, encoding, count = session_stats_mod._read_audit_token_footprint(tmp_path)
    assert tokens is None
    assert encoding is None
    assert count == 0


def test_read_audit_token_footprint_when_db_missing(tmp_path: Path) -> None:
    _write_audit_pyproject(tmp_path)
    tokens, encoding, count = session_stats_mod._read_audit_token_footprint(tmp_path)
    assert tokens is None
    assert encoding is None
    assert count == 0


def test_resolve_mcp_tokens_with_audit_data(tmp_path: Path) -> None:
    """Exercise _resolve_mcp_tokens with existing audit DB (lines 585-592)."""
    from codeclone.audit.events import (
        EVENT_PATCH_VERIFIED,
        AuditEvent,
        repo_root_digest,
    )
    from codeclone.audit.writer import SqliteAuditWriter

    db_path = tmp_path / ".cache" / "codeclone" / "db" / "audit.sqlite3"
    _write_audit_pyproject(tmp_path)
    writer = SqliteAuditWriter(db_path=db_path, payloads="compact", retention_days=30)
    try:
        writer.emit(
            AuditEvent(
                event_type=EVENT_PATCH_VERIFIED,
                severity="info",
                repo_root_digest=repo_root_digest(tmp_path),
                agent_pid=123,
                agent_label="agent",
                run_id="run123",
                status="accepted",
                payload={"data": "value"},
            )
        )
    finally:
        writer.close()

    tokens, encoding, count = session_stats_mod._read_audit_token_footprint(tmp_path)

    assert tokens is not None
    assert tokens > 0
    assert encoding is not None
    assert count == 1


def test_resolve_mcp_tokens_no_db(tmp_path: Path) -> None:
    """_read_audit_token_footprint returns (None, None, 0) when no DB exists."""
    tokens, encoding, count = session_stats_mod._read_audit_token_footprint(tmp_path)

    assert tokens is None
    assert encoding is None
    assert count == 0


def test_resolve_mcp_tokens_corrupt_db(tmp_path: Path) -> None:
    """_read_audit_token_footprint tolerates corrupt audit storage."""
    db_path = tmp_path / ".cache" / "codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("NOT A DATABASE")

    tokens, encoding, count = session_stats_mod._read_audit_token_footprint(tmp_path)

    assert tokens is None
    assert encoding is None
    assert count == 0
