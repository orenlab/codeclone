# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Patch-contract next_step hints and status messages."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

NEXT_STEP_HINTS: Final[dict[str, str]] = {
    "no_before_run": (
        "Run analyze_repository, then pass the run_id as"
        " before_run_id — or pass intent_id to auto-resolve."
    ),
    "no_after_run": (
        "Run analyze_repository after editing, then pass the"
        " new run_id as after_run_id."
    ),
    "after_run_not_new": (
        "After-run matches the intent before-run. Run analyze_repository "
        "after editing and pass the new run_id as after_run_id."
    ),
    "after_run_required_for_governance": (
        "Governance config changes require a post-edit analysis."
        " Run analyze_repository and pass after_run_id."
    ),
    "incomparable_runs": (
        "Before and after runs are not comparable."
        " Re-run analyze_repository with the same settings."
    ),
    "intent_not_active": (
        "Queued intent must be promoted before editing or"
        " verification. Call"
        " manage_change_intent(action='promote')."
    ),
    "report_digest_mismatch": (
        "Intent was declared against a different report."
        " Do not redeclare on the after-run — use the original"
        " intent_id with the original before_run_id."
    ),
    "state_artifact_mutation": (
        "Baseline, cache, or generated state was touched."
        " Remove those files from the patch and use a separate"
        " workflow."
    ),
    "scope_violation": (
        "Patch touched files outside declared scope."
        " Redeclare intent with expanded scope, or remove the"
        " out-of-scope changes."
    ),
}


def next_step_hint(reason: str) -> str | None:
    return NEXT_STEP_HINTS.get(reason)


QUEUED_BUDGET_MESSAGE: Final = (
    "Budget computed for queued intent. Do not edit until promoted."
)

STATE_ARTIFACT_VIOLATION_MESSAGE: Final = (
    "Patch touched CodeClone generated state. "
    "This requires a separate explicit workflow."
)

PATCH_CONTRACT_EXPIRED_MESSAGE: Final = (
    "Patch contract expired: intent was declared for another report digest."
)

BUDGET_RELAXED_ADVISORY: Final = (
    "Relaxed patch budget is advisory; gate failures are not blocking."
)
BUDGET_OUTSIDE: Final = "Current run is already outside the selected patch budget."
BUDGET_INSIDE: Final = "Current run is inside the selected patch budget."

VERIFY_ACCEPTED: Final = "Patch contract accepted."
VERIFY_ACCEPTED_EXTERNAL: Final = (
    "Patch contract accepted; external workspace changes detected."
)
HEALTH_REGRESSION_ADVISORY: Final = (
    "Patch accepted, but repository health changed negatively between "
    "before-run and after-run. Report this as advisory context, not as "
    "regression-free verification."
)
VERIFY_UNVERIFIED_PREFIX: Final = "Patch contract unverified: {reason}."


def verify_message(
    *,
    status: str,
    violations: Sequence[str],
    health_delta: int | None = None,
) -> str:
    if status == "accepted":
        message = VERIFY_ACCEPTED
    elif status == "accepted_with_external_changes":
        message = VERIFY_ACCEPTED_EXTERNAL
    else:
        return "Patch contract violated: " + ", ".join(violations)
    if health_delta is not None and health_delta < 0:
        return f"{message} {HEALTH_REGRESSION_ADVISORY}"
    return message


def budget_message(*, relaxed: bool, would_fail: bool) -> str:
    if relaxed:
        return BUDGET_RELAXED_ADVISORY
    if would_fail:
        return BUDGET_OUTSIDE
    return BUDGET_INSIDE
