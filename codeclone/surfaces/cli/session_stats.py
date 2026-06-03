# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import time
from pathlib import Path

from ... import ui_messages as ui
from ...contracts import ExitCode
from ...controller_insights.session_stats import (
    SessionSnapshot as _SessionSnapshot,
)
from ...controller_insights.session_stats import (
    WorkflowFootprintSnapshot as _WorkflowFootprintSnapshot,
)
from ...controller_insights.session_stats import (
    _active_intent_count,
    _format_age,
    _format_duration,
    _live_agent_count,
    _visible_intent_count,
    collect_session_snapshot,
)
from . import console as cli_console
from .types import PrinterLike

_MAX_ALLOWED_FILES_SHOWN = 2
_MAX_TOP_WORKFLOWS_SHOWN = 3
_PLAIN_LABEL_WIDTH = 25


def render_session_stats(
    *,
    console: PrinterLike,
    root_path: Path,
    quiet: bool,
) -> int:
    """Render workspace session status. Returns ExitCode int."""
    try:
        snapshot = collect_session_snapshot(root_path)
    except Exception as exc:
        console.print(
            ui.fmt_contract_error(ui.SESSION_STATS_READ_FAILED.format(error=exc))
        )
        return int(ExitCode.CONTRACT_ERROR)
    if quiet:
        return _render_quiet(console, snapshot)
    return _render_verbose(console, snapshot)


def _render_quiet(console: PrinterLike, snapshot: _SessionSnapshot) -> int:
    line = ui.SESSION_STATS_QUIET_TEMPLATE.format(
        prefix=ui.SESSION_STATS_QUIET_PREFIX,
        workspace_health=snapshot.workspace_health,
        live_agents=_live_agent_count(snapshot),
        active_intents=_active_intent_count(snapshot),
        visible_intents=_visible_intent_count(snapshot),
        stale=snapshot.stale_count,
        latest_run=snapshot.latest_run_id or ui.SESSION_STATS_LATEST_RUN_NONE,
    )
    if snapshot.latest_run_health is not None:
        line += " " + ui.SESSION_STATS_QUIET_HEALTH.format(
            health=snapshot.latest_run_health
        )
    console.print(line)
    return int(ExitCode.SUCCESS)


