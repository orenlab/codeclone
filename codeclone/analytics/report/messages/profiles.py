# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence

PROFILE_REJECTION_MESSAGES = {
    "technically_invalid": "The partition failed technical validity checks.",
    "too_few_clusters": (
        "The partition has fewer non-noise clusters than this lens allows."
    ),
    "too_many_clusters": (
        "The partition has more non-noise clusters than this lens allows."
    ),
    "dominant_ratio_above_max": "The dominant cluster exceeds this lens maximum.",
    "dominant_ratio_below_min": "The dominant cluster is below this lens minimum.",
    "noise_ratio_above_max": "The noise ratio exceeds this lens maximum.",
    "noise_ratio_below_min": "The noise ratio is below this lens minimum.",
    "insufficient_assigned_mass": (
        "Too few corpus items are assigned to non-noise clusters."
    ),
}


def profile_rejection_message(code: str) -> str:
    return PROFILE_REJECTION_MESSAGES.get(code, code.replace("_", " "))


def profile_banner_message(
    kind: str,
    *,
    failed_invariants: Sequence[str] = (),
    profile_label: str | None = None,
) -> str:
    label = profile_label or "selected profile"
    messages = {
        "maintainer_selected": (
            "Maintainer-selected run. Selection is review evidence, not taxonomy truth."
        ),
        "profile_recommended": (
            f"Technically valid run recommended by the {label} lens."
        ),
        "heuristic_recommended": (
            "Heuristically recommended run. Recommendation is not a semantic verdict."
        ),
        "valid_but_profile_rejected": (
            f"Technically valid partition rejected by the {label} lens."
        ),
        "no_profile_suitable_candidate": (
            f"No technically valid candidate satisfied the {label} lens."
        ),
        "candidate_only": (
            "Candidate run - not recommended or maintainer-selected. "
            "Inspect it as one clustering output, not as corpus taxonomy."
        ),
    }
    if kind == "technically_invalid":
        return "Technically invalid clustering run. Failed invariants: " + ", ".join(
            failed_invariants
        )
    return messages.get(kind, "Run presentation is unavailable.")


__all__ = [
    "PROFILE_REJECTION_MESSAGES",
    "profile_banner_message",
    "profile_rejection_message",
]
