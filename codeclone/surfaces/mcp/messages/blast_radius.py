# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Blast-radius boundary reasons and guardrails."""

from __future__ import annotations

from typing import Final

BOUNDARY_REASON_BASELINE_OR_STATE: Final = (
    "baseline, CodeClone state/cache, and generated artifacts "
    "require explicit separate changes"
)
BOUNDARY_REASON_EXPLICIT_FORBIDDEN: Final = "declared forbidden path"
REVIEW_REASON_KNOWN_BASELINE_DEBT: Final = "known baseline debt outside declared origin"
REVIEW_REASON_GOLDEN_FIXTURE_SURFACE: Final = "golden fixture clone suppression surface"
REVIEW_REASON_SECURITY_BOUNDARY: Final = "report-only security boundary inventory"
REVIEW_REASON_REPORT_ONLY_DESIGN: Final = "report-only design signal"
BOUNDARY_REASON_AFFECTED_NOT_ALLOWED: Final = (
    "affected by blast radius but outside declared edit scope"
)

GUARDRAIL_REVIEW_DEPENDENTS: Final = (
    "review direct dependents before editing public behavior"
)
GUARDRAIL_CLONE_COHORT_CONTEXT: Final = (
    "treat clone cohort members as comparison context, not automatic edit targets"
)
GUARDRAIL_HIGH_RADIUS_APPROVAL: Final = (
    "high blast radius requires explicit human scope approval"
)
GUARDRAIL_DO_NOT_TOUCH_APPROVAL: Final = (
    "do-not-touch paths require separate explicit approval"
)

BLAST_SUMMARY_UNKNOWN: Final = "unknown"
