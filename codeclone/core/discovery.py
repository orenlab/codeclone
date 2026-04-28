# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..cache.store import Cache, file_stat_signature
from ..models import (
    ClassMetrics,
    DeadCandidate,
    GroupItem,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    SecuritySurface,
    StructuralFindingGroup,
)
from ..scanner import iter_py_files
from ._types import (
    BootstrapResult,
    DiscoveryResult,
    _class_metric_sort_key,
    _coerce_segment_report_projection,
    _dead_candidate_sort_key,
    _group_item_sort_key,
    _module_dep_sort_key,
    _should_collect_structural_findings,
)
from .discovery_cache import (
    decode_cached_structural_finding_group as _decode_cached_structural_finding_group,
)
from .discovery_cache import (
    load_cached_metrics_extended as _load_cached_metrics_extended,
)
from .discovery_cache import usable_cached_source_stats as _usable_cached_source_stats

DiscoveryBuffers = tuple[
    list[GroupItem],
    list[GroupItem],
    list[GroupItem],
    list[ClassMetrics],
    list[ModuleDep],
    list[DeadCandidate],
    set[str],
    set[str],
    list[ModuleTypingCoverage],
    list[ModuleDocstringCoverage],
    list[ModuleApiSurface],
    list[SecuritySurface],
    list[str],
    list[str],
]


def _group_items_from_cache(rows: Sequence[Mapping[str, object]]) -> list[GroupItem]:
    return [dict(row) for row in rows]


def _new_discovery_buffers() -> DiscoveryBuffers:
    # Keep buffer order aligned with DiscoveryBuffers above.
    return [], [], [], [], [], [], set(), set(), [], [], [], [], [], []


def discover(*, boot: BootstrapResult, cache: Cache) -> DiscoveryResult:
    files_found = 0
    cache_hits = 0
    files_skipped = 0
    collect_structural_findings = _should_collect_structural_findings(boot.output_paths)
    cached_segment_projection = _coerce_segment_report_projection(
        getattr(cache, "segment_report_projection", None)
    )
    (
        cached_units,
        cached_blocks,
        cached_segments,
        cached_class_metrics,
        cached_module_deps,
        cached_dead_candidates,
        cached_referenced_names,
        cached_referenced_qualnames,
        cached_typing_modules,
        cached_docstring_modules,
        cached_api_modules,
        cached_security_surfaces,
        files_to_process,
        skipped_warnings,
    ) = _new_discovery_buffers()
    cached_sf: list[StructuralFindingGroup] = []
    cached_source_stats_by_file: list[tuple[str, int, int, int, int]] = []
    cached_lines = 0
    cached_functions = 0
    cached_methods = 0
    cached_classes = 0
    all_file_paths: list[str] = []

    for filepath in iter_py_files(str(boot.root)):
        files_found += 1
        all_file_paths.append(filepath)
        try:
            stat = file_stat_signature(filepath)
        except OSError as exc:
            files_skipped += 1
            skipped_warnings.append(f"{filepath}: {exc}")
            continue
        cached = cache.get_file_entry(filepath)
        if cached and cached.get("stat") == stat:
            cached_source_stats = _usable_cached_source_stats(
                cached,
                skip_metrics=boot.args.skip_metrics,
                collect_structural_findings=collect_structural_findings,
            )
            if cached_source_stats is None:
                files_to_process.append(filepath)
                continue
            cache_hits += 1
            lines, functions, methods, classes = cached_source_stats
            cached_lines += lines
            cached_functions += functions
            cached_methods += methods
            cached_classes += classes
            cached_source_stats_by_file.append(
                (filepath, lines, functions, methods, classes)
            )
            cached_units.extend(_group_items_from_cache(cached["units"]))
            cached_blocks.extend(_group_items_from_cache(cached["blocks"]))
            cached_segments.extend(_group_items_from_cache(cached["segments"]))
            if not boot.args.skip_metrics:
                (
                    class_metrics,
                    module_deps,
                    dead_candidates,
                    referenced_names,
                    referenced_qualnames,
                    typing_coverage,
                    docstring_coverage,
                    api_surface,
                    security_surfaces,
                ) = _load_cached_metrics_extended(cached, filepath=filepath)
                cached_class_metrics.extend(class_metrics)
                cached_module_deps.extend(module_deps)
                cached_dead_candidates.extend(dead_candidates)
                cached_referenced_names.update(referenced_names)
                cached_referenced_qualnames.update(referenced_qualnames)
                if typing_coverage is not None:
                    cached_typing_modules.append(typing_coverage)
                if docstring_coverage is not None:
                    cached_docstring_modules.append(docstring_coverage)
                if api_surface is not None:
                    cached_api_modules.append(api_surface)
                cached_security_surfaces.extend(security_surfaces)
            if collect_structural_findings:
                cached_sf.extend(
                    _decode_cached_structural_finding_group(group_dict, filepath)
                    for group_dict in cached.get("structural_findings") or []
                )
            continue
        files_to_process.append(filepath)

    cache.prune_file_entries(all_file_paths)

    return DiscoveryResult(
        files_found=files_found,
        cache_hits=cache_hits,
        files_skipped=files_skipped,
        all_file_paths=tuple(all_file_paths),
        cached_units=tuple(sorted(cached_units, key=_group_item_sort_key)),
        cached_blocks=tuple(sorted(cached_blocks, key=_group_item_sort_key)),
        cached_segments=tuple(sorted(cached_segments, key=_group_item_sort_key)),
        cached_class_metrics=tuple(
            sorted(cached_class_metrics, key=_class_metric_sort_key)
        ),
        cached_module_deps=tuple(sorted(cached_module_deps, key=_module_dep_sort_key)),
        cached_dead_candidates=tuple(
            sorted(cached_dead_candidates, key=_dead_candidate_sort_key)
        ),
        cached_referenced_names=frozenset(cached_referenced_names),
        cached_security_surfaces=tuple(
            sorted(
                cached_security_surfaces,
                key=lambda item: (
                    item.filepath,
                    item.start_line,
                    item.end_line,
                    item.qualname,
                    item.category,
                    item.capability,
                    item.evidence_symbol,
                ),
            )
        ),
        cached_referenced_qualnames=frozenset(cached_referenced_qualnames),
        cached_typing_modules=tuple(
            sorted(cached_typing_modules, key=lambda item: (item.filepath, item.module))
        ),
        cached_docstring_modules=tuple(
            sorted(
                cached_docstring_modules,
                key=lambda item: (item.filepath, item.module),
            )
        ),
        cached_api_modules=tuple(
            sorted(cached_api_modules, key=lambda item: (item.filepath, item.module))
        ),
        files_to_process=tuple(files_to_process),
        skipped_warnings=tuple(sorted(skipped_warnings)),
        cached_structural_findings=tuple(cached_sf),
        cached_segment_report_projection=cached_segment_projection,
        cached_lines=cached_lines,
        cached_functions=cached_functions,
        cached_methods=cached_methods,
        cached_classes=cached_classes,
        cached_source_stats_by_file=tuple(
            sorted(cached_source_stats_by_file, key=lambda row: row[0])
        ),
    )
