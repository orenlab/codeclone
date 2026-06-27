# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import orjson

from ...audit.events import (
    EVENT_INTENT_CHECKED,
    EVENT_INTENT_DECLARED,
    EVENT_INTENT_VIOLATED,
    EVENT_PATCH_TRAIL_COMPUTED,
    EVENT_PATCH_VERIFIED,
    EVENT_PATCH_VIOLATED,
)
from ...audit.reader import AuditRecord
from .dto import (
    BlastRadiusSnapshot,
    HygieneSnapshot,
    PatchTrailEvidenceInput,
    PatchTrailInputs,
    VerifySnapshot,
)
from .patch_trail import PatchTrail, compute_patch_trail, patch_trail_from_mapping
from .projector import TrajectoryProjectionError


@dataclass
class _WorkflowAuditState:
    intent_id: str | None = None
    intent_description: str = ""
    declared_files: tuple[str, ...] = ()
    declared_related: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    unexpected_files: tuple[str, ...] = ()
    forbidden_touched: tuple[str, ...] = ()
    scope_check_status: str = "partial"
    verify: VerifySnapshot = field(
        default_factory=lambda: VerifySnapshot(
            verification_profile="unknown",
            verification_status="not_reached",
            verification_skipped=(),
            verification_failed=(),
        )
    )
    intent_declared_seq: int | None = None
    scope_check_seq: int | None = None
    patch_verify_seq: int | None = None
    patch_trail_seq: int | None = None
    receipt_seq: int | None = None
    report_digest: str | None = None


def project_patch_trail_from_audit(
    *,
    records: Sequence[AuditRecord],
    repo_root_digest: str,
) -> PatchTrail | None:
    if not records:
        return None
    workflow_id = records[0].workflow_id or ""
    if not workflow_id.startswith("intent:"):
        return None
    ordered = tuple(sorted(records, key=_record_order_key))
    stored = _patch_trail_from_computed_event(ordered)
    if stored is not None:
        return stored
    state = _WorkflowAuditState()
    for record in ordered:
        _apply_audit_record(state, record)
    if not state.declared_files and not state.changed_files:
        return None
    inputs = PatchTrailInputs(
        intent_id=state.intent_id,
        intent_description=state.intent_description,
        declared_files=state.declared_files,
        declared_related=state.declared_related,
        changed_files=state.changed_files,
        unexpected_files=state.unexpected_files,
        forbidden_touched=state.forbidden_touched,
        expanded_related_files=tuple(
            sorted(
                path
                for path in state.changed_files
                if path in set(state.declared_related)
            )
        ),
        scope_check_status=state.scope_check_status,
        blast_radius=BlastRadiusSnapshot(
            do_not_touch_declared=(),
            review_context_declared=(),
        ),
        verify=state.verify,
        hygiene=HygieneSnapshot(
            blocks_finish=False,
            finish_block_reason=None,
            unacknowledged_dirty_in_scope=(),
            dirty_paths_outside_scope=(),
            attribution_counts={},
        ),
        evidence=PatchTrailEvidenceInput(
            repo_root_digest=repo_root_digest,
            report_digest=state.report_digest,
            intent_declared_audit_sequence=state.intent_declared_seq,
            scope_check_audit_sequence=state.scope_check_seq,
            patch_verify_audit_sequence=state.patch_verify_seq,
            receipt_audit_sequence=state.receipt_seq,
            patch_trail_audit_sequence=state.patch_trail_seq,
        ),
    )
    return compute_patch_trail(inputs)


def _patch_trail_from_computed_event(
    records: Sequence[AuditRecord],
) -> PatchTrail | None:
    for record in reversed(records):
        if record.event_type != EVENT_PATCH_TRAIL_COMPUTED:
            continue
        payload = _audit_payload_mapping(record.payload_json)
        if payload is None:
            continue
        trail = patch_trail_from_mapping(payload)
        if trail is not None:
            return trail
    return None


def _audit_payload_mapping(payload_json: str | None) -> Mapping[str, object] | None:
    if not payload_json or payload_json == "{}":
        return None
    try:
        loaded = orjson.loads(payload_json)
    except orjson.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _apply_audit_record(state: _WorkflowAuditState, record: AuditRecord) -> None:
    if record.audit_sequence is None:
        return
    if record.report_digest:
        state.report_digest = record.report_digest
    if record.event_type == EVENT_INTENT_DECLARED:
        state.intent_id = record.intent_id or state.intent_id
        state.intent_declared_seq = record.audit_sequence
        if record.summary:
            state.intent_description = record.summary
        core = _event_core(record)
        state.declared_files = _facts_paths(core, "scope_paths") or state.declared_files
        return
    if record.event_type in {EVENT_INTENT_CHECKED, EVENT_INTENT_VIOLATED}:
        state.scope_check_seq = record.audit_sequence
        state.scope_check_status = (
            _clean_text(record.status) or state.scope_check_status
        )
        core = _event_core(record)
        state.declared_files = (
            _facts_paths(core, "declared_scope_paths") or state.declared_files
        )
        state.changed_files = _facts_paths(core, "changed_files")
        state.unexpected_files = _facts_paths(core, "unexpected_files_list")
        state.forbidden_touched = _facts_paths(core, "forbidden_touched_list")
        if not state.scope_check_status:
            state.scope_check_status = _clean_text(core.get("status")) or "partial"
        return
    if record.event_type in {EVENT_PATCH_VERIFIED, EVENT_PATCH_VIOLATED}:
        state.patch_verify_seq = record.audit_sequence
        core = _event_core(record)
        status = _clean_text(record.status) or _clean_text(core.get("status"))
        state.verify = VerifySnapshot(
            verification_profile="unknown",
            verification_status=status or "not_reached",
            verification_skipped=(),
            verification_failed=(),
        )
        return
    if record.event_type == EVENT_PATCH_TRAIL_COMPUTED:
        state.patch_trail_seq = record.audit_sequence
        return
    if record.event_type == "receipt.created":
        state.receipt_seq = record.audit_sequence


def _record_order_key(record: AuditRecord) -> tuple[int, str]:
    sequence = record.audit_sequence
    if sequence is None:
        raise TrajectoryProjectionError("audit event is missing audit_sequence")
    return (sequence, record.event_id)


def _event_core(record: AuditRecord) -> Mapping[str, object]:
    if not record.event_core_json or not record.event_core_sha256:
        return {}
    actual = hashlib.sha256(record.event_core_json.encode("utf-8")).hexdigest()
    if actual != record.event_core_sha256:
        raise TrajectoryProjectionError("event core digest mismatch")
    loaded = orjson.loads(record.event_core_json)
    return loaded if isinstance(loaded, dict) else {}


def _facts_paths(core: Mapping[str, object], key: str) -> tuple[str, ...]:
    facts = core.get("facts")
    if not isinstance(facts, Mapping):
        return ()
    raw = facts.get(key)
    if not isinstance(raw, list):
        return ()
    paths = [
        text.strip().replace("\\", "/")
        for item in raw
        if isinstance(item, str) and (text := item.strip())
    ]
    return tuple(sorted(set(paths)))


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = ["project_patch_trail_from_audit"]
