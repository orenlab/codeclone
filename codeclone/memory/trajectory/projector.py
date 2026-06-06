# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence

from ...audit.events import (
    EVENT_BASELINE_ABUSE,
    EVENT_CLAIM_VIOLATED,
    EVENT_INTENT_EXPIRED,
    EVENT_INTENT_PROMOTED,
    EVENT_INTENT_QUEUE_BLOCKED,
    EVENT_INTENT_VIOLATED,
    EVENT_PATCH_EXPIRED,
    EVENT_PATCH_VERIFIED,
    EVENT_PATCH_VIOLATED,
    EVENT_WORKSPACE_CONFLICT,
)
from ...audit.reader import AuditRecord
from ...report.meta import current_report_timestamp_utc
from .models import (
    TRAJECTORY_PROJECTION_VERSION,
    Trajectory,
    TrajectoryEvidence,
    TrajectoryLabel,
    TrajectoryOutcome,
    TrajectoryQualityTier,
    TrajectoryStep,
    TrajectorySubject,
)


class TrajectoryProjectionError(ValueError):
    """Raised when audit event core cannot be projected deterministically."""


def project_trajectory(
    *,
    project_id: str,
    repo_root_digest: str,
    workflow_id: str,
    records: Sequence[AuditRecord],
    projection_version: str = TRAJECTORY_PROJECTION_VERSION,
    projected_at_utc: str | None = None,
) -> Trajectory:
    if not records:
        raise TrajectoryProjectionError("trajectory projection requires events")
    ordered = tuple(sorted(records, key=_record_order_key))
    _validate_single_workflow(workflow_id, ordered)
    cores = tuple(_validated_event_core(record) for record in ordered)
    steps = tuple(
        _step_from_record(index, record) for index, record in enumerate(ordered)
    )
    labels = _labels(ordered, cores)
    outcome = _outcome(ordered, cores)
    quality_tier = _quality_tier(outcome=outcome, records=ordered, labels=labels)
    run_ids = tuple(
        value for value in (_clean_text(record.run_id) for record in ordered) if value
    )
    report_digests = tuple(
        value
        for value in (
            _canonical_report_digest(record.report_digest) for record in ordered
        )
        if value
    )
    intent_id = _first_text(record.intent_id for record in ordered)
    now = projected_at_utc or current_report_timestamp_utc()
    event_count = len(ordered)
    incident_count = sum(
        1 for record in ordered if record.severity in {"warn", "error"}
    )
    first_run_id = run_ids[0] if run_ids else None
    last_run_id = run_ids[-1] if run_ids else None
    primary_run_id = last_run_id or first_run_id
    report_digest = report_digests[-1] if report_digests else None
    source_stream_digest = _source_event_stream_digest(ordered)
    summary = _summary(
        workflow_id=workflow_id,
        outcome=outcome,
        quality_tier=quality_tier,
        event_count=event_count,
        incident_count=incident_count,
        labels=labels,
        first_summary=_first_text(record.summary for record in ordered),
    )
    trajectory_id = _trajectory_id(
        projection_version=projection_version,
        repo_root_digest=repo_root_digest,
        workflow_id=workflow_id,
    )
    subjects = _subjects(
        workflow_id=workflow_id,
        intent_id=intent_id,
        run_ids=run_ids,
        report_digests=report_digests,
        cores=cores,
    )
    evidence = (
        TrajectoryEvidence(
            evidence_kind="audit_event_stream",
            ref=workflow_id,
            locator=str(ordered[0].audit_sequence),
            digest=source_stream_digest,
            created_at_utc=now,
        ),
    )
    trajectory_digest = _trajectory_digest(
        projection_version=projection_version,
        repo_root_digest=repo_root_digest,
        workflow_id=workflow_id,
        outcome=outcome,
        quality_tier=quality_tier,
        labels=labels,
        summary=summary,
        source_event_stream_digest=source_stream_digest,
        steps=steps,
    )
    return Trajectory(
        id=trajectory_id,
        project_id=project_id,
        repo_root_digest=repo_root_digest,
        workflow_id=workflow_id,
        intent_id=intent_id,
        primary_run_id=primary_run_id,
        first_run_id=first_run_id,
        last_run_id=last_run_id,
        report_digest=report_digest,
        outcome=outcome,
        quality_tier=quality_tier,
        labels=labels,
        summary=summary,
        trajectory_digest=trajectory_digest,
        source_event_stream_digest=source_stream_digest,
        projection_version=projection_version,
        event_count=event_count,
        step_count=len(steps),
        incident_count=incident_count,
        started_at_utc=ordered[0].created_at_utc,
        finished_at_utc=ordered[-1].created_at_utc,
        projected_at_utc=now,
        updated_at_utc=now,
        steps=steps,
        subjects=subjects,
        evidence=evidence,
    )


