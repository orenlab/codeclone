# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .contracts import ExitCode
from .ui_messages import fmt_contract_error


class _Printer(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def _validate_output_path(
    path: str,
    *,
    expected_suffix: str,
    label: str,
    console: _Printer,
    invalid_message: Callable[..., str],
    invalid_path_message: Callable[..., str],
) -> Path:
    out = Path(path).expanduser()
    if out.suffix.lower() != expected_suffix:
        console.print(
            fmt_contract_error(
                invalid_message(label=label, path=out, expected_suffix=expected_suffix)
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    try:
        return out.resolve()
    except OSError as e:
        console.print(
            fmt_contract_error(invalid_path_message(label=label, path=out, error=e))
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
