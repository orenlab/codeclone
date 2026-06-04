# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..utils.coerce import as_mapping, as_sequence
from .models import MemoryEvidence, MemoryRecord, MemorySubject, RecordBatch
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


def _skip_refresh_candidate(record: MemoryRecord) -> bool:
    # Drafts are unapproved agent candidates awaiting human governance.
    # Marking them stale before review is premature — they become subject
    # to normal staleness only after promotion to active.
    return record.status in ("stale", "draft") or record.origin == "human"


def _normalize_subject_path(subject_key: str) -> str:
    return subject_key.replace("\\", "/").strip("/")


def _subject_inventory_stale_reason(
    subject: MemorySubject,
    inventory_paths: frozenset[str],
) -> str | None:
    if subject.subject_kind == "path":
        path = _normalize_subject_path(subject.subject_key)
        if path and path not in inventory_paths:
            return "linked_path_missing"
    elif subject.subject_kind == "test":
        path = _normalize_subject_path(subject.subject_key)
        if path and path not in inventory_paths:
            return "linked_test_missing"
    return None


def _subject_stale_reasons(
    subjects: Sequence[MemorySubject],
    inventory_paths: frozenset[str],
) -> list[str]:
    for subject in subjects:
        reason = _subject_inventory_stale_reason(subject, inventory_paths)
        if reason is not None:
            return [reason]
    return []


def _evidence_stale_reasons(
    record: MemoryRecord,
    evidence_items: Sequence[MemoryEvidence],
    batch_evidence: dict[tuple[str, str, str], str | None],
) -> list[str]:
    for evidence in evidence_items:
        key = (record.identity_key, evidence.evidence_kind, evidence.ref)
        batch_digest = batch_evidence.get(key)
        if batch_digest is None:
            continue
        if evidence.digest is not None and batch_digest != evidence.digest:
            return ["evidence_digest_mismatch"]
    return []


def _collect_refresh_staleness_reasons(
    record: MemoryRecord,
    *,
    batch_identity_keys: frozenset[str],
    batch_by_identity: Mapping[str, MemoryRecord],
    batch_evidence: dict[tuple[str, str, str], str | None],
    inventory_paths: frozenset[str],
    report_digest: str | None,
    subjects: Sequence[MemorySubject],
    evidence_items: Sequence[MemoryEvidence],
) -> list[str]:
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

    reasons.extend(_subject_stale_reasons(subjects, inventory_paths))
    reasons.extend(_evidence_stale_reasons(record, evidence_items, batch_evidence))

    if (
        record.report_digest is not None
        and record.identity_key not in batch_identity_keys
        and report_digest is not None
        and record.report_digest != report_digest
    ):
        reasons.append("report_digest_shift")
    return reasons


def _refresh_stale_primary_reason(
    store: SqliteEngineeringMemoryStore,
    record: MemoryRecord,
    *,
    batch_identity_keys: frozenset[str],
    batch_by_identity: Mapping[str, MemoryRecord],
    batch_evidence: dict[tuple[str, str, str], str | None],
    inventory_paths: frozenset[str],
    report_digest: str | None,
) -> str | None:
    if _skip_refresh_candidate(record):
        return None
    reasons = _collect_refresh_staleness_reasons(
        record,
        batch_identity_keys=batch_identity_keys,
        batch_by_identity=batch_by_identity,
        batch_evidence=batch_evidence,
        inventory_paths=inventory_paths,
        report_digest=report_digest,
        subjects=store.list_subjects_for_memory(record.id),
        evidence_items=store.list_evidence_for_memory(record.id),
    )
    return reasons[0] if reasons else None


def apply_refresh_staleness(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    batch: RecordBatch,
    report_document: Mapping[str, object],
    report_digest: str | None = None,
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
        primary = _refresh_stale_primary_reason(
            store,
            record,
            batch_identity_keys=batch_identity_keys,
            batch_by_identity=batch_by_identity,
            batch_evidence=batch_evidence,
            inventory_paths=inventory_paths,
            report_digest=report_digest,
        )
        if primary is None:
            continue
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
