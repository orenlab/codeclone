# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from ...utils.repo_links import RepositoryRoots, refuse_link_leaving_repository


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


def resolve_cache_path(
    *, root_path: Path, args: object, spelled_root: Path | None = None
) -> Path:
    """The cache path of a run, refused when a repository link leads it out.

    The server never writes the cache, but it reads one; a committed ``.cache``
    link made it reuse a cache file from outside the repository. The rule is
    the CLI's (``utils/repo_links.py``) and raises
    :class:`LinkLeavesRepositoryError`.
    """

    raw_value = getattr(args, "cache_path", None)
    if isinstance(raw_value, str) and raw_value.strip():
        cache_path = Path(raw_value).expanduser()
    else:
        cache_path = root_path / ".cache" / "codeclone" / "cache.json"
    refuse_link_leaving_repository(
        cache_path,
        RepositoryRoots(spelled=spelled_root or root_path, resolved=root_path),
    )
    return cache_path


def _int_attr(args: object, name: str, default: int = 0) -> int:
    value = getattr(args, name, default)
    return value if isinstance(value, int) else default
