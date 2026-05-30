# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ... import ui_messages as ui
from ...contracts import ExitCode
from .types import PrinterLike

if TYPE_CHECKING:
    from ..mcp._workspace_intents import WorkspaceIntentRecord

_REPORT_PATH_PARTS = (".cache", "codeclone", "report.json")
_MAX_ALLOWED_FILES_SHOWN = 5


@dataclass(frozen=True, slots=True)
class _IntentSnapshot:
    intent_id: str
    status: str
    ownership: str
    scope_file_count: int
    allowed_files: tuple[str, ...]
    declared_at_utc: str
    lease_remaining_seconds: int


@dataclass(frozen=True, slots=True)
class _AgentSnapshot:
    pid: int
    start_epoch: int
    label: str
    alive: bool
    intents: tuple[_IntentSnapshot, ...]


@dataclass(frozen=True, slots=True)
class _SessionSnapshot:
    root: Path
    agents: tuple[_AgentSnapshot, ...]
    stale_count: int
    expired_count: int
    recoverable_count: int
    latest_run_id: str | None
    latest_run_health: int | None
    latest_run_findings: int | None
    latest_run_files: int | None
    latest_run_age_seconds: int | None
    cache_present: bool
    workspace_health: str
    intent_registry_backend: str
    intent_registry_storage: str
    audit_enabled: bool = False
    audit_storage: str | None = None
    mcp_token_footprint: int | None = None
    mcp_token_encoding: str | None = None
    mcp_token_event_count: int = 0


def render_session_stats(
    *,
    console: PrinterLike,
    root_path: Path,
    quiet: bool,
) -> int:
    """Render workspace session status. Returns ExitCode int."""
    try:
        snapshot = _collect_session_snapshot(root_path)
    except Exception as exc:
        console.print(
            ui.fmt_contract_error(ui.SESSION_STATS_READ_FAILED.format(error=exc))
        )
        return int(ExitCode.CONTRACT_ERROR)
    if quiet:
        return _render_quiet(console, snapshot)
    return _render_verbose(console, snapshot)


def _collect_session_snapshot(root_path: Path) -> _SessionSnapshot:
    from ...surfaces.mcp._workspace_intents import (
        IntentOwnership,
        classify_intent_ownership,
        list_workspace_intent_records_for_recovery,
        utc_now,
    )

    now = utc_now()
    own_pid = os.getpid()
    own_start_epoch = _process_start_epoch()

    try:
        records = list_workspace_intent_records_for_recovery(root=root_path)
    except Exception:
        records = ()

    stale_count = 0
    expired_count = 0
    recoverable_count = 0
    agent_intents: dict[tuple[int, int], list[_IntentSnapshot]] = defaultdict(list)
    agent_labels: dict[tuple[int, int], str] = {}
    agent_alive: dict[tuple[int, int], bool] = {}

    for record in records:
        ownership = classify_intent_ownership(
            record,
            own_pid=own_pid,
            own_start_epoch=own_start_epoch,
            now=now,
        )

        if ownership == IntentOwnership.EXPIRED:
            expired_count += 1
            continue
        if ownership == IntentOwnership.OWN_STALE:
            stale_count += 1
        if ownership == IntentOwnership.RECOVERABLE:
            recoverable_count += 1

        lease_remaining = _lease_remaining_seconds(record, now)
        scope = record.scope
        allowed_files: list[str] = []
        if isinstance(scope, dict):
            raw_files = scope.get("allowed_files")
            if isinstance(raw_files, list):
                allowed_files = [str(f) for f in raw_files]

        agent_key = (record.agent_pid, record.agent_start_epoch)
        agent_labels[agent_key] = record.agent_label
        if agent_key not in agent_alive:
            agent_alive[agent_key] = _is_pid_alive(record.agent_pid)

        agent_intents[agent_key].append(
            _IntentSnapshot(
                intent_id=record.intent_id,
                status=record.status,
                ownership=ownership.value,
                scope_file_count=len(allowed_files),
                allowed_files=tuple(sorted(allowed_files)),
                declared_at_utc=record.declared_at_utc,
                lease_remaining_seconds=lease_remaining,
            )
        )

    agents: list[_AgentSnapshot] = []
    for agent_key in sorted(agent_intents):
        pid, start_epoch = agent_key
        agents.append(
            _AgentSnapshot(
                pid=pid,
                start_epoch=start_epoch,
                label=agent_labels.get(agent_key, ""),
                alive=agent_alive.get(agent_key, False),
                intents=tuple(agent_intents[agent_key]),
            )
        )

    (
        latest_run_id,
        latest_run_health,
        latest_run_findings,
        latest_run_files,
        latest_run_age_seconds,
        cache_present,
    ) = _read_cached_report(root_path)

    workspace_health = _classify_workspace_health(
        agents=agents,
        stale_count=stale_count,
        expired_count=expired_count,
    )

    mcp_tokens, mcp_enc, mcp_count = _read_audit_token_footprint(root_path)
    audit_enabled, audit_storage = _read_audit_config(root_path)
    from ...config.intent_registry import intent_registry_summary

    registry = intent_registry_summary(root_path)

    return _SessionSnapshot(
        root=root_path,
        agents=tuple(agents),
        stale_count=stale_count,
        expired_count=expired_count,
        recoverable_count=recoverable_count,
        latest_run_id=latest_run_id,
        latest_run_health=latest_run_health,
        latest_run_findings=latest_run_findings,
        latest_run_files=latest_run_files,
        latest_run_age_seconds=latest_run_age_seconds,
        cache_present=cache_present,
        workspace_health=workspace_health,
        intent_registry_backend=registry["registry_backend"],
        intent_registry_storage=registry["registry_storage"],
        audit_enabled=audit_enabled,
        audit_storage=audit_storage,
        mcp_token_footprint=mcp_tokens,
        mcp_token_encoding=mcp_enc,
        mcp_token_event_count=mcp_count,
    )


