# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ... import ui_messages as ui
from ...audit.reader import (
    AuditSummary,
    PayloadFootprint,
    payload_footprint_to_dict,
    read_audit_summary,
)
from ...audit.validation import AuditConfigError, AuditReadError, resolve_audit_path
from ...contracts import ExitCode
from .types import PrinterLike


def render_audit(
    *,
    console: PrinterLike,
    root_path: Path,
    audit_enabled: bool,
    audit_path: str,
    quiet: bool,
    json_summary: bool = False,
) -> int:
    if not audit_enabled:
        console.print(ui.fmt_contract_error("audit is not enabled."))
        return int(ExitCode.CONTRACT_ERROR)
    try:
        db_path = resolve_audit_path(root_path=root_path, value=audit_path)
        summary = read_audit_summary(db_path=db_path, limit=50)
    except (AuditConfigError, AuditReadError) as exc:
        console.print(ui.fmt_contract_error(str(exc)))
        return int(ExitCode.CONTRACT_ERROR)
    except Exception as exc:
        console.print(ui.fmt_internal_error(exc))
        return int(ExitCode.INTERNAL_ERROR)
    if json_summary:
        return _render_json_summary(console=console, summary=summary)
    if quiet:
        return _render_quiet(console=console, summary=summary)
    return _render_verbose(console=console, summary=summary)


def _render_quiet(*, console: PrinterLike, summary: AuditSummary) -> int:
    console.print(
        "audit: "
        f"{summary.total_events} events | "
        f"intents={summary.intent_events} "
        f"contracts={summary.contract_events} "
        f"receipts={summary.receipt_events} "
        f"violations={summary.violation_events} "
        f"last={_relative_time(summary.latest_event_utc)}"
    )
    return int(ExitCode.SUCCESS)


def _render_json_summary(*, console: PrinterLike, summary: AuditSummary) -> int:
    import json

    fp = summary.payload_footprint
    data = {
        "mcp_payload_footprint": payload_footprint_to_dict(fp) if fp else None,
        "total_events": summary.total_events,
        "intents": summary.intent_events,
        "contracts": summary.contract_events,
        "receipts": summary.receipt_events,
        "violations": summary.violation_events,
    }
    console.print(json.dumps(data, indent=2), markup=False)
    return int(ExitCode.SUCCESS)


def _render_verbose(*, console: PrinterLike, summary: AuditSummary) -> int:
    if _supports_rich(console):
        return _render_verbose_rich(console=console, summary=summary)

    console.print("[bold]╍╍╍ Controller Audit Trail ╍╍╍[/bold]")
    console.print()
    console.print(f"  Database:     {summary.db_path} ({summary.total_events} events)")
    if summary.retention_days is not None:
        console.print(f"  Retention:    {summary.retention_days} days")
    console.print(f"  Oldest event: {summary.oldest_event_utc or 'none'}")
    console.print(f"  Latest event: {summary.latest_event_utc or 'none'}")
    console.print()
    for event in summary.events:
        console.print(
            "  "
            f"{_short_time(event.created_at_utc):<16} "
            f"{_short_type(event.event_type):<10} "
            f"{event.intent_id or '-':<24} "
            f"{event.status or '-':<10} "
            f"{event.run_id or '-'}"
        )
    console.print()
    console.print(
        "  Summary: "
        f"{summary.intent_events} intents, "
        f"{summary.contract_events} contracts, "
        f"{summary.receipt_events} receipts"
    )
    console.print(f"  Violations: {summary.violation_events}")
    return int(ExitCode.SUCCESS)


