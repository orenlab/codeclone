"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Final

BASELINE_SCHEMA_VERSION: Final = "1.0"
BASELINE_FINGERPRINT_VERSION: Final = "1"

CACHE_VERSION: Final = "1.1"
REPORT_SCHEMA_VERSION: Final = "1.0"


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
        "gating failure (new clones detected, threshold exceeded)",
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
