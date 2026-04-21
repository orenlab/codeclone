# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from ..findings.clones.grouping import (
    build_block_groups,
    build_groups,
    build_segment_groups,
)
from ..findings.structural.detectors import (
    build_clone_cohort_structural_findings,
)
from ..golden_fixtures import (
    build_suppressed_clone_groups,
    split_clone_groups_for_golden_fixtures,
)
from ..metrics._base import MetricProjectContext
from ..metrics.coverage_join import CoverageJoinParseError, build_coverage_join
from ..metrics.dead_code import find_suppressed_unused
from ..metrics.registry import (
    METRIC_FAMILIES,
    build_project_metrics,
    project_metrics_defaults,
)
from ..models import (
    ClassMetrics,
    CoverageJoinResult,
    DeadCandidate,
    DeadItem,
    DepGraph,
    GroupItemLike,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    ProjectMetrics,
    StructuralFindingGroup,
    Suggestion,
)
from ..report.blocks import prepare_block_report_groups
from ..report.explain import build_block_group_facts
from ..report.segments import prepare_segment_report_groups
from ..report.suggestions import generate_suggestions
from ._types import (
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    ProcessingResult,
    _segment_groups_digest,
    _should_collect_structural_findings,
)
from .bootstrap import _resolve_optional_runtime_path
from .metrics_payload import build_metrics_report_payload


def compute_project_metrics(
    *,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    module_deps: Sequence[ModuleDep],
    dead_candidates: Sequence[DeadCandidate],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str],
    typing_modules: Sequence[ModuleTypingCoverage] = (),
    docstring_modules: Sequence[ModuleDocstringCoverage] = (),
    api_modules: Sequence[ModuleApiSurface] = (),
    files_found: int,
    files_analyzed_or_cached: int,
    function_clone_groups: int,
    block_clone_groups: int,
    skip_dependencies: bool,
    skip_dead_code: bool,
) -> tuple[ProjectMetrics, DepGraph, tuple[DeadItem, ...]]:
    context = MetricProjectContext(
        units=tuple(units),
        class_metrics=tuple(class_metrics),
        module_deps=tuple(module_deps),
        dead_candidates=tuple(dead_candidates),
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        typing_modules=tuple(typing_modules),
        docstring_modules=tuple(docstring_modules),
        api_modules=tuple(api_modules),
        files_found=files_found,
        files_analyzed_or_cached=files_analyzed_or_cached,
        function_clone_groups=function_clone_groups,
        block_clone_groups=block_clone_groups,
        skip_dependencies=skip_dependencies,
        skip_dead_code=skip_dead_code,
    )
    project_fields = project_metrics_defaults()
    dep_graph = DepGraph(
        modules=frozenset(),
        edges=(),
        cycles=(),
        max_depth=0,
        longest_chains=(),
    )
    dead_items: tuple[DeadItem, ...] = ()
    for family in METRIC_FAMILIES.values():
        aggregate = family.aggregate([family.compute(context)])
        project_fields.update(aggregate.project_fields)
        dep_graph = cast("DepGraph", aggregate.artifacts.get("dep_graph", dep_graph))
        dead_items = cast(
            "tuple[DeadItem, ...]",
            aggregate.artifacts.get("dead_items", dead_items),
        )
    return build_project_metrics(project_fields), dep_graph, dead_items


def compute_suggestions(
    *,
    project_metrics: ProjectMetrics,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    func_groups: Mapping[str, Sequence[GroupItemLike]],
    block_groups: Mapping[str, Sequence[GroupItemLike]],
    segment_groups: Mapping[str, Sequence[GroupItemLike]],
    block_group_facts: Mapping[str, Mapping[str, str]] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    scan_root: str = "",
) -> tuple[Suggestion, ...]:
    return generate_suggestions(
        project_metrics=project_metrics,
        units=units,
        class_metrics=class_metrics,
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_group_facts=block_group_facts,
        structural_findings=structural_findings,
        scan_root=scan_root,
    )


