# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Read-only workspace intent gate for local enforcement hooks.

The workspace intent registry is the durable coordination source for agent
change-control. MCP writes it; hooks read it. This module intentionally exposes a
small public read API so plugin hooks do not parse registry files or assume a
specific registry backend. Queued intents remain visible but do not authorize
local edit hooks.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from codeclone.config.intent_registry import (
    IntentRegistryConfig,
    IntentRegistryConfigError,
    resolve_intent_registry_config,
)
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_contract import WorkspaceIntentRecord
from codeclone.surfaces.mcp._workspace_intent_lifecycle import (
    WorkspaceIntentStatus,
    is_terminal_workspace_intent_status,
    utc_now,
)
from codeclone.surfaces.mcp._workspace_intent_models import (
    parse_workspace_document,
    parse_workspace_document_json,
    record_from_document,
)
from codeclone.surfaces.mcp._workspace_intent_paths import (
    read_payload,
    record_sort_key,
    registry_files,
)

GateReason = Literal[
    "active_intent",
    "no_active_intent",
    "queued_intent_not_editable",
    "registry_error",
]

_ALLOWING_OWNERSHIP: frozenset[workspace_intents.IntentOwnership] = frozenset(
    {
        workspace_intents.IntentOwnership.OWN_ACTIVE,
        workspace_intents.IntentOwnership.FOREIGN_ACTIVE,
    }
)


@dataclass(frozen=True, slots=True)
class WorkspaceEditGateDecision:
    """Structured read-only decision for local hook enforcement."""

    allowed: bool
    reason: GateReason
    intent_id: str | None = None
    status: str | None = None
    ownership: str | None = None
    agent_label: str | None = None
    registry_backend: str | None = None
    registry_path: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


def evaluate_workspace_edit_gate(root: Path | str) -> WorkspaceEditGateDecision:
    """Return whether repository writes are authorized by a live intent record.

    The function is read-only: it does not lazy-close records, migrate SQLite
    schemas, create registry directories, or write marker files.
    """

    root_path = Path(root).resolve()
    try:
        config = resolve_intent_registry_config(root_path)
    except (IntentRegistryConfigError, OSError, ValueError) as exc:
        return WorkspaceEditGateDecision(
            allowed=False,
            reason="registry_error",
            registry_backend=None,
            registry_path=None,
            details={"error": str(exc)},
        )

    try:
        records = _load_registry_records_read_only(root_path, config)
    except (OSError, sqlite3.Error, ValueError) as exc:
        return WorkspaceEditGateDecision(
            allowed=False,
            reason="registry_error",
            registry_backend=config.backend,
            registry_path=_display_registry_path(root_path, config.storage_path),
            details={"error": str(exc)},
        )

    return _decision_from_records(
        records,
        registry_backend=config.backend,
        registry_path=_display_registry_path(root_path, config.storage_path),
    )


def has_authorized_workspace_intent(root: Path | str) -> bool:
    """True when a live active registry intent authorizes local hook writes."""

    return evaluate_workspace_edit_gate(root).allowed


def has_blocking_workspace_intent(root: Path | str) -> bool:
    """Compatibility boolean for hooks that historically asked for a lock."""

    return has_authorized_workspace_intent(root)


def _decision_from_records(
    records: Iterable[WorkspaceIntentRecord],
    *,
    registry_backend: str,
    registry_path: str,
) -> WorkspaceEditGateDecision:
    current_time = utc_now()
    queued: WorkspaceIntentRecord | None = None
    ignored_count = 0
    for record in sorted(records, key=record_sort_key):
        if not is_terminal_workspace_intent_status(record.status):
            ownership = workspace_intents.classify_intent_ownership(
                record,
                own_pid=0,
                own_start_epoch=0,
                now=current_time,
            )
            if record.status == WorkspaceIntentStatus.QUEUED.value:
                queued = queued or record
                continue
            if (
                record.status == WorkspaceIntentStatus.ACTIVE.value
                and ownership in _ALLOWING_OWNERSHIP
            ):
                return WorkspaceEditGateDecision(
                    allowed=True,
                    reason="active_intent",
                    intent_id=record.intent_id,
                    status=record.status,
                    ownership=ownership.value,
                    agent_label=record.agent_label,
                    registry_backend=registry_backend,
                    registry_path=registry_path,
                    details={
                        "run_id": record.run_id[:8],
                        "lease_seconds": record.lease_seconds,
                    },
                )
        if record.status != WorkspaceIntentStatus.QUEUED.value:
            ignored_count += 1
    if queued is not None:
        return WorkspaceEditGateDecision(
            allowed=False,
            reason="queued_intent_not_editable",
            intent_id=queued.intent_id,
            status=queued.status,
            agent_label=queued.agent_label,
            registry_backend=registry_backend,
            registry_path=registry_path,
            details={"ignored_records": ignored_count},
        )
    return WorkspaceEditGateDecision(
        allowed=False,
        reason="no_active_intent",
        registry_backend=registry_backend,
        registry_path=registry_path,
        details={"ignored_records": ignored_count},
    )


def _load_registry_records_read_only(
    root: Path,
    config: IntentRegistryConfig,
) -> tuple[WorkspaceIntentRecord, ...]:
    if config.backend == "file":
        return _load_file_records(root)
    if config.backend == "sqlite":
        return _load_sqlite_records(config.storage_path)
    raise ValueError(f"Unsupported intent registry backend: {config.backend!r}")


def _load_file_records(root: Path) -> tuple[WorkspaceIntentRecord, ...]:
    records: list[WorkspaceIntentRecord] = []
    for path in registry_files(root):
        payload = read_payload(path)
        record = _record_from_payload(payload)
        if record is not None:
            records.append(record)
    return tuple(sorted(records, key=record_sort_key))


def _load_sqlite_records(db_path: Path) -> tuple[WorkspaceIntentRecord, ...]:
    if not db_path.is_file():
        return ()
    uri = f"file:{quote(str(db_path), safe='/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            """
            SELECT payload_json
            FROM workspace_intents
            ORDER BY declared_at_utc, agent_pid, intent_id
            """
        ).fetchall()
    finally:
        conn.close()
    records = [
        record
        for record in (_record_from_payload(row[0]) for row in rows)
        if record is not None
    ]
    return tuple(sorted(records, key=record_sort_key))


def _record_from_payload(payload: object) -> WorkspaceIntentRecord | None:
    if isinstance(payload, str):
        document = parse_workspace_document_json(payload)
    elif isinstance(payload, Mapping):
        document = parse_workspace_document(payload)
    else:
        return None
    if document is None:
        return None
    return record_from_document(document)


def _display_registry_path(root: Path, registry_path: Path) -> str:
    try:
        return str(registry_path.relative_to(root))
    except ValueError:
        return str(registry_path)


__all__ = [
    "WorkspaceEditGateDecision",
    "evaluate_workspace_edit_gate",
    "has_authorized_workspace_intent",
    "has_blocking_workspace_intent",
]
