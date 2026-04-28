# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import Enum
from typing import Final

METRICS_BASELINE_GENERATOR: Final = "codeclone"
MAX_METRICS_BASELINE_SIZE_BYTES: Final = 5 * 1024 * 1024


class MetricsBaselineStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    TOO_LARGE = "too_large"
    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    MISSING_FIELDS = "missing_fields"
    MISMATCH_SCHEMA_VERSION = "mismatch_schema_version"
    MISMATCH_PYTHON_VERSION = "mismatch_python_version"
    GENERATOR_MISMATCH = "generator_mismatch"
    INTEGRITY_MISSING = "integrity_missing"
    INTEGRITY_FAILED = "integrity_failed"


METRICS_BASELINE_UNTRUSTED_STATUSES: Final[frozenset[MetricsBaselineStatus]] = (
    frozenset(
        {
            MetricsBaselineStatus.MISSING,
            MetricsBaselineStatus.TOO_LARGE,
            MetricsBaselineStatus.INVALID_JSON,
            MetricsBaselineStatus.INVALID_TYPE,
            MetricsBaselineStatus.MISSING_FIELDS,
            MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION,
            MetricsBaselineStatus.MISMATCH_PYTHON_VERSION,
            MetricsBaselineStatus.GENERATOR_MISMATCH,
            MetricsBaselineStatus.INTEGRITY_MISSING,
            MetricsBaselineStatus.INTEGRITY_FAILED,
        }
    )
)

_TOP_LEVEL_REQUIRED_KEYS = frozenset({"meta", "metrics"})
_TOP_LEVEL_ALLOWED_KEYS = _TOP_LEVEL_REQUIRED_KEYS | frozenset(
    {"clones", "api_surface"}
)
_META_REQUIRED_KEYS = frozenset(
    {"generator", "schema_version", "python_tag", "created_at", "payload_sha256"}
)
_METRICS_REQUIRED_KEYS = frozenset(
    {
        "max_complexity",
        "high_risk_functions",
        "max_coupling",
        "high_coupling_classes",
        "max_cohesion",
        "low_cohesion_classes",
        "dependency_cycles",
        "dependency_max_depth",
        "dead_code_items",
        "health_score",
        "health_grade",
    }
)
_METRICS_OPTIONAL_KEYS = frozenset(
    {
        "typing_param_permille",
        "typing_return_permille",
        "docstring_permille",
        "typing_any_count",
    }
)
_METRICS_PAYLOAD_SHA256_KEY = "metrics_payload_sha256"
_API_SURFACE_PAYLOAD_SHA256_KEY = "api_surface_payload_sha256"


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
    "METRICS_BASELINE_GENERATOR",
    "METRICS_BASELINE_UNTRUSTED_STATUSES",
    "MetricsBaselineStatus",
    "coerce_metrics_baseline_status",
]
