# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..utils.coerce import as_mapping, as_sequence
from .models import RecordBatch
from .sqlite_store import SqliteEngineeringMemoryStore, record_content_equal


@dataclass(frozen=True, slots=True)
class StalenessReport:
    records_marked_stale: int
    reasons: dict[str, int]


def inventory_paths_from_report(
    report_document: Mapping[str, object],
) -> frozenset[str]:
    inventory = as_mapping(report_document.get("inventory"))
    file_registry = as_mapping(inventory.get("file_registry"))
    file_items = as_sequence(file_registry.get("items"))
    paths: set[str] = set()
    for item in file_items:
        file_path = str(item).replace("\\", "/").strip("/")
        if file_path:
            paths.add(file_path)
    return frozenset(paths)


def _batch_evidence_index(
    batch: RecordBatch,
) -> dict[tuple[str, str, str], str | None]:
    record_identity: dict[str, str] = {
        record.id: record.identity_key for record in batch.records
    }
    index: dict[tuple[str, str, str], str | None] = {}
    for evidence in batch.evidence:
        identity = record_identity.get(evidence.memory_id)
        if identity is None:
            continue
        key = (identity, evidence.evidence_kind, evidence.ref)
        index[key] = evidence.digest
    return index


def apply_refresh_staleness(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    batch: RecordBatch,
    report_document: Mapping[str, object],
    commit: bool = True,
) -> StalenessReport:
    """Mark affected records stale after a refresh ingest."""
    batch_identity_keys = frozenset(record.identity_key for record in batch.records)
    inventory_paths = inventory_paths_from_report(report_document)
    batch_evidence = _batch_evidence_index(batch)
    batch_by_identity = {record.identity_key: record for record in batch.records}

    reason_counts: dict[str, int] = {}
    marked = 0

    candidates = store.list_records_for_project(
        project_id,
        statuses=("active", "draft"),
    )
    for record in candidates:
        if record.status == "stale":
            continue
        if record.origin == "human":
            continue

        reasons: list[str] = []

        if record.origin == "system" and record.identity_key not in batch_identity_keys:
            reasons.append("missing_from_refresh")

        incoming = batch_by_identity.get(record.identity_key)
        if (
            incoming is not None
            and record.approved_by
            and not record_content_equal(record, incoming)
        ):
            reasons.append("refresh_content_contradiction")

        for subject in store.list_subjects_for_memory(record.id):
            if subject.subject_kind == "path":
                path = subject.subject_key.replace("\\", "/").strip("/")
                if path and path not in inventory_paths:
                    reasons.append("linked_path_missing")
                    break
            if subject.subject_kind == "test":
                path = subject.subject_key.replace("\\", "/").strip("/")
                if path and path not in inventory_paths:
                    reasons.append("linked_test_missing")
                    break

        for evidence in store.list_evidence_for_memory(record.id):
            key = (record.identity_key, evidence.evidence_kind, evidence.ref)
            batch_digest = batch_evidence.get(key)
            if batch_digest is None:
                continue
            if evidence.digest is not None and batch_digest != evidence.digest:
                reasons.append("evidence_digest_mismatch")
                break

        if record.report_digest is not None:
            meta_digest = store.get_meta("last_report_digest")
            if meta_digest and meta_digest != record.report_digest:
                reasons.append("report_digest_shift")

        if not reasons:
            continue
        primary = reasons[0]
        store.mark_stale(record.id, primary, commit=False)
        marked += 1
        reason_counts[primary] = reason_counts.get(primary, 0) + 1

    if commit:
        store.commit()

    return StalenessReport(
        records_marked_stale=marked,
        reasons=dict(sorted(reason_counts.items())),
    )


def apply_scope_staleness(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    changed_paths: Sequence[str],
    commit: bool = True,
) -> StalenessReport:
    """Mark records stale when linked paths were touched in an accepted patch."""
    normalized = frozenset(
        path.replace("\\", "/").strip("/").removeprefix("./") for path in changed_paths
    )
    reason_counts: dict[str, int] = {}
    marked = 0
    for record in store.list_records_for_project(project_id, statuses=("active",)):
        if record.status == "stale":
            continue
        for subject in store.list_subjects_for_memory(record.id):
            subj_path = subject.subject_key.replace("\\", "/").strip("/")
            if subj_path in normalized or any(
                subj_path.startswith(f"{scope}/") for scope in normalized
            ):
                store.mark_stale(
                    record.id,
                    "scope_files_changed",
                    commit=False,
                )
                marked += 1
                reason_counts["scope_files_changed"] = (
                    reason_counts.get("scope_files_changed", 0) + 1
                )
                break
    if commit:
        store.commit()
    return StalenessReport(
        records_marked_stale=marked,
        reasons=dict(sorted(reason_counts.items())),
    )


__all__ = [
    "StalenessReport",
    "apply_refresh_staleness",
    "apply_scope_staleness",
    "inventory_paths_from_report",
]
