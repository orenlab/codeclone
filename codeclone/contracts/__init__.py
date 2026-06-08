# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import IntEnum
from typing import Final

BASELINE_SCHEMA_VERSION: Final = "2.1"
BASELINE_FINGERPRINT_VERSION: Final = "1"

CACHE_VERSION: Final = "2.8"
REPORT_SCHEMA_VERSION: Final = "2.11"
METRICS_BASELINE_SCHEMA_VERSION: Final = "1.2"
ENGINEERING_MEMORY_SCHEMA_VERSION: Final = "1.5"
# Semantic retrieval index (Phase 20). Derived, rebuildable sidecar — NOT
# covered by ENGINEERING_MEMORY_SCHEMA_VERSION. Bump to invalidate the index
# on an incompatible projection/row-format change (forces a rebuild, not a
# SQLite migration).
SEMANTIC_INDEX_FORMAT_VERSION: Final = "1"
PATCH_TRAIL_SCHEMA_VERSION: Final = "1"

# Memory-derived projection/derivation versions. NOT persistence schema
# versions: bump to supersede previously derived rows on an incompatible
# projection/scoring/distillation change (re-projection, not a SQLite
# migration). Defined here so all version constants live in one place; the
# owning modules re-export these names.
TRAJECTORY_PROJECTION_VERSION: Final = "trajectory-v3"
TRAJECTORY_PROJECTION_VERSION_V1: Final = "trajectory-v1"
TRAJECTORY_QUALITY_SCORE_VERSION: Final = "2"
EXPERIENCE_DISTILLATION_VERSION: Final = "experience-v1"
# IDE governance HMAC attestation protocol version (VS Code Memory channel).
IDE_GOVERNANCE_PROTOCOL_VERSION: Final = 2

DEFAULT_COMPLEXITY_THRESHOLD: Final = 20
DEFAULT_COUPLING_THRESHOLD: Final = 10
DEFAULT_COHESION_THRESHOLD: Final = 4
DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD: Final = 20
DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD: Final = 10
DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD: Final = 4
DEFAULT_HEALTH_THRESHOLD: Final = 60
DEFAULT_ROOT: Final = "."
DEFAULT_MIN_LOC: Final = 10
DEFAULT_MIN_STMT: Final = 6
DEFAULT_BLOCK_MIN_LOC: Final = 20
DEFAULT_BLOCK_MIN_STMT: Final = 8
DEFAULT_SEGMENT_MIN_LOC: Final = 20
DEFAULT_SEGMENT_MIN_STMT: Final = 10
DEFAULT_PROCESSES: Final = 4
DEFAULT_MAX_CACHE_SIZE_MB: Final = 50
DEFAULT_MAX_BASELINE_SIZE_MB: Final = 5
DEFAULT_COVERAGE_MIN: Final = 50
DEFAULT_BASELINE_PATH: Final = "codeclone.baseline.json"
DEFAULT_HTML_REPORT_PATH: Final = ".codeclone/report.html"
DEFAULT_JSON_REPORT_PATH: Final = ".codeclone/report.json"
DEFAULT_MARKDOWN_REPORT_PATH: Final = ".codeclone/report.md"
DEFAULT_SARIF_REPORT_PATH: Final = ".codeclone/report.sarif"
DEFAULT_TEXT_REPORT_PATH: Final = ".codeclone/report.txt"

COMPLEXITY_RISK_LOW_MAX: Final = 10
COMPLEXITY_RISK_MEDIUM_MAX: Final = 20
COUPLING_RISK_LOW_MAX: Final = 5
COUPLING_RISK_MEDIUM_MAX: Final = 10
COHESION_RISK_MEDIUM_MAX: Final = 3
HEALTH_DEPENDENCY_CYCLE_PENALTY: Final = 25
HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY: Final = 4
HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER: Final = 2.0
HEALTH_DEPENDENCY_DEPTH_P95_MARGIN: Final = 1

