# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import time
from pathlib import Path

from ... import ui_messages as ui
from ...api.novelty import (
    CLONE_NOVELTY_KNOWN,
    CLONE_NOVELTY_NEW,
    CLONE_NOVELTY_UNAVAILABLE,
)
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
    latest_run_source_label,
)
from ...ui_messages.styling import _L
from . import console as cli_console
from .state import CLI_SESSION_START_EPOCH
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
        snapshot = collect_session_snapshot(
            root_path,
            # This process, named by what it stamped when it started -- not by
            # what the clock says at the moment somebody ran --session-stats.
            own_pid=os.getpid(),
            own_start_epoch=CLI_SESSION_START_EPOCH,
        )
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

    if snapshot.latest_run_id:
        age_str = _format_age(snapshot.latest_run_age_seconds)
        health_part = (
            f", health={snapshot.latest_run_health}"
            if snapshot.latest_run_health is not None
            else ""
        )
        findings_part = _findings_text(snapshot)
        source_part = _latest_run_source_suffix(snapshot)
        console.print(
            f"  {ui.SESSION_STATS_LATEST_RUN:<{_PLAIN_LABEL_WIDTH}}"
            f"{snapshot.latest_run_id}"
            f" ({age_str}{health_part}{findings_part}{source_part})"
        )
        if snapshot.cache_present and snapshot.latest_run_files is not None:
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


def _workspace_is_quiet(snapshot: _SessionSnapshot) -> bool:
    """True when every counter the full screen would list is zero.

    The domain's ``workspace_health`` says ``idle`` for "no live agent"; this
    asks the narrower question the compact screen needs -- is there any
    count at all worth a row of its own -- so a stale or recoverable intent
    still gets the full screen while a truly empty workspace gets four lines.
    """

    return (
        snapshot.workspace_health == "idle"
        and not any(agent.alive for agent in snapshot.agents)
        and _active_intent_count(snapshot) == 0
        and _visible_intent_count(snapshot) == 0
        and snapshot.stale_count == 0
        and snapshot.expired_count == 0
        and snapshot.recoverable_count == 0
        and not (
            snapshot.mcp_token_footprint is not None
            and snapshot.mcp_token_event_count > 0
        )
    )


def _audit_row(snapshot: _SessionSnapshot) -> tuple[str, str]:
    """The audit row: enabled, and the file the trail is written to."""

    return (
        ui.SESSION_STATS_AUDIT_SHORT,
        f"{ui.SESSION_STATS_AUDIT_ENABLED} ({ui.esc(snapshot.audit_storage)})",
    )


def _latest_run_rows(snapshot: _SessionSnapshot) -> list[tuple[str, str]]:
    """The latest-run row, and the cache row when a report backs it."""

    if not snapshot.latest_run_id:
        return [
            (
                ui.SESSION_STATS_LATEST_RUN.rstrip(":"),
                ui.SESSION_STATS_LATEST_RUN_NONE_VERBOSE,
            )
        ]
    rows = [(ui.SESSION_STATS_LATEST_RUN.rstrip(":"), _latest_run_text(snapshot))]
    if snapshot.cache_present and snapshot.latest_run_files is not None:
        rows.append(
            (
                ui.SESSION_STATS_CACHE.rstrip(":"),
                ui.SESSION_STATS_REPORT_PRESENT.format(files=snapshot.latest_run_files),
            )
        )
    return rows