def _record_order_key(record: AuditRecord) -> tuple[int, str]:
    sequence = record.audit_sequence
    if sequence is None:
        raise TrajectoryProjectionError("audit event is missing audit_sequence")
    return (sequence, record.event_id)


def _validate_single_workflow(
    workflow_id: str,
    records: Sequence[AuditRecord],
) -> None:
    for record in records:
        if record.workflow_id != workflow_id:
            raise TrajectoryProjectionError("mixed workflow ids in trajectory")


def _validated_event_core(record: AuditRecord) -> Mapping[str, object]:
    if not record.event_core_json or not record.event_core_sha256:
        raise TrajectoryProjectionError("audit event is missing event core")
    actual = hashlib.sha256(record.event_core_json.encode("utf-8")).hexdigest()
    if actual != record.event_core_sha256:
        raise TrajectoryProjectionError("event core digest mismatch")
    loaded = json.loads(record.event_core_json)
    if not isinstance(loaded, dict):
        raise TrajectoryProjectionError("event core must be a JSON object")
    return loaded


def _step_from_record(index: int, record: AuditRecord) -> TrajectoryStep:
    if record.audit_sequence is None:
        raise TrajectoryProjectionError("audit event is missing audit_sequence")
    if not record.event_core_json or not record.event_core_sha256:
        raise TrajectoryProjectionError("audit event is missing event core")
    return TrajectoryStep(
        step_index=index,
        audit_sequence=record.audit_sequence,
        event_id=record.event_id,
        event_type=record.event_type,
        status=record.status,
        run_id=record.run_id,
        report_digest=_canonical_report_digest(record.report_digest),
        event_core_sha256=record.event_core_sha256,
        event_core_json=record.event_core_json,
        summary=record.summary,
        created_at_utc=record.created_at_utc,
    )


def _outcome(
    records: Sequence[AuditRecord],
    cores: Sequence[Mapping[str, object]],
) -> TrajectoryOutcome:
    event_types = {record.event_type for record in records}
    statuses = {
        status
        for status in (_clean_text(record.status) for record in records)
        if status is not None
    }
    core_statuses = {
        status
        for status in (_clean_text(core.get("status")) for core in cores)
        if status is not None
    }
    all_statuses = statuses | core_statuses
    if event_types & {
        EVENT_BASELINE_ABUSE,
        EVENT_CLAIM_VIOLATED,
        EVENT_PATCH_VIOLATED,
        EVENT_INTENT_VIOLATED,
    }:
        return "violated"
    if any(_core_fact_bool(core, "baseline_abuse") for core in cores):
        return "violated"
    if EVENT_PATCH_VERIFIED in event_types:
        if "accepted_with_external_changes" in all_statuses:
            return "accepted_with_external_changes"
        if "accepted" in all_statuses:
            return "accepted"
    if event_types & {EVENT_PATCH_EXPIRED, EVENT_INTENT_EXPIRED}:
        return "abandoned"
    if event_types & {EVENT_INTENT_QUEUE_BLOCKED, EVENT_WORKSPACE_CONFLICT}:
        return "blocked"
    return "partial"


def _labels(
    records: Sequence[AuditRecord],
    cores: Sequence[Mapping[str, object]],
) -> tuple[TrajectoryLabel, ...]:
    labels: set[TrajectoryLabel] = set()
    event_types = {record.event_type for record in records}
    if EVENT_BASELINE_ABUSE in event_types or any(
        _core_fact_bool(core, "baseline_abuse") for core in cores
    ):
        labels.add("baseline_abuse_detected")
    if EVENT_CLAIM_VIOLATED in event_types:
        labels.add("claim_guard_failed")
    if EVENT_WORKSPACE_CONFLICT in event_types:
        labels.add("foreign_conflict_seen")
    if EVENT_INTENT_PROMOTED in event_types:
        labels.add("recovered")
    if any(
        record.surface == "hook" and record.severity in {"warn", "error"}
        for record in records
    ):
        labels.add("hook_blocked")
    if any(
        (record.tool_name or "").startswith("manage_engineering_memory")
        for record in records
    ):
        labels.add("memory_used")
    if any(record.status == "accepted_with_external_changes" for record in records):
        labels.add("external_changes_accepted")
    return tuple(sorted(labels))


