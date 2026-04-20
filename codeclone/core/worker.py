# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

from ..analysis.normalizer import NormalizationConfig
from ..analysis.units import extract_units_and_stats_from_source
from ..cache import FileStat
from ..scanner import module_name_from_path
from ._types import MAX_FILE_SIZE, FileProcessResult


def process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    collect_structural_findings: bool = True,
    collect_api_surface: bool = False,
    api_include_private_modules: bool = False,
    block_min_loc: int = 20,
    block_min_stmt: int = 8,
    segment_min_loc: int = 20,
    segment_min_stmt: int = 10,
) -> FileProcessResult:
    try:
        try:
            stat_result = os.stat(filepath)
            if stat_result.st_size > MAX_FILE_SIZE:
                return FileProcessResult(
                    filepath=filepath,
                    success=False,
                    error=(
                        f"File too large: {stat_result.st_size} bytes "
                        f"(max {MAX_FILE_SIZE})"
                    ),
                    error_kind="file_too_large",
                )
        except OSError as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                error=f"Cannot stat file: {exc}",
                error_kind="stat_error",
            )
        stat: FileStat = {
            "mtime_ns": stat_result.st_mtime_ns,
            "size": stat_result.st_size,
        }
        try:
            source = Path(filepath).read_text("utf-8")
        except UnicodeDecodeError as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                error=f"Encoding error: {exc}",
                error_kind="source_read_error",
            )
        except OSError as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                error=f"Cannot read file: {exc}",
                error_kind="source_read_error",
            )
        module_name = module_name_from_path(root, filepath)
        units, blocks, segments, source_stats, file_metrics, structural_findings = (
            extract_units_and_stats_from_source(
                source=source,
                filepath=filepath,
                module_name=module_name,
                cfg=cfg,
                min_loc=min_loc,
                min_stmt=min_stmt,
                block_min_loc=block_min_loc,
                block_min_stmt=block_min_stmt,
                segment_min_loc=segment_min_loc,
                segment_min_stmt=segment_min_stmt,
                collect_structural_findings=collect_structural_findings,
                collect_api_surface=collect_api_surface,
                api_include_private_modules=api_include_private_modules,
            )
        )
        return FileProcessResult(
            filepath=filepath,
            success=True,
            units=units,
            blocks=blocks,
            segments=segments,
            lines=source_stats.lines,
            functions=source_stats.functions,
            methods=source_stats.methods,
            classes=source_stats.classes,
            stat=stat,
            file_metrics=file_metrics,
            structural_findings=structural_findings,
        )
    except Exception as exc:  # pragma: no cover - defensive shell around workers
        return FileProcessResult(
            filepath=filepath,
            success=False,
            error=f"Unexpected error: {type(exc).__name__}: {exc}",
            error_kind="unexpected_error",
        )


def _invoke_process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    *,
    collect_structural_findings: bool,
    collect_api_surface: bool,
    api_include_private_modules: bool,
    block_min_loc: int,
    block_min_stmt: int,
    segment_min_loc: int,
    segment_min_stmt: int,
) -> FileProcessResult:
    optional_kwargs: dict[str, object] = {
        "collect_structural_findings": collect_structural_findings,
        "collect_api_surface": collect_api_surface,
        "api_include_private_modules": api_include_private_modules,
        "block_min_loc": block_min_loc,
        "block_min_stmt": block_min_stmt,
        "segment_min_loc": segment_min_loc,
        "segment_min_stmt": segment_min_stmt,
    }
    try:
        signature = inspect.signature(process_file)
    except (TypeError, ValueError):
        supported_kwargs = optional_kwargs
    else:
        parameters = tuple(signature.parameters.values())
        if any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters
        ):
            supported_kwargs = optional_kwargs
        else:
            supported_names = {parameter.name for parameter in parameters}
            supported_kwargs = {
                key: value
                for key, value in optional_kwargs.items()
                if key in supported_names
            }
    process_callable = cast("Callable[..., FileProcessResult]", process_file)
    return process_callable(
        filepath,
        root,
        cfg,
        min_loc,
        min_stmt,
        **supported_kwargs,
    )