def _render_verbose_rich(console: PrinterLike, snapshot: _SessionSnapshot) -> int:
    box, _panel_cls, rule_cls, table_cls, text_cls = cli_console.rich_panel_symbols()

    console.print(
        rule_cls(ui.SESSION_STATS_TITLE, style=ui.STYLE_META, characters=ui.GLYPH_RULE)
    )
    sep = f" {ui.GLYPH_SEP} "
    registry = (
        f"{snapshot.intent_registry_backend} ({snapshot.intent_registry_storage})"
    )
    workspace_row = (
        ui.SESSION_STATS_WORKSPACE.rstrip(":"),
        ui.esc(str(snapshot.root)),
    )
    health_word = ui.styled(
        snapshot.workspace_health, _health_style(snapshot.workspace_health)
    )
    if _workspace_is_quiet(snapshot):
        # Nothing is happening: the workspace, what the last run said, and one
        # verdict row carrying the zeros and where a session would register.
        # Six rows of zeros said no more than the word "idle" beside them.
        quiet_rows = [workspace_row, *_latest_run_rows(snapshot)]
        if snapshot.audit_enabled and snapshot.audit_storage:
            # Opt-in, and it names a file: a row of its own, as on the full
            # screen, so the verdict row stays one line at the grid width.
            quiet_rows.append(_audit_row(snapshot))
        quiet_rows.append(
            (
                ui.SESSION_STATS_HEALTH_SHORT,
                sep.join(
                    (
                        health_word,
                        ui.SESSION_STATS_REGISTRY_INLINE.format(
                            backend=snapshot.intent_registry_backend,
                            storage=ui.esc(snapshot.intent_registry_storage),
                        ),
                    )
                ),
            )
        )
        for label, value in quiet_rows:
            console.print(f"  {label:<{_L}}{value}")
        return int(ExitCode.SUCCESS)

    rows: list[tuple[str, str]] = [
        workspace_row,
        (ui.SESSION_STATS_REGISTRY, ui.esc(registry)),
    ]
    if snapshot.audit_enabled and snapshot.audit_storage:
        rows.append(_audit_row(snapshot))
    rows.extend(_latest_run_rows(snapshot))
    rows.append(
        (
            ui.SESSION_STATS_AGENTS,
            sep.join(
                (
                    f"{_live_agent_count(snapshot)} live",
                    f"{_active_intent_count(snapshot)} active intents",
                    f"{_visible_intent_count(snapshot)} visible records",
                )
            ),
        )
    )
    rows.append(
        (
            ui.SESSION_STATS_INTENTS,
            sep.join(
                (
                    f"{snapshot.stale_count} stale",
                    f"{snapshot.expired_count} expired",
                    f"{snapshot.recoverable_count} recoverable",
                )
            ),
        )
    )
    if snapshot.mcp_token_footprint is not None and snapshot.mcp_token_event_count > 0:
        enc = snapshot.mcp_token_encoding or "unknown"
        rows.append(
            (
                ui.SESSION_STATS_FOOTPRINT_SHORT,
                f"~{snapshot.mcp_token_footprint:,} tokens in retention window "
                f"({enc}, {snapshot.mcp_token_event_count} tool calls)",
            )
        )
    rows.append((ui.SESSION_STATS_HEALTH_SHORT, health_word))
    for label, value in rows:
        console.print(f"  {label:<{_L}}{value}")

    live_agents = [agent for agent in snapshot.agents if agent.alive]
    if not live_agents:
        # "Agents  0 live" has said it; a sentence under it said it again.
        _render_rich_top_workflows(console, snapshot.top_workflows)
        return int(ExitCode.SUCCESS)

    table = table_cls(
        title=ui.SESSION_STATS_WORKSPACE_INTENT_RECORDS_TITLE,
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        expand=True,
    )
    table.add_column(ui.SESSION_STATS_COL_PID, no_wrap=True, style=ui.STYLE_META)
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
            text_cls(workflow.agent_label or "-", style=ui.STYLE_META),
        )
    console.print(table)


def _latest_run_text(snapshot: _SessionSnapshot) -> str:
    age_str = _format_age(snapshot.latest_run_age_seconds)
    parts = [f"{snapshot.latest_run_id} ({age_str}"]
    if snapshot.latest_run_health is not None:
        parts.append(f", health={snapshot.latest_run_health}")
    parts.append(_findings_text(snapshot))
    source_part = _latest_run_source_suffix(snapshot)
    if source_part:
        parts.append(source_part)
    parts.append(")")
    return "".join(parts)


def _findings_text(snapshot: _SessionSnapshot) -> str:
    """The findings fragment of the latest-run line, novelty included.

    One fragment for the plain and rich renderers, so the two cannot drift.
    An absent counter is worded, never rendered as 0: a zero would assert a
    baseline comparison the recorded row never made. The counter labels come
    from the novelty vocabulary door, never respelled here. Parentheses, not
    square brackets: the rich renderer reads ``[...]`` as markup and would
    silently swallow the whole novelty fragment.
    """

    if snapshot.latest_run_findings is None:
        return ""
    counters = (
        (CLONE_NOVELTY_NEW, snapshot.latest_run_findings_new),
        (CLONE_NOVELTY_KNOWN, snapshot.latest_run_findings_known),
        (CLONE_NOVELTY_UNAVAILABLE, snapshot.latest_run_findings_unavailable),
    )
    if all(count is None for _label, count in counters):
        novelty = ui.SESSION_STATS_NOVELTY_UNKNOWN
    else:
        novelty = ", ".join(
            f"{label}="
            f"{ui.SESSION_STATS_NOVELTY_VALUE_UNKNOWN if count is None else count}"
            for label, count in counters
        )
    return f", findings={snapshot.latest_run_findings} ({novelty})"


def _latest_run_source_suffix(snapshot: _SessionSnapshot) -> str:
    label = latest_run_source_label(snapshot.latest_run_source)
    if label is None:
        return ""
    return f", source={label}"


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
        "idle": ui.STYLE_META,
        "clean": ui.STYLE_VERDICT_PASS,
        "active": ui.STYLE_ACCENT,
        "contested": ui.STYLE_VERDICT_WARN,
    }.get(value, ui.STYLE_ACCENT)


def _ownership_style(value: str) -> str:
    if value.startswith("own"):
        return ui.STYLE_VERDICT_PASS
    if value == "foreign_stale":
        return ui.STYLE_VERDICT_WARN
    if value == "foreign_active":
        return ui.STYLE_ACCENT
    if value == "recoverable":
        return ui.STYLE_STATE_DRAFT
    return ui.STYLE_META


def _intent_status_style(value: str) -> str:
    return {
        "active": ui.STYLE_ACCENT,
        "clean": ui.STYLE_VERDICT_PASS,
        "expanded": ui.STYLE_VERDICT_WARN,
        "violated": ui.STYLE_VERDICT_FAIL,
        "expired": ui.STYLE_META,
    }.get(value, "")
