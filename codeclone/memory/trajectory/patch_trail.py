# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ...contracts import PATCH_TRAIL_SCHEMA_VERSION
from ..paths import normalize_memory_scope_paths
from .dto import PatchTrailInputs

MAX_DECLARED_FILES = 500
MAX_DECLARED_RELATED = 200
MAX_CHANGED_FILES = 500
MAX_UNTOUCHED_IN_DECLARED = 500
MAX_UNEXPECTED_FILES = 200
MAX_FORBIDDEN_TOUCHED = 50
MAX_EXPANDED_RELATED = 200
MAX_BOUNDARY_PATHS = 200
MAX_HYGIENE_PATHS = 50
MAX_VERIFY_ITEMS = 32
INTENT_DESCRIPTION_COMPACT = 500

_EXTERNAL_EXECUTION_STUB: dict[str, object] = {
    "schema_version": "0",
    "status": "not_collected",
    "failed_commands": [],
    "test_deltas": [],
}


@dataclass(frozen=True, slots=True)
class PatchTrail:
    schema_version: str
    intent_id: str | None
    intent_description: str
    declared_files: tuple[str, ...]
    declared_related: tuple[str, ...]
    changed_files: tuple[str, ...]
    untouched_in_declared: tuple[str, ...]
    unexpected_files: tuple[str, ...]
    forbidden_touched: tuple[str, ...]
    expanded_related_files: tuple[str, ...]
    do_not_touch_declared: tuple[str, ...]
    do_not_touch_held: tuple[str, ...]
    review_context_declared: tuple[str, ...]
    review_context_untouched: tuple[str, ...]
    scope_check_status: str
    verification_profile: str
    verification_status: str
    verification_skipped: tuple[str, ...]
    verification_failed: tuple[str, ...]
    workspace_hygiene: Mapping[str, object]
    external_execution: Mapping[str, object]
    evidence: Mapping[str, object]
    truncation: Mapping[str, bool]
    patch_trail_digest: str

    def counts(self) -> dict[str, int]:
        return {
            "declared": len(self.declared_files),
            "changed": len(self.changed_files),
            "untouched_in_declared": len(self.untouched_in_declared),
            "unexpected": len(self.unexpected_files),
            "forbidden_touched": len(self.forbidden_touched),
            "do_not_touch_declared": len(self.do_not_touch_declared),
            "do_not_touch_held": len(self.do_not_touch_held),
            "review_context_declared": len(self.review_context_declared),
            "review_context_untouched": len(self.review_context_untouched),
        }

    def to_payload(self, *, detail_level: str = "summary") -> dict[str, object]:
        if detail_level == "full":
            return self._full_payload()
        return self._summary_payload()

    def _summary_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "intent_description": self.intent_description[:INTENT_DESCRIPTION_COMPACT],
            "scope_check_status": self.scope_check_status,
            "verification_status": self.verification_status,
            "counts": self.counts(),
            "truncation": dict(self.truncation),
            "patch_trail_digest": self.patch_trail_digest,
            "evidence": dict(self.evidence),
            "retrieval_policy": {
                "patch_trail_does_not_authorize_edits": True,
                "patch_trail_does_not_override_findings": True,
            },
        }

    def _full_payload(self) -> dict[str, object]:
        payload = self._canonical_dict(include_digest=False)
        payload["patch_trail_digest"] = self.patch_trail_digest
        payload["retrieval_policy"] = {
            "patch_trail_does_not_authorize_edits": True,
            "patch_trail_does_not_override_findings": True,
        }
        return payload

    def _canonical_dict(self, *, include_digest: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "intent_description": self.intent_description,
            "declared_files": list(self.declared_files),
            "declared_related": list(self.declared_related),
            "changed_files": list(self.changed_files),
            "untouched_in_declared": list(self.untouched_in_declared),
            "unexpected_files": list(self.unexpected_files),
            "forbidden_touched": list(self.forbidden_touched),
            "expanded_related_files": list(self.expanded_related_files),
            "do_not_touch_declared": list(self.do_not_touch_declared),
            "do_not_touch_held": list(self.do_not_touch_held),
            "review_context_declared": list(self.review_context_declared),
            "review_context_untouched": list(self.review_context_untouched),
            "scope_check_status": self.scope_check_status,
            "verification_profile": self.verification_profile,
            "verification_status": self.verification_status,
            "verification_skipped": list(self.verification_skipped),
            "verification_failed": list(self.verification_failed),
            "workspace_hygiene": dict(self.workspace_hygiene),
            "external_execution": dict(self.external_execution),
            "evidence": dict(self.evidence),
            "truncation": dict(self.truncation),
        }
        if include_digest:
            payload["patch_trail_digest"] = self.patch_trail_digest
        return payload

    def audit_payload(self) -> dict[str, object]:
        return self._canonical_dict(include_digest=True)


