# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
import os
import sys
from collections.abc import Callable
from pathlib import Path

from ..analysis.normalizer import NormalizationConfig
from ..analysis.parser import _ParseTimeoutError
from ..analysis.units import extract_units_and_stats_from_source
from ..cache.entries import FileStat
from ..contracts import (
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
)
from ..contracts.errors import ParseError
from ..scanner import module_name_from_path
from ._types import (
    MAX_FILE_SIZE,
    SKIP_KIND_PARSE_TIMEOUT,
    SKIP_KIND_SYNTAX_ERROR,
    FileProcessResult,
)


def process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    collect_structural_findings: bool = True,
    collect_api_surface: bool = False,
    api_include_private_modules: bool = False,
    block_min_loc: int = DEFAULT_BLOCK_MIN_LOC,
    block_min_stmt: int = DEFAULT_BLOCK_MIN_STMT,
    segment_min_loc: int = DEFAULT_SEGMENT_MIN_LOC,
    segment_min_stmt: int = DEFAULT_SEGMENT_MIN_STMT,
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
        try:
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
        except ParseError as exc:
            # The one ParseError chained from a SyntaxError is the parse of
            # this file's own text (analysis/units.py); only that is a proven
            # syntax rejection. A parse timeout is a resource limit with its
            # own kind. Any other ParseError -- and any SyntaxError raised
            # elsewhere inside CodeClone -- stays an unknown reason below.
            if isinstance(exc.__cause__, SyntaxError):
                return FileProcessResult(
                    filepath=filepath,
                    success=False,
                    error=(
                        "Syntax error under Python "
                        f"{sys.version_info.major}.{sys.version_info.minor}: {exc}"
                    ),
                    error_kind=SKIP_KIND_SYNTAX_ERROR,
                )
            if isinstance(exc.__cause__, _ParseTimeoutError):
                return FileProcessResult(
                    filepath=filepath,
                    success=False,
                    error=f"Parse timeout: {exc}",
                    error_kind=SKIP_KIND_PARSE_TIMEOUT,
                )
            raise
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
    process_callable: Callable[..., FileProcessResult] = process_file
    return process_callable(
        filepath,
        root,
        cfg,
        min_loc,
        min_stmt,
        **supported_kwargs,
    )
