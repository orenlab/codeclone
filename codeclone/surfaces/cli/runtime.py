# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from pathlib import Path

from ... import ui_messages as ui
from ...cache.store import Cache, resolve_cache_status
from ...cache.versioning import CacheStatus
from ...contracts import ExitCode
from . import state as cli_state
from .attrs import bool_attr, int_attr, optional_text_attr, set_bool_attr
from .types import PrinterLike, require_status_console


def validate_numeric_args(args: object) -> bool:
    return bool(
        not (
            int_attr(args, "max_baseline_size_mb") < 0
            or int_attr(args, "max_cache_size_mb") < 0
            or int_attr(args, "fail_threshold", -1) < -1
            or int_attr(args, "fail_complexity", -1) < -1
            or int_attr(args, "fail_coupling", -1) < -1
            or int_attr(args, "fail_cohesion", -1) < -1
            or int_attr(args, "fail_health", -1) < -1
            or int_attr(args, "min_typing_coverage", -1) < -1
            or int_attr(args, "min_typing_coverage", -1) > 100
            or int_attr(args, "min_docstring_coverage", -1) < -1
            or int_attr(args, "min_docstring_coverage", -1) > 100
            or int_attr(args, "coverage_min") < 0
            or int_attr(args, "coverage_min") > 100
        )
    )


def _metrics_flags_requested(args: object) -> bool:
    return bool(
        int_attr(args, "fail_complexity", -1) >= 0
        or int_attr(args, "fail_coupling", -1) >= 0
        or int_attr(args, "fail_cohesion", -1) >= 0
        or bool_attr(args, "fail_cycles")
        or bool_attr(args, "fail_dead_code")
        or int_attr(args, "fail_health", -1) >= 0
        or bool_attr(args, "fail_on_new_metrics")
        or bool_attr(args, "fail_on_typing_regression")
        or bool_attr(args, "fail_on_docstring_regression")
        or bool_attr(args, "fail_on_api_break")
        or bool_attr(args, "fail_on_untested_hotspots")
        or int_attr(args, "min_typing_coverage", -1) >= 0
        or int_attr(args, "min_docstring_coverage", -1) >= 0
        or bool_attr(args, "api_surface")
        or bool_attr(args, "update_metrics_baseline")
        or bool(optional_text_attr(args, "coverage_xml"))
    )


