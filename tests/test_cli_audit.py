from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from rich.console import Console

from codeclone.audit.events import (
    EVENT_BLAST_RADIUS,
    EVENT_INTENT_DECLARED,
    EVENT_PATCH_BUDGET,
    EVENT_PATCH_VERIFIED,
    AuditEvent,
    repo_root_digest,
)

if TYPE_CHECKING:
    from codeclone.audit.events import AuditSeverity
from codeclone.audit.reader import (
    PayloadFootprint,
    TopPayload,
    TypeTokenProfile,
    payload_footprint_to_dict,
    read_audit_summary,
)
from codeclone.audit.writer import SqliteAuditWriter
from codeclone.contracts import ExitCode
from codeclone.surfaces.cli.audit import render_audit
from codeclone.surfaces.cli.types import CLIArgsLike, PrinterLike


class _RecordingPrinter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.lines.append(" ".join(str(item) for item in objects))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _write_audit_event(
    root: Path,
    *,
    event_type: str = EVENT_PATCH_VERIFIED,
    severity: AuditSeverity = "info",
    agent_label: str = "test-agent",
    run_id: str = "abcdef123456",
    intent_id: str = "intent-abcdef12-001",
    status: str = "accepted",
) -> None:
    writer = SqliteAuditWriter(
        db_path=root / ".cache" / "codeclone" / "audit.sqlite3",
        payloads="compact",
        retention_days=30,
    )
    try:
        writer.emit(
            AuditEvent(
                event_type=event_type,
                severity=severity,
                repo_root_digest=repo_root_digest(root),
                agent_pid=123,
                agent_label=agent_label,
                run_id=run_id,
                intent_id=intent_id,
                report_digest="a" * 64,
                status=status,
                payload={
                    "status": status,
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


def _write_multiple_events(root: Path) -> None:
    """Write events of different types to exercise by-type breakdown."""
    events: list[tuple[str, AuditSeverity, str]] = [
        (EVENT_PATCH_VERIFIED, "info", "accepted"),
        (EVENT_PATCH_BUDGET, "info", "ok"),
        (EVENT_INTENT_DECLARED, "info", "active"),
        (EVENT_BLAST_RADIUS, "info", "computed"),
    ]
    writer = SqliteAuditWriter(
        db_path=root / ".cache" / "codeclone" / "audit.sqlite3",
        payloads="compact",
        retention_days=30,
    )
    try:
        for event_type, severity, status in events:
            writer.emit(
                AuditEvent(
                    event_type=event_type,
                    severity=severity,
                    repo_root_digest=repo_root_digest(root),
                    agent_pid=123,
                    agent_label="claude-code/opus-4",
                    run_id="abcdef123456",
                    intent_id="intent-abcdef12-001",
                    report_digest="a" * 64,
                    status=status,
                    payload={
                        "status": status,
                        "data": "x" * 200,  # ensure non-trivial token count
                    },
                )
            )
    finally:
        writer.close()


def _payload_footprint(
    *,
    event_type: str,
    tool_calls: int,
    total_tokens: int,
    avg_tokens: int,
    p95_tokens: int,
    max_tokens: int,
    top_payload_tokens: int | None,
) -> PayloadFootprint:
    top_payloads = (
        ()
        if top_payload_tokens is None
        else (
            TopPayload(
                event_type=event_type,
                event_id="evt_test_1",
                estimated_tokens=top_payload_tokens,
                created_at_utc="2026-05-26T10:00:00Z",
            ),
        )
    )
    return PayloadFootprint(
        encoding="o200k_base",
        tool_calls=tool_calls,
        total_tokens=total_tokens,
        avg_tokens=avg_tokens,
        p95_tokens=p95_tokens,
        max_tokens=max_tokens,
        by_type=(
            TypeTokenProfile(
                event_type=event_type,
                call_count=tool_calls,
                total_tokens=total_tokens,
                max_tokens=max_tokens,
            ),
        ),
        top_payloads=top_payloads,
    )


def _render_payload_analytics_text(fp: PayloadFootprint) -> str:
    from codeclone.surfaces.cli.audit import _render_payload_analytics

    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=160)
    _render_payload_analytics(console=cast(PrinterLike, console), fp=fp)
    return output.getvalue()


# ── Contract error paths ──


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


def test_audit_internal_error_on_unexpected_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the except Exception branch (lines 42-44)."""
    from codeclone.surfaces.cli import audit as audit_mod

    def _boom(*, root_path: Path, value: str) -> Path:
        msg = "simulated crash"
        raise RuntimeError(msg)

    monkeypatch.setattr(audit_mod, "resolve_audit_path", _boom)
    printer = _RecordingPrinter()

    exit_code = render_audit(
        console=printer,
        root_path=tmp_path,
        audit_enabled=True,
        audit_path="whatever",
        quiet=True,
    )

    assert exit_code == int(ExitCode.INTERNAL_ERROR)


# ── Quiet mode ──


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


# ── Plain (non-Rich) verbose ──


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


# ── Rich verbose ──


def test_audit_verbose_uses_rich_table(tmp_path: Path) -> None:
    _write_audit_event(tmp_path)
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, color_system=None, width=240)

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
    assert "accept" in text


def test_audit_rich_with_payload_footprint(tmp_path: Path) -> None:
    """Rich path with multiple events exercises payload analytics panel."""
    _write_multiple_events(tmp_path)
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
    assert "MCP Payload Footprint" in text
    assert "Tokens by Type" in text
    assert "Top Payloads" in text


@pytest.mark.parametrize(
    ("total_tokens", "tool_calls", "avg_tokens", "p95_tokens", "max_tokens", "label"),
    [
        (8000, 10, 800, 1200, 1400, "watch"),
        (20000, 20, 1000, 1800, 2000, "heavy"),
    ],
)
def test_audit_rich_payload_budget_warnings(
    total_tokens: int,
    tool_calls: int,
    avg_tokens: int,
    p95_tokens: int,
    max_tokens: int,
    label: str,
) -> None:
    """Trigger workflow-level payload budget warnings."""
    fp = _payload_footprint(
        event_type="patch_contract.verified",
        tool_calls=tool_calls,
        total_tokens=total_tokens,
        avg_tokens=avg_tokens,
        p95_tokens=p95_tokens,
        max_tokens=max_tokens,
        top_payload_tokens=max_tokens,
    )
    text = _render_payload_analytics_text(fp)
    assert "Payload Budget Warnings" in text
    assert label in text


@pytest.mark.parametrize(
    (
        "tool_calls",
        "total_tokens",
        "avg_tokens",
        "p95_tokens",
        "max_tokens",
        "top_payload_tokens",
        "shows_top_payloads",
    ),
    [
        (3, 900, 300, 400, 450, 450, True),
        (1, 100, 100, 100, 100, None, False),
    ],
)
def test_audit_rich_payload_under_budget_sections(
    tool_calls: int,
    total_tokens: int,
    avg_tokens: int,
    p95_tokens: int,
    max_tokens: int,
    top_payload_tokens: int | None,
    *,
    shows_top_payloads: bool,
) -> None:
    """Under-budget payload analytics render optional sections correctly."""
    fp = _payload_footprint(
        event_type="intent.declared",
        tool_calls=tool_calls,
        total_tokens=total_tokens,
        avg_tokens=avg_tokens,
        p95_tokens=p95_tokens,
        max_tokens=max_tokens,
        top_payload_tokens=top_payload_tokens,
    )
    text = _render_payload_analytics_text(fp)
    assert "Payload Budget Warnings" not in text
    if shows_top_payloads:
        assert "Top Payloads" in text
    else:
        assert "Top Payloads" not in text
    assert "MCP Payload Footprint" in text


# ── JSON summary ──


def test_audit_json_summary_with_footprint(tmp_path: Path) -> None:
    """Exercise _render_json_summary with payload footprint data."""
    _write_multiple_events(tmp_path)
    printer = _RecordingPrinter()

    exit_code = render_audit(
        console=printer,
        root_path=tmp_path,
        audit_enabled=True,
        audit_path=".cache/codeclone/audit.sqlite3",
        quiet=False,
        json_summary=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    data = json.loads(printer.text)
    assert "mcp_payload_footprint" in data
    assert data["mcp_payload_footprint"] is not None
    assert data["mcp_payload_footprint"]["tool_calls"] == 4
    assert "total_tokens" in data["mcp_payload_footprint"]
    assert "by_type" in data["mcp_payload_footprint"]
    assert "top_payloads" in data["mcp_payload_footprint"]


def test_audit_json_summary_without_footprint(tmp_path: Path) -> None:
    """JSON summary with no token data yields null footprint."""
    _write_event_without_tokens(tmp_path)
    printer = _RecordingPrinter()

    exit_code = render_audit(
        console=printer,
        root_path=tmp_path,
        audit_enabled=True,
        audit_path=".cache/codeclone/audit.sqlite3",
        quiet=False,
        json_summary=True,
    )

    assert exit_code == int(ExitCode.SUCCESS)
    data = json.loads(printer.text)
    assert data["mcp_payload_footprint"] is None
    assert data["total_events"] == 1


def _write_event_without_tokens(root: Path) -> None:
    """Insert an event row directly with NULL token columns."""
    db_path = root / ".cache" / "codeclone" / "audit.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        from codeclone.audit.schema import ensure_schema

        ensure_schema(conn)
        conn.execute(
            "INSERT INTO controller_events "
            "(event_id, event_type, severity, created_at_utc, "
            "repo_root_digest, agent_label, agent_pid, status, run_id, intent_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt_no_tokens",
                EVENT_PATCH_VERIFIED,
                "info",
                "2026-05-26T10:00:00Z",
                "digest123",
                "test-agent",
                123,
                "accepted",
                "run123",
                "intent-test-001",
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ── reader.py: payload_footprint_to_dict ──


def test_payload_footprint_to_dict_roundtrip() -> None:
    fp = PayloadFootprint(
        encoding="o200k_base",
        tool_calls=5,
        total_tokens=2500,
        avg_tokens=500,
        p95_tokens=800,
        max_tokens=1000,
        by_type=(
            TypeTokenProfile(
                event_type="intent.declared",
                call_count=3,
                total_tokens=1500,
                max_tokens=700,
            ),
            TypeTokenProfile(
                event_type="patch_contract.verified",
                call_count=2,
                total_tokens=1000,
                max_tokens=1000,
            ),
        ),
        top_payloads=(
            TopPayload(
                event_type="patch_contract.verified",
                event_id="evt_1",
                estimated_tokens=1000,
                created_at_utc="2026-05-26T10:00:00Z",
            ),
        ),
    )
    result = payload_footprint_to_dict(fp)
    assert result["encoding"] == "o200k_base"
    assert result["tool_calls"] == 5
    assert result["total_tokens"] == 2500
    assert result["p95_tokens"] == 800
    assert isinstance(result["by_type"], dict)
    assert "intent.declared" in result["by_type"]
    assert result["by_type"]["intent.declared"]["count"] == 3
    assert isinstance(result["top_payloads"], list)
    assert len(result["top_payloads"]) == 1
    assert result["top_payloads"][0]["tokens"] == 1000
    # Verify JSON-serializable
    json.dumps(result)


# ── reader.py: read_audit_summary with footprint ──


def test_read_audit_summary_includes_payload_footprint(tmp_path: Path) -> None:
    _write_multiple_events(tmp_path)
    db_path = tmp_path / ".cache" / "codeclone" / "audit.sqlite3"
    summary = read_audit_summary(db_path=db_path, limit=50)

    assert summary.payload_footprint is not None
    fp = summary.payload_footprint
    assert fp.tool_calls == 4
    assert fp.total_tokens > 0
    assert fp.avg_tokens > 0
    assert fp.max_tokens >= fp.avg_tokens
    assert fp.p95_tokens > 0
    assert len(fp.by_type) > 0
    assert len(fp.top_payloads) > 0
    assert fp.encoding != "unknown"


def test_read_audit_summary_no_tokens_yields_no_footprint(tmp_path: Path) -> None:
    _write_event_without_tokens(tmp_path)
    db_path = tmp_path / ".cache" / "codeclone" / "audit.sqlite3"
    summary = read_audit_summary(db_path=db_path, limit=50)

    # Event has NULL estimated_tokens → footprint should be None
    assert summary.payload_footprint is None
    assert summary.total_events == 1


# ── Helper functions ──


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("intent-abcdef12-001", "abcdef12-001"),
        (None, "-"),
        ("", "-"),
        ("custom-id-123", "custom-id-123"),
    ],
)
def test_short_intent(value: str | None, expected: str) -> None:
    from codeclone.surfaces.cli.audit import _short_intent

    assert _short_intent(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("claude-code/opus-4", "cc/opus-4"),
        (None, "-"),
        ("", "-"),
        ("test-agent", "test-agent"),
    ],
)
def test_short_agent(value: str | None, expected: str) -> None:
    from codeclone.surfaces.cli.audit import _short_agent

    assert _short_agent(value) == expected


@pytest.mark.parametrize(
    ("delta", "suffix"),
    [
        (timedelta(seconds=30), "s ago"),
        (timedelta(minutes=15), "m ago"),
        (timedelta(hours=5), "h ago"),
        (timedelta(days=3), "d ago"),
    ],
)
def test_relative_time_age_suffixes(delta: timedelta, suffix: str) -> None:
    from codeclone.surfaces.cli.audit import _relative_time

    ts = (datetime.now(timezone.utc) - delta).isoformat()
    assert _relative_time(ts).endswith(suffix)


@pytest.mark.parametrize("value", [None, ""])
def test_relative_time_missing_values(value: str | None) -> None:
    from codeclone.surfaces.cli.audit import _relative_time

    assert _relative_time(value) == "none"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime.now(timezone.utc).isoformat(), "today"),
        ("2025-01-15T10:30:00Z", "2025-01-15"),
        ("not-a-date", "not-a-date"),
        ("", "-"),
    ],
)
def test_short_time(value: str, expected: str) -> None:
    from codeclone.surfaces.cli.audit import _short_time

    assert expected in _short_time(value)


class TestFormatTokens:
    def test_none_returns_dash(self) -> None:
        from codeclone.surfaces.cli.audit import _format_tokens

        assert _format_tokens(None) == "—"

    def test_formats_with_commas(self) -> None:
        from codeclone.surfaces.cli.audit import _format_tokens

        assert _format_tokens(12345) == "12,345"

    def test_zero(self) -> None:
        from codeclone.surfaces.cli.audit import _format_tokens

        assert _format_tokens(0) == "0"


class TestFormatBytes:
    def test_bytes_range(self) -> None:
        from codeclone.surfaces.cli.audit import _format_bytes

        assert _format_bytes(500) == "500 B"

    def test_kib_range(self) -> None:
        from codeclone.surfaces.cli.audit import _format_bytes

        result = _format_bytes(2048)
        assert "KiB" in result

    def test_mib_range(self) -> None:
        from codeclone.surfaces.cli.audit import _format_bytes

        result = _format_bytes(2 * 1024 * 1024)
        assert "MiB" in result


class TestSeverityStyle:
    def test_known_severities(self) -> None:
        from codeclone.surfaces.cli.audit import _severity_style

        assert _severity_style("info") == "green"
        assert _severity_style("warn") == "yellow"
        assert _severity_style("error") == "bold red"

    def test_unknown_severity(self) -> None:
        from codeclone.surfaces.cli.audit import _severity_style

        assert _severity_style("debug") == "white"


# ── workflow.py: _validate_controller_query_flags ──


class TestControllerQueryFlagValidation:
    """Cover the validation branches in _validate_controller_query_flags."""

    @staticmethod
    def _validate(**attrs: object) -> None:
        from argparse import Namespace

        import codeclone.surfaces.cli.workflow as wf

        wf.console = wf._make_plain_console()
        defaults: dict[str, object] = {
            "blast_radius": None,
            "patch_verify": False,
            "session_stats": False,
            "audit": False,
            "audit_json": False,
            "strictness": "ci",
            "update_baseline": False,
            "update_metrics_baseline": False,
            "changed_only": False,
            "diff_against": None,
            "paths_from_git_diff": None,
        }
        defaults.update(attrs)
        args = Namespace(**defaults)
        wf._validate_controller_query_flags(args=args)

    def test_invalid_strictness(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(patch_verify=True, strictness="ultra")

    def test_strictness_without_patch_verify(self) -> None:
        from argparse import Namespace

        import codeclone.surfaces.cli.workflow as wf

        wf.console = wf._make_plain_console()
        args = Namespace(
            blast_radius=None,
            patch_verify=False,
            session_stats=False,
            audit=True,
            audit_json=False,
            strictness="strict",
            update_baseline=False,
            update_metrics_baseline=False,
            changed_only=False,
            diff_against=None,
            paths_from_git_diff=None,
        )
        with pytest.raises(SystemExit):
            wf._validate_controller_query_flags(args=args, strictness_explicit=True)

    def test_session_stats_with_audit(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(session_stats=True, audit=True)

    def test_session_stats_with_blast_radius(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(
                session_stats=True,
                blast_radius=("pkg/a.py",),
            )

    def test_audit_with_blast_radius(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(audit=True, blast_radius=("pkg/a.py",))

    def test_audit_with_patch_verify(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(audit=True, patch_verify=True)

    def test_update_baseline_in_controller_mode(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(audit=True, update_baseline=True)

    def test_update_metrics_baseline_in_controller_mode(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(audit=True, update_metrics_baseline=True)

    def test_changed_only_in_controller_mode(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(audit=True, changed_only=True)

    def test_diff_against_in_controller_mode(self) -> None:
        with pytest.raises(SystemExit):
            self._validate(audit=True, diff_against="HEAD")

    def test_report_outputs_in_controller_mode(self) -> None:
        from argparse import Namespace

        import codeclone.surfaces.cli.workflow as wf

        wf.console = wf._make_plain_console()
        args = Namespace(
            blast_radius=None,
            patch_verify=False,
            session_stats=False,
            audit=True,
            audit_json=False,
            strictness="ci",
            update_baseline=False,
            update_metrics_baseline=False,
            changed_only=False,
            diff_against=None,
            paths_from_git_diff=None,
        )
        with pytest.raises(SystemExit):
            wf._validate_controller_query_flags(
                args=args, report_outputs_requested=True
            )

    def test_valid_audit_mode_passes(self) -> None:
        # Should NOT raise
        self._validate(audit=True)

    def test_valid_audit_json_mode_passes(self) -> None:
        # Should NOT raise
        self._validate(audit_json=True)

    def test_non_controller_mode_noop(self) -> None:
        # No controller flags → should return without raising
        self._validate()


# ── workflow.py: _run_pre_analysis_controller_query ──


class TestRunPreAnalysisControllerQuery:
    """Cover _run_pre_analysis_controller_query branches (lines 294-317, 475)."""

    @staticmethod
    def _make_args(**attrs: object) -> CLIArgsLike:
        from argparse import Namespace

        defaults: dict[str, object] = {
            "session_stats": False,
            "audit": False,
            "audit_json": False,
            "no_color": True,
            "quiet": True,
            "audit_enabled": False,
            "audit_path": ".cache/codeclone/audit.sqlite3",
        }
        defaults.update(attrs)
        return cast(CLIArgsLike, Namespace(**defaults))

    def test_session_stats_branch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Exercise session_stats branch (lines 294-302)."""
        import codeclone.surfaces.cli.workflow as wf

        monkeypatch.setattr(
            "codeclone.surfaces.cli.session_stats.render_session_stats",
            lambda **kw: 0,
        )
        args = self._make_args(session_stats=True)
        result = wf._run_pre_analysis_controller_query(args=args, root_path=tmp_path)
        assert result == 0

    def test_audit_branch(self, tmp_path: Path) -> None:
        """Exercise audit branch (lines 309-317)."""
        import codeclone.surfaces.cli.workflow as wf

        args = self._make_args(audit=True, audit_enabled=False)
        result = wf._run_pre_analysis_controller_query(args=args, root_path=tmp_path)
        # audit_enabled=False → CONTRACT_ERROR
        assert result == int(ExitCode.CONTRACT_ERROR)

    def test_audit_json_branch(self, tmp_path: Path) -> None:
        """Exercise audit_json branch (lines 307-324)."""
        import codeclone.surfaces.cli.workflow as wf

        args = self._make_args(audit_json=True, audit_enabled=False)
        result = wf._run_pre_analysis_controller_query(args=args, root_path=tmp_path)
        assert result == int(ExitCode.CONTRACT_ERROR)

    def test_no_controller_mode_returns_none(self, tmp_path: Path) -> None:
        import codeclone.surfaces.cli.workflow as wf

        args = self._make_args()
        result = wf._run_pre_analysis_controller_query(args=args, root_path=tmp_path)
        assert result is None


class TestParseUtc:
    def test_valid_iso(self) -> None:
        from codeclone.surfaces.cli.audit import _parse_utc

        result = _parse_utc("2026-05-26T10:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_empty(self) -> None:
        from codeclone.surfaces.cli.audit import _parse_utc

        assert _parse_utc("") is None

    def test_invalid(self) -> None:
        from codeclone.surfaces.cli.audit import _parse_utc

        assert _parse_utc("not-valid") is None


# ── reader.py: schema without token columns ──


def test_read_audit_summary_no_token_columns(tmp_path: Path) -> None:
    """Exercise the no-token-columns branch (lines 135-143)."""
    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(str(db_path))
    try:
        # Create schema without token columns
        conn.execute("""
            CREATE TABLE IF NOT EXISTS controller_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'info',
                created_at_utc TEXT NOT NULL,
                repo_root_digest TEXT NOT NULL DEFAULT '',
                run_id TEXT,
                intent_id TEXT,
                report_digest TEXT,
                agent_label TEXT NOT NULL DEFAULT '',
                agent_pid INTEGER NOT NULL DEFAULT 0,
                status TEXT,
                payload_json TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS controller_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO controller_meta (key, value) VALUES ('schema_version', '1')"
        )
        conn.execute(
            "INSERT INTO controller_events "
            "(event_id, event_type, severity, created_at_utc, "
            "repo_root_digest, agent_label, agent_pid, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "evt_old_1",
                EVENT_PATCH_VERIFIED,
                "info",
                "2026-05-26T10:00:00Z",
                "digest",
                "agent",
                1,
                "accepted",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    summary = read_audit_summary(db_path=db_path, limit=50)
    assert summary.total_events == 1
    assert summary.payload_footprint is None
    assert summary.total_estimated_tokens is None
    assert summary.token_encoding is None
    assert summary.token_event_count == 0


# ── reader.py: private helper edge cases ──


def test_reader_db_size_oserror(tmp_path: Path) -> None:
    """_db_size returns 0 on missing path."""
    from codeclone.audit.reader import _db_size

    assert _db_size(tmp_path / "nonexistent.db") == 0


def test_reader_int_or_none_bool() -> None:
    """_int_or_none rejects bool (isinstance(True, int) is True in Python)."""
    from codeclone.audit.reader import _int_or_none

    assert _int_or_none(True) is None
    assert _int_or_none(False) is None
    assert _int_or_none(42) == 42
    assert _int_or_none("text") is None


def test_reader_connect_error(tmp_path: Path) -> None:
    """read_audit_summary wraps sqlite3.Error during connect (reader.py:90-91)."""
    from unittest.mock import patch

    from codeclone.audit.validation import AuditReadError

    db_path = tmp_path / "audit.sqlite3"
    db_path.write_text("")  # file exists but triggers error

    with (
        patch("sqlite3.connect", side_effect=sqlite3.Error("disk I/O error")),
        pytest.raises(AuditReadError, match="cannot open audit database"),
    ):
        read_audit_summary(db_path=db_path, limit=50)


def test_reader_count_none_result() -> None:
    """_count returns 0 when fetchone yields None (reader.py:320)."""
    from codeclone.audit.reader import _count

    conn = sqlite3.connect(":memory:")
    # Empty table → COUNT(*) always returns a value, so we use a mock
    from unittest.mock import MagicMock

    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_conn.execute.return_value = mock_result
    assert _count(mock_conn, "SELECT COUNT(*) FROM t") == 0
    conn.close()


def test_reader_text_scalar_none_row() -> None:
    """_text_scalar returns None when row is None (reader.py:328)."""
    from unittest.mock import MagicMock

    from codeclone.audit.reader import _text_scalar

    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_conn.execute.return_value = mock_result
    assert _text_scalar(mock_conn, "SELECT x FROM t") is None


def test_reader_int_meta_value_error() -> None:
    """_int_meta returns None on non-numeric meta value (reader.py:338-339)."""
    from codeclone.audit.reader import _int_meta

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT INTO audit_meta (key, value) VALUES ('retention_days', 'not_a_number')"
    )
    conn.commit()
    result = _int_meta(conn, "retention_days")
    assert result is None
    conn.close()
