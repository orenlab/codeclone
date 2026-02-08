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
    CLI_ERROR = 1
    CONTRACT_ERROR = 2
    GATING_FAILURE = 3
    INTERNAL_ERROR = 5
