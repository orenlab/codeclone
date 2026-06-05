# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from .. import __version__
from .events import (
    ANALYSIS_SOURCE_CLI,
    ANALYSIS_SOURCE_MCP,
    EVENT_ANALYSIS_COMPLETED,
    AnalysisSource,
    AuditEvent,
    repo_root_digest,
)
from .writer import AuditWriter, NullAuditWriter


def analysis_completed_payload(
    *,
    summary: Mapping[str, object],
    source: AnalysisSource,
) -> dict[str, object]:
    """Build the audit payload for ``analysis.completed`` from a run summary."""

    health = _mapping(summary.get("health"))
    findings = _findings_summary(summary)
    inventory = _mapping(summary.get("inventory"))
    diff = _mapping(summary.get("diff"))
    return {
        "source": source,
        "focus": str(summary.get("focus", "repository")),
        "mode": _analysis_mode(summary),
        "schema": str(summary.get("schema", summary.get("report_schema_version", ""))),
        "health": {
            "score": health.get("score"),
            "grade": health.get("grade"),
        },
        "findings": {
            "total": findings.get("total"),
            "new": findings.get("new"),
        },
        "inventory": {
            "files": inventory.get("files"),
            "lines": inventory.get("lines"),
            "functions": inventory.get("functions"),
        },
        "diff": {
            "new_clones": diff.get("new_clones"),
            "health_delta": diff.get("health_delta"),
        },
    }


def analysis_completed_payload_from_report(
    *,
    report_document: Mapping[str, object],
    source: AnalysisSource,
    new_func_count: int,
    new_block_count: int,
) -> dict[str, object]:
    """Build an analysis.completed payload from a canonical report document."""

    meta = _mapping(report_document.get("meta"))
    runtime = _mapping(meta.get("runtime"))
    inventory = _mapping(report_document.get("inventory"))
    file_registry = _mapping(inventory.get("file_registry"))
    findings = _mapping(report_document.get("findings"))
    findings_summary = _mapping(findings.get("summary"))
    metrics = _mapping(report_document.get("metrics"))
    metrics_summary = _mapping(metrics.get("summary"))
    health = _mapping(metrics_summary.get("health"))
    return {
        "source": source,
        "focus": "repository",
        "mode": str(runtime.get("analysis_mode", meta.get("analysis_mode", "full"))),
        "schema": str(report_document.get("report_schema_version", "")),
        "health": {
            "score": health.get("score", meta.get("health_score")),
            "grade": health.get("grade", meta.get("health_grade")),
        },
        "findings": {
            "total": findings_summary.get("total", findings.get("total")),
            "new": findings_summary.get("new"),
        },
        "inventory": {
            "files": len(_sequence(file_registry.get("items"))),
            "lines": inventory.get("lines"),
            "functions": inventory.get("functions"),
        },
        "diff": {
            "new_clones": new_func_count + new_block_count,
            "health_delta": None,
        },
    }


def emit_analysis_completed(
    *,
    root_path: Path,
    summary: Mapping[str, object],
    source: AnalysisSource,
    report_digest: str,
    run_id: str,
    agent_pid: int,
    agent_start_epoch: int,
    agent_label: str,
    writer: AuditWriter | None = None,
) -> None:
    """Append an ``analysis.completed`` audit row when audit is enabled."""

    from .runtime import open_audit_writer_for_root

    active_writer = (
        writer if writer is not None else open_audit_writer_for_root(root_path)
    )
    if isinstance(active_writer, NullAuditWriter):
        return
    payload = analysis_completed_payload(summary=summary, source=source)
    status = _analysis_mode(summary)
    active_writer.emit(
        AuditEvent(
            event_type=EVENT_ANALYSIS_COMPLETED,
            severity="info",
            repo_root_digest=repo_root_digest(root_path),
            agent_pid=agent_pid,
            agent_start_epoch=agent_start_epoch,
            agent_label=agent_label,
            run_id=run_id,
            report_digest=report_digest,
            status=status,
            payload=payload,
        )
    )


def emit_analysis_completed_from_report(
    *,
    root_path: Path,
    report_document: Mapping[str, object],
    report_digest: str,
    run_id: str,
    source: AnalysisSource,
    new_func_count: int,
    new_block_count: int,
    agent_pid: int | None = None,
    agent_start_epoch: int | None = None,
    agent_label: str | None = None,
    writer: AuditWriter | None = None,
) -> None:
    payload = analysis_completed_payload_from_report(
        report_document=report_document,
        source=source,
        new_func_count=new_func_count,
        new_block_count=new_block_count,
    )
    summary = {
        **payload,
        "focus": payload["focus"],
        "mode": payload["mode"],
        "schema": payload["schema"],
        "health": payload["health"],
        "findings": payload["findings"],
        "inventory": payload["inventory"],
        "diff": payload["diff"],
    }
    emit_analysis_completed(
        root_path=root_path,
        summary=summary,
        source=source,
        report_digest=report_digest,
        run_id=run_id,
        agent_pid=agent_pid if agent_pid is not None else os.getpid(),
        agent_start_epoch=agent_start_epoch if agent_start_epoch is not None else 0,
        agent_label=agent_label or f"codeclone-cli/{__version__}",
        writer=writer,
    )


def _analysis_mode(summary: Mapping[str, object]) -> str:
    mode = summary.get("mode") or summary.get("analysis_mode")
    if mode is None:
        return "completed"
    text = str(mode).strip()
    return text or "completed"


def _findings_summary(summary: Mapping[str, object]) -> Mapping[str, object]:
    findings = _mapping(summary.get("findings"))
    if findings:
        return findings
    return _mapping(summary.get("findings_summary"))


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, str):
        return ()
    if isinstance(value, list):
        return tuple(value)
    return ()


__all__ = [
    "ANALYSIS_SOURCE_CLI",
    "ANALYSIS_SOURCE_MCP",
    "AnalysisSource",
    "analysis_completed_payload",
    "analysis_completed_payload_from_report",
    "emit_analysis_completed",
    "emit_analysis_completed_from_report",
]