def _render_verbose(console: PrinterLike, snapshot: _SessionSnapshot) -> int:
    if cli_console.supports_rich_console(console):
        return _render_verbose_rich(console, snapshot)
    console.print(f"[bold]╍╍╍ {ui.SESSION_STATS_TITLE} ╍╍╍[/bold]")
    console.print()
    console.print(
        f"  {ui.SESSION_STATS_WORKSPACE:<{_PLAIN_LABEL_WIDTH}}{snapshot.root}"
    )
    console.print(
        f"  {ui.SESSION_STATS_INTENT_REGISTRY:<{_PLAIN_LABEL_WIDTH}}"
        f"{snapshot.intent_registry_backend} ({snapshot.intent_registry_storage})"
    )
    if snapshot.audit_enabled and snapshot.audit_storage:
        console.print(
            f"  {ui.SESSION_STATS_AUDIT:<{_PLAIN_LABEL_WIDTH}}"
            f"{ui.SESSION_STATS_AUDIT_ENABLED} ({snapshot.audit_storage})"
        )

    if snapshot.cache_present and snapshot.latest_run_id:
        age_str = _format_age(snapshot.latest_run_age_seconds)
        health_part = (
            f", health={snapshot.latest_run_health}"
            if snapshot.latest_run_health is not None
            else ""
        )
        findings_part = (
            f", findings={snapshot.latest_run_findings}"
            if snapshot.latest_run_findings is not None
            else ""
        )
        console.print(
            f"  {ui.SESSION_STATS_LATEST_RUN:<{_PLAIN_LABEL_WIDTH}}"
            f"{snapshot.latest_run_id}"
            f" ({age_str}{health_part}{findings_part})"
        )
        if snapshot.latest_run_files is not None:
            console.print(
                f"  {ui.SESSION_STATS_CACHE:<{_PLAIN_LABEL_WIDTH}}"
                f"{ui.SESSION_STATS_REPORT_PRESENT.format(files=snapshot.latest_run_files)}"
            )
    else:
        console.print(
            f"  {ui.SESSION_STATS_LATEST_RUN:<{_PLAIN_LABEL_WIDTH}}"
            f"{ui.SESSION_STATS_LATEST_RUN_NONE}"
        )

    console.print()
    live_agents = [a for a in snapshot.agents if a.alive]
    console.print(
        f"  {ui.SESSION_STATS_LIVE_AGENTS:<{_PLAIN_LABEL_WIDTH}}{len(live_agents)}"
    )
    console.print(
        f"  {ui.SESSION_STATS_ACTIVE_INTENTS:<{_PLAIN_LABEL_WIDTH}}"
        f"{_active_intent_count(snapshot)}"
    )
    console.print(
        f"  {ui.SESSION_STATS_VISIBLE_INTENTS:<{_PLAIN_LABEL_WIDTH}}"
        f"{_visible_intent_count(snapshot)}"
    )

    for agent in live_agents:
        label = agent.label or "unknown"
        started_ago = _format_age(int(time.time()) - agent.start_epoch)
        console.print(f"    PID {agent.pid} ({label}) — started {started_ago}")
        for intent in agent.intents:
            file_count_label = f"{intent.scope_file_count} file" + (
                "s" if intent.scope_file_count != 1 else ""
            )
            console.print(
                f"      {intent.intent_id}  {intent.status}   scope: {file_count_label}"
            )
            shown_files = intent.allowed_files[:_MAX_ALLOWED_FILES_SHOWN]
            if shown_files:
                files_str = ", ".join(shown_files)
                if len(intent.allowed_files) > _MAX_ALLOWED_FILES_SHOWN:
                    remaining = len(intent.allowed_files) - _MAX_ALLOWED_FILES_SHOWN
                    files_str += f" ... and {remaining} more"
                console.print(f"        allowed: {files_str}")
            lease_str = _format_duration(intent.lease_remaining_seconds)
            console.print(f"        lease: {lease_str} remaining")

    console.print()
    console.print(
        f"  {ui.SESSION_STATS_STALE:<{_PLAIN_LABEL_WIDTH}}{snapshot.stale_count}"
    )
    console.print(
        f"  {ui.SESSION_STATS_EXPIRED:<{_PLAIN_LABEL_WIDTH}}{snapshot.expired_count}"
    )
    console.print(
        f"  {ui.SESSION_STATS_RECOVERABLE:<{_PLAIN_LABEL_WIDTH}}"
        f"{snapshot.recoverable_count}"
    )
    if snapshot.mcp_token_footprint is not None and snapshot.mcp_token_event_count > 0:
        enc = snapshot.mcp_token_encoding or "unknown"
        console.print(
            "  "
            + ui.SESSION_STATS_RETENTION_FOOTPRINT_VERBOSE.format(
                tokens=snapshot.mcp_token_footprint,
                encoding=enc,
                calls=snapshot.mcp_token_event_count,
            )
        )
        _render_plain_top_workflows(console, snapshot.top_workflows)
    console.print()
    console.print(f"  {ui.SESSION_STATS_WORKSPACE_HEALTH} {snapshot.workspace_health}")
    return int(ExitCode.SUCCESS)


