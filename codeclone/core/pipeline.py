# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from ..contracts import (
    CLONE_KIND_BLOCK,
    CLONE_KIND_FUNCTION,
    CLONE_KIND_SEGMENT,
    DEFAULT_COVERAGE_MIN,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
)
from ..findings.clones.golden_fixtures import (
    build_suppressed_clone_groups,
    split_clone_groups_for_golden_fixtures,
)
from ..findings.clones.grouping import (
    build_block_groups,
    build_groups,
    build_segment_groups,
    clone_eligible_units,
)
from ..findings.clones.near_miss import build_near_miss_pairs
from ..findings.clones.renamed_structure import build_renamed_structure_groups
from ..findings.structural.detectors import (
    build_clone_cohort_structural_findings,
)
from ..metrics.coupling import resolve_project_class_coupling
from ..metrics.coverage_join import CoverageJoinParseError, build_coverage_join
from ..metrics.dead_code import (
    collect_test_reference_sources,
    find_suppressed_unused,
)
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
    FunctionRelationshipFacts,
    GroupItemLike,
    LiveRootReason,
    MetricProjectContext,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleRegistryHandle,
    ModuleTypingCoverage,
    ProjectMetrics,
    RuntimeReachabilityFact,
    SecuritySurface,
    SemanticAuthorityResult,
    StructuralFindingGroup,
    Suggestion,
)
from ..observability.runtime import span
from ..observations.contracts import ObservationContractError
from ..observations.lanes import (
    build_observation_lanes,
    canonical_observation_lane_bytes,
    observation_lane_item_count,
)
from ..observations.projection import build_observation_bundle
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
from .entrypoints import (
    collect_project_entrypoint_qualnames,
    collect_project_export_root_evidence,
)
from .metrics_payload import build_metrics_report_payload


def _artifact_dep_graph(value: object, default: DepGraph) -> DepGraph:
    return value if isinstance(value, DepGraph) else default


def _artifact_dead_items(
    value: object,
    default: tuple[DeadItem, ...],
) -> tuple[DeadItem, ...]:
    if isinstance(value, tuple):
        dead_items = tuple(item for item in value if isinstance(item, DeadItem))
        if len(dead_items) == len(value):
            return dead_items
    return default


def _with_export_root_reasons(
    candidates: Sequence[DeadCandidate],
    *,
    evidence: Sequence[tuple[str, LiveRootReason]],
) -> tuple[DeadCandidate, ...]:
    """Fold whole-project export-root reasons onto the per-file candidates.

    A candidate that already carries a walk-resolved reason keeps it: the
    module walk saw direct evidence, which is the more specific fact.
    """
    if not evidence:
        return tuple(candidates)
    reason_by_qualname = dict(evidence)
    return tuple(
        replace(candidate, live_root_reason=reason)
        if candidate.live_root_reason is None
        and (reason := reason_by_qualname.get(candidate.qualname)) is not None
        else candidate
        for candidate in candidates
    )


