# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from ..analysis.normalizer import NormalizationConfig
from ._types import BootstrapResult, OutputPaths


def bootstrap(
    *,
    args: Namespace,
    root: Path,
    output_paths: OutputPaths,
    cache_path: Path,
) -> BootstrapResult:
    return BootstrapResult(
        root=root,
        config=NormalizationConfig(),
        args=args,
        output_paths=output_paths,
        cache_path=cache_path,
    )


def _resolve_optional_runtime_path(value: object, *, root: Path) -> Path | None:
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    candidate = Path(text).expanduser()
    resolved = candidate if candidate.is_absolute() else root / candidate
    try:
        return resolved.resolve()
    except OSError:
        return resolved.absolute()