def _render_verbose_rich(console: PrinterLike, snapshot: _SessionSnapshot) -> int:
    box, panel_cls, rule_cls, table_cls, text_cls = cli_console.rich_panel_symbols()

    console.print(rule_cls(ui.SESSION_STATS_TITLE, style="dim", characters="─"))

    summary = table_cls.grid(padding=(0, 2))
    summary.add_column(style="dim", no_wrap=True)
    summary.add_column()
    summary.add_row(ui.SESSION_STATS_WORKSPACE.rstrip(":"), str(snapshot.root))
    summary.add_row(
        ui.SESSION_STATS_INTENT_REGISTRY.rstrip(":"),
        f"{snapshot.intent_registry_backend} ({snapshot.intent_registry_storage})",
    )
    if snapshot.audit_enabled and snapshot.audit_storage:
        summary.add_row(
            ui.SESSION_STATS_AUDIT.rstrip(":"),
            f"{ui.SESSION_STATS_AUDIT_ENABLED} ({snapshot.audit_storage})",
        )
    if snapshot.cache_present and snapshot.latest_run_id:
        run_text = _latest_run_text(snapshot)
        summary.add_row(ui.SESSION_STATS_LATEST_RUN.rstrip(":"), run_text)
        if snapshot.latest_run_files is not None:
            summary.add_row(
                ui.SESSION_STATS_CACHE.rstrip(":"),
                ui.SESSION_STATS_REPORT_PRESENT.format(files=snapshot.latest_run_files),
            )
    else:
        summary.add_row(
            ui.SESSION_STATS_LATEST_RUN.rstrip(":"),
            ui.SESSION_STATS_LATEST_RUN_NONE,
        )
    summary.add_row(
        ui.SESSION_STATS_LIVE_AGENTS.rstrip(":"),
        str(_live_agent_count(snapshot)),
    )
    summary.add_row(
        ui.SESSION_STATS_ACTIVE_INTENTS.rstrip(":"),
        str(_active_intent_count(snapshot)),
    )
    summary.add_row(
        ui.SESSION_STATS_VISIBLE_INTENTS.rstrip(":"),
        str(_visible_intent_count(snapshot)),
    )
    summary.add_row(
        ui.SESSION_STATS_STALE.rstrip(":"),
        str(snapshot.stale_count),
    )
    summary.add_row(
        ui.SESSION_STATS_EXPIRED.rstrip(":"),
        str(snapshot.expired_count),
    )
    summary.add_row(
        ui.SESSION_STATS_RECOVERABLE.rstrip(":"),
        str(snapshot.recoverable_count),
    )
    if snapshot.mcp_token_footprint is not None and snapshot.mcp_token_event_count > 0:
        enc = snapshot.mcp_token_encoding or "unknown"
        summary.add_row(
            ui.SESSION_STATS_RETENTION_FOOTPRINT,
            f"~{snapshot.mcp_token_footprint:,} tokens in retention window "
            f"({enc}, {snapshot.mcp_token_event_count} tool calls)",
        )
    health_text = text_cls(
        snapshot.workspace_health,
        style=_health_style(snapshot.workspace_health),
    )
    summary.add_row(
        ui.SESSION_STATS_WORKSPACE_HEALTH.rstrip(":"),
        health_text,
    )
    console.print(
        panel_cls(summary, border_style=_health_style(snapshot.workspace_health))
    )

    live_agents = [agent for agent in snapshot.agents if agent.alive]
    if not live_agents:
        console.print(f"[dim]{ui.SESSION_STATS_NO_AGENTS}[/dim]")
        _render_rich_top_workflows(console, snapshot.top_workflows)
        return int(ExitCode.SUCCESS)

    table = table_cls(
        title=ui.SESSION_STATS_WORKSPACE_INTENT_RECORDS_TITLE,
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        expand=True,
    )
    table.add_column(ui.SESSION_STATS_COL_PID, no_wrap=True, style="dim")
    table.add_column(ui.SESSION_STATS_COL_AGENT, overflow="fold")
    table.add_column(ui.SESSION_STATS_COL_OWNERSHIP, no_wrap=True)
    table.add_column(ui.SESSION_STATS_COL_STATUS, no_wrap=True)
    table.add_column(ui.SESSION_STATS_COL_SCOPE, justify="right", no_wrap=True)
    table.add_column(ui.SESSION_STATS_COL_LEASE, no_wrap=True)
    table.add_column(ui.SESSION_STATS_COL_FILES, overflow="ellipsis", max_width=42)

    for agent in live_agents:
        label = agent.label or ui.SESSION_STATS_AGENT_UNKNOWN
        for intent in agent.intents:
            table.add_row(
                str(agent.pid),
                label,
                text_cls(intent.ownership, style=_ownership_style(intent.ownership)),
                text_cls(intent.status, style=_intent_status_style(intent.status)),
                str(intent.scope_file_count),
                _format_duration(intent.lease_remaining_seconds),
                _allowed_files_label(intent.allowed_files),
            )
    console.print(table)
    _render_rich_top_workflows(console, snapshot.top_workflows)
    return int(ExitCode.SUCCESS)