HEALTH_WEIGHTS: Final[dict[str, float]] = {
    "clones": 0.25,
    "complexity": 0.20,
    "coupling": 0.10,
    "cohesion": 0.15,
    "dead_code": 0.10,
    "dependencies": 0.10,
    "coverage": 0.10,
}


class ExitCode(IntEnum):
    SUCCESS = 0
    CONTRACT_ERROR = 2
    GATING_FAILURE = 3
    INTERNAL_ERROR = 5


REPOSITORY_URL: Final = "https://github.com/orenlab/codeclone"
ISSUES_URL: Final = "https://github.com/orenlab/codeclone/issues"
DOCS_URL: Final = "https://orenlab.github.io/codeclone/"


def cli_help_epilog() -> str:
    return "\n".join(
        [
            "Exit codes:",
            "  0  Success.",
            "  2  Contract error: untrusted or invalid baseline, invalid output",
            "     configuration, incompatible versions, or unreadable sources in",
            "     CI/gating mode.",
            "  3  Gating failure: new clones, threshold violations, or metrics",
            "     quality gate failures.",
            "  5  Internal error: unexpected exception.",
            "",
            f"Repository: {REPOSITORY_URL}",
            f"Issues:     {ISSUES_URL}",
            f"Docs:       {DOCS_URL}",
        ]
    )


__all__ = [
    "BASELINE_FINGERPRINT_VERSION",
    "BASELINE_SCHEMA_VERSION",
    "CACHE_VERSION",
    "COHESION_RISK_MEDIUM_MAX",
    "COMPLEXITY_RISK_LOW_MAX",
    "COMPLEXITY_RISK_MEDIUM_MAX",
    "COUPLING_RISK_LOW_MAX",
    "COUPLING_RISK_MEDIUM_MAX",
    "DEFAULT_BASELINE_PATH",
    "DEFAULT_BLOCK_MIN_LOC",
    "DEFAULT_BLOCK_MIN_STMT",
    "DEFAULT_COHESION_THRESHOLD",
    "DEFAULT_COMPLEXITY_THRESHOLD",
    "DEFAULT_COUPLING_THRESHOLD",
    "DEFAULT_COVERAGE_MIN",
    "DEFAULT_HEALTH_THRESHOLD",
    "DEFAULT_HTML_REPORT_PATH",
    "DEFAULT_JSON_REPORT_PATH",
    "DEFAULT_MARKDOWN_REPORT_PATH",
    "DEFAULT_MAX_BASELINE_SIZE_MB",
    "DEFAULT_MAX_CACHE_SIZE_MB",
    "DEFAULT_MIN_LOC",
    "DEFAULT_MIN_STMT",
    "DEFAULT_PROCESSES",
    "DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD",
    "DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD",
    "DEFAULT_ROOT",
    "DEFAULT_SARIF_REPORT_PATH",
    "DEFAULT_SEGMENT_MIN_LOC",
    "DEFAULT_SEGMENT_MIN_STMT",
    "DEFAULT_TEXT_REPORT_PATH",
    "DOCS_URL",
    "ENGINEERING_MEMORY_SCHEMA_VERSION",
    "EXPERIENCE_DISTILLATION_VERSION",
    "HEALTH_DEPENDENCY_CYCLE_PENALTY",
    "HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER",
    "HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY",
    "HEALTH_DEPENDENCY_DEPTH_P95_MARGIN",
    "HEALTH_WEIGHTS",
    "IDE_GOVERNANCE_PROTOCOL_VERSION",
    "ISSUES_URL",
    "METRICS_BASELINE_SCHEMA_VERSION",
    "PATCH_TRAIL_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "REPOSITORY_URL",
    "SEMANTIC_INDEX_FORMAT_VERSION",
    "TRAJECTORY_PROJECTION_VERSION",
    "TRAJECTORY_PROJECTION_VERSION_V1",
    "TRAJECTORY_QUALITY_SCORE_VERSION",
    "ExitCode",
    "cli_help_epilog",
]
