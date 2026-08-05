# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from collections.abc import Callable, Sequence
from dataclasses import replace
from functools import partial
from hashlib import sha256 as _sha256
from typing import TypeVar

from .. import qualnames as _qualnames
from ..blocks import extract_blocks, extract_segments, stmt_hashes
from ..contracts import (
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
)
from ..contracts.errors import ParseError
from ..findings.clones.grouping import is_clone_eligible
from ..findings.structural.detectors import scan_function_structure
from ..metrics.adoption import collect_module_adoption
from ..metrics.api_surface import collect_module_api_surface
from ..metrics.complexity import risk_level
from ..metrics.source_decisions import source_decision_complexity
from ..models import (
    BlockUnit,
    ClassMetrics,
    DeadCandidate,
    FileMetrics,
    FunctionContractSummary,
    LiveRootReason,
    ModuleRegistryHandle,
    RehydratedCacheNeutral,
    ResolvedSourceIdentity,
    SegmentUnit,
    SemanticFileFacts,
    SourceStats,
    StructuralFindingGroup,
    Unit,
)
from ..paths import is_test_filepath
from ..semantics.flow import summarize_function_contract
from ._module_walk import (
    _build_suppression_index_for_source,
    _cohesion_ignored_method_names,
    _collect_dead_candidates,
    _collect_function_relationship_facts,
    _collect_module_walk_data,
    _is_typing_overload_stub,
    resolve_import_observation,
)
from .binding import BindingContext, build_module_bindings
from .class_metrics import _class_metrics_for_node, _node_line_span
from .fingerprint import (
    _cfg_fingerprint_and_complexity,
    bucket_loc,
    near_miss_statement_sequence,
)
from .normalizer import NormalizationConfig
from .parser import PARSE_TIMEOUT_SECONDS, _parse_with_limits
from .phase_ledger import (
    INERT_PHASE_LEDGER,
    SUBPHASE_MODULE_PASSES_ADOPTION_US,
    SUBPHASE_MODULE_PASSES_SECURITY_US,
    AnalysisPhaseKey,
    AnalysisVolumeKey,
    PhaseLedger,
)
from .reachability import collect_runtime_reachability
from .security_surfaces import project_security_surfaces
from .statement_reachability import unreachable_statements

__all__ = ["extract_units_and_stats_from_source"]

_TCloneUnit = TypeVar("_TCloneUnit", BlockUnit, SegmentUnit)


def _stmt_count(node: ast.AST) -> int:
    body = getattr(node, "body", None)
    return len(body) if isinstance(body, list) else 0


def _module_bindings(
    tree: ast.Module,
    identity: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
) -> BindingContext:
    """Build the module's lexical scope graph for wire emission.

    The only context the scope graph cannot read off the tree is where a
    relative import points, which depends on this module's package position.
    That is resolved through the same rules the module walk already uses, so
    both agree on what `from . import x` names.
    """

    def resolve(node: ast.ImportFrom) -> str | None:
        return resolve_import_observation(identity, node, registry).resolved_target

    return build_module_bindings(tree, resolve_from_import=resolve)


_STMT_COUNT_IMPL = _stmt_count