def _render_plain_top_workflows(
    console: PrinterLike,
    workflows: tuple[_WorkflowFootprintSnapshot, ...],
) -> None:
    if not workflows:
        return
    console.print(f"  {ui.SESSION_STATS_TOP_WORKFLOWS}:")
    for workflow in workflows[:_MAX_TOP_WORKFLOWS_SHOWN]:
        console.print(f"    {_workflow_label(workflow)}")


def _render_rich_top_workflows(
    console: PrinterLike,
    workflows: tuple[_WorkflowFootprintSnapshot, ...],
) -> None:
    if not workflows or not cli_console.supports_rich_console(console):
        return
    box, _panel_cls, _rule_cls, table_cls, text_cls = cli_console.rich_panel_symbols()
    table = table_cls(
        title=ui.SESSION_STATS_TOP_WORKFLOWS,
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        expand=True,
    )
    table.add_column(ui.SESSION_STATS_COL_WORKFLOW, overflow="ellipsis")
    table.add_column(ui.SESSION_STATS_COL_TOKENS, justify="right", no_wrap=True)
    table.add_column(ui.SESSION_STATS_COL_CALLS, justify="right", no_wrap=True)
    table.add_column(ui.SESSION_STATS_COL_AGENT, overflow="ellipsis")
    for workflow in workflows[:_MAX_TOP_WORKFLOWS_SHOWN]:
        table.add_row(
            _workflow_name(workflow),
            f"~{workflow.total_tokens:,}",
            str(workflow.call_count),
            text_cls(workflow.agent_label or "-", style="dim"),
        )
    console.print(table)


def _latest_run_text(snapshot: _SessionSnapshot) -> str:
    age_str = _format_age(snapshot.latest_run_age_seconds)
    parts = [f"{snapshot.latest_run_id} ({age_str}"]
    if snapshot.latest_run_health is not None:
        parts.append(f", health={snapshot.latest_run_health}")
    if snapshot.latest_run_findings is not None:
        parts.append(f", findings={snapshot.latest_run_findings}")
    parts.append(")")
    return "".join(parts)


def _allowed_files_label(files: tuple[str, ...]) -> str:
    if not files:
        return "-"
    shown = files[:_MAX_ALLOWED_FILES_SHOWN]
    label = ", ".join(shown)
    if len(files) > _MAX_ALLOWED_FILES_SHOWN:
        extra = ui.BLAST_RADIUS_MORE.format(count=len(files) - _MAX_ALLOWED_FILES_SHOWN)
        label += f" {extra}"
    return label


def _workflow_name(workflow: _WorkflowFootprintSnapshot) -> str:
    prefix = workflow.workflow_kind or "workflow"
    workflow_id = workflow.workflow_id or "-"
    return f"{prefix}:{workflow_id}"


def _workflow_label(workflow: _WorkflowFootprintSnapshot) -> str:
    agent = workflow.agent_label or "-"
    return (
        f"{_workflow_name(workflow)}  "
        f"~{workflow.total_tokens:,} tokens / "
        f"{workflow.call_count} calls  "
        f"agent={agent}"
    )


def _health_style(value: str) -> str:
    return {
        "idle": "dim",
        "clean": "green",
        "active": "cyan",
        "contested": "yellow",
    }.get(value, "cyan")


def _ownership_style(value: str) -> str:
    if value.startswith("own"):
        return "green"
    if value == "foreign_stale":
        return "yellow"
    if value == "foreign_active":
        return "cyan"
    if value == "recoverable":
        return "magenta"
    return "dim"


def _intent_status_style(value: str) -> str:
    return {
        "active": "cyan",
        "clean": "green",
        "expanded": "yellow",
        "violated": "red",
        "expired": "dim",
    }.get(value, "white")
