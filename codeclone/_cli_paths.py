"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from rich.console import Console

from .contracts import ExitCode
from .ui_messages import fmt_contract_error


def expand_path(p: str) -> Path:
    return Path(p).expanduser().resolve()


def _validate_output_path(
    path: str,
    *,
    expected_suffix: str,
    label: str,
    console: Console,
    invalid_message: Callable[..., str],
) -> Path:
    out = Path(path).expanduser()
    if out.suffix.lower() != expected_suffix:
        console.print(
            fmt_contract_error(
                invalid_message(label=label, path=out, expected_suffix=expected_suffix)
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    return out.resolve()