def compute_patch_trail(inputs: PatchTrailInputs) -> PatchTrail:
    declared_files, declared_trunc = _bounded_paths(
        inputs.declared_files,
        limit=MAX_DECLARED_FILES,
    )
    declared_related, related_trunc = _bounded_paths(
        inputs.declared_related,
        limit=MAX_DECLARED_RELATED,
    )
    changed_files, changed_trunc = _bounded_paths(
        inputs.changed_files,
        limit=MAX_CHANGED_FILES,
    )
    unexpected_files, unexpected_trunc = _bounded_paths(
        inputs.unexpected_files,
        limit=MAX_UNEXPECTED_FILES,
    )
    forbidden_touched, forbidden_trunc = _bounded_paths(
        inputs.forbidden_touched,
        limit=MAX_FORBIDDEN_TOUCHED,
    )
    expanded_related_files, expanded_trunc = _bounded_paths(
        inputs.expanded_related_files,
        limit=MAX_EXPANDED_RELATED,
    )
    do_not_touch_declared, dnt_decl_trunc = _bounded_paths(
        inputs.blast_radius.do_not_touch_declared,
        limit=MAX_BOUNDARY_PATHS,
    )
    review_context_declared, rc_decl_trunc = _bounded_paths(
        inputs.blast_radius.review_context_declared,
        limit=MAX_BOUNDARY_PATHS,
    )
    changed_set = set(changed_files)
    untouched_full = tuple(sorted(set(declared_files) - changed_set))
    untouched_in_declared, untouched_trunc = _bounded_paths(
        untouched_full,
        limit=MAX_UNTOUCHED_IN_DECLARED,
    )
    do_not_touch_held, dnt_held_trunc = _bounded_paths(
        tuple(sorted(set(do_not_touch_declared) - changed_set)),
        limit=MAX_BOUNDARY_PATHS,
    )
    review_context_untouched, rc_untouched_trunc = _bounded_paths(
        tuple(sorted(set(review_context_declared) - changed_set)),
        limit=MAX_BOUNDARY_PATHS,
    )
    unack, unack_trunc = _bounded_paths(
        inputs.hygiene.unacknowledged_dirty_in_scope,
        limit=MAX_HYGIENE_PATHS,
    )
    outside, outside_trunc = _bounded_paths(
        inputs.hygiene.dirty_paths_outside_scope,
        limit=MAX_HYGIENE_PATHS,
    )
    verification_skipped, skipped_trunc = _bounded_strings(
        inputs.verify.verification_skipped,
        limit=MAX_VERIFY_ITEMS,
    )
    verification_failed, failed_trunc = _bounded_strings(
        inputs.verify.verification_failed,
        limit=MAX_VERIFY_ITEMS,
    )
    truncation: dict[str, bool] = {
        "declared_files": declared_trunc,
        "declared_related": related_trunc,
        "changed_files": changed_trunc,
        "untouched_in_declared": untouched_trunc,
        "unexpected_files": unexpected_trunc,
        "forbidden_touched": forbidden_trunc,
        "expanded_related_files": expanded_trunc,
        "do_not_touch_declared": dnt_decl_trunc,
        "do_not_touch_held": dnt_held_trunc,
        "review_context_declared": rc_decl_trunc,
        "review_context_untouched": rc_untouched_trunc,
        "hygiene_paths": unack_trunc or outside_trunc,
        "verification_skipped": skipped_trunc,
        "verification_failed": failed_trunc,
    }
    workspace_hygiene: dict[str, object] = {
        "blocks_finish": inputs.hygiene.blocks_finish,
        "finish_block_reason": inputs.hygiene.finish_block_reason,
        "unacknowledged_dirty_in_scope": list(unack),
        "dirty_paths_outside_scope": list(outside),
        "attribution_counts": dict(inputs.hygiene.attribution_counts),
    }
    evidence: dict[str, object] = {
        "repo_root_digest": inputs.evidence.repo_root_digest,
        "report_digest": inputs.evidence.report_digest,
        "intent_declared_audit_sequence": (
            inputs.evidence.intent_declared_audit_sequence
        ),
        "scope_check_audit_sequence": inputs.evidence.scope_check_audit_sequence,
        "patch_verify_audit_sequence": inputs.evidence.patch_verify_audit_sequence,
        "receipt_audit_sequence": inputs.evidence.receipt_audit_sequence,
        "patch_trail_audit_sequence": inputs.evidence.patch_trail_audit_sequence,
    }
    trail = PatchTrail(
        schema_version=PATCH_TRAIL_SCHEMA_VERSION,
        intent_id=inputs.intent_id,
        intent_description=inputs.intent_description,
        declared_files=declared_files,
        declared_related=declared_related,
        changed_files=changed_files,
        untouched_in_declared=untouched_in_declared,
        unexpected_files=unexpected_files,
        forbidden_touched=forbidden_touched,
        expanded_related_files=expanded_related_files,
        do_not_touch_declared=do_not_touch_declared,
        do_not_touch_held=do_not_touch_held,
        review_context_declared=review_context_declared,
        review_context_untouched=review_context_untouched,
        scope_check_status=inputs.scope_check_status,
        verification_profile=inputs.verify.verification_profile,
        verification_status=inputs.verify.verification_status,
        verification_skipped=verification_skipped,
        verification_failed=verification_failed,
        workspace_hygiene=workspace_hygiene,
        external_execution=dict(_EXTERNAL_EXECUTION_STUB),
        evidence=evidence,
        truncation=truncation,
        patch_trail_digest="",
    )
    digest = _patch_trail_digest(trail._canonical_dict(include_digest=False))
    return PatchTrail(
        schema_version=trail.schema_version,
        intent_id=trail.intent_id,
        intent_description=trail.intent_description,
        declared_files=trail.declared_files,
        declared_related=trail.declared_related,
        changed_files=trail.changed_files,
        untouched_in_declared=trail.untouched_in_declared,
        unexpected_files=trail.unexpected_files,
        forbidden_touched=trail.forbidden_touched,
        expanded_related_files=trail.expanded_related_files,
        do_not_touch_declared=trail.do_not_touch_declared,
        do_not_touch_held=trail.do_not_touch_held,
        review_context_declared=trail.review_context_declared,
        review_context_untouched=trail.review_context_untouched,
        scope_check_status=trail.scope_check_status,
        verification_profile=trail.verification_profile,
        verification_status=trail.verification_status,
        verification_skipped=trail.verification_skipped,
        verification_failed=trail.verification_failed,
        workspace_hygiene=trail.workspace_hygiene,
        external_execution=trail.external_execution,
        evidence=trail.evidence,
        truncation=trail.truncation,
        patch_trail_digest=digest,
    )


