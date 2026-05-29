# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Claim-guard validation and violation messages."""

from __future__ import annotations

from typing import Final

ERR_TEXT_NOT_STRING: Final = "text must be a string."
ERR_TEXT_EMPTY: Final = "text must not be empty."
ERR_TEXT_TOO_LONG: Final = (
    "text exceeds the maximum supported length ({max_chars} characters)."
)

VIOLATION_REASON_SECURITY_NOT_VULNERABILITY: Final = (
    "Security Surfaces are report-only trust-boundary inventory, "
    "not vulnerability claims."
)
VIOLATION_REASON_REPORT_ONLY_GATE: Final = (
    "'{family}' is a report-only signal (gate_keys=()). "
    "It cannot fail CI or block a pipeline."
)
VIOLATION_REASON_KNOWN_DEBT_OVERCLAIM: Final = (
    "This finding has novelty='known'; it exists in baseline "
    "and cannot be described as a new regression."
)
VIOLATION_REASON_DEAD_CODE_REACHABILITY: Final = (
    "'{qualname}' has runtime reachability evidence; it must not be claimed "
    "as definitely dead code."
)
VIOLATION_REASON_FIX_WITHOUT_VERIFICATION: Final = (
    "Fix claimed but no post-patch analysis run is available. "
    "Run analysis after editing and verify the patch contract."
)

WARN_NO_CITATIONS: Final = (
    "No known CodeClone finding IDs or metric family citations were found in the text."
)
WARN_UNKNOWN_FINDING: Final = (
    "Finding citation '{cited_id}' is not present in this run."
)
WARN_STRUCTURAL_CHECKS_NOT_APPLICABLE: Final = (
    "Review references structural verification, but the verification profile "
    "is '{profile}' — structural checks were not applicable for this patch."
)
