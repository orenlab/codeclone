# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..utils.coerce import as_mapping, as_sequence
from .enums import MemoryStatus
from .models import MemoryEvidence, MemoryRecord, MemorySubject, RecordBatch
from .project import subject_fingerprint_for_subject
from .sqlite_store import SqliteEngineeringMemoryStore, record_content_equal

SUBJECT_FINGERPRINT_DRIFT = "subject_fingerprint_drift"
ANCHOR_SUBJECT_KINDS = ("path", "test", "doc", "module")


@dataclass(frozen=True, slots=True)
class StalenessReport:
    records_marked_stale: int
    records_marked_historical: int
    records_reactivated: int
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
    return record.status == "draft"


def _reactivate_on_fingerprint_match(record: MemoryRecord) -> bool:
    return record.status == "historical" or (
        record.status == "stale" and record.stale_reason == SUBJECT_FINGERPRINT_DRIFT
    )


def _primary_anchor_subject(
    subjects: Sequence[MemorySubject],
) -> MemorySubject | None:
    for kind in ANCHOR_SUBJECT_KINDS:
        for subject in subjects:
            if subject.subject_kind == kind:
                return subject
    return None


def _evaluate_anchor_drift_status(
    record: MemoryRecord,
    *,
    anchor_subject: MemorySubject,
    root_path: Path,
) -> MemoryStatus | None:
    if not record.created_at_commit or record.code_fingerprint is None:
        return None

    current_fingerprint = subject_fingerprint_for_subject(root_path, anchor_subject)
    anchored_fingerprint = record.code_fingerprint

    if current_fingerprint is None:
        if record.status == "historical":
            return None
        return "historical"

    if current_fingerprint == anchored_fingerprint:
        if _reactivate_on_fingerprint_match(record):
            return "active"
        return None

    return "stale"


@dataclass(frozen=True, slots=True)
class _AnchorDriftOutcome:
    handled: bool
    marked_stale: int = 0
    marked_historical: int = 0
    reactivated: int = 0
    counter_key: str | None = None


@dataclass(frozen=True, slots=True)
class _DriftTransitionSpec:
    apply: Callable[[SqliteEngineeringMemoryStore, str], None]
    marked_stale: int = 0
    marked_historical: int = 0
    reactivated: int = 0
    counter_key: str = ""


def _mark_historical_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
) -> None:
    store.mark_historical(record_id, commit=False)


def _mark_active_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
) -> None:
    store.restore_anchor_active(record_id, commit=False)


def _mark_stale_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
) -> None:
    store.mark_stale(record_id, SUBJECT_FINGERPRINT_DRIFT, commit=False)


_DRIFT_TRANSITIONS: dict[MemoryStatus, _DriftTransitionSpec] = {
    "historical": _DriftTransitionSpec(
        apply=_mark_historical_transition,
        marked_historical=1,
        counter_key="historical",
    ),
    "active": _DriftTransitionSpec(
        apply=_mark_active_transition,
        reactivated=1,
        counter_key="reactivated",
    ),
    "stale": _DriftTransitionSpec(
        apply=_mark_stale_transition,
        marked_stale=1,
        counter_key=SUBJECT_FINGERPRINT_DRIFT,
    ),
}


def _commit_anchor_drift_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
    drift_status: MemoryStatus,
) -> _AnchorDriftOutcome:
    spec = _DRIFT_TRANSITIONS.get(drift_status, _DRIFT_TRANSITIONS["stale"])
    spec.apply(store, record_id)
    return _AnchorDriftOutcome(
        handled=True,
        marked_stale=spec.marked_stale,
        marked_historical=spec.marked_historical,
        reactivated=spec.reactivated,
        counter_key=spec.counter_key or None,
    )


def _apply_anchor_drift_for_record(
    store: SqliteEngineeringMemoryStore,
    record: MemoryRecord,
    *,
    anchor_subject: MemorySubject,
    root_path: Path,
) -> _AnchorDriftOutcome:
    drift_status = _evaluate_anchor_drift_status(
        record,
        anchor_subject=anchor_subject,
        root_path=root_path,
    )
    if drift_status is None:
        return _AnchorDriftOutcome(handled=False)
    if drift_status == record.status:
        return _AnchorDriftOutcome(handled=True)
    return _commit_anchor_drift_transition(store, record.id, drift_status)


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
    report_digest: str | None,
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
    report_digest: str | None,
) -> str | None:
    if _skip_refresh_candidate(record) or record.status in {"historical"}:
        return None
    if record.status == "stale":
        return None
    reasons = _collect_refresh_staleness_reasons(
        record,
        batch_identity_keys=batch_identity_keys,
        batch_by_identity=batch_by_identity,
        batch_evidence=batch_evidence,
        report_digest=report_digest,
        evidence_items=store.list_evidence_for_memory(record.id),
    )
    return reasons[0] if reasons else None


def apply_refresh_staleness(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    batch: RecordBatch,
    report_document: Mapping[str, object],
    root_path: Path,
    report_digest: str | None = None,
    commit: bool = True,
) -> StalenessReport:
    """Mark affected records stale/historical/active after a refresh ingest."""

    del report_document  # inventory membership no longer drives freshness.
    batch_identity_keys = frozenset(record.identity_key for record in batch.records)
    batch_evidence = _batch_evidence_index(batch)
    batch_by_identity = {record.identity_key: record for record in batch.records}
    resolved_root = root_path.resolve()

    reason_counts: dict[str, int] = {}
    marked_stale = 0
    marked_historical = 0
    reactivated = 0

    candidates = store.list_records_for_project(
        project_id,
        statuses=("active", "historical", "stale"),
    )
    for record in candidates:
        if _skip_refresh_candidate(record):
            continue

        subjects = store.list_subjects_for_memory(record.id)
        anchor_subject = _primary_anchor_subject(subjects)
        if anchor_subject is not None:
            drift_outcome = _apply_anchor_drift_for_record(
                store,
                record,
                anchor_subject=anchor_subject,
                root_path=resolved_root,
            )
            if drift_outcome.handled:
                marked_stale += drift_outcome.marked_stale
                marked_historical += drift_outcome.marked_historical
                reactivated += drift_outcome.reactivated
                if drift_outcome.counter_key is not None:
                    key = drift_outcome.counter_key
                    reason_counts[key] = reason_counts.get(key, 0) + 1
                continue

        primary = _refresh_stale_primary_reason(
            store,
            record,
            batch_identity_keys=batch_identity_keys,
            batch_by_identity=batch_by_identity,
            batch_evidence=batch_evidence,
            report_digest=report_digest,
        )
        if primary is None:
            continue
        store.mark_stale(record.id, primary, commit=False)
        marked_stale += 1
        reason_counts[primary] = reason_counts.get(primary, 0) + 1

    if commit:
        store.commit()

    return StalenessReport(
        records_marked_stale=marked_stale,
        records_marked_historical=marked_historical,
        records_reactivated=reactivated,
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
        records_marked_historical=0,
        records_reactivated=0,
        reasons=dict(sorted(reason_counts.items())),
    )


__all__ = [
    "ANCHOR_SUBJECT_KINDS",
    "SUBJECT_FINGERPRINT_DRIFT",
    "StalenessReport",
    "apply_refresh_staleness",
    "apply_scope_staleness",
    "inventory_paths_from_report",
]
