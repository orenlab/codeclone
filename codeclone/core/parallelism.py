# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed

from ..cache import Cache, SourceStatsDict
from ..models import (
    ClassMetrics,
    DeadCandidate,
    GroupItem,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    StructuralFindingGroup,
)
from ._types import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RUNTIME_PROCESSES,
    PARALLEL_MIN_FILES_FLOOR,
    PARALLEL_MIN_FILES_PER_WORKER,
    BootstrapResult,
    DiscoveryResult,
    FileProcessResult,
    ProcessingResult,
    _block_to_group_item,
    _class_metric_sort_key,
    _dead_candidate_sort_key,
    _group_item_sort_key,
    _module_dep_sort_key,
    _segment_to_group_item,
    _should_collect_structural_findings,
    _unit_to_group_item,
)
from .worker import _invoke_process_file


def _parallel_min_files(processes: int) -> int:
    return max(PARALLEL_MIN_FILES_FLOOR, processes * PARALLEL_MIN_FILES_PER_WORKER)


def _resolve_process_count(processes: object) -> int:
    if not isinstance(processes, int):
        return DEFAULT_RUNTIME_PROCESSES
    return max(1, processes)


def _should_use_parallel(files_count: int, processes: int) -> bool:
    if processes <= 1:
        return False
    return files_count >= _parallel_min_files(processes)


