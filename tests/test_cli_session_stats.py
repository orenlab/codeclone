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
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from rich.console import Console

import codeclone.controller_insights.session_stats as insights_mod
import codeclone.surfaces.cli.session_stats as session_stats_mod
from codeclone import ui_messages as ui
from codeclone.contracts import ExitCode
from codeclone.controller_insights.session_stats import (
    AgentSnapshot,
    IntentSnapshot,
    SessionSnapshot,
    WorkflowFootprintSnapshot,
    _classify_workspace_health,
    _format_age,
    _format_duration,
    _has_scope_overlap,
    _is_pid_alive,
    _lease_remaining_seconds,
    _read_audit_config,
    _read_audit_token_footprint,
    _read_disk_report,
    collect_session_snapshot,
)
from codeclone.surfaces.cli.session_stats import render_session_stats
from codeclone.surfaces.cli.types import PrinterLike
from codeclone.surfaces.mcp._workspace_intent_paths import registry_dir
from codeclone.surfaces.mcp._workspace_intents import (
    MIN_LEASE_SECONDS,
    WorkspaceIntentRecord,
    compute_scope_digest,
    expires_at,
    format_utc,
    write_workspace_intent,
)
from codeclone.utils.run_identity import report_run_identity

from ._report_fixtures import build_test_report_document, health_family_for_population

#: Fixed so the written report has a generation time the reader can age, and
#: so two documents in one test differ only where the test made them differ.
_REPORT_GENERATED_AT = "2026-08-13T10:00:00Z"

#: One clone group, so the document carries a finding rather than none. A
#: findings total of zero cannot tell "the reader found the count" from "the
#: reader found nothing and reported a default", and the count is the fact
#: the surface prints.
_ONE_CLONE_GROUP: dict[str, list[dict[str, object]]] = {
    "fp-a|20-49": [
        {
            "qualname": "pkg.a:run",
            "filepath": "/repo/pkg/a.py",
            "start_line": 1,
            "end_line": 20,
            "loc": 20,
            "stmt_count": 8,
            "fingerprint": "fp-a",
            "loc_bucket": "20-49",
        },
        {
            "qualname": "pkg.b:run",
            "filepath": "/repo/pkg/b.py",
            "start_line": 1,
            "end_line": 20,
            "loc": 20,
            "stmt_count": 8,
            "fingerprint": "fp-a",
            "loc_bucket": "20-49",
        },
    ]
}


def _repo_root_from_intents_dir(intents_dir: Path) -> Path:
    resolved = intents_dir.resolve()
    current = resolved.parent
    while current != current.parent:
        if registry_dir(current) == resolved:
            return current
        current = current.parent
    msg = f"cannot resolve repository root from intents dir: {intents_dir}"
    raise ValueError(msg)


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
    # Alive by construction. An unreserved "surely absent" default would hand
    # any future caller a premise the machine can refute.
    pid: int = os.getpid(),
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
    root = _repo_root_from_intents_dir(intents_dir)
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


def _write_report(
    root: Path,
    *,
    files: int = 10,
    analyzed: int | None = None,
    generated_at: str | None = _REPORT_GENERATED_AT,
) -> dict[str, object]:
    """Write the report the product actually emits, and hand it back.

    The disk reader is a consumer of ``report.json``. A hand-written stand-in
    lets it drift against the document it claims to read: the shape this
    fixture used to build carried ``integrity.digest``, a top-level ``health``
    block and ``findings.total``, none of which report-v3 emits -- so the
    reader's navigations and the fixture agreed with each other and with
    nothing else.

    The document is returned rather than its path so that no caller types a
    run id, a health score or a file count. Each is read off the document that
    was written, and a change in which key carries a fact moves the fixture
    with the document instead of leaving a literal behind.

    ``analyzed`` under-runs ``files`` when a caller needs a health score that
    is not the ubiquitous 100 of a defect-free fixture. ``generated_at=None``
    builds the document the builder produces when no generation time was
    supplied -- ``meta.runtime.report_generated_at_utc`` is null -- which is
    the only shape that makes the reader fall back to the file's mtime for the
    run's age.
    """

    document = build_test_report_document(
        func_groups=_ONE_CLONE_GROUP,
        block_groups={},
        segment_groups={},
        meta={} if generated_at is None else {"report_generated_at_utc": generated_at},
        inventory={"file_list": [f"f{index}.py" for index in range(files)]},
        metrics={
            "health": health_family_for_population(
                found=files,
                analyzed=files if analyzed is None else analyzed,
            )
        },
    )
    _write_report_payload(root, document)
    return document


def _document_run_id(document: Mapping[str, object]) -> str:
    """The run id a reader must derive from a report document.

    The tier is not named here and is not this test's invention:
    :func:`codeclone.utils.run_identity.report_run_identity` is the one place
    the product decides which digest names a run, and holding the disk
    reader to that owner is what keeps one document from answering "which run
    is this" in two tiers. The reader shortens the digest for display, so the
    expectation is shortened the same way.
    """

    return report_run_identity(document)[:8]


def _document_digest_prefix(document: Mapping[str, object], tier: str) -> str:
    digests = cast("Mapping[str, object]", document["integrity"])["digests"]
    return cast("Mapping[str, Mapping[str, str]]", digests)[tier]["value"][:8]


