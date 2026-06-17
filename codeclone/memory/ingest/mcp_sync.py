# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ...config.memory import MemoryConfig, resolve_memory_config
from ..project import report_digest_from_report, resolve_memory_db_path
from ..sqlite_store import SqliteEngineeringMemoryStore
from . import InitOptions, InitReport
from .runner import run_memory_init

MemorySyncAction = Literal["bootstrap", "refresh", "none"]
MemorySyncStatus = Literal["completed", "skipped", "unchanged"]
MemorySyncTrigger = Literal["auto", "explicit"]


@dataclass(frozen=True, slots=True)
class MemorySyncDecision:
    action: MemorySyncAction
    reason: str


def read_stored_report_digest(db_path: Path) -> str | None:
    if not db_path.exists():
        return None
    store = SqliteEngineeringMemoryStore(db_path)
    try:
        return store.get_meta("last_report_digest")
    finally:
        store.close()


def decide_mcp_memory_sync(
    *,
    policy: str,
    db_path: Path,
    report_digest: str,
    stored_digest: str | None,
) -> MemorySyncDecision:
    if policy == "off":
        return MemorySyncDecision(action="none", reason="policy_off")
    if not db_path.exists():
        return MemorySyncDecision(action="bootstrap", reason="missing_db")
    if policy == "refresh_when_stale":
        if stored_digest != report_digest:
            return MemorySyncDecision(action="refresh", reason="digest_changed")
        return MemorySyncDecision(action="none", reason="digest_unchanged")
    return MemorySyncDecision(action="none", reason="db_present")


def sync_report_document_to_memory(
    *,
    root_path: Path,
    report_document: Mapping[str, object],
    refresh: bool,
) -> InitReport:
    return run_memory_init(
        root_path=root_path,
        report_document=report_document,
        options=InitOptions(
            refresh=refresh,
            include_docs=True,
            include_tests=True,
        ),
    )


def memory_sync_result_payload(
    *,
    status: MemorySyncStatus,
    trigger: MemorySyncTrigger,
    run_id: str,
    report_digest: str | None,
    init_report: InitReport | None,
    reason: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "trigger": trigger,
        "run_id": run_id,
        "report_digest": report_digest,
        "reason": reason,
    }
    if init_report is None:
        return payload
    payload.update(
        {
            "mode": "refresh"
            if init_report.ingestion_mode == "refresh"
            else "bootstrap",
            "project_id": init_report.project_id,
            "db_path": str(init_report.db_path) if init_report.db_path else None,
            "analysis_fingerprint": init_report.analysis_fingerprint,
            "stats": dict(init_report.stats),
            "planned_counts": dict(init_report.planned_counts),
            "records_marked_stale": init_report.records_marked_stale,
            "vacuum_deleted": init_report.vacuum_deleted,
        }
    )
    return payload


def _complete_memory_sync(
    *,
    root_path: Path,
    report_document: Mapping[str, object],
    trigger: MemorySyncTrigger,
    run_id: str,
    report_digest: str,
    refresh: bool,
    reason: str,
) -> dict[str, object]:
    init_report = sync_report_document_to_memory(
        root_path=root_path,
        report_document=report_document,
        refresh=refresh,
    )
    return memory_sync_result_payload(
        status="completed",
        trigger=trigger,
        run_id=run_id,
        report_digest=report_digest,
        init_report=init_report,
        reason=reason,
    )


def execute_mcp_memory_sync(
    *,
    root_path: Path,
    report_document: Mapping[str, object],
    config: MemoryConfig | None = None,
    trigger: MemorySyncTrigger,
    run_id: str,
    force: bool = False,
) -> dict[str, object]:
    resolved_root = root_path.resolve()
    resolved_config = config or resolve_memory_config(resolved_root)
    db_path = resolve_memory_db_path(resolved_root, resolved_config)
    report_digest = report_digest_from_report(dict(report_document))
    stored_digest = read_stored_report_digest(db_path)

    if report_digest is None:
        return memory_sync_result_payload(
            status="skipped",
            trigger=trigger,
            run_id=run_id,
            report_digest=None,
            init_report=None,
            reason="missing_report_digest",
        )

    if force or trigger == "explicit":
        return _complete_memory_sync(
            root_path=resolved_root,
            report_document=report_document,
            trigger=trigger,
            run_id=run_id,
            report_digest=report_digest,
            refresh=db_path.exists(),
            reason="forced" if force else "explicit_refresh",
        )

    decision = decide_mcp_memory_sync(
        policy=resolved_config.mcp_sync_policy,
        db_path=db_path,
        report_digest=report_digest,
        stored_digest=stored_digest,
    )
    if decision.action == "none":
        return memory_sync_result_payload(
            status="unchanged",
            trigger=trigger,
            run_id=run_id,
            report_digest=report_digest,
            init_report=None,
            reason=decision.reason,
        )

    return _complete_memory_sync(
        root_path=resolved_root,
        report_document=report_document,
        trigger=trigger,
        run_id=run_id,
        report_digest=report_digest,
        refresh=decision.action == "refresh",
        reason=decision.reason,
    )


__all__ = [
    "MemorySyncAction",
    "MemorySyncDecision",
    "MemorySyncStatus",
    "MemorySyncTrigger",
    "decide_mcp_memory_sync",
    "execute_mcp_memory_sync",
    "memory_sync_result_payload",
    "read_stored_report_digest",
    "sync_report_document_to_memory",
]
