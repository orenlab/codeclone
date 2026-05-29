# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Controlled-change workflow user messages."""

from __future__ import annotations

from typing import Final

START_NEEDS_ANALYSIS: Final = (
    "No analysis run available for this root. Call analyze_repository first."
)

START_QUEUED: Final = (
    "Intent queued behind active workspace intent. Do not edit until promoted."
)

FINISH_PROMOTE_BEFORE_VERIFY: Final = (
    "Promote the queued intent before editing or verification."
)

FINISH_QUEUED_NOT_ACTIVE: Final = "Queued intent must be promoted before verification."

FINISH_DIGEST_MISMATCH: Final = "Intent expired: report digest mismatch."

FINISH_DIGEST_MISMATCH_NEXT: Final = (
    "Intent was declared against a different report. "
    "Do not redeclare on the after-run — use the "
    "original intent_id with the original before_run_id."
)

FINISH_SCOPE_VIOLATION: Final = "Patch touched files outside declared scope."

FINISH_SCOPE_VIOLATION_NEXT: Final = (
    "Redeclare intent with expanded scope, or remove the out-of-scope changes."
)

START_INTENT_ACTIVE: Final = "Intent active."
START_HIGH_BLAST_RADIUS: Final = "Blast radius is high — review transitive summary."
START_BUDGET_OUTSIDE_CI: Final = "Budget is already outside CI thresholds."
START_BUDGET_WITHIN_CI: Final = "Budget is within CI thresholds."

FINISH_RECEIPT_FAILED: Final = (
    "Change verified but receipt creation failed. Intent not cleared for retry."
)

FINISH_DONE: Final = "Done. Intent cleared."

FINISH_EVIDENCE_XOR: Final = (
    "finish_controlled_change requires exactly one of "
    "changed_files or diff_ref, not both."
)
FINISH_EVIDENCE_REQUIRED: Final = (
    "finish_controlled_change requires changed_files or diff_ref."
)


def start_controlled_change_message(
    *,
    radius_level: str,
    budget_would_fail: bool,
) -> str:
    parts: list[str] = [START_INTENT_ACTIVE]
    if radius_level == "high":
        parts.append(START_HIGH_BLAST_RADIUS)
    if budget_would_fail:
        parts.append(START_BUDGET_OUTSIDE_CI)
    else:
        parts.append(START_BUDGET_WITHIN_CI)
    return " ".join(parts)


def finish_controlled_change_message(
    *,
    verify_status: str,
    intent_cleared: bool,
    receipt_error: str | None,
) -> str:
    if receipt_error is not None:
        return FINISH_RECEIPT_FAILED
    if intent_cleared:
        return FINISH_DONE
    return f"Verified ({verify_status}). Intent still active."
