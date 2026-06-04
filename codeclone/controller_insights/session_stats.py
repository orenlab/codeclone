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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..surfaces.mcp._workspace_intents import WorkspaceIntentRecord

from ..paths.workspace import REPORT_JSON_PARTS as _REPORT_PATH_PARTS

_MAX_ALLOWED_FILES_SHOWN = 2
_MAX_TOP_WORKFLOWS_SHOWN = 3
_PLAIN_LABEL_WIDTH = 25


@dataclass(frozen=True, slots=True)
class WorkflowFootprintSnapshot:
    workflow_kind: str
    workflow_id: str
    call_count: int
    total_tokens: int
    max_tokens: int
    agent_label: str


@dataclass(frozen=True, slots=True)
class IntentSnapshot:
    intent_id: str
    status: str
    ownership: str
    scope_file_count: int
    allowed_files: tuple[str, ...]
    declared_at_utc: str
    lease_remaining_seconds: int


@dataclass(frozen=True, slots=True)
class AgentSnapshot:
    pid: int
    start_epoch: int
    label: str
    alive: bool
    intents: tuple[IntentSnapshot, ...]


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    root: Path
    agents: tuple[AgentSnapshot, ...]
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
    top_workflows: tuple[WorkflowFootprintSnapshot, ...] = ()


def collect_session_snapshot(root_path: Path) -> SessionSnapshot:
    from ..surfaces.mcp._workspace_intents import (
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
    agent_intents: dict[tuple[int, int], list[IntentSnapshot]] = defaultdict(list)
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
            IntentSnapshot(
                intent_id=record.intent_id,
                status=record.status,
                ownership=ownership.value,
                scope_file_count=len(allowed_files),
                allowed_files=tuple(sorted(allowed_files)),
                declared_at_utc=record.declared_at_utc,
                lease_remaining_seconds=lease_remaining,
            )
        )

    agents: list[AgentSnapshot] = []
    for agent_key in sorted(agent_intents):
        pid, start_epoch = agent_key
        agents.append(
            AgentSnapshot(
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

    mcp_tokens, mcp_enc, mcp_count, top_workflows = _read_audit_token_footprint(
        root_path
    )
    audit_enabled, audit_storage = _read_audit_config(root_path)
    from ..config.intent_registry import intent_registry_summary

    registry = intent_registry_summary(root_path)

    return SessionSnapshot(
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
        top_workflows=top_workflows,
    )


def _live_agent_count(snapshot: SessionSnapshot) -> int:
    return sum(1 for agent in snapshot.agents if agent.alive)


def _active_intent_count(snapshot: SessionSnapshot) -> int:
    return sum(
        1
        for agent in snapshot.agents
        for intent in agent.intents
        if agent.alive and intent.status == "active"
    )


def _visible_intent_count(snapshot: SessionSnapshot) -> int:
    return sum(len(agent.intents) for agent in snapshot.agents)


def _classify_workspace_health(
    *,
    agents: list[AgentSnapshot] | tuple[AgentSnapshot, ...],
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


def _has_scope_overlap(agents: list[AgentSnapshot]) -> bool:
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
    from ..surfaces.mcp._workspace_intents import _lease_expiry

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
        from ..audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
        from ..config.pyproject_loader import (
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
) -> tuple[int | None, str | None, int, tuple[WorkflowFootprintSnapshot, ...]]:
    """Read aggregate token estimation from audit trail, if available."""
    try:
        from ..audit.reader import read_audit_summary
        from ..audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
        from ..config.pyproject_loader import (
            load_pyproject_config,
        )

        config = load_pyproject_config(root_path)
        if not bool(config.get("audit_enabled", False)):
            return None, None, 0, ()
        db_path = resolve_audit_path(
            root_path=root_path,
            value=config.get("audit_path", DEFAULT_AUDIT_PATH),
        )
        if not db_path.is_file():
            return None, None, 0, ()
        summary = read_audit_summary(db_path=db_path, limit=1)
        footprint = summary.payload_footprint
        if footprint is not None:
            workflows = tuple(
                WorkflowFootprintSnapshot(
                    workflow_kind=workflow.workflow_kind,
                    workflow_id=workflow.workflow_id,
                    call_count=workflow.call_count,
                    total_tokens=workflow.total_tokens,
                    max_tokens=workflow.max_tokens,
                    agent_label=workflow.agent_label,
                )
                for workflow in footprint.top_workflows[:_MAX_TOP_WORKFLOWS_SHOWN]
            )
            return (
                footprint.total_tokens,
                footprint.encoding,
                footprint.tool_calls,
                workflows,
            )
        return (
            summary.total_estimated_tokens,
            summary.token_encoding,
            summary.token_event_count,
            (),
        )
    except Exception:
        return None, None, 0, ()


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


def session_snapshot_to_payload(snapshot: SessionSnapshot) -> dict[str, object]:
    agents = [
        {
            "pid": agent.pid,
            "start_epoch": agent.start_epoch,
            "label": agent.label,
            "alive": agent.alive,
            "intents": [
                {
                    "intent_id": intent.intent_id,
                    "status": intent.status,
                    "ownership": intent.ownership,
                    "scope_file_count": intent.scope_file_count,
                    "allowed_files": list(intent.allowed_files),
                    "declared_at_utc": intent.declared_at_utc,
                    "lease_remaining_seconds": intent.lease_remaining_seconds,
                }
                for intent in agent.intents
            ],
        }
        for agent in snapshot.agents
    ]
    workflows = [
        {
            "workflow_kind": workflow.workflow_kind,
            "workflow_id": workflow.workflow_id,
            "call_count": workflow.call_count,
            "total_tokens": workflow.total_tokens,
            "max_tokens": workflow.max_tokens,
            "agent_label": workflow.agent_label,
        }
        for workflow in snapshot.top_workflows
    ]
    return {
        "status": "ok",
        "workspace": {
            "root": str(snapshot.root),
            "health": snapshot.workspace_health,
            "intent_registry_backend": snapshot.intent_registry_backend,
            "intent_registry_storage": snapshot.intent_registry_storage,
        },
        "counts": {
            "live_agents": _live_agent_count(snapshot),
            "active_intents": _active_intent_count(snapshot),
            "visible_intents": _visible_intent_count(snapshot),
            "stale": snapshot.stale_count,
            "expired": snapshot.expired_count,
            "recoverable": snapshot.recoverable_count,
        },
        "latest_run": {
            "run_id": snapshot.latest_run_id,
            "health": snapshot.latest_run_health,
            "findings": snapshot.latest_run_findings,
            "files": snapshot.latest_run_files,
            "age_seconds": snapshot.latest_run_age_seconds,
            "cache_present": snapshot.cache_present,
        },
        "audit": {
            "enabled": snapshot.audit_enabled,
            "storage": snapshot.audit_storage,
        },
        "token_footprint": {
            "total_tokens": snapshot.mcp_token_footprint,
            "encoding": snapshot.mcp_token_encoding,
            "tool_calls": snapshot.mcp_token_event_count,
        },
        "top_workflows": workflows,
        "agents": agents,
    }


def workspace_session_stats_payload(root_path: Path) -> dict[str, object]:
    return session_snapshot_to_payload(collect_session_snapshot(root_path))


__all__ = [
    "AgentSnapshot",
    "IntentSnapshot",
    "SessionSnapshot",
    "WorkflowFootprintSnapshot",
    "_active_intent_count",
    "_format_age",
    "_format_duration",
    "_live_agent_count",
    "_visible_intent_count",
    "collect_session_snapshot",
    "session_snapshot_to_payload",
    "workspace_session_stats_payload",
]
