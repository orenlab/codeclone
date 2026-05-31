# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from ...config.memory import resolve_memory_config
from ...report.meta import current_report_timestamp_utc
from ..models import IngestionRun, MemoryProject, RecordBatch, generate_memory_id
from ..project import (
    GitProvenance,
    analysis_fingerprint_from_report,
    read_git_provenance,
    report_digest_from_report,
    resolve_memory_db_path,
    resolve_project_identity,
)
from ..schema import create_schema_v1, open_memory_db
from ..sqlite_store import SqliteEngineeringMemoryStore
from ..staleness import apply_refresh_staleness
from ..vacuum import run_memory_vacuum
from . import InitOptions, InitReport
from .extractors import (
    extract_contract_notes,
    extract_contradictions,
    extract_document_links,
    extract_git_hotspots,
    extract_module_roles,
    extract_public_surfaces,
    extract_risk_notes,
    extract_test_anchors,
    merge_batches,
)


def build_init_batch(
    *,
    root_path: Path,
    project: object,
    report_document: Mapping[str, object],
    git: object,
    report_digest: str | None,
    analysis_fingerprint: str | None,
    options: InitOptions,
) -> RecordBatch:
    if not isinstance(project, MemoryProject):
        raise TypeError("project must be MemoryProject")
    if not isinstance(git, GitProvenance):
        raise TypeError("git must be GitProvenance")

    batches = [
        extract_module_roles(
            project=project,
            report_document=report_document,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
        ),
        extract_contract_notes(
            project=project,
            root_path=root_path,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
        ),
        extract_public_surfaces(
            project=project,
            root_path=root_path,
            report_document=report_document,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
        ),
        extract_risk_notes(
            project=project,
            report_document=report_document,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
        ),
        extract_git_hotspots(
            project=project,
            root_path=root_path,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
        ),
        extract_contradictions(
            project=project,
            root_path=root_path,
            git=git,
            report_digest=report_digest,
            analysis_fingerprint=analysis_fingerprint,
        ),
    ]
    if options.include_tests:
        batches.append(
            extract_test_anchors(
                project=project,
                root_path=root_path,
                git=git,
                report_digest=report_digest,
                analysis_fingerprint=analysis_fingerprint,
            )
        )
    if options.include_docs:
        batches.append(
            extract_document_links(
                project=project,
                root_path=root_path,
                git=git,
                report_digest=report_digest,
                analysis_fingerprint=analysis_fingerprint,
            )
        )
    return merge_batches(batches)


def planned_type_counts(batch: RecordBatch) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in batch.records:
        counter[str(record.type)] += 1
    return dict(sorted(counter.items()))


def run_memory_init(
    *,
    root_path: Path,
    report_document: Mapping[str, object],
    options: InitOptions,
) -> InitReport:
    resolved_root = root_path.resolve()
    config = resolve_memory_config(resolved_root)
    db_path = resolve_memory_db_path(resolved_root, config)
    project = resolve_project_identity(resolved_root)
    git = read_git_provenance(resolved_root)
    analysis_fingerprint = analysis_fingerprint_from_report(dict(report_document))
    report_digest = report_digest_from_report(dict(report_document))

    batch = build_init_batch(
        root_path=resolved_root,
        project=project,
        report_document=report_document,
        git=git,
        report_digest=report_digest,
        analysis_fingerprint=analysis_fingerprint,
        options=options,
    )
    planned = planned_type_counts(batch)

    if options.dry_run:
        conn = open_memory_db(Path(":memory:"))
        try:
            create_schema_v1(conn)
        finally:
            conn.close()
        return InitReport(
            project_id=project.id,
            db_path=None,
            dry_run=True,
            analysis_fingerprint=analysis_fingerprint,
            planned_counts=planned,
            git=git,
        )

    store = SqliteEngineeringMemoryStore(db_path)
    started = current_report_timestamp_utc()
    ingestion_run = IngestionRun(
        id=generate_memory_id(prefix="mem-init"),
        project_id=project.id,
        mode="refresh" if options.refresh else "init",
        started_at_utc=started,
        finished_at_utc=None,
        status="running",
        analysis_fingerprint=analysis_fingerprint,
        report_digest=report_digest,
        branch=git.branch,
        commit=git.head,
    )
    stats: dict[str, int] = {}
    stale_marked = 0
    vacuum_deleted = 0
    try:
        with store.exclusive_init_lock():
            store.initialize(project)
            with store.transaction():
                stats = store.persist_batch(batch)
                if options.refresh:
                    stale_report = apply_refresh_staleness(
                        store,
                        project_id=project.id,
                        batch=batch,
                        report_document=report_document,
                        commit=False,
                    )
                    stale_marked = stale_report.records_marked_stale
                    vacuum_report = run_memory_vacuum(
                        store,
                        config,
                        commit=False,
                    )
                    vacuum_deleted = vacuum_report.total_deleted
                ingestion_run = IngestionRun(
                    id=ingestion_run.id,
                    project_id=ingestion_run.project_id,
                    mode=ingestion_run.mode,
                    started_at_utc=ingestion_run.started_at_utc,
                    finished_at_utc=current_report_timestamp_utc(),
                    status="completed",
                    analysis_fingerprint=ingestion_run.analysis_fingerprint,
                    report_digest=ingestion_run.report_digest,
                    branch=ingestion_run.branch,
                    commit=ingestion_run.commit,
                    records_created=stats.get("created", 0),
                    records_updated=stats.get("updated", 0),
                    records_marked_stale=stale_marked,
                    candidates_created=planned.get("contradiction_note", 0),
                    contradictions_found=planned.get("contradiction_note", 0),
                    message=(
                        f"vacuum_deleted={vacuum_deleted}" if vacuum_deleted else None
                    ),
                )
                store.write_ingestion_run(ingestion_run)
            store.set_meta("last_analysis_fingerprint", analysis_fingerprint or "")
            store.set_meta("last_report_digest", report_digest or "")
            store.set_meta("last_init_run_id", ingestion_run.id)
            store.set_meta("project_id", project.id)
            store.set_meta("project_root", project.root)
    finally:
        store.close()

    return InitReport(
        project_id=project.id,
        db_path=db_path,
        dry_run=False,
        analysis_fingerprint=analysis_fingerprint,
        stats=stats,
        planned_counts=planned,
        git=git,
    )


__all__ = ["build_init_batch", "planned_type_counts", "run_memory_init"]