def _document_health(document: Mapping[str, object]) -> int:
    metrics = cast("Mapping[str, Mapping[str, Mapping[str, int]]]", document["metrics"])
    return metrics["summary"]["health"]["score"]


def _document_findings_total(document: Mapping[str, object]) -> int:
    findings = cast("Mapping[str, Mapping[str, int]]", document["findings"])
    return findings["summary"]["total"]


def _document_file_count(document: Mapping[str, object]) -> int:
    inventory = cast("Mapping[str, Mapping[str, Sequence[str]]]", document["inventory"])
    return len(inventory["file_registry"]["items"])


def _latest_run_line(text: str) -> str:
    """The single line the user reads the latest run off."""

    lines = [line for line in text.splitlines() if ui.SESSION_STATS_LATEST_RUN in line]
    assert len(lines) == 1, text
    return lines[0]


def _write_report_payload(root: Path, payload: object) -> Path:
    report_dir = root / ".codeclone"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(payload))
    return report_path


def _assert_snapshot_latest_run_from_audit(
    snapshot: SessionSnapshot,
    *,
    run_id: str,
    health: int,
    findings: int,
    files: int,
) -> None:
    assert snapshot.latest_run_source == "audit_mcp"
    assert snapshot.latest_run_id == run_id
    assert snapshot.latest_run_health == health
    assert snapshot.latest_run_findings == findings
    assert snapshot.latest_run_files == files


def _render_session_stats_text(root: Path, *, quiet: bool) -> str:
    printer = _RecordingPrinter()
    exit_code = render_session_stats(
        console=printer,
        root_path=root,
        quiet=quiet,
    )
    assert exit_code == int(ExitCode.SUCCESS)
    return printer.text


def _render_rich_session_stats(root: Path, *, width: int = 120) -> str:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=width)
    exit_code = render_session_stats(
        console=cast(PrinterLike, console),
        root_path=root,
        quiet=False,
    )
    assert exit_code == int(ExitCode.SUCCESS)
    return output.getvalue()


def _render_rich_snapshot(
    snapshot: SessionSnapshot,
    *,
    width: int = 120,
) -> str:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=width)
    exit_code = session_stats_mod._render_verbose_rich(
        cast(PrinterLike, console),
        snapshot,
    )
    assert exit_code == int(ExitCode.SUCCESS)
    return output.getvalue()


def _snapshot(
    *,
    agents: tuple[AgentSnapshot, ...] = (),
    workspace_health: str = "idle",
    latest_run_id: str | None = None,
    latest_run_health: int | None = None,
    latest_run_findings: int | None = None,
    latest_run_files: int | None = None,
    latest_run_age_seconds: int | None = None,
    latest_run_source: str | None = None,
    cache_present: bool = False,
    mcp_token_footprint: int | None = None,
    mcp_token_encoding: str | None = None,
    mcp_token_event_count: int = 0,
    top_workflows: tuple[WorkflowFootprintSnapshot, ...] = (),
) -> SessionSnapshot:
    return SessionSnapshot(
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
        latest_run_source=latest_run_source,
        cache_present=cache_present,
        workspace_health=workspace_health,
        intent_registry_backend="file",
        intent_registry_storage=".codeclone/intents",
        mcp_token_footprint=mcp_token_footprint,
        mcp_token_encoding=mcp_token_encoding,
        mcp_token_event_count=mcp_token_event_count,
        top_workflows=top_workflows,
    )


