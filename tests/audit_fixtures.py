# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from codeclone.audit.analysis_completed import AnalysisSource, emit_analysis_completed
from codeclone.audit.writer import SqliteAuditWriter


def write_compact_analysis_completed_event(
    tmp_path: Path,
    *,
    db_path: Path | None = None,
    summary: Mapping[str, object],
    source: AnalysisSource,
    report_digest: str,
    run_id: str,
    agent_pid: int,
    agent_start_epoch: int,
    agent_label: str,
) -> Path:
    resolved_db = db_path or (tmp_path / "audit.sqlite3")
    writer = SqliteAuditWriter(
        db_path=resolved_db,
        payloads="compact",
        retention_days=30,
    )
    emit_analysis_completed(
        root_path=tmp_path,
        summary=dict(summary),
        source=source,
        report_digest=report_digest,
        run_id=run_id,
        agent_pid=agent_pid,
        agent_start_epoch=agent_start_epoch,
        agent_label=agent_label,
        writer=writer,
    )
    writer.close()
    return resolved_db
