# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from enum import IntEnum
from typing import Final

BASELINE_SCHEMA_VERSION: Final = "2.0"
BASELINE_FINGERPRINT_VERSION: Final = "1"

CACHE_VERSION: Final = "2.1"
REPORT_SCHEMA_VERSION: Final = "2.1"
METRICS_BASELINE_SCHEMA_VERSION: Final = "1.0"

DEFAULT_COMPLEXITY_THRESHOLD: Final = 20
DEFAULT_COUPLING_THRESHOLD: Final = 10
DEFAULT_COHESION_THRESHOLD: Final = 4
DEFAULT_HEALTH_THRESHOLD: Final = 60

COMPLEXITY_RISK_LOW_MAX: Final = 10
COMPLEXITY_RISK_MEDIUM_MAX: Final = 20
COUPLING_RISK_LOW_MAX: Final = 5
COUPLING_RISK_MEDIUM_MAX: Final = 10
COHESION_RISK_MEDIUM_MAX: Final = 3

HEALTH_WEIGHTS: Final[dict[str, float]] = {
    "clones": 0.25,
    "complexity": 0.20,
    "coupling": 0.15,
    "cohesion": 0.10,
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
DOCS_URL: Final = "https://github.com/orenlab/codeclone/tree/main/docs"

EXIT_CODE_DESCRIPTIONS: Final[tuple[tuple[ExitCode, str], ...]] = (
    (ExitCode.SUCCESS, "success"),
    (
        ExitCode.CONTRACT_ERROR,
        (
            "contract error (baseline missing/untrusted, invalid output "
            "extensions, incompatible versions, unreadable source files in CI/gating)"
        ),
    ),
    (
        ExitCode.GATING_FAILURE,
        (
            "gating failure (new clones detected, threshold exceeded, "
            "or metrics quality gates failed)"
        ),
    ),
    (
        ExitCode.INTERNAL_ERROR,
        "internal error (unexpected exception; please report)",
    ),
)


def cli_help_epilog() -> str:
    lines = ["Exit codes"]
    for code, description in EXIT_CODE_DESCRIPTIONS:
        lines.append(f"  - {int(code)} - {description}")
    lines.extend(
        [
            "",
            f"Repository: {REPOSITORY_URL}",
            f"Issues: {ISSUES_URL}",
            f"Docs: {DOCS_URL}",
        ]
    )
    return "\n".join(lines)
