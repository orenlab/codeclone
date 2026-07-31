# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import Enum
from typing import Final

MAX_METRICS_BASELINE_SIZE_BYTES: Final = 5 * 1024 * 1024


class MetricsBaselineStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    TOO_LARGE = "too_large"
    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    MISSING_FIELDS = "missing_fields"
    MISMATCH_SCOPE_ID = "mismatch_scope_id"
    MISMATCH_SCHEMA_VERSION = "mismatch_schema_version"
    MISMATCH_PYTHON_VERSION = "mismatch_python_version"
    # The artifact is intact and belongs to this project and interpreter, but
    # its lanes were produced by a different metrics contract, so its values
    # describe a different computation. Distinct from the mismatches around it
    # because the honest operator instruction is "regenerate the metrics
    # baseline" — never "your code regressed".
    INCOMPATIBLE_METRICS_CONTRACT = "incompatible_metrics_contract"
    GENERATOR_MISMATCH = "generator_mismatch"
    INTEGRITY_MISSING = "integrity_missing"
    INTEGRITY_FAILED = "integrity_failed"


def coerce_metrics_baseline_status(
    raw_status: str | MetricsBaselineStatus | None,
) -> MetricsBaselineStatus:
    if isinstance(raw_status, MetricsBaselineStatus):
        return raw_status
    if isinstance(raw_status, str):
        try:
            return MetricsBaselineStatus(raw_status)
        except ValueError:
            return MetricsBaselineStatus.INVALID_TYPE
    return MetricsBaselineStatus.INVALID_TYPE


__all__ = [
    "MAX_METRICS_BASELINE_SIZE_BYTES",
    "MetricsBaselineStatus",
    "coerce_metrics_baseline_status",
]
