# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from ..cache._validators import _is_relationship_record_dict
from ..cache.entries import (
    _as_relationship_kind,
    _as_relationship_origin_lane,
    _as_relationship_resolution_status,
)
from ..cache.projection import rehydrate_cache_neutral
from ..cache.reuse import clone_artifact_channels, prove_cached_source_identity
from ..cache.store import Cache, file_stat_signature
from ..models import (
    CacheEntryV3,
    CacheLaneReuseReason,
    ClassMetrics,
    ContentIdentityVerdict,
    DeadCandidate,
    FunctionContractSummary,
    FunctionRelationshipFacts,
    GroupItem,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    RehydratedCacheNeutral,
    RelationshipRecord,
    RuntimeReachabilityFact,
    SecuritySurface,
    SemanticEvent,
    StructuralFindingGroup,
)
from ..observability import SpanHandle, span
from ..paths.git_snapshot import collect_git_content_snapshot
from ..paths.module_identity.inventory import build_module_registry
from ..paths.worktree_topology import nested_worktree_warnings
from ._types import (
    BootstrapResult,
    DiscoveryResult,
    _block_to_group_item,
    _class_metric_sort_key,
    _coerce_segment_report_projection,
    _dead_candidate_sort_key,
    _group_item_sort_key,
    _module_dep_sort_key,
    _segment_to_group_item,
    _unit_to_group_item,
    structural_findings_required,
)
from .discovery_cache import CachedSourceStatsRefusal
from .discovery_cache import (
    cached_source_stats_refusal as _cached_source_stats_refusal,
)
from .discovery_cache import (
    decode_cached_structural_finding_group as _decode_cached_structural_finding_group,
)
from .discovery_cache import (
    # Explicit re-export: discovery is the public-ring seam for the cached
    # metrics loader, so callers reach it here instead of importing the
    # internal discovery_cache module directly.
    load_cached_metrics_extended as load_cached_metrics_extended,
)
from .discovery_cache import usable_cached_source_stats as _usable_cached_source_stats

# Each reuse decision already carried its reason; nothing published it, so a
# cold run caused by content was diagnosable to its cause and a cold run caused
# by a profile, a binding context or a channel set was not diagnosable at all.
# The keys are literals because the closed vocabulary is checked literally, and
# they are keyed by the decision's own alias so a reason with no counter (or a
# counter with no reason) fails in tests rather than going quiet in a run.
_NEUTRAL_LANE_REASON_COUNTERS: Final[Mapping[CacheLaneReuseReason, str]] = {
    "binding_context_mismatch": "cache_lane_neutral_binding_context_mismatch",
    "clone_channels_mismatch": "cache_lane_neutral_clone_channels_mismatch",
    "content_miss": "cache_lane_neutral_content_miss",
    "hit": "cache_lane_neutral_hit",
    "neutral_profile_mismatch": "cache_lane_neutral_profile_mismatch",
}

_DEPENDENT_LANE_REASON_COUNTERS: Final[Mapping[CacheLaneReuseReason, str]] = {
    "api_surface_witness_mismatch": "cache_lane_dependent_api_surface_witness_mismatch",
    "content_miss": "cache_lane_dependent_content_miss",
    "dependent_profile_mismatch": "cache_lane_dependent_profile_mismatch",
    "hit": "cache_lane_dependent_hit",
}

# The refusal that happens AFTER both lanes agree. This is the one that
# reached nothing at all: the row is still true, it simply does not carry the
# sections this run asked for, and every entry rejected this way was
# indistinguishable from an entry that was never cached.
_POST_LANE_REFUSAL_COUNTERS: Final[Mapping[CachedSourceStatsRefusal, str]] = {
    "structural_findings_absent": "cache_reuse_structural_findings_absent",
}

#: Every member is published on every run, zero included, so a zero means
#: "measured none" and an absent key means "this span did not run". A family
#: that only appears when it is non-zero cannot tell those apart.
_REUSE_REASON_COUNTER_KEYS: Final[tuple[str, ...]] = (
    *_NEUTRAL_LANE_REASON_COUNTERS.values(),
    *_DEPENDENT_LANE_REASON_COUNTERS.values(),
    *_POST_LANE_REFUSAL_COUNTERS.values(),
)


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


def _new_discovery_buffers() -> DiscoveryBuffers:
    # Keep buffer order aligned with DiscoveryBuffers above.
    return [], [], [], [], [], [], set(), set(), [], [], [], [], [], [], []


ContentIdentityCounters = tuple[int, int, int, int, int, int, int, int]


def _content_identity_counters(
    verdict: ContentIdentityVerdict,
) -> ContentIdentityCounters:
    return (
        int(verdict.reason == "blob_hit"),
        int(verdict.reason == "digest_hit"),
        int(verdict.reason == "digest_miss"),
        int(verdict.git_fallback_reason == "dirty"),
        int(verdict.git_fallback_reason == "git_unavailable"),
        int(verdict.git_fallback_reason == "index_ambiguous"),
        int(verdict.git_fallback_reason == "racy"),
        int(verdict.git_fallback_reason == "untracked"),
    )


