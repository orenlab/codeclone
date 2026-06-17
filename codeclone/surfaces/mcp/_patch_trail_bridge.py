# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ...audit.events import repo_root_digest
from ...memory.trajectory.dto import (
    BlastRadiusSnapshot,
    HygieneSnapshot,
    PatchTrailEvidenceInput,
    PatchTrailInputs,
    VerifySnapshot,
)
from ._intent import IntentRecord
from ._workspace_hygiene import WorkspaceHygieneResult


def build_patch_trail_inputs(
    *,
    root_path: Path,
    intent: IntentRecord,
    check_payload: Mapping[str, object],
    verify_payload: Mapping[str, object],
    hygiene: WorkspaceHygieneResult,
    report_digest: str | None,
    scope_check_audit_sequence: int | None,
    patch_verify_audit_sequence: int | None,
    receipt_audit_sequence: int | None = None,
) -> PatchTrailInputs:
    declared_files = _path_tuple(check_payload.get("declared_scope"))
    declared_related = tuple(sorted(set(intent.scope.allowed_related)))
    changed_files = _path_tuple(check_payload.get("actual_changed_files"))
    unexpected_files = _path_tuple(check_payload.get("unexpected_files"))
    forbidden_touched = _path_tuple(check_payload.get("forbidden_touched"))
    untouched = _path_tuple(check_payload.get("untouched_in_declared"))
    if not untouched and declared_files and changed_files:
        untouched = tuple(sorted(set(declared_files) - set(changed_files)))
    expanded_related = tuple(
        sorted(path for path in changed_files if path in set(declared_related))
    )
    blast_summary = intent.blast_radius_summary or {}
    blast = BlastRadiusSnapshot(
        do_not_touch_declared=_path_tuple(blast_summary.get("do_not_touch_declared")),
        review_context_declared=_path_tuple(
            blast_summary.get("review_context_declared")
        ),
    )
    verify = VerifySnapshot(
        verification_profile=str(verify_payload.get("verification_profile", "unknown")),
        verification_status=str(verify_payload.get("status", "not_reached")),
        verification_skipped=_string_tuple(verify_payload.get("checks_not_applicable")),
        verification_failed=_string_tuple(verify_payload.get("contract_violations")),
    )
    hygiene_snapshot = HygieneSnapshot(
        blocks_finish=hygiene.blocks_finish,
        finish_block_reason=hygiene.finish_block_reason,
        unacknowledged_dirty_in_scope=hygiene.unacknowledged_dirty_in_scope,
        dirty_paths_outside_scope=hygiene.dirty_paths_outside_scope,
        attribution_counts=hygiene._counts(),
    )
    evidence = PatchTrailEvidenceInput(
        repo_root_digest=repo_root_digest(root_path.resolve()),
        report_digest=report_digest,
        scope_check_audit_sequence=scope_check_audit_sequence,
        patch_verify_audit_sequence=patch_verify_audit_sequence,
        receipt_audit_sequence=receipt_audit_sequence,
    )
    return PatchTrailInputs(
        intent_id=intent.intent_id,
        intent_description=intent.intent_description,
        declared_files=declared_files,
        declared_related=declared_related,
        changed_files=changed_files,
        unexpected_files=unexpected_files,
        forbidden_touched=forbidden_touched,
        expanded_related_files=expanded_related,
        scope_check_status=str(check_payload.get("status", "")),
        blast_radius=blast,
        verify=verify,
        hygiene=hygiene_snapshot,
        evidence=evidence,
    )


def _path_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(
        sorted(
            {
                str(item).replace("\\", "/").strip()
                for item in value
                if str(item).strip()
            }
        )
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


__all__ = ["build_patch_trail_inputs"]