def _workflow_snapshot(
    *,
    workflow_kind: str = "intent",
    workflow_id: str = "intent-test-001",
    calls: int = 5,
    tokens: int = 4200,
    agent: str = "test-agent",
) -> WorkflowFootprintSnapshot:
    return WorkflowFootprintSnapshot(
        workflow_kind=workflow_kind,
        workflow_id=workflow_id,
        call_count=calls,
        total_tokens=tokens,
        max_tokens=tokens,
        agent_label=agent,
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


def _write_audit_analysis_row(
    root: Path,
    *,
    findings: dict[str, int],
    run_id: str = "runaudit1234567890",
) -> Path:
    """Enable audit for ``root`` and store one analysis row with ``findings``.

    One writer for every audit-sourced latest-run test, so the summary shape
    is spelled once and each test states only the findings block it is about.
    """

    from codeclone.audit.analysis_completed import ANALYSIS_SOURCE_MCP

    from .audit_fixtures import write_compact_analysis_completed_event

    _write_audit_pyproject(root)
    db_path = root / ".codeclone/db/audit.sqlite3"
    write_compact_analysis_completed_event(
        root,
        db_path=db_path,
        summary={
            "mode": "full",
            "health": {"score": 93, "grade": "A"},
            "findings": findings,
            "inventory": {"files": 11, "lines": 1, "functions": 1},
            "diff": {"new_clones": 0, "health_delta": None},
        },
        source=ANALYSIS_SOURCE_MCP,
        report_digest="a" * 64,
        run_id=run_id,
        agent_pid=1,
        agent_start_epoch=1,
        agent_label="mcp/test",
    )
    return db_path


def _snapshot_with_audit_and_run(
    *,
    health: int = 88,
    findings: int = 3,
    age_seconds: int = 12,
    files: int | None = None,
) -> SessionSnapshot:
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
        audit_storage=".codeclone/db/audit.sqlite3",
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
    assert "live_agents=0" in printer.text
    assert "active_intents=0" in printer.text
    assert "visible_intents=0" in printer.text
    assert "latest_run=none" in printer.text


def test_session_stats_active_quiet(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".codeclone" / "intents"
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
    assert "live_agents=1" in text
    assert "active_intents=1" in text
    assert "visible_intents=1" in text


def test_session_stats_with_cached_report(tmp_path: Path) -> None:
    document = _write_report(tmp_path, files=42)
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert f"latest_run={_document_run_id(document)}" in printer.text
    assert f"health={_document_health(document)}" in printer.text


def test_session_stats_stale_quiet(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    _write_intent_file(
        intents_dir,
        pid=2,
        start_epoch=1000000,
        status="active",
        lease_seconds=MIN_LEASE_SECONDS,
    )
    printer = _RecordingPrinter()

    with patch.object(insights_mod, "_is_pid_alive", return_value=False):
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
    assert "Live agents:" in text
    assert "Active edit intents:" in text
    assert "Visible intent records:" in text
    assert "Workspace health: idle" in text


def test_session_stats_active_verbose(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".codeclone" / "intents"
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
    assert "Live agents:" in text
    assert "Active edit intents:" in text
    assert "Visible intent records:" in text
    assert f"PID {current_pid}" in text
    assert "src/a.py" in text
    assert "Workspace health: active" in text


def test_session_stats_verbose_with_report(tmp_path: Path) -> None:
    document = _write_report(tmp_path, files=100)
    printer = _RecordingPrinter()

    exit_code = render_session_stats(
        console=printer,
        root_path=tmp_path,
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = printer.text
    assert _document_run_id(document) in text
    assert f"health={_document_health(document)}" in text
    assert f"{_document_file_count(document)} files" in text


def test_default_config_reports_the_run_its_disk_report_names(tmp_path: Path) -> None:
    """Audit off plus a report on disk means a run on screen, never ``none``.

    This is the default installation: ``audit_enabled`` defaults to False, so
    the document on disk is the only place the surface can answer from, and
    ``Latest run: none`` printed beside a live ``report.json`` is the product
    defect this pin holds shut for good.

    It is stated as what the user reads, not as what ``_read_disk_report``
    returns, so it keeps holding however that reader is rewritten -- and the
    document is built by the report builder rather than typed here, so a
    document that stops carrying one of these facts reaches this pin instead
    of being shadowed by a literal.
    """

    document = _write_report(tmp_path, files=6)
    # Without this the pin could pass through the audit trail and prove
    # nothing about the path the default user is actually on.
    assert _read_audit_config(tmp_path) == (False, None)

    line = _latest_run_line(_render_session_stats_text(tmp_path, quiet=False))

    assert ui.SESSION_STATS_LATEST_RUN_NONE not in line
    assert _document_run_id(document) in line
    assert f"health={_document_health(document)}" in line
    assert f"findings={_document_findings_total(document)}" in line


def _plain_latest_run_line(snapshot: SessionSnapshot) -> str:
    """The latest-run line the plain renderer prints for one snapshot."""

    printer = _RecordingPrinter()
    exit_code = session_stats_mod._render_verbose(cast(PrinterLike, printer), snapshot)
    assert exit_code == int(ExitCode.SUCCESS)
    return _latest_run_line(printer.text)


def test_latest_run_line_renders_novelty_tristate() -> None:
    """A tristate audit row reaches the user as three labelled counters."""

    line = _plain_latest_run_line(
        replace(
            _snapshot(
                latest_run_id="run1234567890",
                latest_run_health=90,
                latest_run_findings=141,
                latest_run_age_seconds=12,
            ),
            latest_run_findings_new=0,
            latest_run_findings_known=115,
            latest_run_findings_unavailable=26,
        )
    )
    assert "findings=141" in line
    assert "new=0" in line
    assert "known=115" in line
    assert "unavailable=26" in line


def test_latest_run_line_words_unknown_novelty_never_zero() -> None:
    """A row without novelty counters renders the word, not a zero.

    A zero here would assert a comparison the row never recorded -- the
    trail cannot be recomputed, so absence must stay legible as absence.
    """

    line = _plain_latest_run_line(
        _snapshot(
            latest_run_id="run1234567890",
            latest_run_health=90,
            latest_run_findings=26,
            latest_run_age_seconds=12,
        )
    )
    assert "findings=26" in line
    assert ui.SESSION_STATS_NOVELTY_UNKNOWN in line
    assert "new=0" not in line
    assert "known=0" not in line
    assert "unavailable=0" not in line


def test_latest_run_line_words_partial_novelty_unknown() -> None:
    """A legacy row (total+new only) words the two missing counters.

    ``new=0`` beside a worded unknown is exactly the honest reading: the row
    counted zero regressions but never said whether a comparison ran.
    """

    line = _plain_latest_run_line(
        replace(
            _snapshot(
                latest_run_id="run1234567890",
                latest_run_health=90,
                latest_run_findings=11,
                latest_run_age_seconds=12,
            ),
            latest_run_findings_new=0,
        )
    )
    assert "new=0" in line
    assert f"known={ui.SESSION_STATS_NOVELTY_VALUE_UNKNOWN}" in line
    assert f"unavailable={ui.SESSION_STATS_NOVELTY_VALUE_UNKNOWN}" in line
    assert "known=0" not in line
    assert "unavailable=0" not in line


def test_rich_latest_run_shows_novelty_tristate() -> None:
    """The rich cockpit and the plain one print the same tristate facts."""

    text = _render_rich_snapshot(
        replace(
            _snapshot(
                latest_run_id="run1234567890",
                latest_run_health=90,
                latest_run_findings=141,
                latest_run_age_seconds=12,
            ),
            latest_run_findings_new=0,
            latest_run_findings_known=115,
            latest_run_findings_unavailable=26,
        )
    )
    assert "findings=141" in text
    assert "new=0" in text
    assert "known=115" in text
    assert "unavailable=26" in text


def test_session_snapshot_payload_carries_novelty_tristate() -> None:
    """The machine payload carries the counters, null meaning unknown."""

    payload = insights_mod.session_snapshot_to_payload(
        replace(
            _snapshot(
                latest_run_id="run1234567890",
                latest_run_findings=141,
            ),
            latest_run_findings_new=0,
            latest_run_findings_known=115,
            latest_run_findings_unavailable=26,
        )
    )
    latest_run = cast(Mapping[str, object], payload["latest_run"])
    assert latest_run["findings_new"] == 0
    assert latest_run["findings_known"] == 115
    assert latest_run["findings_unavailable"] == 26

    unknown_payload = insights_mod.session_snapshot_to_payload(
        _snapshot(latest_run_id="run1234567890", latest_run_findings=26)
    )
    unknown_latest = cast(Mapping[str, object], unknown_payload["latest_run"])
    assert unknown_latest["findings_new"] is None
    assert unknown_latest["findings_known"] is None
    assert unknown_latest["findings_unavailable"] is None


def test_session_stats_verbose_uses_rich_table(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".codeclone" / "intents"
    intents_dir.mkdir(parents=True)
    _write_intent_file(
        intents_dir,
        pid=os.getpid(),
        start_epoch=int(time.time()),
        allowed_files=["src/a.py"],
    )
    text = _render_rich_session_stats(tmp_path, width=100)
    assert "Session Stats" in text
    assert "Workspace intent records" in text
    assert "src/a.py" in text


def test_session_stats_verbose_with_report_without_file_count(
    tmp_path: Path,
) -> None:
    """A report that lost its file registry still renders, without a count.

    Built by removing that one block from a real document rather than by
    writing a thin payload around it: report-v3 always emits
    ``inventory.file_registry``, so this branch is unreachable from a complete
    document and the fixture has to say out loud which block it took away.
    """

    document = _corrupted_report()
    inventory = cast("dict[str, object]", document["inventory"])
    del inventory["file_registry"]
    _write_report_payload(tmp_path, document)

    text = _render_session_stats_text(tmp_path, quiet=False)

    assert _document_run_id(document) in text
    assert f"findings={_document_findings_total(document)}" in text
    assert "Cache:" not in text


def test_session_stats_verbose_truncates_allowed_files(tmp_path: Path) -> None:
    intents_dir = tmp_path / ".codeclone" / "intents"
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
    assert "and 5 more" in printer.text


def test_session_stats_verbose_handles_empty_allowed_files(tmp_path: Path) -> None:
    printer = _RecordingPrinter()
    snapshot = SessionSnapshot(
        root=tmp_path,
        agents=(
            AgentSnapshot(
                pid=123,
                start_epoch=int(time.time()),
                label="agent",
                alive=True,
                intents=(
                    IntentSnapshot(
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
        latest_run_source=None,
        cache_present=False,
        workspace_health="active",
        intent_registry_backend="file",
        intent_registry_storage=".codeclone/intents",
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
    intents_dir = tmp_path / ".codeclone" / "intents"
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
    report_dir = tmp_path / ".codeclone"
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
        "collect_session_snapshot",
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
    monkeypatch.setattr(insights_mod, "_process_start_epoch", lambda: 100)
    snapshot = collect_session_snapshot(tmp_path)
    assert len(snapshot.agents) == 1
    assert snapshot.agents[0].intents[0].allowed_files == ()


def test_session_stats_counts_expired_stale_and_recoverable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intents_dir = tmp_path / ".codeclone" / "intents"
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

    monkeypatch.setattr(insights_mod, "_process_start_epoch", lambda: own_start_epoch)
    monkeypatch.setattr(
        insights_mod,
        "_is_pid_alive",
        lambda pid: pid == os.getpid(),
    )
    # ``recoverable_count`` is decided by classify_intent_ownership, which reads
    # the mcp seam -- not the insights one patched above. Without this the count
    # is a function of whether pid 999999 happens to exist on this machine.
    monkeypatch.setattr(
        "codeclone.surfaces.mcp._workspace_intent_pid.is_agent_pid_alive",
        lambda pid: pid == os.getpid(),
    )

    snapshot = collect_session_snapshot(tmp_path)

    assert snapshot.stale_count == 1
    assert snapshot.recoverable_count == 1
    assert snapshot.expired_count == 1


def test_session_stats_groups_multiple_intents_per_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intents_dir = tmp_path / ".codeclone" / "intents"
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

    monkeypatch.setattr(insights_mod, "_process_start_epoch", lambda: start_epoch)
    snapshot = collect_session_snapshot(tmp_path)

    assert len(snapshot.agents) == 1
    assert len(snapshot.agents[0].intents) == 2


# ── Data collection helpers ──


def test_read_disk_report_missing(tmp_path: Path) -> None:
    run_id, _health, _findings, _files, _age, present = _read_disk_report(tmp_path)
    assert run_id is None
    assert not present


def test_read_disk_report_valid(tmp_path: Path) -> None:
    document = _write_report(tmp_path, files=50)
    run_id, health, findings, files, age, present = _read_disk_report(tmp_path)
    assert run_id == _document_run_id(document)
    assert health == _document_health(document)
    assert findings == _document_findings_total(document)
    assert files == _document_file_count(document)
    assert present is True
    assert age is not None and age >= 0


def test_disk_report_run_id_is_the_evaluation_digest(tmp_path: Path) -> None:
    """The run is named by the tier the CLI's identity owner names it by.

    The tier is never spelled in this test: the expectation comes back
    through ``report_run_identity``. The neighbouring ``comparison`` tier is
    asserted to differ first, so a reader answering from the neighbour -- or
    from the withdrawn ``integrity.digest`` block, which yields no id at all
    -- cannot pass here by coincidence.
    """

    document = _write_report(tmp_path, files=4)
    expected = _document_run_id(document)
    assert expected != _document_digest_prefix(document, "comparison")

    run_id, _health, _findings, _files, _age, present = _read_disk_report(tmp_path)

    assert present is True
    assert run_id == expected


def test_disk_report_health_is_the_documents_metrics_summary(tmp_path: Path) -> None:
    """Health comes from the metrics summary the document publishes.

    The population is deliberately partial so the score is not the 100 that a
    defect-free fixture prints from every dimension: a pin resting on 100
    cannot tell the health summary apart from any other perfect number in the
    document.
    """

    document = _write_report(tmp_path, files=10, analyzed=5)
    expected = _document_health(document)
    assert expected != 100

    _run_id, health, _findings, _files, _age, present = _read_disk_report(tmp_path)

    assert present is True
    assert health == expected


def test_disk_report_findings_total_is_the_documents_summary(tmp_path: Path) -> None:
    """The finding count comes from the findings summary, and is not absence.

    The document carries a real finding, so "read the wrong address" answers
    ``None`` while "read the right one" answers a number -- a distinction a
    zero-finding fixture cannot make.
    """

    document = _write_report(tmp_path, files=4)
    expected = _document_findings_total(document)
    assert expected > 0

    _run_id, _health, findings, _files, _age, present = _read_disk_report(tmp_path)

    assert present is True
    assert findings == expected


def test_read_disk_report_non_object_payload(tmp_path: Path) -> None:
    _write_report_payload(tmp_path, [])

    run_id, _health, _findings, _files, age, present = _read_disk_report(tmp_path)

    assert (run_id, _health, _findings, _files) == (None, None, None, None)
    assert age is not None
    assert present is True


def _corrupted_report(**replacements: object) -> dict[str, object]:
    """A real document with named addresses replaced by the wrong type.

    Corrupting the document the product emits is what keeps these probes
    honest. Hand-writing a malformed payload lets it name addresses the report
    never carries -- which is how they came to malform ``integrity.digest``,
    a key no document has -- and a reader that skips such a payload proves
    nothing about the payload it will actually be handed.
    """

    document = build_test_report_document(
        func_groups=_ONE_CLONE_GROUP,
        block_groups={},
        segment_groups={},
        meta={"report_generated_at_utc": _REPORT_GENERATED_AT},
        inventory={"file_list": ["a.py"]},
        metrics={"health": health_family_for_population(found=1, analyzed=1)},
    )
    for dotted, value in replacements.items():
        *parents, leaf = dotted.split("__")
        current: object = document
        for key in parents:
            current = cast("Mapping[str, object]", current)[key]
        assert leaf in cast("Mapping[str, object]", current), dotted
        cast("dict[str, object]", current)[leaf] = value
    return document


def test_read_disk_report_nested_type_mismatches(tmp_path: Path) -> None:
    _write_report_payload(
        tmp_path,
        _corrupted_report(
            integrity__digests=[],
            inventory__file_registry=[],
            metrics__summary=[],
            findings__summary=[],
        ),
    )

    run_id, _health, _findings, _files, age, present = _read_disk_report(tmp_path)

    assert (run_id, _health, _findings, _files) == (None, None, None, None)
    assert age is not None
    assert present is True


def test_read_disk_report_leaf_type_mismatches(tmp_path: Path) -> None:
    _write_report_payload(
        tmp_path,
        _corrupted_report(
            integrity__digests__evaluation__value=123,
            inventory__file_registry__items="bad",
            metrics__summary__health=[],
            findings__summary__total="bad",
        ),
    )

    run_id, _health, _findings, _files, age, present = _read_disk_report(tmp_path)

    assert (run_id, _health, _findings, _files) == (None, None, None, None)
    assert age is not None
    assert present is True


def test_read_disk_report_stat_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _write_report(tmp_path, generated_at=None)

    def raise_stat_error(self: Path) -> object:
        raise OSError("stat failed")

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "stat", raise_stat_error)

    run_id, _health, _findings, _files, age, present = _read_disk_report(tmp_path)

    assert run_id == _document_run_id(document)
    assert age is None
    assert present is True


# ── Workspace health classification ──


def test_classify_idle_no_agents() -> None:
    assert (
        _classify_workspace_health(agents=[], stale_count=0, expired_count=0) == "idle"
    )


def test_classify_clean_no_active_intents() -> None:
    agent = AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(
            IntentSnapshot(
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
    agent = AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(
            IntentSnapshot(
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
    intent_a = IntentSnapshot(
        intent_id="ia",
        status="active",
        ownership="own_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    intent_b = IntentSnapshot(
        intent_id="ib",
        status="active",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agent_a = AgentSnapshot(
        pid=1, start_epoch=1, label="a", alive=True, intents=(intent_a,)
    )
    agent_b = AgentSnapshot(
        pid=2, start_epoch=2, label="b", alive=True, intents=(intent_b,)
    )
    result = _classify_workspace_health(
        agents=[agent_a, agent_b], stale_count=0, expired_count=0
    )
    assert result == "contested"


def test_classify_active_non_overlapping_agents() -> None:
    intent_a = IntentSnapshot(
        intent_id="ia",
        status="active",
        ownership="own_active",
        scope_file_count=1,
        allowed_files=("a.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    intent_b = IntentSnapshot(
        intent_id="ib",
        status="active",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("b.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agent_a = AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(intent_a,),
    )
    agent_b = AgentSnapshot(
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
    inactive = IntentSnapshot(
        intent_id="ia",
        status="clean",
        ownership="own_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    empty_active = IntentSnapshot(
        intent_id="ib",
        status="active",
        ownership="foreign_active",
        scope_file_count=0,
        allowed_files=(),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agent_a = AgentSnapshot(
        pid=1,
        start_epoch=1,
        label="a",
        alive=True,
        intents=(inactive,),
    )
    agent_b = AgentSnapshot(
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
        top_workflows=(_workflow_snapshot(),),
    )

    exit_code = session_stats_mod._render_verbose(printer, snapshot)

    assert exit_code == int(ExitCode.SUCCESS)
    assert "Retention payload footprint" in printer.text
    assert "5,000" in printer.text
    assert "o200k_base" in printer.text
    assert "Top payload workflows" in printer.text
    assert "intent:intent-test-001" in printer.text


# ── Rich verbose with cached report + file count ──


def test_session_stats_rich_with_cached_report_and_files(tmp_path: Path) -> None:
    """Exercise Rich path with latest_run_files (lines 298-301)."""
    document = _write_report(tmp_path, files=100)
    text = _render_rich_session_stats(tmp_path)
    assert "report.json present" in text
    assert f"{_document_file_count(document)} files" in text


# ── Rich verbose with token footprint ──


def test_session_stats_rich_with_token_footprint() -> None:
    """Exercise Rich path with mcp_token_footprint (lines 312-313)."""
    snapshot = _snapshot(
        mcp_token_footprint=3000,
        mcp_token_encoding="o200k_base",
        mcp_token_event_count=7,
        top_workflows=(_workflow_snapshot(tokens=3000),),
    )

    text = _render_rich_snapshot(snapshot)
    assert "Retention payload footprint" in text
    assert "3,000" in text
    assert "Top payload workflows" in text
    assert "intent-test-001" in text


# ── Rich verbose with no live agents ──


def test_session_stats_rich_no_live_agents() -> None:
    """Exercise Rich path with dead agent only (lines 329-330)."""
    snapshot = _snapshot(
        agents=(
            AgentSnapshot(
                pid=999999,
                start_epoch=int(time.time()),
                label="dead-agent",
                alive=False,
                intents=(),
            ),
        ),
    )

    text = _render_rich_snapshot(snapshot)
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
    assert "and 5 more" in result


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
        audit_path=".codeclone/db/audit.sqlite3",
    )
    enabled, storage = _read_audit_config(tmp_path)
    assert enabled is True
    assert storage == ".codeclone/db/audit.sqlite3"


def test_read_audit_config_config_validation_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.config.pyproject_loader import ConfigValidationError

    monkeypatch.setattr(
        "codeclone.config.pyproject_loader.load_pyproject_config",
        lambda _root: (_ for _ in ()).throw(ConfigValidationError("bad")),
    )
    enabled, storage = _read_audit_config(tmp_path)
    assert enabled is False
    assert storage is None


def test_read_audit_config_disabled(tmp_path: Path) -> None:
    enabled, storage = _read_audit_config(tmp_path)
    assert enabled is False
    assert storage is None


def test_read_audit_config_enabled_with_absolute_path(tmp_path: Path) -> None:
    _write_audit_pyproject(tmp_path, audit_path="/tmp/audit.sqlite3")
    enabled, storage = _read_audit_config(tmp_path)
    assert enabled is True
    assert storage is None


def test_read_audit_config_storage_falls_back_when_not_relative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = Path("/tmp/codeclone-audit-outside.sqlite3")
    _write_audit_pyproject(tmp_path, audit_path=".codeclone/db/audit.sqlite3")
    monkeypatch.setattr(
        "codeclone.audit.validation.resolve_audit_path",
        lambda **_: outside,
    )
    enabled, storage = _read_audit_config(tmp_path)
    assert enabled is True
    assert storage == str(outside)


def test_has_scope_overlap_ignores_non_active_intents() -> None:
    queued = IntentSnapshot(
        intent_id="queued",
        status="queued",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("shared.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    active = IntentSnapshot(
        intent_id="active",
        status="active",
        ownership="foreign_active",
        scope_file_count=1,
        allowed_files=("other.py",),
        declared_at_utc="",
        lease_remaining_seconds=60,
    )
    agents = (
        AgentSnapshot(pid=1, start_epoch=1, label="a", alive=True, intents=(queued,)),
        AgentSnapshot(pid=2, start_epoch=2, label="b", alive=True, intents=(active,)),
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
    tokens, encoding, count, workflows = _read_audit_token_footprint(tmp_path)
    assert tokens is None
    assert encoding is None
    assert count == 0
    assert workflows == ()


def test_read_audit_token_footprint_when_db_missing(tmp_path: Path) -> None:
    _write_audit_pyproject(tmp_path)
    tokens, encoding, count, workflows = _read_audit_token_footprint(tmp_path)
    assert tokens is None
    assert encoding is None
    assert count == 0
    assert workflows == ()


def test_resolve_mcp_tokens_with_audit_data(tmp_path: Path) -> None:
    """Exercise _resolve_mcp_tokens with existing audit DB (lines 585-592)."""
    from codeclone.audit.events import (
        EVENT_PATCH_VERIFIED,
        AuditEvent,
        repo_root_digest,
    )
    from codeclone.audit.writer import SqliteAuditWriter

    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
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
                intent_id="intent-run123-001",
                status="accepted",
                payload={"data": "value"},
            )
        )
    finally:
        writer.close()

    tokens, encoding, count, workflows = _read_audit_token_footprint(tmp_path)

    assert tokens is not None
    assert tokens > 0
    assert encoding is not None
    assert count == 1
    assert workflows
    assert workflows[0].workflow_kind == "intent"
    assert workflows[0].workflow_id == "intent-run123-001"


def test_resolve_mcp_tokens_no_db(tmp_path: Path) -> None:
    """_read_audit_token_footprint returns (None, None, 0) when no DB exists."""
    tokens, encoding, count, workflows = _read_audit_token_footprint(tmp_path)

    assert tokens is None
    assert encoding is None
    assert count == 0
    assert workflows == ()


def test_resolve_mcp_tokens_corrupt_db(tmp_path: Path) -> None:
    """_read_audit_token_footprint tolerates corrupt audit storage."""
    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True)
    db_path.write_text("NOT A DATABASE")

    tokens, encoding, count, workflows = _read_audit_token_footprint(tmp_path)

    assert tokens is None
    assert encoding is None
    assert count == 0
    assert workflows == ()


def test_read_audit_token_footprint_uses_summary_totals_without_footprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.audit.reader import AuditSummary

    _write_audit_pyproject(tmp_path)
    db_path = tmp_path / ".codeclone" / "db" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(b"")
    fake_summary = AuditSummary(
        db_path=db_path,
        db_size_bytes=0,
        retention_days=30,
        total_events=1,
        intent_events=0,
        contract_events=0,
        receipt_events=0,
        violation_events=0,
        oldest_event_utc=None,
        latest_event_utc=None,
        events=(),
        total_estimated_tokens=42,
        token_encoding="chars_approx",
        token_event_count=3,
        payload_footprint=None,
    )
    monkeypatch.setattr(
        "codeclone.audit.reader.read_audit_summary",
        lambda **kwargs: fake_summary,
    )
    tokens, encoding, count, workflows = _read_audit_token_footprint(tmp_path)
    assert tokens == 42
    assert encoding == "chars_approx"
    assert count == 3
    assert workflows == ()


def test_collect_session_snapshot_prefers_audit_latest_run(tmp_path: Path) -> None:
    _write_audit_analysis_row(tmp_path, findings={"total": 2, "new": 0})
    document = _write_report(tmp_path, files=99)

    # The audit row only proves it wins while the report on disk would have
    # answered differently. Asserted, not assumed: a document that happened to
    # agree would make the preference invisible.
    assert _document_health(document) != 93
    assert _document_findings_total(document) != 2
    assert _document_file_count(document) != 11

    _assert_snapshot_latest_run_from_audit(
        collect_session_snapshot(tmp_path),
        run_id="runaudit",
        health=93,
        findings=2,
        files=11,
    )


def test_collect_session_snapshot_transports_novelty_tristate(
    tmp_path: Path,
) -> None:
    """The counters survive the whole path from the trail row to the snapshot.

    The reader tests prove the reader; this pin proves the plumbing between
    the reader and the cockpit does not drop the two new counters the way the
    audit row itself used to.
    """

    _write_audit_analysis_row(
        tmp_path,
        findings={"total": 26, "new": 0, "known": 0, "unavailable": 26},
    )

    snapshot = collect_session_snapshot(tmp_path)
    assert snapshot.latest_run_findings == 26
    assert snapshot.latest_run_findings_new == 0
    assert snapshot.latest_run_findings_known == 0
    assert snapshot.latest_run_findings_unavailable == 26


def test_legacy_audit_row_renders_worded_unknown_end_to_end(
    tmp_path: Path,
) -> None:
    """A legacy trail row reaches the screen with words, not invented zeros.

    The snapshot-level pins feed the renderer directly; this one walks the
    whole path -- stored legacy row, reader, plumbing, renderer -- so a
    coercion anywhere along it is caught at the line the user reads.
    """

    # The writer of this build stores the tristate, so a legacy row -- one
    # written before the counters existed -- is made by dropping them from
    # the stored payload, exactly what backfill-less history holds.
    db_path = _write_audit_analysis_row(
        tmp_path,
        findings={"total": 26, "new": 0},
        run_id="runlegacy12345678",
    )
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(db_path)
    try:
        stored = conn.execute(
            "SELECT payload_json FROM controller_events LIMIT 1"
        ).fetchone()
        payload = json.loads(str(stored[0]))
        payload.pop("findings_known")
        payload.pop("findings_unavailable")
        conn.execute(
            "UPDATE controller_events SET payload_json = ?",
            (json.dumps(payload),),
        )
        conn.commit()
    finally:
        conn.close()

    line = _latest_run_line(_render_session_stats_text(tmp_path, quiet=False))
    assert "findings=26" in line
    assert "new=0" in line
    assert f"known={ui.SESSION_STATS_NOVELTY_VALUE_UNKNOWN}" in line
    assert f"unavailable={ui.SESSION_STATS_NOVELTY_VALUE_UNKNOWN}" in line
    assert "known=0" not in line
    assert "unavailable=0" not in line


def test_the_disk_report_answers_only_where_the_audit_trail_cannot(
    tmp_path: Path,
) -> None:
    """One document, two configurations: a fallback that stayed a fallback.

    Reaching the disk report is a repair on one side of a precedence rule, and
    a repair like that can quietly install a second authority: hoist the disk
    read above the audit read, or let it answer when the audit row already
    has, and the surface starts naming runs by whichever source happens to
    exist rather than by the ratified order. One pin on the fixed side cannot
    see that -- it passes either way.

    So both cells are asserted over the same document, and the two candidate
    answers are asserted to differ first. Whichever id comes out therefore
    names the source that spoke, and neither cell can pass by the two sources
    agreeing.
    """

    from codeclone.audit.analysis_completed import ANALYSIS_SOURCE_MCP

    from .audit_fixtures import write_compact_analysis_completed_event

    without_audit = tmp_path / "default_install"
    with_audit = tmp_path / "audit_enabled"
    without_audit.mkdir()
    with_audit.mkdir()

    disk_only = _write_report(without_audit, files=6)
    also_on_disk = _write_report(with_audit, files=6)
    # The two roots hold the same report; only the configuration differs.
    assert _document_run_id(disk_only) == _document_run_id(also_on_disk)

    _write_audit_pyproject(with_audit)
    write_compact_analysis_completed_event(
        with_audit,
        db_path=with_audit / ".codeclone/db/audit.sqlite3",
        summary={
            "mode": "full",
            "health": {"score": 93, "grade": "A"},
            "findings": {"total": 2, "new": 0},
            "inventory": {"files": 11, "lines": 1, "functions": 1},
            "diff": {"new_clones": 0, "health_delta": None},
        },
        source=ANALYSIS_SOURCE_MCP,
        report_digest="a" * 64,
        run_id="runaudit1234567890",
        agent_pid=1,
        agent_start_epoch=1,
        agent_label="mcp/test",
    )
    assert _document_run_id(also_on_disk) != "runaudit"

    assert _read_audit_config(without_audit) == (False, None)
    no_trail = collect_session_snapshot(without_audit)
    assert no_trail.latest_run_source == "disk_report"
    assert no_trail.latest_run_id == _document_run_id(disk_only)

    assert _read_audit_config(with_audit)[0] is True
    trail = collect_session_snapshot(with_audit)
    assert trail.latest_run_source == "audit_mcp"
    assert trail.latest_run_id == "runaudit"
    assert trail.latest_run_id != _document_run_id(also_on_disk)


def test_collect_session_snapshot_tolerates_audit_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_audit_pyproject(tmp_path)
    _write_report(tmp_path, files=3)

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("audit read failed")

    monkeypatch.setattr(
        "codeclone.audit.reader.read_latest_analysis_run",
        _boom,
    )
    snapshot = collect_session_snapshot(tmp_path)
    assert snapshot.latest_run_source == "disk_report"


def test_latest_run_text_without_health_or_findings() -> None:
    snapshot = _snapshot(
        latest_run_id="def67890",
        latest_run_age_seconds=60,
    )
    result = session_stats_mod._latest_run_text(snapshot)
    assert "def67890" in result
    assert "health=" not in result
    assert "findings=" not in result


def test_plain_top_workflows_prints_nothing_when_empty() -> None:
    from codeclone.surfaces.cli.console import PlainConsole

    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=100)
    session_stats_mod._render_plain_top_workflows(
        cast("PrinterLike", PlainConsole()), ()
    )
    session_stats_mod._render_rich_top_workflows(cast("PrinterLike", console), ())
    assert output.getvalue() == ""


def test_verbose_rich_omits_cache_row_without_cache() -> None:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=120)
    snapshot = _snapshot(
        latest_run_id="ghi13579",
        latest_run_age_seconds=30,
        latest_run_files=10,
        cache_present=False,
        workspace_health="clean",
    )
    exit_code = session_stats_mod._render_verbose_rich(
        cast("PrinterLike", console), snapshot
    )
    assert exit_code == 0
    assert "ghi13579" in output.getvalue()
