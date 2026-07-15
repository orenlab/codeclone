# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from ..cache._validators import _is_relationship_record_dict
from ..cache.entries import (
    _as_relationship_kind,
    _as_relationship_origin_lane,
    _as_relationship_resolution_status,
)
from ..cache.reuse import prove_cached_source_identity
from ..cache.store import Cache, file_stat_signature
from ..models import (
    ClassMetrics,
    DeadCandidate,
    FunctionRelationshipFacts,
    GroupItem,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    RelationshipRecord,
    RuntimeReachabilityFact,
    SecuritySurface,
    StructuralFindingGroup,
)
from ..observability import span
from ..paths.git_snapshot import collect_git_content_snapshot
from ..paths.module_identity.inventory import build_module_registry
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


def _decode_cached_relationship_record(value: object) -> RelationshipRecord | None:
    if not _is_relationship_record_dict(value):
        return None
    relation_kind = _as_relationship_kind(value["relation_kind"])
    resolution_status = _as_relationship_resolution_status(value["resolution_status"])
    origin_lane = _as_relationship_origin_lane(value["origin_lane"])
    if relation_kind is None or resolution_status is None or origin_lane is None:
        return None
    return RelationshipRecord(
        relation_kind=relation_kind,
        resolution_status=resolution_status,
        origin_lane=origin_lane,
        source_qualname=value["source_qualname"],
        target_qualname=value["target_qualname"],
        path=value["path"],
        line=value["line"],
        expression=value["expression"],
        resolution_rule=value["resolution_rule"],
    )


def _decode_cached_function_relationship_facts(
    rows: Sequence[Mapping[str, object]],
) -> list[FunctionRelationshipFacts]:
    """Reconstruct typed relationship facts from a trusted cache entry.

    Kept local to discovery (not in the shared cached-metrics decoder) so the
    canonical ``load_cached_metrics_extended`` path stays byte-identical. The
    cache is already integrity-validated on store, so this is a lean rehydration.
    """
    facts: list[FunctionRelationshipFacts] = []
    for row in rows:
        relationships = row.get("relationships")
        source_qualname = row.get("source_qualname")
        if not isinstance(relationships, list) or not isinstance(source_qualname, str):
            continue
        records = tuple(
            record
            for raw_record in relationships
            if (record := _decode_cached_relationship_record(raw_record)) is not None
            and record.source_qualname == source_qualname
        )
        facts.append(
            FunctionRelationshipFacts(
                source_qualname=source_qualname, relationships=records
            )
        )
    return facts


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
    list[RuntimeReachabilityFact],
    list[SecuritySurface],
    list[str],
    list[str],
]


def _group_items_from_cache(rows: Sequence[Mapping[str, object]]) -> list[GroupItem]:
    return [dict(row) for row in rows]


