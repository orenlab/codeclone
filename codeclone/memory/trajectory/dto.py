# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BlastRadiusSnapshot:
    do_not_touch_declared: tuple[str, ...]
    review_context_declared: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerifySnapshot:
    verification_profile: str
    verification_status: str
    verification_skipped: tuple[str, ...]
    verification_failed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HygieneSnapshot:
    blocks_finish: bool
    finish_block_reason: str | None
    unacknowledged_dirty_in_scope: tuple[str, ...]
    dirty_paths_outside_scope: tuple[str, ...]
    attribution_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class PatchTrailEvidenceInput:
    repo_root_digest: str
    report_digest: str | None
    intent_declared_audit_sequence: int | None = None
    scope_check_audit_sequence: int | None = None
    patch_verify_audit_sequence: int | None = None
    receipt_audit_sequence: int | None = None
    patch_trail_audit_sequence: int | None = None


@dataclass(frozen=True, slots=True)
class PatchTrailInputs:
    intent_id: str | None
    intent_description: str
    declared_files: tuple[str, ...]
    declared_related: tuple[str, ...]
    changed_files: tuple[str, ...]
    unexpected_files: tuple[str, ...]
    forbidden_touched: tuple[str, ...]
    expanded_related_files: tuple[str, ...]
    scope_check_status: str
    blast_radius: BlastRadiusSnapshot
    verify: VerifySnapshot
    hygiene: HygieneSnapshot
    evidence: PatchTrailEvidenceInput


__all__ = [
    "BlastRadiusSnapshot",
    "HygieneSnapshot",
    "PatchTrailEvidenceInput",
    "PatchTrailInputs",
    "VerifySnapshot",
]
