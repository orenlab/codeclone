# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The trust words several layers read, with one owner.

A lane's trust reason travels from the baseline container check to the
canonical document, the report and the patch-verify gate label; a clone
baseline's file status from the baseline loader to the document's meta and
the same label. Each layer used to spell the words it needed, and a surface
that may not import the layer owning them kept private copies -- a renamed
word would have changed what the gate label means with nothing failing.

Only the genuinely shared words live here (maintainer ruling 2026-10-26).
The metrics-baseline statuses and the cache statuses keep owners of their
own: the same string in two subsystems is not proof of one contract. These
are wire values; changing one changes every report and baseline that
carries it.
"""

from __future__ import annotations

from typing import Final

# -- per-lane trust reasons (``baseline.sorted_lane_trust[].reason``) ---------

#: The reason a trusted lane carries.
LANE_TRUST_COMPATIBLE: Final = "compatible"
#: The reason every lane carries when there is no baseline container at all.
LANE_TRUST_BASELINE_MISSING: Final = "baseline_missing"
#: The reason a lane carries when the container's root was not verified.
LANE_TRUST_ROOT_UNVERIFIED: Final = "root_unverified"
#: Every lane-trust reason: the container check's own reasons
#: (``codeclone.models.LaneTrustReason``) plus the two the document adds.
LANE_TRUST_REASONS: Final = (
    "algorithm_revision",
    LANE_TRUST_BASELINE_MISSING,
    "baseline_scope_id",
    "canonicalization_version",
    LANE_TRUST_COMPATIBLE,
    "descriptor_version",
    "lane_digest_mismatch",
    "payload_schema",
    "payload_schema_outdated",
    "required_contract",
    "root_digest_mismatch",
    LANE_TRUST_ROOT_UNVERIFIED,
    "runtime_lane_unknown",
)
#: The reasons that are not a refusal of the lane: it was trusted, or there
#: was no container to refuse. Every other reason is a refusal.
LANE_TRUST_NOT_REFUSED: Final = frozenset(
    {LANE_TRUST_COMPATIBLE, LANE_TRUST_BASELINE_MISSING}
)

# -- clone-baseline file statuses (``meta.baseline.status``) ------------------

BASELINE_STATUS_OK: Final = "ok"
BASELINE_STATUS_MISSING: Final = "missing"
BASELINE_STATUS_TOO_LARGE: Final = "too_large"
BASELINE_STATUS_INVALID_JSON: Final = "invalid_json"
BASELINE_STATUS_INVALID_TYPE: Final = "invalid_type"
BASELINE_STATUS_MISSING_FIELDS: Final = "missing_fields"
BASELINE_STATUS_MISMATCH_SCHEMA_VERSION: Final = "mismatch_schema_version"
BASELINE_STATUS_MISMATCH_FINGERPRINT_VERSION: Final = "mismatch_fingerprint_version"
BASELINE_STATUS_MISMATCH_PYTHON_VERSION: Final = "mismatch_python_version"
BASELINE_STATUS_MISMATCH_SCOPE_ID: Final = "mismatch_scope_id"
BASELINE_STATUS_GENERATOR_MISMATCH: Final = "generator_mismatch"
BASELINE_STATUS_INTEGRITY_MISSING: Final = "integrity_missing"
BASELINE_STATUS_INTEGRITY_FAILED: Final = "integrity_failed"
#: Every clone-baseline file status, sorted.
BASELINE_STATUSES: Final = tuple(
    sorted(
        (
            BASELINE_STATUS_OK,
            BASELINE_STATUS_MISSING,
            BASELINE_STATUS_TOO_LARGE,
            BASELINE_STATUS_INVALID_JSON,
            BASELINE_STATUS_INVALID_TYPE,
            BASELINE_STATUS_MISSING_FIELDS,
            BASELINE_STATUS_MISMATCH_SCHEMA_VERSION,
            BASELINE_STATUS_MISMATCH_FINGERPRINT_VERSION,
            BASELINE_STATUS_MISMATCH_PYTHON_VERSION,
            BASELINE_STATUS_MISMATCH_SCOPE_ID,
            BASELINE_STATUS_GENERATOR_MISMATCH,
            BASELINE_STATUS_INTEGRITY_MISSING,
            BASELINE_STATUS_INTEGRITY_FAILED,
        )
    )
)
#: The file statuses that are not a refusal: no file, or a loaded one. Every
#: other status is a file the run found and refused.
BASELINE_STATUS_NOT_REFUSED: Final = frozenset(
    {BASELINE_STATUS_MISSING, BASELINE_STATUS_OK}
)

__all__ = [
    "BASELINE_STATUSES",
    "BASELINE_STATUS_GENERATOR_MISMATCH",
    "BASELINE_STATUS_INTEGRITY_FAILED",
    "BASELINE_STATUS_INTEGRITY_MISSING",
    "BASELINE_STATUS_INVALID_JSON",
    "BASELINE_STATUS_INVALID_TYPE",
    "BASELINE_STATUS_MISMATCH_FINGERPRINT_VERSION",
    "BASELINE_STATUS_MISMATCH_PYTHON_VERSION",
    "BASELINE_STATUS_MISMATCH_SCHEMA_VERSION",
    "BASELINE_STATUS_MISMATCH_SCOPE_ID",
    "BASELINE_STATUS_MISSING",
    "BASELINE_STATUS_MISSING_FIELDS",
    "BASELINE_STATUS_NOT_REFUSED",
    "BASELINE_STATUS_OK",
    "BASELINE_STATUS_TOO_LARGE",
    "LANE_TRUST_BASELINE_MISSING",
    "LANE_TRUST_COMPATIBLE",
    "LANE_TRUST_NOT_REFUSED",
    "LANE_TRUST_REASONS",
    "LANE_TRUST_ROOT_UNVERIFIED",
]
