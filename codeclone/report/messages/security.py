# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Security surfaces inventory copy."""

from __future__ import annotations

from typing import Final

SECURITY_EMPTY_TITLE: Final = (
    "No security-relevant capability surfaces matched the exact registry."
)
SECURITY_EMPTY_DETAIL: Final = (
    "This inventory is report-only and focuses on exact boundary "
    "capabilities rather than vulnerability claims."
)
SECURITY_STAT_SURFACES: Final = "Surfaces"
SECURITY_STAT_CATEGORIES: Final = "Categories"
SECURITY_STAT_PRODUCTION: Final = "Production"
SECURITY_STAT_EXACT_ITEMS: Final = "Exact items"
SECURITY_TABLE_TITLE: Final = "Security-relevant capability inventory"
SECURITY_TABLE_HEADERS: Final[tuple[str, ...]] = (
    "Category",
    "Capability",
    "Evidence",
    "Source",
    "Location",
    "Review",
)
SECURITY_TABLE_EMPTY: Final = "No exact security surfaces are available."
SECURITY_TABLE_EMPTY_DESC: Final = (
    "CodeClone inventories trust-boundary capabilities but does not "
    "claim vulnerabilities or exploitability."
)
UNKNOWN_LABEL: Final = "(unknown)"

SECURITY_REVIEW_BANNER_QUESTION: Final = "How should I review this inventory?"
SECURITY_REVIEW_HOW_TO_READ: Final = "How to read"
SECURITY_REVIEW_ORDER: Final = "Review order"
SECURITY_REVIEW_SIGNAL: Final = "Signal"
SECURITY_REVIEW_SIGNAL_VALUE: Final = "boundary inventory"
SECURITY_REVIEW_EVIDENCE: Final = "Evidence"
SECURITY_REVIEW_EVIDENCE_VALUE: Final = "exact imports/calls/builtins"
SECURITY_REVIEW_MEANING: Final = "Meaning"
SECURITY_REVIEW_MEANING_VALUE: Final = "inventory, not vulnerability proof"
SECURITY_REVIEW_START_WITH: Final = "Start with"
SECURITY_REVIEW_COVERAGE_JOIN: Final = "Coverage join"
SECURITY_REVIEW_THEN_REVIEW: Final = "Then review"
SECURITY_REVIEW_PRODUCTION_MODULE_ROWS: Final = "production module rows only"
SECURITY_REVIEW_NO_INVENTORY_ROWS: Final = "no inventory-only rows"
SECURITY_REVIEW_NO_OVERLAP: Final = "no overlap in current review set"
SECURITY_REVIEW_COVERAGE_UNAVAILABLE: Final = "unavailable for this run"