def analyze(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
) -> AnalysisResult:
    golden_fixture_paths = tuple(
        str(pattern).strip()
        for pattern in getattr(boot.args, "golden_fixture_paths", ())
        if str(pattern).strip()
    )
    func_split = split_clone_groups_for_golden_fixtures(
        groups=build_groups(processing.units),
        kind="function",
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )
    block_split = split_clone_groups_for_golden_fixtures(
        groups=build_block_groups(processing.blocks),
        kind="block",
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )
    segment_split = split_clone_groups_for_golden_fixtures(
        groups=build_segment_groups(processing.segments),
        kind="segment",
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )

    func_groups = func_split.active_groups
    block_groups = block_split.active_groups
    segment_groups_raw = segment_split.active_groups
    segment_groups_raw_digest = _segment_groups_digest(segment_groups_raw)
    cached_projection = discovery.cached_segment_report_projection
    if (
        cached_projection is not None
        and cached_projection.get("digest") == segment_groups_raw_digest
    ):
        projection_groups = cached_projection.get("groups", {})
        segment_groups = {
            group_key: [
                {
                    "segment_hash": str(item["segment_hash"]),
                    "segment_sig": str(item["segment_sig"]),
                    "filepath": str(item["filepath"]),
                    "qualname": str(item["qualname"]),
                    "start_line": int(item["start_line"]),
                    "end_line": int(item["end_line"]),
                    "size": int(item["size"]),
                }
                for item in projection_groups[group_key]
            ]
            for group_key in sorted(projection_groups)
        }
        suppressed_segment_groups = int(cached_projection.get("suppressed", 0))
    else:
        segment_groups, suppressed_segment_groups = prepare_segment_report_groups(
            segment_groups_raw
        )

    block_groups_report = prepare_block_report_groups(block_groups)
    suppressed_block_groups_report = prepare_block_report_groups(
        block_split.suppressed_groups
    )
    if segment_split.suppressed_groups:
        suppressed_segment_groups_report, _ = prepare_segment_report_groups(
            segment_split.suppressed_groups
        )
    else:
        suppressed_segment_groups_report = {}
    suppressed_clone_groups = (
        *build_suppressed_clone_groups(
            kind="function",
            groups=func_split.suppressed_groups,
            matched_patterns=func_split.matched_patterns,
        ),
        *build_suppressed_clone_groups(
            kind="block",
            groups=suppressed_block_groups_report,
            matched_patterns=block_split.matched_patterns,
        ),
        *build_suppressed_clone_groups(
            kind="segment",
            groups=suppressed_segment_groups_report,
            matched_patterns=segment_split.matched_patterns,
        ),
    )
    block_group_facts = build_block_group_facts(
        {**block_groups_report, **suppressed_block_groups_report}
    )

    func_clones_count = len(func_groups)
    block_clones_count = len(block_groups)
    segment_clones_count = len(segment_groups)
    files_analyzed_or_cached = processing.files_analyzed + discovery.cache_hits

    project_metrics: ProjectMetrics | None = None
    metrics_payload: dict[str, object] | None = None
    suggestions: tuple[Suggestion, ...] = ()
    suppressed_dead_items: tuple[DeadItem, ...] = ()
    coverage_join: CoverageJoinResult | None = None
    cohort_structural_findings: tuple[StructuralFindingGroup, ...] = ()
    if _should_collect_structural_findings(boot.output_paths):
        cohort_structural_findings = build_clone_cohort_structural_findings(
            func_groups=func_groups
        )
    combined_structural_findings = (
        *processing.structural_findings,
        *cohort_structural_findings,
    )
    if not boot.args.skip_metrics:
        project_metrics, _, _ = compute_project_metrics(
            units=processing.units,
            class_metrics=processing.class_metrics,
            module_deps=processing.module_deps,
            dead_candidates=processing.dead_candidates,
            referenced_names=processing.referenced_names,
            referenced_qualnames=processing.referenced_qualnames,
            typing_modules=processing.typing_modules,
            docstring_modules=processing.docstring_modules,
            api_modules=processing.api_modules,
            files_found=discovery.files_found,
            files_analyzed_or_cached=files_analyzed_or_cached,
            function_clone_groups=func_clones_count,
            block_clone_groups=block_clones_count,
            skip_dependencies=boot.args.skip_dependencies,
            skip_dead_code=boot.args.skip_dead_code,
        )
        if not boot.args.skip_dead_code:
            suppressed_dead_items = find_suppressed_unused(
                definitions=tuple(processing.dead_candidates),
                referenced_names=processing.referenced_names,
                referenced_qualnames=processing.referenced_qualnames,
            )
        suggestions = compute_suggestions(
            project_metrics=project_metrics,
            units=processing.units,
            class_metrics=processing.class_metrics,
            func_groups=func_groups,
            block_groups=block_groups_report,
            segment_groups=segment_groups,
            block_group_facts=block_group_facts,
            structural_findings=combined_structural_findings,
            scan_root=str(boot.root),
        )
        coverage_xml_path = _resolve_optional_runtime_path(
            getattr(boot.args, "coverage_xml", None),
            root=boot.root,
        )
        if coverage_xml_path is not None:
            try:
                coverage_join = build_coverage_join(
                    coverage_xml=coverage_xml_path,
                    root_path=boot.root,
                    units=processing.units,
                    hotspot_threshold_percent=int(
                        getattr(boot.args, "coverage_min", 50)
                    ),
                )
            except CoverageJoinParseError as exc:
                coverage_join = CoverageJoinResult(
                    coverage_xml=str(coverage_xml_path),
                    status="invalid",
                    hotspot_threshold_percent=int(
                        getattr(boot.args, "coverage_min", 50)
                    ),
                    invalid_reason=str(exc),
                )
        metrics_payload = build_metrics_report_payload(
            scan_root=str(boot.root),
            project_metrics=project_metrics,
            coverage_join=coverage_join,
            units=processing.units,
            class_metrics=processing.class_metrics,
            module_deps=processing.module_deps,
            source_stats_by_file=processing.source_stats_by_file,
            suppressed_dead_code=suppressed_dead_items,
        )

    return AnalysisResult(
        func_groups=func_groups,
        block_groups=block_groups,
        block_groups_report=block_groups_report,
        segment_groups=segment_groups,
        suppressed_clone_groups=tuple(suppressed_clone_groups),
        suppressed_segment_groups=suppressed_segment_groups,
        block_group_facts=block_group_facts,
        func_clones_count=func_clones_count,
        block_clones_count=block_clones_count,
        segment_clones_count=segment_clones_count,
        files_analyzed_or_cached=files_analyzed_or_cached,
        project_metrics=project_metrics,
        metrics_payload=metrics_payload,
        suggestions=suggestions,
        segment_groups_raw_digest=segment_groups_raw_digest,
        coverage_join=coverage_join,
        suppressed_dead_code_items=len(suppressed_dead_items),
        structural_findings=combined_structural_findings,
    )