def _render_verbose_rich(*, console: PrinterLike, summary: AuditSummary) -> int:
    from rich import box
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    console.print(Rule("Controller Audit Trail", style="dim", characters="─"))

    meta = Table.grid(padding=(0, 2))
    meta.add_column(style="dim", no_wrap=True)
    meta.add_column()
    meta.add_row(
        "Database",
        f"{summary.db_path} ({summary.total_events} events, "
        f"{_format_bytes(summary.db_size_bytes)})",
    )
    if summary.retention_days is not None:
        meta.add_row("Retention", f"{summary.retention_days} days")
    meta.add_row("Oldest event", summary.oldest_event_utc or "none")
    meta.add_row("Latest event", summary.latest_event_utc or "none")
    meta.add_row(
        "Summary",
        (
            f"{summary.intent_events} intents, "
            f"{summary.contract_events} contracts, "
            f"{summary.receipt_events} receipts"
        ),
    )
    meta.add_row(
        "Violations",
        Text(
            str(summary.violation_events),
            style="red" if summary.violation_events else "green",
        ),
    )
    fp = summary.payload_footprint
    if fp is not None:
        meta.add_row(
            "MCP payload footprint",
            f"~{fp.total_tokens:,} tokens ({fp.encoding}, {fp.tool_calls} tool calls)",
        )
    console.print(Panel(meta, border_style="cyan"))

    table = Table(box=box.SIMPLE_HEAVY)
    table.add_column("Tokens", justify="right", no_wrap=True)
    table.add_column("Time", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Severity", no_wrap=True)
    table.add_column("Intent", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Run", no_wrap=True)
    table.add_column("Agent", no_wrap=True)
    for event in summary.events:
        table.add_row(
            _format_tokens(event.estimated_tokens),
            _short_time(event.created_at_utc),
            _short_type(event.event_type),
            Text(event.severity, style=_severity_style(event.severity)),
            _short_intent(event.intent_id),
            event.status or "-",
            _short_run(event.run_id),
            _short_agent(event.agent_label),
        )
    console.print(table)

    if fp is not None:
        _render_payload_analytics(console=console, fp=fp)

    return int(ExitCode.SUCCESS)


# Payload budget thresholds (tokens)
_SINGLE_PAYLOAD_OK = 500
_SINGLE_PAYLOAD_WATCH = 1500
_WORKFLOW_OK = 5000
_WORKFLOW_WATCH = 15000


def _render_payload_analytics(
    *,
    console: PrinterLike,
    fp: PayloadFootprint,
) -> None:
    from rich import box
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    # ── Aggregate stats ──
    stats = Table.grid(padding=(0, 2))
    stats.add_column(style="dim", no_wrap=True)
    stats.add_column(justify="right", no_wrap=True)
    stats.add_row("Total tokens", f"~{fp.total_tokens:,}")
    stats.add_row("Tool calls", str(fp.tool_calls))
    stats.add_row("Avg tokens/call", str(fp.avg_tokens))
    stats.add_row("p95 tokens", str(fp.p95_tokens))
    stats.add_row("Max tokens", str(fp.max_tokens))
    stats.add_row("Encoding", fp.encoding)

    # ── Breakdown by type ──
    breakdown = Table(box=box.SIMPLE, show_edge=False)
    breakdown.add_column("Type", no_wrap=True)
    breakdown.add_column("Calls", justify="right", no_wrap=True)
    breakdown.add_column("Total", justify="right", no_wrap=True)
    breakdown.add_column("Max", justify="right", no_wrap=True)
    for tp in fp.by_type:
        breakdown.add_row(
            _short_type(tp.event_type),
            str(tp.call_count),
            f"{tp.total_tokens:,}",
            str(tp.max_tokens),
        )

    # ── Top payloads ──
    top = Table(box=box.SIMPLE, show_edge=False)
    top.add_column("#", justify="right", no_wrap=True, style="dim")
    top.add_column("Type", no_wrap=True)
    top.add_column("Tokens", justify="right", no_wrap=True)
    top.add_column("Time", no_wrap=True)
    for i, payload in enumerate(fp.top_payloads, 1):
        style = (
            "bold red"
            if payload.estimated_tokens > _SINGLE_PAYLOAD_WATCH
            else "yellow"
            if payload.estimated_tokens > _SINGLE_PAYLOAD_OK
            else ""
        )
        top.add_row(
            str(i),
            _short_type(payload.event_type),
            Text(f"{payload.estimated_tokens:,}", style=style),
            _short_time(payload.created_at_utc),
        )

    # ── Budget warnings ──
    warnings: list[str] = []
    if fp.total_tokens > _WORKFLOW_WATCH:
        warnings.append(
            f"Workflow total {fp.total_tokens:,} tokens exceeds "
            f"{_WORKFLOW_WATCH:,} threshold (heavy)"
        )
    elif fp.total_tokens > _WORKFLOW_OK:
        warnings.append(
            f"Workflow total {fp.total_tokens:,} tokens exceeds "
            f"{_WORKFLOW_OK:,} threshold (watch)"
        )
    warnings.extend(
        f"{_short_type(payload.event_type)} payload "
        f"{payload.estimated_tokens:,} tokens (heavy)"
        for payload in fp.top_payloads
        if payload.estimated_tokens > _SINGLE_PAYLOAD_WATCH
    )

    # ── Render ──
    console.print()
    console.print(Panel(stats, title="MCP Payload Footprint", border_style="cyan"))
    console.print(Panel(breakdown, title="Tokens by Type", border_style="dim"))
    if fp.top_payloads:
        console.print(Panel(top, title="Top Payloads", border_style="dim"))
    if warnings:
        warning_text = Text()
        for w in warnings:
            warning_text.append(f"  ⚠ {w}\n", style="yellow")
        console.print(
            Panel(
                warning_text,
                title="Payload Budget Warnings",
                border_style="yellow",
            )
        )


def _supports_rich(console: PrinterLike) -> bool:
    return console.__class__.__module__.startswith("rich.")


def _short_type(event_type: str) -> str:
    aliases = {
        "intent.declared": "decl",
        "intent.checked": "check",
        "intent.expanded": "expand",
        "intent.violated": "intent!",
        "intent.cleared": "clear",
        "intent.renewed": "renew",
        "blast_radius.computed": "radius",
        "patch_budget.computed": "budget",
        "patch_contract.verified": "verify",
        "patch_contract.violated": "verify!",
        "patch_contract.expired": "expired",
        "claim_validation.completed": "claims",
        "claim_validation.violated": "claims!",
        "review_receipt.created": "receipt",
        "baseline_abuse.detected": "baseline!",
        "workspace.conflict_detected": "conflict",
        "workspace.gc_completed": "gc",
    }
    return aliases.get(event_type, event_type.rsplit(".", maxsplit=1)[-1])


def _short_intent(intent_id: str | None) -> str:
    if not intent_id:
        return "-"
    return intent_id.removeprefix("intent-")


def _short_agent(agent_label: str | None) -> str:
    if not agent_label:
        return "-"
    return agent_label.replace("claude-code/", "cc/")


def _short_run(run_id: str | None) -> str:
    return run_id[:8] if run_id else "-"


def _short_time(value: str) -> str:
    parsed = _parse_utc(value)
    if parsed is None:
        return value or "-"
    now = datetime.now(timezone.utc)
    if parsed.date() == now.date():
        return parsed.strftime("%H:%M today")
    return parsed.strftime("%Y-%m-%d %H:%M")


def _relative_time(value: str | None) -> str:
    parsed = _parse_utc(value or "")
    if parsed is None:
        return "none"
    seconds = max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def _format_tokens(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    kib = value / 1024
    if kib < 1024:
        return f"{kib:.1f} KiB"
    return f"{kib / 1024:.1f} MiB"


def _severity_style(value: str) -> str:
    return {"info": "green", "warn": "yellow", "error": "bold red"}.get(
        value,
        "white",
    )


__all__ = ["render_audit"]