def compute_project_metrics(
    *,
    units: Sequence[GroupItemLike],
    class_metrics: Sequence[ClassMetrics],
    module_deps: Sequence[ModuleDep],
    dead_candidates: Sequence[DeadCandidate],
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str],
    runtime_reachability: Sequence[RuntimeReachabilityFact] = (),
    function_relationship_facts: Sequence[FunctionRelationshipFacts] = (),
    security_surfaces: Sequence[SecuritySurface] = (),
    typing_modules: Sequence[ModuleTypingCoverage] = (),
    docstring_modules: Sequence[ModuleDocstringCoverage] = (),
    api_modules: Sequence[ModuleApiSurface] = (),
    semantic_authority: SemanticAuthorityResult | None = None,
    files_found: int,
    files_analyzed_or_cached: int,
    function_clone_groups: int,
    block_clone_groups: int,
    module_registry: ModuleRegistryHandle,
    skip_dependencies: bool,
    skip_dead_code: bool,
    scan_root: str = "",
    golden_fixture_paths: Sequence[str] = (),
) -> tuple[ProjectMetrics, DepGraph, tuple[DeadItem, ...]]:
    context = MetricProjectContext(
        units=tuple(units),
        # Resolving imported call targets needs the whole class index, so the
        # coupling fold is applied here rather than per file. It is idempotent,
        # which is what lets the pipeline fold once for its own consumers and
        # still route through this entry point.
        class_metrics=resolve_project_class_coupling(tuple(class_metrics)),
        module_deps=tuple(module_deps),
        dead_candidates=tuple(dead_candidates),
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        test_reference_sources=collect_test_reference_sources(
            tuple(function_relationship_facts)
        ),
        runtime_reachability=tuple(runtime_reachability),
        security_surfaces=tuple(security_surfaces),
        typing_modules=tuple(typing_modules),
        docstring_modules=tuple(docstring_modules),
        api_modules=tuple(api_modules),
        semantic_authority=semantic_authority,
        files_found=files_found,
        files_analyzed_or_cached=files_analyzed_or_cached,
        function_clone_groups=function_clone_groups,
        block_clone_groups=block_clone_groups,
        module_registry=module_registry,
        skip_dependencies=skip_dependencies,
        skip_dead_code=skip_dead_code,
        scan_root=scan_root,
        golden_fixture_paths=tuple(golden_fixture_paths),
    )
    project_fields = project_metrics_defaults()
    dep_graph = DepGraph(
        modules=frozenset(),
        edges=(),
        cycles=(),
        max_depth=0,
        avg_depth=0.0,
        p95_depth=0,
        longest_chains=(),
    )
    dead_items: tuple[DeadItem, ...] = ()
    for family in METRIC_FAMILIES.values():
        aggregate = family.aggregate([family.compute(context)])
        project_fields.update(aggregate.project_fields)
        dep_graph = _artifact_dep_graph(aggregate.artifacts.get("dep_graph"), dep_graph)
        dead_items = _artifact_dead_items(
            aggregate.artifacts.get("dead_items"),
            dead_items,
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
    collect_block_group_facts: bool = True,
) -> AnalysisResult:
    golden_fixture_paths = tuple(
        str(pattern).strip()
        for pattern in getattr(boot.args, "golden_fixture_paths", ())
        if str(pattern).strip()
    )
    # processing.units carries a metric fact per defined function; the clone
    # lane takes only the units its floors accept (39Y Y5).
    clone_lane_units = clone_eligible_units(
        processing.units,
        min_loc=int(getattr(boot.args, "min_loc", DEFAULT_MIN_LOC)),
        min_stmt=int(getattr(boot.args, "min_stmt", DEFAULT_MIN_STMT)),
    )
    # The near-miss tier reads the same population as the exact tier but keeps
    # its own channel: its pairs never become func_groups, so they reach no
    # observation lane, no baseline novelty and no gate (39Y Y8). Confinement
    # is what makes it gate-neutral; the opt-in below decides whether it runs
    # at all, so a new finding kind never appears unrequested. The flag has
    # exactly one owner: the ``near_miss`` OptionSpec in ``config/spec.py``.
    # ``None`` carries "the producer was never invoked" to the report
    # container (state: disabled); an empty tuple is a completed empty
    # measurement (state: complete, count: 0). The distinction must be made
    # here, at the opt-in decision, because ``else ()`` would erase the
    # execution fact before any serializer could state it (T1, 2026-08-24).
    near_miss_pairs = (
        build_near_miss_pairs(clone_lane_units)
        if bool(getattr(boot.args, "near_miss", False))
        else None
    )
    # Wave C mirrors that confinement exactly: renamed-structure groups keep
    # their own channel beside the clone lane, and the opt-in below decides
    # whether the channel is produced at all. The flag has exactly one owner:
    # the ``renamed_structure`` OptionSpec in ``config/spec.py``. The same
    # execution witness applies: ``None`` means not produced, ``()`` means
    # produced empty.
    renamed_structure_groups = (
        build_renamed_structure_groups(clone_lane_units)
        if bool(getattr(boot.args, "renamed_structure", False))
        else None
    )
    func_split = split_clone_groups_for_golden_fixtures(
        groups=build_groups(clone_lane_units),
        kind=CLONE_KIND_FUNCTION,
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )
    block_split = split_clone_groups_for_golden_fixtures(
        groups=build_block_groups(processing.blocks),
        kind=CLONE_KIND_BLOCK,
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )
    segment_split = split_clone_groups_for_golden_fixtures(
        groups=build_segment_groups(processing.segments),
        kind=CLONE_KIND_SEGMENT,
        golden_fixture_paths=golden_fixture_paths,
        scan_root=str(boot.root),
    )

    func_groups = func_split.active_groups
    block_groups = block_split.active_groups
    segment_groups_raw = segment_split.active_groups
    segment_groups_raw_digest = _segment_groups_digest(segment_groups_raw)
    cached_projection = discovery.cached_segment_report_projection
    segment_groups: dict[str, list[dict[str, object]]]
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
            kind=CLONE_KIND_FUNCTION,
            groups=func_split.suppressed_groups,
            matched_patterns=func_split.matched_patterns,
        ),
        *build_suppressed_clone_groups(
            kind=CLONE_KIND_BLOCK,
            groups=suppressed_block_groups_report,
            matched_patterns=block_split.matched_patterns,
        ),
        *build_suppressed_clone_groups(
            kind=CLONE_KIND_SEGMENT,
            groups=suppressed_segment_groups_report,
            matched_patterns=segment_split.matched_patterns,
        ),
    )
    # Explaining block groups re-parses their source files, and the facts are
    # observable only through the report document (findings and suggestions
    # both ride it). The caller that knows whether a report body will exist
    # gates the build; every other caller keeps the collect-everything default.
    block_group_facts = (
        build_block_group_facts(
            {**block_groups_report, **suppressed_block_groups_report}
        )
        if collect_block_group_facts
        else {}
    )

    func_clones_count = len(func_groups)
    block_clones_count = len(block_groups)
    segment_clones_count = len(segment_groups)
    # Cache hits are analyzed files whose facts came off the cache wire —
    # semantic events and contract summaries included — so they belong in the
    # health denominators exactly like freshly walked files. Excluding them
    # under semantic authority made a warm run score itself as if almost
    # nothing had been analyzed.
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
    # Export roots are a whole-project fact, so they are resolved once here and
    # folded onto the candidates. External-decorator reasons already ride the
    # candidates from the module walk (and therefore the cache), which is what
    # keeps the merged set identical on cold and warm runs.
    export_root_evidence = collect_project_export_root_evidence(
        module_deps=processing.module_deps,
        referenced_qualnames=processing.referenced_qualnames,
        dead_candidates=processing.dead_candidates,
        module_registry=discovery.module_registry,
    )
    dead_candidates = _with_export_root_reasons(
        processing.dead_candidates,
        evidence=export_root_evidence,
    )
    # Same shape as the export-root fold above: whether an imported callable is
    # a class is a whole-project fact, so it is resolved once and every
    # consumer below reads the same coupling numbers.
    class_metrics = resolve_project_class_coupling(processing.class_metrics)
    if not boot.args.skip_metrics:
        referenced_qualnames = frozenset(
            {
                *processing.referenced_qualnames,
                *collect_project_entrypoint_qualnames(
                    root=boot.root,
                    dead_candidates=dead_candidates,
                ),
                *(qualname for qualname, _reason in export_root_evidence),
            }
        )
        project_metrics, dep_graph, _ = compute_project_metrics(
            units=processing.units,
            class_metrics=class_metrics,
            module_deps=processing.module_deps,
            dead_candidates=dead_candidates,
            referenced_names=processing.referenced_names,
            referenced_qualnames=referenced_qualnames,
            runtime_reachability=processing.runtime_reachability,
            function_relationship_facts=processing.function_relationship_facts,
            security_surfaces=processing.security_surfaces,
            typing_modules=processing.typing_modules,
            docstring_modules=processing.docstring_modules,
            api_modules=processing.api_modules,
            semantic_authority=processing.semantic_authority,
            files_found=discovery.files_found,
            files_analyzed_or_cached=files_analyzed_or_cached,
            function_clone_groups=func_clones_count,
            block_clone_groups=block_clones_count,
            module_registry=discovery.module_registry,
            skip_dependencies=boot.args.skip_dependencies,
            skip_dead_code=boot.args.skip_dead_code,
            scan_root=str(boot.root),
            golden_fixture_paths=golden_fixture_paths,
        )
        if not boot.args.skip_dead_code:
            suppressed_dead_items = find_suppressed_unused(
                definitions=tuple(processing.dead_candidates),
                referenced_names=processing.referenced_names,
                referenced_qualnames=referenced_qualnames,
                runtime_reachability=processing.runtime_reachability,
                function_relationship_facts=processing.function_relationship_facts,
                class_metrics=class_metrics,
                module_registry=discovery.module_registry,
            )
        suggestions = compute_suggestions(
            project_metrics=project_metrics,
            units=processing.units,
            class_metrics=class_metrics,
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
                        getattr(boot.args, "coverage_min", DEFAULT_COVERAGE_MIN)
                    ),
                )
            except CoverageJoinParseError as exc:
                coverage_join = CoverageJoinResult(
                    coverage_xml=str(coverage_xml_path),
                    status="invalid",
                    hotspot_threshold_percent=int(
                        getattr(boot.args, "coverage_min", DEFAULT_COVERAGE_MIN)
                    ),
                    invalid_reason=str(exc),
                )
        metrics_payload = build_metrics_report_payload(
            scan_root=str(boot.root),
            project_metrics=project_metrics,
            dep_graph=dep_graph,
            coverage_join=coverage_join,
            units=processing.units,
            class_metrics=class_metrics,
            module_deps=processing.module_deps,
            module_registry=discovery.module_registry,
            runtime_reachability=processing.runtime_reachability,
            security_surfaces=processing.security_surfaces,
            source_stats_by_file=processing.source_stats_by_file,
            suppressed_dead_code=suppressed_dead_items,
        )

    collect_metrics = not bool(boot.args.skip_metrics)
    collect_api_surface = collect_metrics and bool(
        getattr(boot.args, "api_surface", False)
    )
    unresolved_override_items = (
        () if project_metrics is None else project_metrics.unresolved_overrides
    )
    with span(name="observations.build") as observation_span:
        try:
            observation_bundle = build_observation_bundle(
                scan_root=boot.root,
                module_registry=discovery.module_registry,
                function_clone_keys=tuple(func_groups),
                block_clone_keys=tuple(block_groups),
                module_deps=processing.module_deps,
                api_modules=processing.api_modules,
                dead_candidates=dead_candidates,
                abstained_qualnames=frozenset(
                    item.qualname for item in unresolved_override_items
                ),
                referenced_names=processing.referenced_names,
                referenced_qualnames=processing.referenced_qualnames,
                runtime_reachability=processing.runtime_reachability,
                units=processing.units,
                class_metrics=class_metrics,
                typing_modules=processing.typing_modules,
                docstring_modules=processing.docstring_modules,
                semantic_authority=processing.semantic_authority,
                collect_metrics=collect_metrics,
                collect_dependencies=(
                    collect_metrics and not bool(boot.args.skip_dependencies)
                ),
                collect_dead_code=(
                    collect_metrics and not bool(boot.args.skip_dead_code)
                ),
                collect_api_surface=collect_api_surface,
            )
        except ObservationContractError:
            observation_span.set_counter("observations_contract_failures", 1)
            raise
        observation_span.set_counter(
            "observations_fact_families",
            len(observation_bundle.contract.enabled_lanes),
        )
        observation_span.set_counter(
            "observations_semantic_reuse",
            int(observation_bundle.semantic is not None),
        )

    with span(name="observations.lanes.build") as lanes_span:
        try:
            observation_lanes = build_observation_lanes(observation_bundle)
        except ObservationContractError:
            lanes_span.set_counter("observations_contract_failures", 1)
            raise
        lanes_span.set_counter("observations_enabled_lanes", len(observation_lanes))
        lanes_span.set_counter(
            "observations_lane_items",
            sum(observation_lane_item_count(lane) for lane in observation_lanes),
        )
        lanes_span.set_counter(
            "observations_lane_bytes",
            sum(
                len(canonical_observation_lane_bytes(lane))
                for lane in observation_lanes
            ),
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
        observation_bundle=observation_bundle,
        coverage_join=coverage_join,
        suppressed_dead_code_items=len(suppressed_dead_items),
        structural_findings=combined_structural_findings,
        near_miss_pairs=near_miss_pairs,
        renamed_structure_groups=renamed_structure_groups,
    )
