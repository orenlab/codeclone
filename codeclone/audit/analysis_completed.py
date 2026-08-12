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
from ..utils.mapping_paths import sections
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
    """Build the audit payload for ``analysis.completed`` from a run summary.

    The summary is the canonical run summary a surface publishes -- the same
    object the MCP session returns to its caller -- where every figure is
    already a count. The session's *internal* summary carries the report
    document's own sub-blocks under these names instead, so feeding that one
    here recorded a mapping where a file count belongs.
    """

    health = _mapping(summary.get("health"))
    findings = _mapping(summary.get("findings"))
    inventory = _mapping(summary.get("inventory"))
    diff = _mapping(summary.get("diff"))
    return {
        "source": source,
        "focus": str(summary.get("focus", "repository")),
        "mode": _mode_text(summary.get("mode")),
        "schema": str(summary.get("schema", "")),
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
    new_func_count: int | None,
    new_block_count: int | None,
) -> dict[str, object]:
    """Build an analysis.completed payload from a canonical report document.

    ``None`` counts mean no clone lane was compared against the baseline, and
    the recorded ``diff.new_clones`` stays null rather than claiming a zero the
    run never measured.

    Every figure is the one the document publishes. The file count in
    particular is ``inventory.files.total_found`` and not the length of the
    file registry: the registry lists the paths that resolved under the scan
    root, so counting it here was a second counter of a fact the document
    already carries, and the two disagree whenever a path does not resolve.
    """

    (
        meta,
        inventory_files,
        inventory_code,
        findings_summary,
        health,
    ) = sections(
        report_document,
        "meta",
        "inventory.files",
        "inventory.code",
        "findings.summary",
        "metrics.summary.health",
    )
    return {
        "source": source,
        "focus": "repository",
        "mode": _mode_text(meta.get("analysis_mode")),
        "schema": str(report_document.get("report_schema_version", "")),
        "health": {
            "score": health.get("score"),
            "grade": health.get("grade"),
        },
        "findings": {
            "total": findings_summary.get("total"),
            # The document publishes novelty per finding and a clone-lane
            # rollup, but no cross-family "new" total. Counting the groups here
            # would be a second counter of a fact the document does not claim,
            # so the row records the absence instead.
            "new": None,
        },
        "inventory": {
            "files": inventory_files.get("total_found"),
            "lines": inventory_code.get("parsed_lines"),
            # Methods are function definitions too, and the MCP surface records
            # this same field with methods included. One event field cannot
            # mean two things depending on which surface wrote the row.
            "functions": _summed_counts(
                inventory_code.get("functions"),
                inventory_code.get("methods"),
            ),
        },
        "diff": {
            "new_clones": (
                None
                if new_func_count is None or new_block_count is None
                else new_func_count + new_block_count
            ),
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

    _emit_payload(
        root_path=root_path,
        payload=analysis_completed_payload(summary=summary, source=source),
        source=source,
        report_digest=report_digest,
        run_id=run_id,
        agent_pid=agent_pid,
        agent_start_epoch=agent_start_epoch,
        agent_label=agent_label,
        writer=writer,
    )


def _emit_payload(
    *,
    root_path: Path,
    payload: Mapping[str, object],
    source: AnalysisSource,
    report_digest: str,
    run_id: str,
    agent_pid: int,
    agent_start_epoch: int,
    agent_label: str,
    writer: AuditWriter | None,
) -> None:
    """Write one built payload, or nothing when audit is disabled.

    Both entry points build their own payload from the shape they are handed
    and hand it here. Re-deriving one payload from the other through a
    synthesized summary is what made a builder change able to reach the wire
    twice, in two different spellings.
    """

    from .runtime import open_audit_writer_for_root

    active_writer = (
        writer if writer is not None else open_audit_writer_for_root(root_path)
    )
    if isinstance(active_writer, NullAuditWriter):
        return
    status = _mode_text(payload.get("mode"))
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
            payload=dict(payload),
            surface=source,
            tool_name=f"{source}:analysis",
        )
    )


def emit_analysis_completed_from_report(
    *,
    root_path: Path,
    report_document: Mapping[str, object],
    report_digest: str,
    run_id: str,
    source: AnalysisSource,
    new_func_count: int | None,
    new_block_count: int | None,
    agent_pid: int | None = None,
    agent_start_epoch: int | None = None,
    agent_label: str | None = None,
    writer: AuditWriter | None = None,
) -> None:
    _emit_payload(
        root_path=root_path,
        payload=analysis_completed_payload_from_report(
            report_document=report_document,
            source=source,
            new_func_count=new_func_count,
            new_block_count=new_block_count,
        ),
        source=source,
        report_digest=report_digest,
        run_id=run_id,
        agent_pid=agent_pid if agent_pid is not None else os.getpid(),
        agent_start_epoch=agent_start_epoch if agent_start_epoch is not None else 0,
        agent_label=agent_label or f"codeclone-cli/{__version__}",
        writer=writer,
    )


def _mode_text(mode: object) -> str:
    """One spelling of an analysis mode, and "completed" when there is none."""

    if mode is None:
        return "completed"
    text = str(mode).strip()
    return text or "completed"


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _summed_counts(*values: object) -> int | None:
    """Add the counts that were published, or answer None when none was.

    A run that never counted entities publishes neither, and a zero there
    would be a measurement the run did not make.
    """

    counts = [
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool)
    ]
    return sum(counts) if counts else None


__all__ = [
    "ANALYSIS_SOURCE_CLI",
    "ANALYSIS_SOURCE_MCP",
    "AnalysisSource",
    "analysis_completed_payload",
    "analysis_completed_payload_from_report",
    "emit_analysis_completed",
    "emit_analysis_completed_from_report",
]