def _count_lane_reason(
    counts: dict[str, int],
    counters: Mapping[CacheLaneReuseReason, str],
    reason: CacheLaneReuseReason,
) -> None:
    """Attribute one lane verdict to its reason, when that lane can decide it.

    Each lane decides a subset of the alias: a dependent lane never answers
    ``clone_channels_mismatch``. A reason outside the lane's own domain is not
    counted here rather than being folded into a neighbouring key, so the
    family sums to the number of rows the lane actually judged -- which is the
    arithmetic the tests hold this to, and what would break if a new reason
    appeared with no counter behind it.
    """

    counter_key = counters.get(reason)
    if counter_key is not None:
        counts[counter_key] += 1


def _count_post_lane_refusal(
    counts: dict[str, int],
    entry: CacheEntryV3,
    *,
    collect_structural_findings: bool,
) -> None:
    """Attribute a row both lanes accepted but this run cannot serve."""

    refusal = _cached_source_stats_refusal(
        entry, collect_structural_findings=collect_structural_findings
    )
    if refusal is not None:
        counts[_POST_LANE_REFUSAL_COUNTERS[refusal]] += 1


def _publish_reuse_reasons(handle: SpanHandle, counts: Mapping[str, int]) -> None:
    """Put every declared reason on the span, zeros included."""

    for counter_key, counted in counts.items():
        handle.set_counter(counter_key, counted)


