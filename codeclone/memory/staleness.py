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
from .ownership import (
    EVIDENCE_DIGEST_MISMATCH,
    MISSING_FROM_REFRESH,
    REFERENCE_UNRESOLVED,
    REFRESH_CONTENT_CONTRADICTION,
    REPORT_DIGEST_SHIFT,
    SCOPE_FILES_CHANGED,
    SUBJECT_FINGERPRINT_DRIFT,
    owner_subject,
    reference_subjects,
    subject_reference_resolves,
)
from .project import subject_fingerprint_for_subject
from .sqlite_store import SqliteEngineeringMemoryStore, record_content_equal


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
    # Both anchor verdicts are retractable: the owner's content came back, or
    # the reference resolves again. Reasons raised by other machinery (a patch
    # touched the file, a refresh contradicted the statement) are not ours to
    # withdraw here.
    return record.status == "historical" or (
        record.status == "stale"
        and record.stale_reason in (SUBJECT_FINGERPRINT_DRIFT, REFERENCE_UNRESOLVED)
    )


# What the owner's witness says right now: the status to move to, paired with
# the key this transition is counted under. For "stale" that key is also the
# reason written to the record. None means "no verdict".
_OwnerDecision = tuple[MemoryStatus, str]


def _evaluate_owner_status(
    record: MemoryRecord,
    *,
    anchor_subject: MemorySubject,
    references: Sequence[MemorySubject],
    root_path: Path,
) -> _OwnerDecision | None:
    """Decide freshness from the owner's content, then the references.

    Order matters: a changed owner is a fact about the record's own subject and
    outranks anything its references are doing. Only once the owner is known
    unchanged does an unresolved reference become the interesting news.

    Reports what is true now without consulting what the store already says;
    whether that is news is :func:`_already_recorded`'s question, asked once.
    """

    if not record.created_at_commit or record.code_fingerprint is None:
        return None

    current_fingerprint = subject_fingerprint_for_subject(root_path, anchor_subject)
    anchored_fingerprint = record.code_fingerprint

    if current_fingerprint is None:
        # The record's own subject is gone, so there is nothing left to assert.
        return ("historical", "historical")

    if current_fingerprint != anchored_fingerprint:
        return ("stale", SUBJECT_FINGERPRINT_DRIFT)

    unresolved = [
        subject
        for subject in references
        if not subject_reference_resolves(root_path, subject)
    ]
    if unresolved:
        return ("stale", REFERENCE_UNRESOLVED)

    if _reactivate_on_fingerprint_match(record):
        return ("active", "reactivated")
    return None


@dataclass(frozen=True, slots=True)
class _AnchorDriftOutcome:
    handled: bool
    marked_stale: int = 0
    marked_historical: int = 0
    reactivated: int = 0
    counter_key: str | None = None


@dataclass(frozen=True, slots=True)
class _DriftTransitionSpec:
    apply: Callable[[SqliteEngineeringMemoryStore, str, str], None]
    marked_stale: int = 0
    marked_historical: int = 0
    reactivated: int = 0


def _mark_historical_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
    _reason: str,
) -> None:
    store.mark_historical(record_id, commit=False)


def _mark_active_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
    _reason: str,
) -> None:
    store.restore_anchor_active(record_id, commit=False)


def _mark_stale_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
    reason: str,
) -> None:
    store.mark_stale(record_id, reason, commit=False)


# Table-driven so the three transitions do not become three near-identical
# branches; only the stale one consumes the reason.
_OWNER_TRANSITIONS: dict[MemoryStatus, _DriftTransitionSpec] = {
    "historical": _DriftTransitionSpec(
        apply=_mark_historical_transition,
        marked_historical=1,
    ),
    "active": _DriftTransitionSpec(
        apply=_mark_active_transition,
        reactivated=1,
    ),
    "stale": _DriftTransitionSpec(
        apply=_mark_stale_transition,
        marked_stale=1,
    ),
}


def _commit_owner_transition(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
    decision: _OwnerDecision,
) -> _AnchorDriftOutcome:
    status, counter_key = decision
    spec = _OWNER_TRANSITIONS[status]
    spec.apply(store, record_id, counter_key)
    return _AnchorDriftOutcome(
        handled=True,
        marked_stale=spec.marked_stale,
        marked_historical=spec.marked_historical,
        reactivated=spec.reactivated,
        counter_key=counter_key,
    )


def _already_recorded(record: MemoryRecord, decision: _OwnerDecision) -> bool:
    """Is the store already saying exactly this?

    Status alone is not enough now that a stale record carries *why*: a record
    stale from drift whose owner has since been restored, but whose reference
    has gone, is still ``stale`` yet no longer stale for the recorded reason.
    Comparing only the status would leave the old reason in place and quietly
    misreport which fact changed.
    """

    status, reason = decision
    if status != record.status:
        return False
    if status != "stale":
        return True
    return record.stale_reason == reason


def _apply_anchor_drift_for_record(
    store: SqliteEngineeringMemoryStore,
    record: MemoryRecord,
    *,
    anchor_subject: MemorySubject,
    references: Sequence[MemorySubject],
    root_path: Path,
) -> _AnchorDriftOutcome:
    decision = _evaluate_owner_status(
        record,
        anchor_subject=anchor_subject,
        references=references,
        root_path=root_path,
    )
    if decision is None:
        return _AnchorDriftOutcome(handled=False)
    if _already_recorded(record, decision):
        return _AnchorDriftOutcome(handled=True)
    return _commit_owner_transition(store, record.id, decision)


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
            return [EVIDENCE_DIGEST_MISMATCH]
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
        reasons.append(MISSING_FROM_REFRESH)

    incoming = batch_by_identity.get(record.identity_key)
    if (
        incoming is not None
        and record.approved_by
        and not record_content_equal(record, incoming)
    ):
        reasons.append(REFRESH_CONTENT_CONTRADICTION)

    reasons.extend(_evidence_stale_reasons(record, evidence_items, batch_evidence))

    if (
        record.report_digest is not None
        and record.identity_key not in batch_identity_keys
        and report_digest is not None
        and record.report_digest != report_digest
    ):
        reasons.append(REPORT_DIGEST_SHIFT)
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