def _new_discovery_buffers() -> DiscoveryBuffers:
    # Keep buffer order aligned with DiscoveryBuffers above.
    return [], [], [], [], [], [], set(), set(), [], [], [], [], [], [], []


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
        cached_runtime_reachability,
        cached_security_surfaces,
        files_to_process,
        skipped_warnings,
    ) = _new_discovery_buffers()
    cached_sf: list[StructuralFindingGroup] = []
    cached_relationship_facts: list[FunctionRelationshipFacts] = []
    cached_source_stats_by_file: list[tuple[str, int, int, int, int]] = []
    cached_lines = cached_functions = cached_methods = cached_classes = 0
    all_file_paths: list[str] = []

    raw_source_roots = getattr(boot.args, "source_roots", (".",))
    source_roots = (
        raw_source_roots
        if isinstance(raw_source_roots, tuple)
        and all(isinstance(value, str) for value in raw_source_roots)
        else (".",)
    )
    module_registry = build_module_registry(
        root=boot.root,
        source_roots=source_roots,
    )
    analyzed_paths = tuple(
        str(boot.root / entry.identity.file.path)
        for entry in module_registry.entries_by_path.values()
        if entry.analyzed
    )
    git_snapshot = collect_git_content_snapshot(boot.root, analyzed_paths)
    cache.bind_git_content_snapshot(git_snapshot)
    blob_hits = digest_hits = digest_misses = 0
    dirty_fallbacks = git_unavailable_fallbacks = 0
    index_ambiguous_fallbacks = racy_fallbacks = untracked_fallbacks = 0
    digest_verify_cost_us = stat_fast_rejects = 0

    with span(name="cache.content_identity") as content_span:
        for filepath in analyzed_paths:
            files_found += 1
            all_file_paths.append(filepath)
            try:
                stat = file_stat_signature(filepath)
            except OSError as exc:
                files_skipped += 1
                skipped_warnings.append(f"{filepath}: {exc}")
                continue
            cached = cache.get_file_entry(filepath)
            if cached is not None:
                verdict = prove_cached_source_identity(
                    path=Path(filepath),
                    entry=cached,
                    current_stat=stat,
                    git_snapshot=git_snapshot,
                )
                if verdict.reason == "blob_hit":
                    blob_hits += 1
                elif verdict.reason == "digest_hit":
                    digest_hits += 1
                elif verdict.reason == "digest_miss":
                    digest_misses += 1
                if verdict.git_fallback_reason == "dirty":
                    dirty_fallbacks += 1
                elif verdict.git_fallback_reason == "git_unavailable":
                    git_unavailable_fallbacks += 1
                elif verdict.git_fallback_reason == "index_ambiguous":
                    index_ambiguous_fallbacks += 1
                elif verdict.git_fallback_reason == "racy":
                    racy_fallbacks += 1
                elif verdict.git_fallback_reason == "untracked":
                    untracked_fallbacks += 1
                digest_verify_cost_us += verdict.digest_verify_cost_us
                stat_fast_rejects += int(verdict.stat_fast_reject)
                if verdict.hit:
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
                            runtime_reachability,
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
                        cached_runtime_reachability.extend(runtime_reachability)
                        cached_security_surfaces.extend(security_surfaces)
                    if collect_structural_findings:
                        cached_sf.extend(
                            _decode_cached_structural_finding_group(
                                group_dict,
                                filepath,
                            )
                            for group_dict in cached.get("structural_findings") or []
                        )
                    cached_relationship_facts.extend(
                        _decode_cached_function_relationship_facts(
                            cached.get("function_relationship_facts") or []
                        )
                    )
                    continue
            files_to_process.append(filepath)

        content_span.set_counter("cache_content_decision_blob_hit", blob_hits)
        content_span.set_counter("cache_content_decision_digest_hit", digest_hits)
        content_span.set_counter("cache_content_decision_digest_miss", digest_misses)
        content_span.set_counter("cache_content_decision_dirty", dirty_fallbacks)
        content_span.set_counter(
            "cache_content_decision_git_unavailable",
            git_unavailable_fallbacks,
        )
        content_span.set_counter(
            "cache_content_decision_index_ambiguous",
            index_ambiguous_fallbacks,
        )
        content_span.set_counter("cache_content_decision_racy", racy_fallbacks)
        content_span.set_counter(
            "cache_content_decision_untracked",
            untracked_fallbacks,
        )
        content_span.set_counter(
            "cache_content_digest_verify_cost_us",
            digest_verify_cost_us,
        )
        content_span.set_counter("cache_stat_fast_reject", stat_fast_rejects)

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
        cached_runtime_reachability=tuple(
            sorted(
                cached_runtime_reachability,
                key=lambda item: (
                    item.filepath,
                    item.start_line,
                    item.end_line,
                    item.target_qualname,
                    item.framework,
                    item.edge_kind,
                    item.evidence_symbol,
                ),
            )
        ),
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
        module_registry=module_registry,
        cached_structural_findings=tuple(cached_sf),
        cached_function_relationship_facts=tuple(
            sorted(cached_relationship_facts, key=lambda facts: facts.source_qualname)
        ),
        cached_segment_report_projection=cached_segment_projection,
        cached_lines=cached_lines,
        cached_functions=cached_functions,
        cached_methods=cached_methods,
        cached_classes=cached_classes,
        cached_source_stats_by_file=tuple(
            sorted(cached_source_stats_by_file, key=lambda row: row[0])
        ),
    )
