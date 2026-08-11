# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import tokenize
from io import BytesIO
from pathlib import Path

from ..analysis.normalizer import NormalizationConfig
from ..analysis.phase_ledger import (
    INERT_PHASE_LEDGER,
    AnalysisVolumeKey,
    PhaseLedger,
)
from ..analysis.units import extract_units_and_stats_from_source
from ..analysis.wire import WireUnsupportedNode
from ..cache.reuse import source_content_digest
from ..contracts import (
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
)
from ..models import (
    FileStat,
    ModuleRegistryHandle,
    RehydratedCacheNeutral,
    ResolvedSourceIdentity,
)
from ..scanner import resolved_path_under_root
from ._types import (
    MAX_FILE_SIZE,
    UNSUPPORTED_CONSTRUCT_ERROR_PREFIX,
    FileProcessResult,
)


def decode_python_source(raw_source: bytes) -> str:
    """Decode module bytes the way CPython decodes them before compiling.

    A strict UTF-8 decode is not the rule the language uses. It throws away
    two kinds of file the interpreter imports without complaint: one carrying
    a UTF-8 BOM, which decodes but then reaches the parser as a leading
    ``U+FEFF`` and dies there, and one declaring a legacy codec in a PEP 263
    cookie, which never decodes at all. Both were reported as skipped files
    while the run still claimed a verdict over the tree.

    ``tokenize.detect_encoding`` is the same detector the tokenizer uses, so
    the set of files this analyser can read is the set CPython can import —
    by construction, not by a second guess at the rule.
    """

    encoding, _first_lines = tokenize.detect_encoding(BytesIO(raw_source).readline)
    return raw_source.decode(encoding)


_WORKER_MODULE_REGISTRY: ModuleRegistryHandle | None = None


def _install_module_registry(registry: ModuleRegistryHandle) -> None:
    """Install one immutable registry in a worker process before file tasks."""

    global _WORKER_MODULE_REGISTRY
    _WORKER_MODULE_REGISTRY = registry


def _source_identity_for_worker(
    *,
    registry: ModuleRegistryHandle,
    root: str,
    resolved_path: Path,
) -> ResolvedSourceIdentity:
    relative_path = resolved_path.relative_to(Path(root).resolve()).as_posix()
    entry = registry.entries_by_path.get(relative_path)
    if entry is None:
        raise ValueError(f"source path is absent from module registry: {relative_path}")
    return entry.identity


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
    phase_ledger: PhaseLedger = INERT_PHASE_LEDGER,
    neutral_reuse: RehydratedCacheNeutral | None = None,
) -> FileProcessResult:
    try:
        resolved = resolved_path_under_root(filepath, root)
        if resolved is None:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                source_content_digest=None,
                error="Source path resolves outside repository root.",
                error_kind="source_read_error",
            )
        try:
            stat_result = os.stat(resolved)
            if stat_result.st_size > MAX_FILE_SIZE:
                return FileProcessResult(
                    filepath=filepath,
                    success=False,
                    source_content_digest=None,
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
                source_content_digest=None,
                error=f"Cannot stat file: {exc}",
                error_kind="stat_error",
            )
        stat: FileStat = {
            "mtime_ns": stat_result.st_mtime_ns,
            "size": stat_result.st_size,
        }
        try:
            raw_source = resolved.read_bytes()
            parsed_source_digest = source_content_digest(raw_source)
            source = decode_python_source(raw_source)
        except (UnicodeDecodeError, SyntaxError, LookupError) as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                source_content_digest=parsed_source_digest,
                error=f"Encoding error: {exc}",
                error_kind="source_read_error",
            )
        except OSError as exc:
            return FileProcessResult(
                filepath=filepath,
                success=False,
                source_content_digest=None,
                error=f"Cannot read file: {exc}",
                error_kind="source_read_error",
            )
        registry = _WORKER_MODULE_REGISTRY
        if registry is None:
            raise RuntimeError("module registry is not installed in worker")
        identity = _source_identity_for_worker(
            registry=registry,
            root=root,
            resolved_path=resolved,
        )
        try:
            extracted = extract_units_and_stats_from_source(
                source=source,
                filepath=filepath,
                identity=identity,
                registry=registry,
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
                phase_ledger=phase_ledger,
                neutral_reuse=neutral_reuse,
            )
        except WireUnsupportedNode as exc:
            # A construct outside the reviewed wire whitelist — typically
            # syntax newer than this engine (PEP 810 ``is_lazy`` was the class
            # incident). A typed outcome keeps the loss visible: counted as
            # skipped, attributed in the report, and summarized on the console.
            return FileProcessResult(
                filepath=filepath,
                success=False,
                source_content_digest=parsed_source_digest,
                error=f"{UNSUPPORTED_CONSTRUCT_ERROR_PREFIX}{exc}",
                error_kind="unsupported_construct",
            )
        units, blocks, segments, source_stats, file_metrics, structural_findings = (
            extracted
        )
        phase_snapshot = None
        if phase_ledger.active:
            phase_ledger.add_volume(AnalysisVolumeKey.FILES_TIMED)
            phase_snapshot = phase_ledger.snapshot()
        return FileProcessResult(
            filepath=filepath,
            success=True,
            source_content_digest=parsed_source_digest,
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
            phase_snapshot=phase_snapshot,
        )
    except Exception as exc:  # pragma: no cover - defensive shell around workers
        return FileProcessResult(
            filepath=filepath,
            success=False,
            source_content_digest=None,
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
    phase_ledger: PhaseLedger | None = None,
    neutral_reuse: RehydratedCacheNeutral | None = None,
) -> FileProcessResult:
    return process_file(
        filepath,
        root,
        cfg,
        min_loc,
        min_stmt,
        collect_structural_findings=collect_structural_findings,
        collect_api_surface=collect_api_surface,
        api_include_private_modules=api_include_private_modules,
        block_min_loc=block_min_loc,
        block_min_stmt=block_min_stmt,
        segment_min_loc=segment_min_loc,
        segment_min_stmt=segment_min_stmt,
        phase_ledger=phase_ledger or INERT_PHASE_LEDGER,
        neutral_reuse=neutral_reuse,
    )
