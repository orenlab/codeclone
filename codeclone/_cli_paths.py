# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .contracts import ExitCode
from .ui_messages import fmt_contract_error

if TYPE_CHECKING:
    from collections.abc import Callable


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