def patch_trail_summary_line(trail: PatchTrail) -> str:
    counts = trail.counts()
    return (
        f"declared={counts['declared']} changed={counts['changed']} "
        f"untouched={counts['untouched_in_declared']} "
        f"verify={trail.verification_status} tier={trail.scope_check_status}"
    )


def patch_trail_from_mapping(payload: Mapping[str, object]) -> PatchTrail | None:
    if str(payload.get("schema_version", "")) != PATCH_TRAIL_SCHEMA_VERSION:
        return None
    return PatchTrail(
        schema_version=PATCH_TRAIL_SCHEMA_VERSION,
        intent_id=_optional_str(payload.get("intent_id")),
        intent_description=str(payload.get("intent_description", "")),
        declared_files=_path_tuple(payload.get("declared_files")),
        declared_related=_path_tuple(payload.get("declared_related")),
        changed_files=_path_tuple(payload.get("changed_files")),
        untouched_in_declared=_path_tuple(payload.get("untouched_in_declared")),
        unexpected_files=_path_tuple(payload.get("unexpected_files")),
        forbidden_touched=_path_tuple(payload.get("forbidden_touched")),
        expanded_related_files=_path_tuple(payload.get("expanded_related_files")),
        do_not_touch_declared=_path_tuple(payload.get("do_not_touch_declared")),
        do_not_touch_held=_path_tuple(payload.get("do_not_touch_held")),
        review_context_declared=_path_tuple(payload.get("review_context_declared")),
        review_context_untouched=_path_tuple(payload.get("review_context_untouched")),
        scope_check_status=str(payload.get("scope_check_status", "")),
        verification_profile=str(payload.get("verification_profile", "")),
        verification_status=str(payload.get("verification_status", "")),
        verification_skipped=_string_tuple(payload.get("verification_skipped")),
        verification_failed=_string_tuple(payload.get("verification_failed")),
        workspace_hygiene=_mapping(payload.get("workspace_hygiene")),
        external_execution=_mapping(payload.get("external_execution")),
        evidence=_mapping(payload.get("evidence")),
        truncation={
            str(key): bool(value)
            for key, value in _mapping(payload.get("truncation")).items()
        },
        patch_trail_digest=str(payload.get("patch_trail_digest", "")),
    )


def _bounded_paths(
    paths: Sequence[str],
    *,
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    if not paths:
        return (), False
    normalized = normalize_memory_scope_paths(paths)
    unique = tuple(sorted(set(normalized)))
    if len(unique) <= limit:
        return unique, False
    return unique[:limit], True


def _bounded_strings(
    values: Sequence[str],
    *,
    limit: int,
) -> tuple[tuple[str, ...], bool]:
    unique = tuple(sorted({str(item).strip() for item in values if str(item).strip()}))
    if len(unique) <= limit:
        return unique, False
    return unique[:limit], True


def _patch_trail_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _path_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    items = [str(item) for item in value if str(item).strip()]
    if not items:
        return ()
    return normalize_memory_scope_paths(items)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "PatchTrail",
    "compute_patch_trail",
    "patch_trail_from_mapping",
    "patch_trail_summary_line",
]