def configure_metrics_mode(
    *,
    args: object,
    metrics_baseline_exists: bool,
    console: PrinterLike,
) -> None:
    metrics_flags_requested = _metrics_flags_requested(args)

    if bool_attr(args, "skip_metrics") and metrics_flags_requested:
        console.print(
            ui.fmt_contract_error(
                "--skip-metrics cannot be used together with metrics gating/update "
                "flags."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    if (
        not bool_attr(args, "skip_metrics")
        and not metrics_flags_requested
        and not metrics_baseline_exists
    ):
        set_bool_attr(args, "skip_metrics", True)

    if bool_attr(args, "skip_metrics"):
        set_bool_attr(args, "skip_dead_code", True)
        set_bool_attr(args, "skip_dependencies", True)
        return

    if bool_attr(args, "fail_dead_code"):
        set_bool_attr(args, "skip_dead_code", False)
    if bool_attr(args, "fail_cycles"):
        set_bool_attr(args, "skip_dependencies", False)
    if bool_attr(args, "fail_on_api_break"):
        set_bool_attr(args, "api_surface", True)


def resolve_cache_path(
    *,
    root_path: Path,
    args: object,
    from_args: bool,
    legacy_cache_path: Path,
    console: PrinterLike,
) -> Path:
    cache_path_arg = optional_text_attr(args, "cache_path")
    if from_args and cache_path_arg:
        return Path(cache_path_arg).expanduser()

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


def metrics_computed(args: object) -> tuple[str, ...]:
    if bool_attr(args, "skip_metrics"):
        return ()

    computed = ["complexity", "coupling", "cohesion", "health"]
    if not bool_attr(args, "skip_dependencies"):
        computed.append("dependencies")
    if not bool_attr(args, "skip_dead_code"):
        computed.append("dead_code")
    computed.append("coverage_adoption")
    if bool_attr(args, "api_surface"):
        computed.append("api_surface")
    if bool(optional_text_attr(args, "coverage_xml")):
        computed.append("coverage_join")
    return tuple(computed)


def resolve_report_cache_path(cache_path: Path) -> Path:
    try:
        return cache_path.resolve()
    except OSError:
        return cache_path


def prepare_metrics_mode_and_ui(
    *,
    args: object,
    root_path: Path,
    baseline_path: Path,
    baseline_exists: bool,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    configure_metrics_mode: object,
    print_banner: object,
) -> None:
    if (
        bool_attr(args, "update_baseline")
        and not bool_attr(args, "skip_metrics")
        and not bool_attr(args, "update_metrics_baseline")
    ):
        set_bool_attr(args, "update_metrics_baseline", True)
    if callable(configure_metrics_mode):
        configure_metrics_mode(
            args=args,
            metrics_baseline_exists=metrics_baseline_exists,
        )
    if (
        bool_attr(args, "update_metrics_baseline")
        and metrics_baseline_path == baseline_path
        and not baseline_exists
        and not bool_attr(args, "update_baseline")
    ):
        set_bool_attr(args, "update_baseline", True)
    if bool_attr(args, "quiet"):
        set_bool_attr(args, "no_progress", True)
        return
    if callable(print_banner):
        print_banner(root=root_path)


def gating_mode_enabled(args: object) -> bool:
    return bool(
        bool_attr(args, "fail_on_new")
        or int_attr(args, "fail_threshold", -1) >= 0
        or int_attr(args, "fail_complexity", -1) >= 0
        or int_attr(args, "fail_coupling", -1) >= 0
        or int_attr(args, "fail_cohesion", -1) >= 0
        or bool_attr(args, "fail_cycles")
        or bool_attr(args, "fail_dead_code")
        or int_attr(args, "fail_health", -1) >= 0
        or bool_attr(args, "fail_on_new_metrics")
        or bool_attr(args, "fail_on_typing_regression")
        or bool_attr(args, "fail_on_docstring_regression")
        or bool_attr(args, "fail_on_api_break")
        or int_attr(args, "min_typing_coverage", -1) >= 0
        or int_attr(args, "min_docstring_coverage", -1) >= 0
    )


def print_failed_files(*, failed_files: tuple[str, ...], console: PrinterLike) -> None:
    if not failed_files:
        return
    console.print(ui.fmt_failed_files_header(len(failed_files)))
    for failure in failed_files[:10]:
        console.print(f"  • {failure}")
    if len(failed_files) > 10:
        console.print(f"  ... and {len(failed_files) - 10} more")


def _resolve_cache_path(
    *,
    root_path: Path,
    args: object,
    from_args: bool,
) -> Path:
    return resolve_cache_path(
        root_path=root_path,
        args=args,
        from_args=from_args,
        legacy_cache_path=cli_state.LEGACY_CACHE_PATH,
        console=require_status_console(cli_state.get_console()),
    )


def _validate_numeric_args(args: object) -> bool:
    return validate_numeric_args(args)


def _configure_metrics_mode(
    *,
    args: object,
    metrics_baseline_exists: bool,
) -> None:
    configure_metrics_mode(
        args=args,
        metrics_baseline_exists=metrics_baseline_exists,
        console=require_status_console(cli_state.get_console()),
    )


def _print_failed_files(failed_files: tuple[str, ...] | list[str]) -> None:
    print_failed_files(
        failed_files=tuple(failed_files),
        console=require_status_console(cli_state.get_console()),
    )


def _metrics_computed(args: object) -> tuple[str, ...]:
    return metrics_computed(args)


def _resolve_cache_status(cache: Cache) -> tuple[CacheStatus, str | None]:
    return resolve_cache_status(cache)