def _raw_source_hash_for_range(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> str:
    window = "".join(source_lines[start_line - 1 : end_line]).strip()
    no_space = "".join(window.split())
    # Moves with the fingerprint version like the other identity domains. This
    # one hashes raw source text rather than the normalized wire, so its
    # meaning does not change between generations -- but it is persisted as
    # ``Unit.raw_hash`` in the cache, which puts it outside the equality-only,
    # never-stored exemption that lets ``ccnm:stmt`` stay put, and a stored
    # digest must not claim a generation it no longer belongs to.
    return _sha256(b"ccfp3:raw\x00" + no_space.encode("utf-8")).hexdigest()


def _unit_shape(node: _qualnames.FunctionNode) -> tuple[int, int, int, int] | None:
    """Return ``(start, end, loc, stmt_count)`` for a locatable function.

    Deliberately independent of the clone floors: a function's shape is a fact
    about the source, not a clone-lane decision. Only a function the parser
    cannot place in the file has no shape (39Y Y5).
    """

    span = _node_line_span(node)
    if span is None:
        return None
    start, end = span
    if end < start:
        return None
    return start, end, end - start + 1, _stmt_count(node)


def _shape_is_clone_eligible(
    unit_shape: tuple[int, int, int, int] | None,
    *,
    min_loc: int,
    min_stmt: int,
) -> bool:
    """Apply the clone lane's floors to an already-computed unit shape."""

    if unit_shape is None:
        return False
    _start, _end, loc, stmt_count = unit_shape
    return is_clone_eligible(
        loc=loc,
        stmt_count=stmt_count,
        min_loc=min_loc,
        min_stmt=min_stmt,
    )


def _record_unit_volumes(
    phase_ledger: PhaseLedger,
    *,
    clone_eligible: bool,
) -> None:
    """Record the per-unit volumes; eligibility counts the clone lane only."""

    if clone_eligible:
        phase_ledger.add_volume(AnalysisVolumeKey.UNITS_ELIGIBLE)
    phase_ledger.add_volume(AnalysisVolumeKey.UNITS_FINGERPRINTED)


def _clone_artifact_needs(
    *,
    clone_eligible: bool,
    local_name: str,
    loc: int,
    stmt_count: int,
    block_min_loc: int,
    block_min_stmt: int,
    segment_min_loc: int,
    segment_min_stmt: int,
) -> tuple[bool, bool]:
    """Return whether a unit needs blocks and/or segments.

    The unit floors come first: blocks and segments are artifacts of a
    clone-eligible unit, so a configuration whose block/segment floors sit
    below the unit floors must not resurrect them (39Y Y5).
    """

    if not clone_eligible:
        return False, False
    needs_blocks = (
        not local_name.endswith("__init__")
        and loc >= block_min_loc
        and stmt_count >= block_min_stmt
    )
    needs_segments = loc >= segment_min_loc and stmt_count >= segment_min_stmt
    return needs_blocks, needs_segments


def _collect_timed_clone_units(
    *,
    phase_ledger: PhaseLedger,
    phase_key: AnalysisPhaseKey,
    volume_key: AnalysisVolumeKey,
    collect: Callable[[], list[_TCloneUnit]],
) -> list[_TCloneUnit]:
    with phase_ledger.phase(phase_key):
        items = collect()
    phase_ledger.add_volume(volume_key, len(items))
    return items


def _uniquely_named_summaries(
    summaries: Sequence[FunctionContractSummary],
) -> tuple[FunctionContractSummary, ...]:
    """Drop summaries whose qualname cannot name a single function.

    A property and its setter share one qualname, as do definitions guarded by
    a conditional. The contract layer keys on qualname and rightly refuses
    duplicates, so such a qualname carries no contract at all — asserting
    either half would attribute a contract nobody wrote.
    """

    seen: dict[str, FunctionContractSummary] = {}
    ambiguous: set[str] = set()
    for summary in summaries:
        if summary.function in seen:
            ambiguous.add(summary.function)
            continue
        seen[summary.function] = summary
    return tuple(
        summary
        for function, summary in sorted(seen.items())
        if function not in ambiguous
    )


def _with_walk_live_root_reasons(
    candidates: tuple[DeadCandidate, ...],
    *,
    reasons: Sequence[tuple[str, LiveRootReason]],
) -> tuple[DeadCandidate, ...]:
    """Attach walk-resolved liveness reasons to the per-symbol candidates.

    The walk resolves external-decorator roots only after every candidate
    exists, so the reason is folded in here rather than at construction. The
    candidate is the carrier because it already rides the cache wire, which is
    what keeps the reason available on a warm run where the walk never runs.
    """

    reason_by_qualname = dict(reasons)
    if not reason_by_qualname:
        return candidates
    return tuple(
        replace(candidate, live_root_reason=reason)
        if (reason := reason_by_qualname.get(candidate.qualname)) is not None
        else candidate
        for candidate in candidates
    )


def extract_units_and_stats_from_source(
    source: str,
    filepath: str,
    identity: ResolvedSourceIdentity,
    registry: ModuleRegistryHandle,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    *,
    block_min_loc: int = DEFAULT_BLOCK_MIN_LOC,
    block_min_stmt: int = DEFAULT_BLOCK_MIN_STMT,
    segment_min_loc: int = DEFAULT_SEGMENT_MIN_LOC,
    segment_min_stmt: int = DEFAULT_SEGMENT_MIN_STMT,
    collect_structural_findings: bool = True,
    collect_api_surface: bool = False,
    api_include_private_modules: bool = False,
    phase_ledger: PhaseLedger = INERT_PHASE_LEDGER,
    neutral_reuse: RehydratedCacheNeutral | None = None,
) -> tuple[
    list[Unit],
    list[BlockUnit],
    list[SegmentUnit],
    SourceStats,
    FileMetrics,
    list[StructuralFindingGroup],
]:
    try:
        with phase_ledger.phase(AnalysisPhaseKey.PARSE):
            tree = _parse_with_limits(source, PARSE_TIMEOUT_SECONDS)
    except SyntaxError as e:
        raise ParseError(f"Failed to parse {filepath}: {e}") from e
    if not isinstance(tree, ast.Module):
        raise ParseError(f"Failed to parse {filepath}: expected module AST root")
    identity_module = identity.python_module
    module_name = (
        identity_module.module if identity_module is not None else identity.file.path
    )

    collector = _qualnames.QualnameCollector()
    with phase_ledger.phase(AnalysisPhaseKey.QUALNAME):
        collector.visit(tree)
    source_lines = source.splitlines()
    source_line_count = len(source_lines)

    is_test_file = is_test_filepath(filepath, module_registry=registry)

    # Single-pass AST walk replaces 3 separate functions / 4 walks.
    with phase_ledger.phase(AnalysisPhaseKey.MODULE_WALK):
        _walk = _collect_module_walk_data(
            tree=tree,
            source=identity,
            registry=registry,
            collector=collector,
            collect_referenced_names=not is_test_file,
        )
    import_names = _walk.import_names
    module_deps = _walk.module_deps
    referenced_names = _walk.referenced_names
    referenced_qualnames = _walk.referenced_qualnames
    protocol_symbol_aliases = _walk.protocol_symbol_aliases
    protocol_module_aliases = _walk.protocol_module_aliases
    non_runtime_decorator_aliases = _walk.non_runtime_decorator_aliases
    pydantic_module_aliases = _walk.pydantic_module_aliases
    cohesion_ignored_decorator_aliases = _walk.cohesion_ignored_decorator_aliases
    with phase_ledger.phase(AnalysisPhaseKey.RELATIONSHIP):
        function_relationship_facts = _collect_function_relationship_facts(
            tree=tree,
            source=identity,
            registry=registry,
            filepath=filepath,
            collector=collector,
            origin_lane="test" if is_test_file else "production",
        )

    with phase_ledger.phase(AnalysisPhaseKey.SUPPRESSIONS):
        suppression_index = _build_suppression_index_for_source(
            source=source,
            filepath=filepath,
            module_name=module_name,
            collector=collector,
        )
    with phase_ledger.phase(AnalysisPhaseKey.MODULE_BINDINGS):
        module_bindings = _module_bindings(tree, identity, registry)
    class_names = frozenset(class_node.name for _, class_node in collector.class_nodes)
    module_class_names = set(class_names)
    imported_binding_names = set(_walk.imported_binding_names)
    class_metrics: list[ClassMetrics] = []

    units: list[Unit] = list(neutral_reuse.units) if neutral_reuse is not None else []
    block_units: list[BlockUnit] = (
        list(neutral_reuse.blocks) if neutral_reuse is not None else []
    )
    segment_units: list[SegmentUnit] = (
        list(neutral_reuse.segments) if neutral_reuse is not None else []
    )
    structural_findings: list[StructuralFindingGroup] = []
    function_contract_summaries: list[FunctionContractSummary] = (
        list(neutral_reuse.semantic_facts.function_contract_summaries)
        if neutral_reuse is not None
        else []
    )

    for local_name, node in collector.units:
        phase_ledger.add_volume(AnalysisVolumeKey.UNITS_SEEN)
        qualname = f"{module_name}:{local_name}"
        unit_shape = _unit_shape(node)
        clone_eligible = _shape_is_clone_eligible(
            unit_shape,
            min_loc=min_loc,
            min_stmt=min_stmt,
        )
        if neutral_reuse is not None:
            if clone_eligible and collect_structural_findings:
                with phase_ledger.phase(AnalysisPhaseKey.UNIT_STRUCTURAL):
                    structure_facts = scan_function_structure(
                        node,
                        filepath,
                        qualname,
                        collect_findings=True,
                    )
                structural_findings.extend(structure_facts.structural_findings)
            continue
        unit_bindings = module_bindings.enter(node)
        graph, fingerprint, cfg_complexity = _cfg_fingerprint_and_complexity(
            node,
            cfg,
            qualname,
            unit_bindings,
            phase_ledger=phase_ledger,
        )
        # Public metric: authored source decisions, single-owned by
        # codeclone.metrics.source_decisions. The CFG value above stays a
        # separate diagnostic (Wave D two-metric doctrine); neither is ever
        # derived from the other.
        complexity = source_decision_complexity(node)
        if not _is_typing_overload_stub(
            node,
            overload_aliases=frozenset(non_runtime_decorator_aliases),
        ):
            function_contract_summaries.append(
                summarize_function_contract(
                    function=qualname,
                    node=node,
                    graph=graph,
                    events=_walk.semantic_events,
                )
            )
        if unit_shape is None:
            continue
        start, end, loc, stmt_count = unit_shape
        _record_unit_volumes(phase_ledger, clone_eligible=clone_eligible)
        with phase_ledger.phase(AnalysisPhaseKey.UNIT_STRUCTURAL):
            structure_facts = scan_function_structure(
                node,
                filepath,
                qualname,
                # Structural findings stay a clone-lane artifact: only the
                # metric facts are decoupled from the floors (39Y Y5).
                collect_findings=collect_structural_findings and clone_eligible,
            )
        depth = structure_facts.nesting_depth
        risk = risk_level(complexity)
        raw_hash = _raw_source_hash_for_range(source_lines, start, end)
        # The near-miss tier is a clone lane, so only the clone lane's own
        # population pays for the sequence. The floors are part of the cache
        # neutral profile, so a floor change re-analyses rather than serving a
        # sequence computed under different eligibility (39Y Y8).
        statement_sequence = (
            near_miss_statement_sequence(graph, cfg, unit_bindings)
            if clone_eligible
            else ()
        )
        # Unconditional, unlike the sequence above: a statement that cannot run
        # is a defect whether or not its function is large enough to be a clone
        # candidate, so no floor is consulted here (39Y Y5, Y9).
        unreachable = unreachable_statements(graph)

        units.append(
            Unit(
                qualname=qualname,
                filepath=filepath,
                start_line=start,
                end_line=end,
                loc=loc,
                stmt_count=stmt_count,
                fingerprint=fingerprint,
                loc_bucket=bucket_loc(loc),
                cyclomatic_complexity=complexity,
                cfg_cyclomatic_complexity=cfg_complexity,
                nesting_depth=depth,
                risk=risk,
                raw_hash=raw_hash,
                entry_guard_count=structure_facts.entry_guard_count,
                entry_guard_terminal_profile=(
                    structure_facts.entry_guard_terminal_profile
                ),
                entry_guard_has_side_effect_before=(
                    structure_facts.entry_guard_has_side_effect_before
                ),
                terminal_kind=structure_facts.terminal_kind,
                try_finally_profile=structure_facts.try_finally_profile,
                side_effect_order_profile=structure_facts.side_effect_order_profile,
                statement_sequence=statement_sequence,
                unreachable_statements=unreachable,
            )
        )

        needs_blocks, needs_segments = _clone_artifact_needs(
            clone_eligible=clone_eligible,
            local_name=local_name,
            loc=loc,
            stmt_count=stmt_count,
            block_min_loc=block_min_loc,
            block_min_stmt=block_min_stmt,
            segment_min_loc=segment_min_loc,
            segment_min_stmt=segment_min_stmt,
        )

        if needs_blocks or needs_segments:
            body = getattr(node, "body", None)
            hashes: list[str] | None = None
            if isinstance(body, list):
                with phase_ledger.phase(AnalysisPhaseKey.UNIT_NORMALIZE_STMT):
                    hashes = stmt_hashes(body, cfg, unit_bindings)

            if needs_blocks:
                blocks = _collect_timed_clone_units(
                    phase_ledger=phase_ledger,
                    phase_key=AnalysisPhaseKey.UNIT_BLOCKS,
                    volume_key=AnalysisVolumeKey.BLOCKS_EMITTED,
                    collect=partial(
                        extract_blocks,
                        node,
                        filepath=filepath,
                        qualname=qualname,
                        cfg=cfg,
                        bindings=unit_bindings,
                        block_size=4,
                        max_blocks=15,
                        precomputed_hashes=hashes,
                    ),
                )
                block_units.extend(blocks)

            if needs_segments:
                segments = _collect_timed_clone_units(
                    phase_ledger=phase_ledger,
                    phase_key=AnalysisPhaseKey.UNIT_SEGMENTS,
                    volume_key=AnalysisVolumeKey.SEGMENTS_EMITTED,
                    collect=partial(
                        extract_segments,
                        node,
                        filepath=filepath,
                        qualname=qualname,
                        cfg=cfg,
                        bindings=unit_bindings,
                        window_size=6,
                        max_segments=60,
                        precomputed_hashes=hashes,
                    ),
                )
                segment_units.extend(segments)

        if collect_structural_findings:
            structural_findings.extend(structure_facts.structural_findings)

    with phase_ledger.phase(AnalysisPhaseKey.CLASS_METRICS):
        # Rule-3 facts are module-walk products, but the class is their
        # subject, so they are attached to the owning ClassMetrics here - the
        # one place where both the walk result and the per-class metric are in
        # hand. The walk keys them locally; the module prefix is added now so
        # that decorator_evidenced_methods matches DeadCandidate.qualname.
        base_names_by_class = dict(_walk.class_base_names)
        evidenced_methods_by_class: dict[str, list[str]] = {}
        for method_local_name in sorted(_walk.decorator_evidenced_methods):
            owner_qualname = method_local_name.rpartition(".")[0]
            evidenced_methods_by_class.setdefault(owner_qualname, []).append(
                f"{module_name}:{method_local_name}"
            )
        for class_qualname, class_node in collector.class_nodes:
            cohesion_ignored_methods = _cohesion_ignored_method_names(
                class_node,
                protocol_symbol_aliases=protocol_symbol_aliases,
                protocol_module_aliases=protocol_module_aliases,
                pydantic_module_aliases=pydantic_module_aliases,
                cohesion_ignored_decorator_aliases=cohesion_ignored_decorator_aliases,
            )
            class_metric = _class_metrics_for_node(
                module_name=module_name,
                class_qualname=class_qualname,
                class_node=class_node,
                filepath=filepath,
                imported_binding_names=imported_binding_names,
                imported_symbol_targets=_walk.binding_symbol_targets,
                imported_module_targets=_walk.binding_module_targets,
                module_class_names=module_class_names,
                cohesion_ignored_methods=cohesion_ignored_methods,
            )
            if class_metric is not None:
                class_metrics.append(
                    replace(
                        class_metric,
                        base_names=base_names_by_class.get(class_qualname, ()),
                        has_unresolved_external_base=(
                            class_qualname in _walk.unresolved_external_base_classes
                        ),
                        decorator_evidenced_methods=tuple(
                            evidenced_methods_by_class.get(class_qualname, ())
                        ),
                    )
                )

    with phase_ledger.phase(AnalysisPhaseKey.DEAD_CODE):
        dead_candidates = _collect_dead_candidates(
            filepath=filepath,
            module_name=module_name,
            collector=collector,
            protocol_symbol_aliases=protocol_symbol_aliases,
            protocol_module_aliases=protocol_module_aliases,
            non_runtime_decorator_aliases=non_runtime_decorator_aliases,
            pydantic_module_aliases=pydantic_module_aliases,
            suppression_rules_by_target=suppression_index,
        )
        dead_candidates = _with_walk_live_root_reasons(
            dead_candidates,
            reasons=_walk.liveness_root_reasons,
        )

    sorted_class_metrics = tuple(
        sorted(
            class_metrics,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
            ),
        )
    )
    with phase_ledger.phase(AnalysisPhaseKey.MODULE_PASSES):
        typing_coverage, docstring_coverage = phase_ledger.run_subphase_us(
            SUBPHASE_MODULE_PASSES_ADOPTION_US,
            lambda: collect_module_adoption(
                tree=tree,
                module_name=module_name,
                filepath=filepath,
                collector=collector,
                imported_names=import_names,
            ),
        )
        api_surface = None
        if collect_api_surface:
            api_surface = collect_module_api_surface(
                tree=tree,
                module_name=module_name,
                filepath=filepath,
                collector=collector,
                imported_names=import_names,
                include_private_modules=api_include_private_modules,
            )
        semantic_events = (
            neutral_reuse.semantic_facts.events
            if neutral_reuse is not None
            else _walk.semantic_events
        )
        security_surfaces = phase_ledger.run_subphase_us(
            SUBPHASE_MODULE_PASSES_SECURITY_US,
            lambda: project_security_surfaces(semantic_events),
        )
        runtime_reachability = collect_runtime_reachability(
            tree=tree,
            module_name=module_name,
            filepath=filepath,
            collector=collector,
            phase_ledger=phase_ledger,
        )

    return (
        units,
        block_units,
        segment_units,
        (
            neutral_reuse.source_stats
            if neutral_reuse is not None
            else SourceStats(
                lines=source_line_count,
                functions=collector.function_count,
                methods=collector.method_count,
                classes=collector.class_count,
            )
        ),
        FileMetrics(
            class_metrics=sorted_class_metrics,
            module_deps=module_deps,
            dead_candidates=dead_candidates,
            referenced_names=referenced_names,
            import_names=import_names,
            class_names=class_names,
            runtime_reachability=runtime_reachability,
            security_surfaces=security_surfaces,
            semantic_facts=SemanticFileFacts(
                events=semantic_events,
                function_contract_summaries=_uniquely_named_summaries(
                    function_contract_summaries
                ),
            ),
            referenced_qualnames=referenced_qualnames,
            typing_coverage=typing_coverage,
            docstring_coverage=docstring_coverage,
            api_surface=api_surface,
            function_relationship_facts=function_relationship_facts,
        ),
        structural_findings,
    )
