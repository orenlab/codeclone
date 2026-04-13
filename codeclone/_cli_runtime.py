# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from pathlib import Path
from typing import Protocol

from . import ui_messages as ui
from .cache import CacheStatus
from .contracts import ExitCode

__all__ = [
    "configure_metrics_mode",
    "metrics_computed",
    "print_failed_files",
    "resolve_cache_path",
    "resolve_cache_status",
    "validate_numeric_args",
]


class _RuntimeArgs(Protocol):
    cache_path: str | None
    coverage_xml: str | None
    max_baseline_size_mb: int
    max_cache_size_mb: int
    fail_threshold: int
    fail_complexity: int
    fail_coupling: int
    fail_cohesion: int
    fail_health: int
    fail_on_new_metrics: bool
    fail_on_typing_regression: bool
    fail_on_docstring_regression: bool
    fail_on_api_break: bool
    fail_on_untested_hotspots: bool
    min_typing_coverage: int
    min_docstring_coverage: int
    coverage_min: int
    typing_coverage: bool
    docstring_coverage: bool
    api_surface: bool
    update_metrics_baseline: bool
    skip_metrics: bool
    fail_cycles: bool
    fail_dead_code: bool
    skip_dead_code: bool
    skip_dependencies: bool


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


class _CacheLike(Protocol):
    @property
    def load_status(self) -> CacheStatus | str | None: ...

    @property
    def load_warning(self) -> str | None: ...

    @property
    def cache_schema_version(self) -> str | None: ...


def validate_numeric_args(args: _RuntimeArgs) -> bool:
    return bool(
        not (
            args.max_baseline_size_mb < 0
            or args.max_cache_size_mb < 0
            or args.fail_threshold < -1
            or args.fail_complexity < -1
            or args.fail_coupling < -1
            or args.fail_cohesion < -1
            or args.fail_health < -1
            or args.min_typing_coverage < -1
            or args.min_typing_coverage > 100
            or args.min_docstring_coverage < -1
            or args.min_docstring_coverage > 100
            or args.coverage_min < 0
            or args.coverage_min > 100
        )
    )


def _metrics_flags_requested(args: _RuntimeArgs) -> bool:
    return bool(
        args.fail_complexity >= 0
        or args.fail_coupling >= 0
        or args.fail_cohesion >= 0
        or args.fail_cycles
        or args.fail_dead_code
        or args.fail_health >= 0
        or args.fail_on_new_metrics
        or args.fail_on_typing_regression
        or args.fail_on_docstring_regression
        or args.fail_on_api_break
        or args.fail_on_untested_hotspots
        or args.min_typing_coverage >= 0
        or args.min_docstring_coverage >= 0
        or args.update_metrics_baseline
        or bool(getattr(args, "coverage_xml", None))
    )


def configure_metrics_mode(
    *,
    args: _RuntimeArgs,
    metrics_baseline_exists: bool,
    console: _PrinterLike,
) -> None:
    metrics_flags_requested = _metrics_flags_requested(args)

    if args.skip_metrics and metrics_flags_requested:
        console.print(
            ui.fmt_contract_error(
                "--skip-metrics cannot be used together with metrics gating/update "
                "flags."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    if (
        not args.skip_metrics
        and not metrics_flags_requested
        and not metrics_baseline_exists
    ):
        args.skip_metrics = True

    if args.skip_metrics:
        args.skip_dead_code = True
        args.skip_dependencies = True
        return

    if args.fail_dead_code:
        args.skip_dead_code = False
    if args.fail_cycles:
        args.skip_dependencies = False
    if bool(getattr(args, "fail_on_api_break", False)):
        args.api_surface = True


def resolve_cache_path(
    *,
    root_path: Path,
    args: _RuntimeArgs,
    from_args: bool,
    legacy_cache_path: Path,
    console: _PrinterLike,
) -> Path:
    if from_args and args.cache_path:
        return Path(args.cache_path).expanduser()

    cache_path = root_path / ".cache" / "codeclone" / "cache.json"
    if legacy_cache_path.exists():
        try:
            legacy_resolved = legacy_cache_path.resolve()
        except OSError:
            legacy_resolved = legacy_cache_path
        if legacy_resolved != cache_path:
            console.print(
                ui.fmt_legacy_cache_warning(
                    legacy_path=legacy_resolved,
                    new_path=cache_path,
                )
            )
    return cache_path


def metrics_computed(args: _RuntimeArgs) -> tuple[str, ...]:
    if args.skip_metrics:
        return ()

    computed = ["complexity", "coupling", "cohesion", "health"]
    if not args.skip_dependencies:
        computed.append("dependencies")
    if not args.skip_dead_code:
        computed.append("dead_code")
    if bool(getattr(args, "typing_coverage", True)) or bool(
        getattr(args, "docstring_coverage", True)
    ):
        computed.append("coverage_adoption")
    if bool(getattr(args, "api_surface", False)):
        computed.append("api_surface")
    if bool(getattr(args, "coverage_xml", None)):
        computed.append("coverage_join")
    return tuple(computed)


def resolve_cache_status(cache: _CacheLike) -> tuple[CacheStatus, str | None]:
    raw_cache_status = getattr(cache, "load_status", None)
    load_warning = getattr(cache, "load_warning", None)
    if isinstance(raw_cache_status, CacheStatus):
        cache_status = raw_cache_status
    elif isinstance(raw_cache_status, str):
        try:
            cache_status = CacheStatus(raw_cache_status)
        except ValueError:
            cache_status = (
                CacheStatus.OK if load_warning is None else CacheStatus.INVALID_TYPE
            )
    else:
        cache_status = (
            CacheStatus.OK if load_warning is None else CacheStatus.INVALID_TYPE
        )

    raw_cache_schema_version = getattr(cache, "cache_schema_version", None)
    cache_schema_version = (
        raw_cache_schema_version if isinstance(raw_cache_schema_version, str) else None
    )
    return cache_status, cache_schema_version


def print_failed_files(*, failed_files: tuple[str, ...], console: _PrinterLike) -> None:
    if not failed_files:
        return
    console.print(ui.fmt_failed_files_header(len(failed_files)))
    for failure in failed_files[:10]:
        console.print(f"  • {failure}")
    if len(failed_files) > 10:
        console.print(f"  ... and {len(failed_files) - 10} more")