def discover(*, boot: BootstrapResult, cache: Cache) -> DiscoveryResult:
    files_found = 0
    cache_hits = 0
    files_skipped = 0
    collect_structural_findings = structural_findings_required()
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
    cached_source_digest_by_file: list[tuple[str, str]] = []
    cached_semantic_events: list[SemanticEvent] = []
    cached_function_contract_summaries: list[FunctionContractSummary] = []
    neutral_reuse_by_file: list[tuple[str, RehydratedCacheNeutral]] = []
    cached_lines = cached_functions = cached_methods = cached_classes = 0
    all_file_paths: list[str] = []

    raw_source_roots = getattr(boot.args, "source_roots", (".",))
    source_roots = (
        raw_source_roots
        if isinstance(raw_source_roots, tuple)
        and all(isinstance(value, str) for value in raw_source_roots)
        else (".",)
    )
    unreadable_paths: list[str] = []
    module_registry = build_module_registry(
        root=boot.root,
        source_roots=source_roots,
        on_unreadable_path=unreadable_paths.append,
    )
    cache.bind_module_registry(module_registry)
    analyzed_paths = tuple(
        str(boot.root / entry.identity.file.path)
        for entry in module_registry.entries_by_path.values()
        if entry.analyzed
    )
    git_snapshot = collect_git_content_snapshot(boot.root, analyzed_paths)
    cache.bind_git_content_snapshot(git_snapshot)
    # A directory the walk could not read is an input the run did not see.
    # It rides the counters that already own lost files rather than a private
    # one of its own: a second channel would be a second thing for every
    # decider to remember to ask, and this one was never asked at all.
    for unreadable_path in unreadable_paths:
        files_found += 1
        files_skipped += 1
        skipped_warnings.append(f"{unreadable_path}: unreadable path, not scanned")
    # A git worktree of this same repository nested inside the root is the
    # opposite absence: nothing was lost, a whole second copy of the project
    # was gained, and the run said nothing. It rides the same warning channel
    # both surfaces already read -- the CLI prints it, the MCP run summary
    # carries it -- and touches no counter, because phase 1 changes what the
    # run SAYS and not one file of what it analysed.
    skipped_warnings.extend(nested_worktree_warnings(boot.root))
    blob_hits = digest_hits = digest_misses = 0
    dirty_fallbacks = git_unavailable_fallbacks = 0
    index_ambiguous_fallbacks = racy_fallbacks = untracked_fallbacks = 0
    digest_verify_cost_us = stat_fast_rejects = 0
    neutral_hits = dependent_misses = 0
    reuse_reasons: dict[str, int] = dict.fromkeys(_REUSE_REASON_COUNTER_KEYS, 0)
    # T2: same flag derivation the processing stage uses for the workers and
    # for the witness it writes; here it is what a cached row's witness must
    # equal before its units are served warm.
    required_clone_channels = clone_artifact_channels(
        near_miss=bool(getattr(boot.args, "near_miss", False)),
        renamed_structure=bool(getattr(boot.args, "renamed_structure", False)),
    )

    with (
        span(name="cache.content_identity") as content_span,
        span(name="cache.profile_reuse") as profile_span,
    ):
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
                (
                    blob_hit,
                    digest_hit,
                    digest_miss,
                    dirty_fallback,
                    git_unavailable_fallback,
                    index_ambiguous_fallback,
                    racy_fallback,
                    untracked_fallback,
                ) = _content_identity_counters(verdict)
                blob_hits += blob_hit
                digest_hits += digest_hit
                digest_misses += digest_miss
                dirty_fallbacks += dirty_fallback
                git_unavailable_fallbacks += git_unavailable_fallback
                index_ambiguous_fallbacks += index_ambiguous_fallback
                racy_fallbacks += racy_fallback
                untracked_fallbacks += untracked_fallback
                digest_verify_cost_us += verdict.digest_verify_cost_us
                stat_fast_rejects += int(verdict.stat_fast_reject)
                decision = cache.reuse_decision(
                    content=verdict,
                    entry=cached,
                    runtime_path=filepath,
                    required_clone_channels=required_clone_channels,
                )
                neutral_hits += int(decision.neutral.hit)
                dependent_misses += int(not decision.dependent.hit)
                _count_lane_reason(
                    reuse_reasons,
                    _NEUTRAL_LANE_REASON_COUNTERS,
                    decision.neutral.reason,
                )
                _count_lane_reason(
                    reuse_reasons,
                    _DEPENDENT_LANE_REASON_COUNTERS,
                    decision.dependent.reason,
                )
                if decision.neutral.hit:
                    registry_entry = module_registry.entries_by_path.get(
                        Path(filepath)
                        .resolve()
                        .relative_to(boot.root.resolve())
                        .as_posix()
                    )
                    if registry_entry is None:
                        # Not counted: no input in eight probed layouts (2026-09-02
                        # -- namespace and regular packages, src layouts, name
                        # collisions, non-identifier names) reaches this branch,
                        # and a counter nothing can raise is not telemetry. If it
                        # ever fires, the lane families stop summing to the rows
                        # judged, which is the arithmetic the tests hold.
                        files_to_process.append(filepath)
                        continue
                    python_module = registry_entry.identity.python_module
                    module_name = (
                        python_module.module
                        if python_module is not None
                        else registry_entry.identity.file.path
                    )
                    neutral = rehydrate_cache_neutral(
                        cached.module_neutral,
                        module_name=module_name,
                        filepath=filepath,
                        analysed_filepath=registry_entry.identity.file.path,
                    )
                    if not decision.dependent.hit:
                        files_to_process.append(filepath)
                        neutral_reuse_by_file.append((filepath, neutral))
                        continue
                    cached_source_stats = _usable_cached_source_stats(
                        cached,
                        skip_metrics=boot.args.skip_metrics,
                        collect_structural_findings=collect_structural_findings,
                    )
                    if cached_source_stats is None:
                        _count_post_lane_refusal(
                            reuse_reasons,
                            cached,
                            collect_structural_findings=collect_structural_findings,
                        )
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
                    cached_source_digest_by_file.append(
                        (filepath, cached.source_content_digest.value)
                    )
                    cached_units.extend(
                        _unit_to_group_item(unit) for unit in neutral.units
                    )
                    cached_blocks.extend(
                        _block_to_group_item(block) for block in neutral.blocks
                    )
                    cached_segments.extend(
                        _segment_to_group_item(segment) for segment in neutral.segments
                    )
                    cached_semantic_events.extend(neutral.semantic_facts.events)
                    cached_function_contract_summaries.extend(
                        neutral.semantic_facts.function_contract_summaries
                    )
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
                        ) = load_cached_metrics_extended(
                            cached,
                            filepath=filepath,
                            module_registry=module_registry,
                        )
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
                    # Unconditional: the row was admitted above only because
                    # it carries this section, so a guard here would be one no
                    # input can reach. The ``or ()`` stays for the legacy row
                    # shape the admission rule refuses -- it never gets here.
                    cached_sf.extend(
                        _decode_cached_structural_finding_group(
                            group_dict,
                            filepath,
                        )
                        for group_dict in (
                            cached.module_dependent.structural_findings or ()
                        )
                    )
                    cached_relationship_facts.extend(
                        _decode_cached_function_relationship_facts(
                            cached.module_dependent.function_relationship_facts
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
        profile_span.set_counter("cache_lane_neutral_hit", neutral_hits)
        profile_span.set_counter("cache_lane_dependent_miss", dependent_misses)
        # Whether reuse *hit*, not just that reuse was attempted: a hit is a
        # file whose whole cached profile was adopted, a miss is a file that had
        # to be processed anyway. Without these the span recorded that profile
        # reuse happened and nothing about whether it worked.
        profile_span.set_counter("cache_profile_hit", cache_hits)
        profile_span.set_counter("cache_profile_miss", len(files_to_process))
        _publish_reuse_reasons(profile_span, reuse_reasons)

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
        cached_semantic_events=tuple(
            sorted(cached_semantic_events, key=lambda event: event.event_id)
        ),
        cached_function_contract_summaries=tuple(
            sorted(
                cached_function_contract_summaries,
                key=lambda summary: summary.function,
            )
        ),
        neutral_reuse_by_file=tuple(
            sorted(neutral_reuse_by_file, key=lambda item: item[0])
        ),
        cached_segment_report_projection=cached_segment_projection,
        cached_lines=cached_lines,
        cached_functions=cached_functions,
        cached_methods=cached_methods,
        cached_classes=cached_classes,
        cached_source_stats_by_file=tuple(
            sorted(cached_source_stats_by_file, key=lambda row: row[0])
        ),
        cached_source_digest_by_file=tuple(sorted(cached_source_digest_by_file)),
    )
