# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

STEP_DISPLAY_NAMES: dict[str, str] = {
    "analysis.completed": "Analysis run completed",
    "baseline_abuse.detected": "Baseline abuse detected",
    "blast_radius.computed": "Blast radius computed",
    "claim_validation.completed": "Claim validation passed",
    "claim_validation.violated": "Claim validation failed",
    "intent.checked": "Scope checked",
    "intent.cleared": "Intent cleared",
    "intent.declared": "Change intent declared",
    "intent.expanded": "Scope expanded",
    "intent.expired": "Intent lease expired",
    "intent.promoted": "Queued intent promoted",
    "intent.queue_blocked": "Intent queue blocked",
    "intent.queued": "Intent queued",
    "intent.renewed": "Intent lease renewed",
    "intent.violated": "Intent scope violated",
    "patch_budget.computed": "Patch budget computed",
    "patch_contract.expired": "Patch verification expired",
    "patch_contract.verified": "Patch contract verified",
    "patch_contract.violated": "Patch contract violated",
    "patch_trail.computed": "Patch trail computed",
    "review_receipt.created": "Review receipt created",
    "workspace.conflict_detected": "Workspace conflict detected",
    "workspace.gc_completed": "Workspace intent GC completed",
}


def step_display_name(*, event_type: str, status: str | None = None) -> str:
    base = STEP_DISPLAY_NAMES.get(
        event_type,
        event_type.replace(".", " \u2192 ").replace("_", " "),
    )
    cleaned = status.strip() if isinstance(status, str) else ""
    if cleaned:
        return f"{base} ({cleaned})"
    return base


__all__ = ["STEP_DISPLAY_NAMES", "step_display_name"]