def _render_quiet(console: PrinterLike, snapshot: _SessionSnapshot) -> int:
    live_agents = [a for a in snapshot.agents if a.alive]
    total_intents = sum(len(a.intents) for a in snapshot.agents)
    line = ui.SESSION_STATS_QUIET_TEMPLATE.format(
        prefix=ui.SESSION_STATS_QUIET_PREFIX,
        workspace_health=snapshot.workspace_health,
        agents=len(live_agents),
        intents=total_intents,
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
    if _supports_rich(console):
        return _render_verbose_rich(console, snapshot)
    console.print(f"[bold]╍╍╍ {ui.SESSION_STATS_TITLE} ╍╍╍[/bold]")
    console.print()
    console.print(f"  {ui.SESSION_STATS_WORKSPACE:<17}{snapshot.root}")
    console.print(
        f"  {ui.SESSION_STATS_INTENT_REGISTRY:<17}"
        f"{snapshot.intent_registry_backend} ({snapshot.intent_registry_storage})"
    )
    if snapshot.audit_enabled and snapshot.audit_storage:
        console.print(
            f"  {ui.SESSION_STATS_AUDIT:<17}"
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
            f"  {ui.SESSION_STATS_LATEST_RUN:<17}{snapshot.latest_run_id}"
            f" ({age_str}{health_part}{findings_part})"
        )
        if snapshot.latest_run_files is not None:
            console.print(
                f"  {ui.SESSION_STATS_CACHE:<17}"
                f"{ui.SESSION_STATS_REPORT_PRESENT.format(files=snapshot.latest_run_files)}"
            )
    else:
        console.print(
            f"  {ui.SESSION_STATS_LATEST_RUN:<17}{ui.SESSION_STATS_LATEST_RUN_NONE}"
        )

    console.print()
    live_agents = [a for a in snapshot.agents if a.alive]
    console.print(f"  {ui.SESSION_STATS_ACTIVE_AGENTS:<17}{len(live_agents)}")

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
    console.print(f"  {ui.SESSION_STATS_STALE:<17}{snapshot.stale_count}")
    console.print(f"  {ui.SESSION_STATS_EXPIRED:<15}{snapshot.expired_count}")
    console.print(f"  {ui.SESSION_STATS_RECOVERABLE:<17}{snapshot.recoverable_count}")
    if snapshot.mcp_token_footprint is not None and snapshot.mcp_token_event_count > 0:
        enc = snapshot.mcp_token_encoding or "unknown"
        console.print(
            "  "
            + ui.SESSION_STATS_MCP_FOOTPRINT_VERBOSE.format(
                tokens=snapshot.mcp_token_footprint,
                encoding=enc,
                calls=snapshot.mcp_token_event_count,
            )
        )
    console.print()
    console.print(f"  {ui.SESSION_STATS_WORKSPACE_HEALTH} {snapshot.workspace_health}")
    return int(ExitCode.SUCCESS)


def _render_verbose_rich(console: PrinterLike, snapshot: _SessionSnapshot) -> int:
    box, panel_cls, rule_cls, table_cls, text_cls = _rich_session_symbols()

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
        ui.SESSION_STATS_ACTIVE_AGENTS.rstrip(":"),
        str(len([a for a in snapshot.agents if a.alive])),
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
            ui.SESSION_STATS_MCP_FOOTPRINT,
            f"~{snapshot.mcp_token_footprint:,} tokens "
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
        return int(ExitCode.SUCCESS)

    table = table_cls(
        title=ui.SESSION_STATS_WORKSPACE_INTENTS_TITLE,
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
    table.add_column(ui.SESSION_STATS_COL_FILES, overflow="fold")

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
    return int(ExitCode.SUCCESS)


def _rich_session_symbols() -> tuple[Any, Any, Any, Any, Any]:
    from rich import box
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    return box, Panel, Rule, Table, Text


def _supports_rich(console: PrinterLike) -> bool:
    return console.__class__.__module__.startswith("rich.")


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


def _classify_workspace_health(
    *,
    agents: list[_AgentSnapshot] | tuple[_AgentSnapshot, ...],
    stale_count: int,
    expired_count: int,
) -> str:
    live_agents = [a for a in agents if a.alive]
    if not live_agents:
        return "idle"

    active_intent_agents = [
        agent
        for agent in live_agents
        if any(intent.status == "active" for intent in agent.intents)
    ]

    if not active_intent_agents:
        return "clean"

    if len(active_intent_agents) >= 2 and _has_scope_overlap(active_intent_agents):
        return "contested"

    return "active"


def _has_scope_overlap(agents: list[_AgentSnapshot]) -> bool:
    all_files: list[set[str]] = []
    for agent in agents:
        agent_files: set[str] = set()
        for intent in agent.intents:
            if intent.status == "active":
                agent_files.update(intent.allowed_files)
        if agent_files:
            all_files.append(agent_files)

    for i in range(len(all_files)):
        for j in range(i + 1, len(all_files)):
            if all_files[i] & all_files[j]:
                return True
    return False


def _read_cached_report(
    root_path: Path,
) -> tuple[str | None, int | None, int | None, int | None, int | None, bool]:
    report_path = root_path.joinpath(*_REPORT_PATH_PARTS)
    if not report_path.is_file():
        return None, None, None, None, None, False
    try:
        with open(report_path, "rb") as fh:
            data = json.load(fh)
    except Exception:
        return None, None, None, None, None, False

    run_id: str | None = None
    health: int | None = None
    findings: int | None = None
    files: int | None = None
    age_seconds: int | None = None

    data_mapping = data if isinstance(data, dict) else {}
    digest_value = _string_field(
        _mapping_at(data_mapping, ("integrity", "digest")), "value"
    )
    if digest_value is not None and len(digest_value) >= 8:
        run_id = digest_value[:8]

    files = _list_field_len(
        _mapping_at(data_mapping, ("inventory", "file_registry")),
        "items",
    )
    if _mapping_at(data_mapping, ("metrics", "families")) is not None:
        health = _int_field(_mapping_at(data_mapping, ("health",)), "score")
    findings = _int_field(_mapping_at(data_mapping, ("findings",)), "total")

    try:
        mtime = report_path.stat().st_mtime
        age_seconds = max(0, int(time.time() - mtime))
    except OSError:
        pass

    return run_id, health, findings, files, age_seconds, True


def _mapping_at(
    payload: Mapping[str, object],
    keys: tuple[str, ...],
) -> Mapping[str, object] | None:
    current: object = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, dict) else None


def _string_field(payload: Mapping[str, object] | None, key: str) -> str | None:
    if payload is None:
        return None
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _int_field(payload: Mapping[str, object] | None, key: str) -> int | None:
    if payload is None:
        return None
    value = payload.get(key)
    return value if isinstance(value, int) else None


def _list_field_len(payload: Mapping[str, object] | None, key: str) -> int | None:
    if payload is None:
        return None
    value = payload.get(key)
    return len(value) if isinstance(value, list) else None


def _lease_remaining_seconds(record: WorkspaceIntentRecord, now: datetime) -> int:
    from ...surfaces.mcp._workspace_intents import _lease_expiry

    expiry = _lease_expiry(record)
    if expiry is None:
        return 0
    delta = (expiry - now).total_seconds()
    return max(0, int(delta))


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_start_epoch() -> int:
    return int(time.time())


def _read_audit_config(root_path: Path) -> tuple[bool, str | None]:
    try:
        from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
        from ...config.pyproject_loader import (
            ConfigValidationError,
            load_pyproject_config,
        )

        config = load_pyproject_config(root_path)
    except (ConfigValidationError, OSError):
        return False, None
    if not bool(config.get("audit_enabled", False)):
        return False, None
    try:
        db_path = resolve_audit_path(
            root_path=root_path,
            value=config.get("audit_path", DEFAULT_AUDIT_PATH),
        )
    except Exception:
        return True, None
    try:
        storage = str(db_path.relative_to(root_path.resolve()))
    except ValueError:
        storage = str(db_path)
    return True, storage


def _read_audit_token_footprint(
    root_path: Path,
) -> tuple[int | None, str | None, int]:
    """Read aggregate token estimation from audit trail, if available."""
    try:
        from ...audit.reader import read_audit_summary
        from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
        from ...config.pyproject_loader import (
            load_pyproject_config,
        )

        config = load_pyproject_config(root_path)
        if not bool(config.get("audit_enabled", False)):
            return None, None, 0
        db_path = resolve_audit_path(
            root_path=root_path,
            value=config.get("audit_path", DEFAULT_AUDIT_PATH),
        )
        if not db_path.is_file():
            return None, None, 0
        summary = read_audit_summary(db_path=db_path, limit=1)
        return (
            summary.total_estimated_tokens,
            summary.token_encoding,
            summary.token_event_count,
        )
    except Exception:
        return None, None, 0


def _format_age(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "unknown"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    remaining_minutes = minutes % 60
    if remaining_minutes:
        return f"{hours}h{remaining_minutes}m ago"
    return f"{hours}h ago"


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "expired"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    remaining_seconds = seconds % 60
    if remaining_seconds:
        return f"{minutes}m{remaining_seconds}s"
    return f"{minutes}m"
