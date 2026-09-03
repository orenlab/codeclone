# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed

from ..analysis.phase_ledger import PhaseLedger, PhaseSnapshot
from ..cache.entries import SourceStatsDict
from ..cache.reuse import clone_artifact_channels
from ..cache.store import Cache
from ..models import (
    ClassMetrics,
    DeadCandidate,
    EventKind,
    FunctionContractSummary,
    FunctionRelationshipFacts,
    GroupItem,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    RuntimeReachabilityFact,
    SecuritySurface,
    SemanticAuthorityResult,
    SemanticEvent,
    StructuralFindingGroup,
    UnsupportedConstructSkip,
)
from ..observability import record_counter, span
from ..semantics.authority import build_semantic_authority
from ..semantics.events import event_counter_key
from ..semantics.registry import parse_authority_registry
from ..utils.lane_selection import api_surface_collection_enabled
from ._types import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RUNTIME_PROCESSES,
    PARALLEL_MIN_FILES_FLOOR,
    PARALLEL_MIN_FILES_PER_WORKER,
    UNSUPPORTED_CONSTRUCT_ERROR_PREFIX,
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
    _unit_to_group_item,
    structural_findings_required,
)
from .worker import _install_module_registry, _invoke_process_file


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


def _build_authority_result(
    *,
    boot: BootstrapResult,
    summaries: Sequence[FunctionContractSummary],
    relationship_facts: Sequence[FunctionRelationshipFacts],
    dead_candidates: Sequence[DeadCandidate],
) -> SemanticAuthorityResult | None:
    registry = parse_authority_registry(getattr(boot.args, "authority", ()))
    enabled = bool(
        getattr(boot.args, "semantic_authority", False)
        or getattr(boot.args, "fail_on_authority_violation", False)
        or registry.entries
    )
    if not enabled:
        return None
    suppressed_rules = {
        candidate.qualname: frozenset(candidate.suppressed_rules)
        for candidate in dead_candidates
        if candidate.suppressed_rules
    }
    return build_semantic_authority(
        summaries,
        relationship_facts,
        registry=registry,
        suppressed_rules=suppressed_rules,
    )


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
    semantic_authority: SemanticAuthorityResult | None = None
    files_to_process = discovery.files_to_process
    registry = discovery.module_registry
    if not files_to_process:
        with span(name="analysis.registry_bind") as registry_span:
            registry_span.set_counter("facts_bound", 0)
            with span(name="analysis.relative_imports") as relative_span:
                relative_span.set_counter("analysis_dependency_targets", 0)
                relative_span.set_counter("analysis_known_internal_not_analyzed", 0)
                relative_span.set_counter("unresolved_relatives", 0)
                relative_span.set_counter("analysis_inventory_submodule_expansions", 0)
                relative_span.set_counter("typed_failures", 0)
        record_counter("registry_worker_installs", 0)
        with span(name="semantics.events") as event_span:
            event_span.set_counter("events_unresolved", 0)
        with span(name="semantics.flow") as flow_span:
            flow_span.set_counter("functions_summarized", 0)
            flow_span.set_counter("unresolved_flow_functions", 0)
        with span(name="semantics.authority.build") as authority_span:
            semantic_authority = _build_authority_result(
                boot=boot,
                summaries=discovery.cached_function_contract_summaries,
                relationship_facts=discovery.cached_function_relationship_facts,
                dead_candidates=discovery.cached_dead_candidates,
            )
            authority_span.set_counter("ir_nodes", 0)
            authority_span.set_counter("scc_count", 0)
            authority_span.set_counter("fixpoint_iterations", 0)
            authority_span.set_counter("sinks_by_status.authoritative", 0)
            authority_span.set_counter("sinks_by_status.adapter", 0)
            authority_span.set_counter("sinks_by_status.shadow", 0)
            authority_span.set_counter("sinks_by_status.mixed", 0)
            authority_span.set_counter("sinks_by_status.unavailable", 0)
            authority_span.set_counter("candidates_emitted", 0)
        return ProcessingResult(
            units=discovery.cached_units,
            blocks=discovery.cached_blocks,
            segments=discovery.cached_segments,
            class_metrics=discovery.cached_class_metrics,
            module_deps=discovery.cached_module_deps,
            dead_candidates=discovery.cached_dead_candidates,
            referenced_names=discovery.cached_referenced_names,
            runtime_reachability=discovery.cached_runtime_reachability,
            security_surfaces=discovery.cached_security_surfaces,
            semantic_events=discovery.cached_semantic_events,
            function_contract_summaries=(discovery.cached_function_contract_summaries),
            semantic_authority=semantic_authority,
            referenced_qualnames=discovery.cached_referenced_qualnames,
            declared_exports=discovery.cached_declared_exports,
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
            function_relationship_facts=discovery.cached_function_relationship_facts,
            source_stats_by_file=discovery.cached_source_stats_by_file,
            source_digest_by_file=discovery.cached_source_digest_by_file,
        )

    all_units: list[GroupItem] = list(discovery.cached_units)
    all_blocks: list[GroupItem] = list(discovery.cached_blocks)
    all_segments: list[GroupItem] = list(discovery.cached_segments)
    all_class_metrics: list[ClassMetrics] = list(discovery.cached_class_metrics)
    all_module_deps: list[ModuleDep] = list(discovery.cached_module_deps)
    all_dead_candidates: list[DeadCandidate] = list(discovery.cached_dead_candidates)
    all_referenced_names: set[str] = set(discovery.cached_referenced_names)
    all_referenced_qualnames: set[str] = set(discovery.cached_referenced_qualnames)
    all_declared_exports: set[str] = set(discovery.cached_declared_exports)
    all_runtime_reachability: list[RuntimeReachabilityFact] = list(
        discovery.cached_runtime_reachability
    )
    all_security_surfaces: list[SecuritySurface] = list(
        discovery.cached_security_surfaces
    )
    all_semantic_events: list[SemanticEvent] = list(discovery.cached_semantic_events)
    all_function_contract_summaries: list[FunctionContractSummary] = list(
        discovery.cached_function_contract_summaries
    )
    all_typing_modules: list[ModuleTypingCoverage] = list(
        discovery.cached_typing_modules
    )
    all_docstring_modules: list[ModuleDocstringCoverage] = list(
        discovery.cached_docstring_modules
    )
    all_api_modules: list[ModuleApiSurface] = list(discovery.cached_api_modules)

    collect_structural_findings = structural_findings_required()
    collect_api_surface = api_surface_collection_enabled(boot.args)
    api_include_private_modules = bool(
        getattr(boot.args, "api_include_private_modules", False)
    )
    # Tier ruling T2: the flags decide what the workers materialize, and the
    # SAME derivation stamps the materialization witness on every cache row
    # written below — one derivation site, so the witness cannot disagree with
    # what the extraction actually did. Flag ownership is unchanged: the
    # ``near_miss`` / ``renamed_structure`` OptionSpecs in ``config/spec.py``.
    collect_near_miss = bool(getattr(boot.args, "near_miss", False))
    collect_renamed_structure = bool(getattr(boot.args, "renamed_structure", False))
    materialized_clone_channels = clone_artifact_channels(
        near_miss=collect_near_miss,
        renamed_structure=collect_renamed_structure,
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
    all_function_relationship_facts: list[FunctionRelationshipFacts] = list(
        discovery.cached_function_relationship_facts
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
    source_digest_by_file: dict[str, str] = dict(discovery.cached_source_digest_by_file)
    neutral_reuse_by_file = dict(discovery.neutral_reuse_by_file)
    failed_files: list[str] = []
    source_read_failures: list[str] = []
    unsupported_construct_skips: list[UnsupportedConstructSkip] = []
    root_str = str(boot.root)
    processes = _resolve_process_count(boot.args.processes)
    min_loc = int(boot.args.min_loc)
    min_stmt = int(boot.args.min_stmt)
    block_min_loc = int(boot.args.block_min_loc)
    block_min_stmt = int(boot.args.block_min_stmt)
    segment_min_loc = int(boot.args.segment_min_loc)
    segment_min_stmt = int(boot.args.segment_min_stmt)
    from codeclone.observability.runtime import is_observability_enabled

    collect_phases = is_observability_enabled()
    batch_snapshot = PhaseSnapshot.empty()

    def _phase_ledger_for_file() -> PhaseLedger | None:
        return PhaseLedger(active=True) if collect_phases else None

    def _accept_result(result: FileProcessResult) -> None:
        nonlocal batch_snapshot
        nonlocal files_analyzed
        nonlocal files_skipped
        nonlocal analyzed_lines
        nonlocal analyzed_functions
        nonlocal analyzed_methods
        nonlocal analyzed_classes

        if result.success:
            if result.stat is None or result.source_content_digest is None:
                raise RuntimeError(
                    "successful file processing requires stat and source digest"
                )
            if result.phase_snapshot is not None:
                batch_snapshot = batch_snapshot.merge(result.phase_snapshot)
            source_stats_payload = SourceStatsDict(
                lines=result.lines,
                functions=result.functions,
                methods=result.methods,
                classes=result.classes,
            )
            cache.put_file_entry(
                result.filepath,
                result.stat,
                result.units or [],
                result.blocks or [],
                result.segments or [],
                source_content_digest=result.source_content_digest,
                source_stats=source_stats_payload,
                file_metrics=result.file_metrics,
                structural_findings=result.structural_findings,
                materialized_clone_channels=materialized_clone_channels,
                # Same value that told the workers whether to collect, so the
                # row cannot claim a lane this extraction did not fill.
                materialized_api_surface=collect_api_surface,
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
            source_digest_by_file[result.filepath] = result.source_content_digest.value
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
                all_declared_exports.update(result.file_metrics.declared_exports)
                all_runtime_reachability.extend(
                    result.file_metrics.runtime_reachability
                )
                all_security_surfaces.extend(result.file_metrics.security_surfaces)
                semantic_facts = result.file_metrics.semantic_facts
                all_semantic_events.extend(semantic_facts.events)
                all_function_contract_summaries.extend(
                    semantic_facts.function_contract_summaries
                )
                all_function_relationship_facts.extend(
                    result.file_metrics.function_relationship_facts
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
        elif result.error_kind == "unsupported_construct":
            unsupported_construct_skips.append(
                UnsupportedConstructSkip(
                    filepath=result.filepath,
                    construct=(result.error or "").removeprefix(
                        UNSUPPORTED_CONSTRUCT_ERROR_PREFIX
                    ),
                )
            )

    def _run_sequential(files: Sequence[str]) -> None:
        _install_module_registry(registry)
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
                    collect_near_miss=collect_near_miss,
                    collect_renamed_structure=collect_renamed_structure,
                    block_min_loc=block_min_loc,
                    block_min_stmt=block_min_stmt,
                    segment_min_loc=segment_min_loc,
                    segment_min_stmt=segment_min_stmt,
                    phase_ledger=_phase_ledger_for_file(),
                    neutral_reuse=neutral_reuse_by_file.get(filepath),
                )
            )
            if on_advance is not None:
                on_advance()

    def _run_files() -> None:
        nonlocal files_skipped
        if _should_use_parallel(len(files_to_process), processes):
            try:
                executor_context = ProcessPoolExecutor(
                    max_workers=processes,
                    initializer=_install_module_registry,
                    initargs=(registry,),
                )
                with executor_context as executor:
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
                                collect_near_miss=collect_near_miss,
                                collect_renamed_structure=collect_renamed_structure,
                                block_min_loc=block_min_loc,
                                block_min_stmt=block_min_stmt,
                                segment_min_loc=segment_min_loc,
                                segment_min_stmt=segment_min_stmt,
                                phase_ledger=_phase_ledger_for_file(),
                                neutral_reuse=neutral_reuse_by_file.get(filepath),
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
                record_counter("registry_worker_installs", processes)
            except (OSError, RuntimeError, PermissionError) as exc:
                if on_parallel_fallback is not None:
                    on_parallel_fallback(exc)
                _run_sequential(files_to_process)
                record_counter("registry_worker_installs", 1)
        else:
            _run_sequential(files_to_process)
            record_counter("registry_worker_installs", 1)

    with span(name="analysis.registry_bind") as registry_span:
        with span(name="analysis.relative_imports") as relative_span:
            with span(name="semantics.events") as event_span:
                with span(name="semantics.flow") as flow_span:
                    _run_files()
                    flow_span.set_counter(
                        "functions_summarized",
                        len(all_function_contract_summaries),
                    )
                    flow_span.set_counter(
                        "unresolved_flow_functions",
                        sum(
                            summary.unresolved_flow
                            for summary in all_function_contract_summaries
                        ),
                    )
                event_counts: Counter[EventKind] = Counter(
                    event.kind for event in all_semantic_events
                )
                for kind, count in sorted(event_counts.items()):
                    event_span.set_counter(event_counter_key(kind), count)
                event_span.set_counter(
                    "events_unresolved",
                    sum(
                        event.resolution == "unavailable"
                        for event in all_semantic_events
                    ),
                )
            relative_span.set_counter(
                "analysis_dependency_targets",
                sum(bool(dep.target) for dep in all_module_deps),
            )
            relative_span.set_counter(
                "analysis_known_internal_not_analyzed",
                sum(
                    dep.resolution == "known_internal_not_analyzed"
                    for dep in all_module_deps
                ),
            )
            relative_span.set_counter(
                "unresolved_relatives",
                sum(dep.resolution == "unresolved_relative" for dep in all_module_deps),
            )
            relative_span.set_counter(
                "analysis_inventory_submodule_expansions",
                sum(dep.inventory_expansion for dep in all_module_deps),
            )
            relative_span.set_counter("typed_failures", len(failed_files))
        registry_span.set_counter("facts_bound", len(source_stats_by_file))

    with span(name="semantics.authority.build") as authority_span:
        semantic_authority = _build_authority_result(
            boot=boot,
            summaries=all_function_contract_summaries,
            relationship_facts=all_function_relationship_facts,
            dead_candidates=all_dead_candidates,
        )
        authority_span.set_counter(
            "ir_nodes",
            len(semantic_authority.contract_ir.contracts)
            if semantic_authority is not None
            else 0,
        )
        authority_span.set_counter(
            "scc_count",
            len(semantic_authority.contract_ir.sccs)
            if semantic_authority is not None
            else 0,
        )
        authority_span.set_counter(
            "fixpoint_iterations",
            semantic_authority.contract_ir.fixpoint_iterations
            if semantic_authority is not None
            else 0,
        )
        authority_status_counts = (
            Counter(sink.authority_status for sink in semantic_authority.sinks)
            if semantic_authority is not None
            else Counter()
        )
        authority_span.set_counter(
            "sinks_by_status.authoritative",
            authority_status_counts["authoritative"],
        )
        authority_span.set_counter(
            "sinks_by_status.adapter",
            authority_status_counts["adapter"],
        )
        authority_span.set_counter(
            "sinks_by_status.shadow",
            authority_status_counts["shadow"],
        )
        authority_span.set_counter(
            "sinks_by_status.mixed",
            authority_status_counts["mixed"],
        )
        authority_span.set_counter(
            "sinks_by_status.unavailable",
            authority_status_counts["unavailable"],
        )
        authority_span.set_counter(
            "candidates_emitted",
            len(semantic_authority.candidates) if semantic_authority is not None else 0,
        )

    volumes = batch_snapshot.volume_map()
    phase_snapshot = batch_snapshot if volumes.get("files_timed", 0) > 0 else None

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
        runtime_reachability=tuple(
            sorted(
                all_runtime_reachability,
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
        security_surfaces=tuple(
            sorted(
                all_security_surfaces,
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
        semantic_events=tuple(
            sorted(
                all_semantic_events,
                key=lambda item: (
                    item.location[0],
                    item.location[1],
                    item.event_id,
                    item.kind,
                    item.subject,
                ),
            )
        ),
        function_contract_summaries=tuple(
            sorted(
                all_function_contract_summaries,
                key=lambda summary: summary.function,
            )
        ),
        semantic_authority=semantic_authority,
        referenced_qualnames=frozenset(all_referenced_qualnames),
        declared_exports=frozenset(all_declared_exports),
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
        unsupported_construct_skips=tuple(
            sorted(
                unsupported_construct_skips,
                key=lambda skip: (skip.filepath, skip.construct),
            )
        ),
        structural_findings=tuple(all_structural_findings),
        function_relationship_facts=tuple(
            sorted(
                all_function_relationship_facts,
                key=lambda facts: facts.source_qualname,
            )
        ),
        source_stats_by_file=tuple(
            (filepath, *stats)
            for filepath, stats in sorted(source_stats_by_file.items())
        ),
        source_digest_by_file=tuple(sorted(source_digest_by_file.items())),
        phase_snapshot=phase_snapshot,
    )
