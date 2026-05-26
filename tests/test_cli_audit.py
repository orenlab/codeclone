from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import pytest
from rich.console import Console

from codeclone.audit.events import EVENT_PATCH_VERIFIED, AuditEvent, repo_root_digest
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.audit import render_audit
from codeclone.surfaces.cli.types import PrinterLike


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _write_audit_event(root: Path) -> None:
    writer = SqliteAuditWriter(
        db_path=root / ".cache" / "codeclone" / "audit.sqlite3",
        payloads="compact",
        retention_days=30,
    )
    try:
        writer.emit(
            AuditEvent(
                event_type=EVENT_PATCH_VERIFIED,
                severity="info",
                repo_root_digest=repo_root_digest(root),
                agent_pid=123,
                agent_label="test-agent",
                run_id="abcdef123456",
                intent_id="intent-abcdef12-001",
                report_digest="a" * 64,
                status="accepted",
                payload={
                    "status": "accepted",
                    "structural_delta": {
                        "regressions": [],
                        "improvements": [],
                        "health_delta": 0,
                    },
                    "contract_violations": [],
                    "baseline_abuse": {"detected": False},
                },
            )
        )
    finally:
        writer.close()


@pytest.mark.parametrize(
    ("audit_enabled", "expected_message"),
    [
        (False, "audit is not enabled"),
        (True, "no audit data"),
    ],
)
def test_audit_contract_errors(
    tmp_path: Path,
    *,
    audit_enabled: bool,
    expected_message: str,
) -> None:
    printer = _RecordingPrinter()

    exit_code = render_audit(
        console=printer,
        root_path=tmp_path,
        audit_enabled=audit_enabled,
        audit_path=".cache/codeclone/audit.sqlite3",
        quiet=True,
    )

    assert exit_code == int(ExitCode.CONTRACT_ERROR)
    assert expected_message in printer.text


def test_audit_quiet_with_events(tmp_path: Path) -> None:
    _write_audit_event(tmp_path)
    printer = _RecordingPrinter()

    exit_code = render_audit(
        console=printer,
        root_path=tmp_path,
        audit_enabled=True,
        audit_path=".cache/codeclone/audit.sqlite3",
        quiet=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "audit: 1 events" in printer.text
    assert "contracts=1" in printer.text


def test_audit_verbose_renders_plain_table(tmp_path: Path) -> None:
    _write_audit_event(tmp_path)
    printer = _RecordingPrinter()

    exit_code = render_audit(
        console=printer,
        root_path=tmp_path,
        audit_enabled=True,
        audit_path=".cache/codeclone/audit.sqlite3",
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    assert "Controller Audit Trail" in printer.text
    assert "intent-abcdef12-001" in printer.text
    assert "accepted" in printer.text


def test_audit_verbose_uses_rich_table(tmp_path: Path) -> None:
    _write_audit_event(tmp_path)
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=160)

    exit_code = render_audit(
        console=cast(PrinterLike, console),
        root_path=tmp_path,
        audit_enabled=True,
        audit_path=".cache/codeclone/audit.sqlite3",
        quiet=False,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    text = output.getvalue()
    assert "Controller Audit Trail" in text
    assert "Workspace" not in text
    assert "verify" in text
    assert "accepted" in text