def process(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    cache: Cache,
    on_advance: Callable[[], None] | None = None,
    on_worker_error: Callable[[str], None] | None = None,
    on_parallel_fallback: Callable[[Exception], None] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ProcessingResult:
    files_to_process = discovery.files_to_process
    if not files_to_process:
        return ProcessingResult(
            units=discovery.cached_units,
            blocks=discovery.cached_blocks,
            segments=discovery.cached_segments,
            class_metrics=discovery.cached_class_metrics,
            module_deps=discovery.cached_module_deps,
            dead_candidates=discovery.cached_dead_candidates,
            referenced_names=discovery.cached_referenced_names,
            referenced_qualnames=discovery.cached_referenced_qualnames,
            typing_modules=discovery.cached_typing_modules,
            docstring_modules=discovery.cached_docstring_modules,
            api_modules=discovery.cached_api_modules,
            files_analyzed=0,
            files_skipped=discovery.files_skipped,
            analyzed_lines=0,
            analyzed_functions=0,
            analyzed_methods=0,
            analyzed_classes=0,
            failed_files=(),
            source_read_failures=(),
            structural_findings=discovery.cached_structural_findings,
            source_stats_by_file=discovery.cached_source_stats_by_file,
        )

    all_units: list[GroupItem] = list(discovery.cached_units)
    all_blocks: list[GroupItem] = list(discovery.cached_blocks)
    all_segments: list[GroupItem] = list(discovery.cached_segments)
    all_class_metrics: list[ClassMetrics] = list(discovery.cached_class_metrics)
    all_module_deps: list[ModuleDep] = list(discovery.cached_module_deps)
    all_dead_candidates: list[DeadCandidate] = list(discovery.cached_dead_candidates)
    all_referenced_names: set[str] = set(discovery.cached_referenced_names)
    all_referenced_qualnames: set[str] = set(discovery.cached_referenced_qualnames)
    all_typing_modules: list[ModuleTypingCoverage] = list(
        discovery.cached_typing_modules
    )
    all_docstring_modules: list[ModuleDocstringCoverage] = list(
        discovery.cached_docstring_modules
    )
    all_api_modules: list[ModuleApiSurface] = list(discovery.cached_api_modules)

    collect_structural_findings = _should_collect_structural_findings(boot.output_paths)
    collect_api_surface = not boot.args.skip_metrics and bool(
        getattr(boot.args, "api_surface", False)
    )
    api_include_private_modules = bool(
        getattr(boot.args, "api_include_private_modules", False)
    )
    files_analyzed = 0
    files_skipped = discovery.files_skipped
    analyzed_lines = 0
    analyzed_functions = 0
    analyzed_methods = 0
    analyzed_classes = 0
    all_structural_findings: list[StructuralFindingGroup] = list(
        discovery.cached_structural_findings
    )
    source_stats_by_file: dict[str, tuple[int, int, int, int]] = {
        filepath: (lines, functions, methods, classes)
        for (
            filepath,
            lines,
            functions,
            methods,
            classes,
        ) in discovery.cached_source_stats_by_file
    }
    failed_files: list[str] = []
    source_read_failures: list[str] = []
    root_str = str(boot.root)
    processes = _resolve_process_count(boot.args.processes)
    min_loc = int(boot.args.min_loc)
    min_stmt = int(boot.args.min_stmt)
    block_min_loc = int(boot.args.block_min_loc)
    block_min_stmt = int(boot.args.block_min_stmt)
    segment_min_loc = int(boot.args.segment_min_loc)
    segment_min_stmt = int(boot.args.segment_min_stmt)

    def _accept_result(result: FileProcessResult) -> None:
        nonlocal files_analyzed
        nonlocal files_skipped
        nonlocal analyzed_lines
        nonlocal analyzed_functions
        nonlocal analyzed_methods
        nonlocal analyzed_classes

        if result.success and result.stat is not None:
            source_stats_payload = SourceStatsDict(
                lines=result.lines,
                functions=result.functions,
                methods=result.methods,
                classes=result.classes,
            )
            structural_payload = (
                result.structural_findings if collect_structural_findings else None
            )
            try:
                cache.put_file_entry(
                    result.filepath,
                    result.stat,
                    result.units or [],
                    result.blocks or [],
                    result.segments or [],
                    source_stats=source_stats_payload,
                    file_metrics=result.file_metrics,
                    structural_findings=structural_payload,
                )
            except TypeError as exc:
                if "source_stats" not in str(exc):
                    raise
                cache.put_file_entry(
                    result.filepath,
                    result.stat,
                    result.units or [],
                    result.blocks or [],
                    result.segments or [],
                    file_metrics=result.file_metrics,
                    structural_findings=structural_payload,
                )
            files_analyzed += 1
            analyzed_lines += result.lines
            analyzed_functions += result.functions
            analyzed_methods += result.methods
            analyzed_classes += result.classes
            source_stats_by_file[result.filepath] = (
                result.lines,
                result.functions,
                result.methods,
                result.classes,
            )
            if result.units:
                all_units.extend(_unit_to_group_item(unit) for unit in result.units)
            if result.blocks:
                all_blocks.extend(
                    _block_to_group_item(block) for block in result.blocks
                )
            if result.segments:
                all_segments.extend(
                    _segment_to_group_item(segment) for segment in result.segments
                )
            if result.structural_findings:
                all_structural_findings.extend(result.structural_findings)
            if not boot.args.skip_metrics and result.file_metrics is not None:
                all_class_metrics.extend(result.file_metrics.class_metrics)
                all_module_deps.extend(result.file_metrics.module_deps)
                all_dead_candidates.extend(result.file_metrics.dead_candidates)
                all_referenced_names.update(result.file_metrics.referenced_names)
                all_referenced_qualnames.update(
                    result.file_metrics.referenced_qualnames
                )
                if result.file_metrics.typing_coverage is not None:
                    all_typing_modules.append(result.file_metrics.typing_coverage)
                if result.file_metrics.docstring_coverage is not None:
                    all_docstring_modules.append(result.file_metrics.docstring_coverage)
                if result.file_metrics.api_surface is not None:
                    all_api_modules.append(result.file_metrics.api_surface)
            return

        files_skipped += 1
        failure = f"{result.filepath}: {result.error}"
        failed_files.append(failure)
        if result.error_kind == "source_read_error":
            source_read_failures.append(failure)

    def _run_sequential(files: Sequence[str]) -> None:
        for filepath in files:
            _accept_result(
                _invoke_process_file(
                    filepath,
                    root_str,
                    boot.config,
                    min_loc,
                    min_stmt,
                    collect_structural_findings=collect_structural_findings,
                    collect_api_surface=collect_api_surface,
                    api_include_private_modules=api_include_private_modules,
                    block_min_loc=block_min_loc,
                    block_min_stmt=block_min_stmt,
                    segment_min_loc=segment_min_loc,
                    segment_min_stmt=segment_min_stmt,
                )
            )
            if on_advance is not None:
                on_advance()

    if _should_use_parallel(len(files_to_process), processes):
        try:
            with ProcessPoolExecutor(max_workers=processes) as executor:
                for idx in range(0, len(files_to_process), batch_size):
                    batch = files_to_process[idx : idx + batch_size]
                    futures = [
                        executor.submit(
                            _invoke_process_file,
                            filepath,
                            root_str,
                            boot.config,
                            min_loc,
                            min_stmt,
                            collect_structural_findings=collect_structural_findings,
                            collect_api_surface=collect_api_surface,
                            api_include_private_modules=api_include_private_modules,
                            block_min_loc=block_min_loc,
                            block_min_stmt=block_min_stmt,
                            segment_min_loc=segment_min_loc,
                            segment_min_stmt=segment_min_stmt,
                        )
                        for filepath in batch
                    ]
                    future_to_path = {
                        id(future): filepath
                        for future, filepath in zip(futures, batch, strict=True)
                    }
                    for future in as_completed(futures):
                        filepath = future_to_path[id(future)]
                        try:
                            _accept_result(future.result())
                        except Exception as exc:  # pragma: no cover - worker crash
                            files_skipped += 1
                            failed_files.append(f"{filepath}: {exc}")
                            if on_worker_error is not None:
                                on_worker_error(str(exc))
                        if on_advance is not None:
                            on_advance()
        except (OSError, RuntimeError, PermissionError) as exc:
            if on_parallel_fallback is not None:
                on_parallel_fallback(exc)
            _run_sequential(files_to_process)
    else:
        _run_sequential(files_to_process)

    return ProcessingResult(
        units=tuple(sorted(all_units, key=_group_item_sort_key)),
        blocks=tuple(sorted(all_blocks, key=_group_item_sort_key)),
        segments=tuple(sorted(all_segments, key=_group_item_sort_key)),
        class_metrics=tuple(sorted(all_class_metrics, key=_class_metric_sort_key)),
        module_deps=tuple(sorted(all_module_deps, key=_module_dep_sort_key)),
        dead_candidates=tuple(
            sorted(all_dead_candidates, key=_dead_candidate_sort_key)
        ),
        referenced_names=frozenset(all_referenced_names),
        referenced_qualnames=frozenset(all_referenced_qualnames),
        typing_modules=tuple(
            sorted(all_typing_modules, key=lambda item: (item.filepath, item.module))
        ),
        docstring_modules=tuple(
            sorted(all_docstring_modules, key=lambda item: (item.filepath, item.module))
        ),
        api_modules=tuple(
            sorted(all_api_modules, key=lambda item: (item.filepath, item.module))
        ),
        files_analyzed=files_analyzed,
        files_skipped=files_skipped,
        analyzed_lines=analyzed_lines,
        analyzed_functions=analyzed_functions,
        analyzed_methods=analyzed_methods,
        analyzed_classes=analyzed_classes,
        failed_files=tuple(sorted(failed_files)),
        source_read_failures=tuple(sorted(source_read_failures)),
        structural_findings=tuple(all_structural_findings),
        source_stats_by_file=tuple(
            (filepath, *stats)
            for filepath, stats in sorted(source_stats_by_file.items())
        ),
    )
