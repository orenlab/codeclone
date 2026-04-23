# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path


def validate_numeric_args(args: object) -> bool:
    return bool(
        not (
            _int_attr(args, "max_baseline_size_mb") < 0
            or _int_attr(args, "max_cache_size_mb") < 0
            or _int_attr(args, "fail_threshold", -1) < -1
            or _int_attr(args, "fail_complexity", -1) < -1
            or _int_attr(args, "fail_coupling", -1) < -1
            or _int_attr(args, "fail_cohesion", -1) < -1
            or _int_attr(args, "fail_health", -1) < -1
            or _int_attr(args, "min_typing_coverage", -1) < -1
            or _int_attr(args, "min_typing_coverage", -1) > 100
            or _int_attr(args, "min_docstring_coverage", -1) < -1
            or _int_attr(args, "min_docstring_coverage", -1) > 100
            or _int_attr(args, "coverage_min") < 0
            or _int_attr(args, "coverage_min") > 100
        )
    )


def resolve_cache_path(*, root_path: Path, args: object) -> Path:
    raw_value = getattr(args, "cache_path", None)
    if isinstance(raw_value, str) and raw_value.strip():
        return Path(raw_value).expanduser()
    return root_path / ".cache" / "codeclone" / "cache.json"


def _int_attr(args: object, name: str, default: int = 0) -> int:
    value = getattr(args, name, default)
    return value if isinstance(value, int) else default