def _quality_tier(
    *,
    outcome: TrajectoryOutcome,
    records: Sequence[AuditRecord],
    labels: Sequence[TrajectoryLabel],
) -> TrajectoryQualityTier:
    if outcome == "violated" or any(
        label in {"baseline_abuse_detected", "claim_guard_failed", "hook_blocked"}
        for label in labels
    ):
        return "incident"
    if outcome == "partial":
        return "partial"
    if outcome in {"accepted", "accepted_with_external_changes"}:
        if any(
            record.event_type in {EVENT_PATCH_VIOLATED, EVENT_INTENT_VIOLATED}
            for record in records
        ):
            return "corrected"
        return "verified"
    return "routine"


def _subjects(
    *,
    workflow_id: str,
    intent_id: str | None,
    run_ids: Sequence[str],
    report_digests: Sequence[str],
    cores: Sequence[Mapping[str, object]],
) -> tuple[TrajectorySubject, ...]:
    subjects = {
        ("workflow", workflow_id, "about"),
        *{("run", run_id, "observed") for run_id in run_ids},
        *{("report_digest", digest, "evidence") for digest in report_digests},
        *{("path", path, "about") for path in _scope_paths_from_cores(cores)},
    }
    if intent_id:
        subjects.add(("intent", intent_id, "about"))
    return tuple(
        TrajectorySubject(subject_kind=kind, subject_key=key, relation=relation)
        for kind, key, relation in sorted(subjects)
    )


def _scope_paths_from_cores(cores: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    paths: set[str] = set()
    for core in cores:
        facts = core.get("facts")
        if not isinstance(facts, Mapping):
            continue
        raw_paths = facts.get("scope_paths")
        if not isinstance(raw_paths, list):
            continue
        for raw_path in raw_paths:
            if isinstance(raw_path, str) and raw_path.strip():
                paths.add(raw_path.strip())
    return tuple(sorted(paths))


def _summary(
    *,
    workflow_id: str,
    outcome: TrajectoryOutcome,
    quality_tier: TrajectoryQualityTier,
    event_count: int,
    incident_count: int,
    labels: Sequence[TrajectoryLabel],
    first_summary: str | None,
) -> str:
    label_text = ",".join(labels) if labels else "none"
    prefix = (
        f"{workflow_id}: outcome={outcome}; tier={quality_tier}; "
        f"events={event_count}; incidents={incident_count}; labels={label_text}"
    )
    if first_summary:
        return f"{prefix}; first_summary={first_summary[:160]}"
    return prefix


def _trajectory_id(
    *,
    projection_version: str,
    repo_root_digest: str,
    workflow_id: str,
) -> str:
    payload = _canonical_json(
        {
            "projection_version": projection_version,
            "repo_root_digest": repo_root_digest,
            "workflow_id": workflow_id,
        }
    )
    return f"traj-{_sha256(payload)[:32]}"


def _source_event_stream_digest(records: Sequence[AuditRecord]) -> str:
    items = [
        {
            "audit_sequence": record.audit_sequence,
            "event_core_sha256": record.event_core_sha256,
        }
        for record in records
    ]
    return _sha256(_canonical_json({"events": items}))


def _trajectory_digest(
    *,
    projection_version: str,
    repo_root_digest: str,
    workflow_id: str,
    outcome: TrajectoryOutcome,
    quality_tier: TrajectoryQualityTier,
    labels: Sequence[TrajectoryLabel],
    summary: str,
    source_event_stream_digest: str,
    steps: Sequence[TrajectoryStep],
) -> str:
    payload = {
        "projection_version": projection_version,
        "repo_root_digest": repo_root_digest,
        "workflow_id": workflow_id,
        "outcome": outcome,
        "quality_tier": quality_tier,
        "labels": list(labels),
        "summary": summary,
        "source_event_stream_digest": source_event_stream_digest,
        "steps": [
            {
                "event_type": step.event_type,
                "status": step.status,
                "run_id": step.run_id,
                "report_digest": step.report_digest,
                "event_core_sha256": step.event_core_sha256,
                "summary": step.summary,
            }
            for step in steps
        ],
    }
    return _sha256(_canonical_json(payload))


def _core_fact_bool(core: Mapping[str, object], key: str) -> bool:
    facts = core.get("facts")
    return bool(facts.get(key)) if isinstance(facts, Mapping) else False


def _first_text(values: Iterable[object]) -> str | None:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return None


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _canonical_report_digest(value: str | None) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    lowered = text.lower()
    digest = lowered[7:] if lowered.startswith("sha256:") else lowered
    if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
        return f"sha256:{digest}"
    return text


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["TrajectoryProjectionError", "project_trajectory"]