@dataclass(frozen=True, slots=True)
class _RefreshStalenessDelta:
    marked_stale: int = 0
    marked_historical: int = 0
    reactivated: int = 0
    reason_counts: tuple[tuple[str, int], ...] = ()


def _refresh_staleness_for_record(
    store: SqliteEngineeringMemoryStore,
    record: MemoryRecord,
    *,
    resolved_root: Path,
    batch_identity_keys: frozenset[str],
    batch_by_identity: Mapping[str, MemoryRecord],
    batch_evidence: dict[tuple[str, str, str], str | None],
    report_digest: str | None,
) -> _RefreshStalenessDelta:
    if _skip_refresh_candidate(record):
        return _RefreshStalenessDelta()

    subjects = store.list_subjects_for_memory(record.id)
    anchor_subject = owner_subject(record.type, subjects)
    if anchor_subject is not None:
        drift_outcome = _apply_anchor_drift_for_record(
            store,
            record,
            anchor_subject=anchor_subject,
            references=reference_subjects(record.type, subjects),
            root_path=resolved_root,
        )
        if drift_outcome.handled:
            reason_counts: tuple[tuple[str, int], ...] = ()
            if drift_outcome.counter_key is not None:
                reason_counts = ((drift_outcome.counter_key, 1),)
            return _RefreshStalenessDelta(
                marked_stale=drift_outcome.marked_stale,
                marked_historical=drift_outcome.marked_historical,
                reactivated=drift_outcome.reactivated,
                reason_counts=reason_counts,
            )

    primary = _refresh_stale_primary_reason(
        store,
        record,
        batch_identity_keys=batch_identity_keys,
        batch_by_identity=batch_by_identity,
        batch_evidence=batch_evidence,
        report_digest=report_digest,
    )
    if primary is None:
        return _RefreshStalenessDelta()
    store.mark_stale(record.id, primary, commit=False)
    return _RefreshStalenessDelta(marked_stale=1, reason_counts=((primary, 1),))


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
        delta = _refresh_staleness_for_record(
            store,
            record,
            resolved_root=resolved_root,
            batch_identity_keys=batch_identity_keys,
            batch_by_identity=batch_by_identity,
            batch_evidence=batch_evidence,
            report_digest=report_digest,
        )
        marked_stale += delta.marked_stale
        marked_historical += delta.marked_historical
        reactivated += delta.reactivated
        for key, count in delta.reason_counts:
            reason_counts[key] = reason_counts.get(key, 0) + count

    if commit:
        store.commit()

    return StalenessReport(
        records_marked_stale=marked_stale,
        records_marked_historical=marked_historical,
        records_reactivated=reactivated,
        reasons=dict(sorted(reason_counts.items())),
    )


def _scope_subjects_for(
    record: MemoryRecord,
    subjects: Sequence[MemorySubject],
) -> tuple[MemorySubject, ...]:
    """Subjects a patch may stale this record through.

    An undeclared kind, or one whose owning subject was never written, keeps
    the broad match: without a declared owner there is nothing to narrow to,
    and silently checking nothing would be worse than checking too much.
    """

    owner = owner_subject(record.type, subjects)
    return (owner,) if owner is not None else tuple(subjects)


def apply_scope_staleness(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    changed_paths: Sequence[str],
    commit: bool = True,
) -> StalenessReport:
    """Mark records stale when the owning path was touched in an accepted patch.

    Scope staleness asks the same ownership question the refresh does. Matching
    on *every* subject let a patch to a referenced file mark the document's own
    record stale -- the same conflation as anchoring on the wrong subject,
    arriving through a second door.
    """

    normalized = frozenset(
        path.replace("\\", "/").strip("/").removeprefix("./") for path in changed_paths
    )
    reason_counts: dict[str, int] = {}
    marked = 0
    candidates = [
        record
        for record in store.list_records_for_project(project_id, statuses=("active",))
        if record.status != "stale"
    ]
    # Asking per record made this scale with the accumulated store instead of
    # with the patch, so it degraded on its own as memory grew.
    subjects_by_record = store.list_subjects_for_memories(
        [record.id for record in candidates]
    )
    for record in candidates:
        scoped_subjects = _scope_subjects_for(
            record,
            subjects_by_record.get(record.id, ()),
        )
        for subject in scoped_subjects:
            subj_path = subject.subject_key.replace("\\", "/").strip("/")
            if subj_path in normalized or any(
                subj_path.startswith(f"{scope}/") for scope in normalized
            ):
                store.mark_stale(
                    record.id,
                    SCOPE_FILES_CHANGED,
                    commit=False,
                )
                marked += 1
                reason_counts[SCOPE_FILES_CHANGED] = (
                    reason_counts.get(SCOPE_FILES_CHANGED, 0) + 1
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
    "REFERENCE_UNRESOLVED",
    "SUBJECT_FINGERPRINT_DRIFT",
    "StalenessReport",
    "apply_refresh_staleness",
    "apply_scope_staleness",
    "inventory_paths_from_report",
]
