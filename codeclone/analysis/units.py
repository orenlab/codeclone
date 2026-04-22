# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from hashlib import sha1 as _sha1

from .. import qualnames as _qualnames
from ..blocks import extract_blocks, extract_segments
from ..contracts import (
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
)
from ..contracts.errors import ParseError
from ..findings.structural.detectors import scan_function_structure
from ..metrics.adoption import collect_module_adoption
from ..metrics.api_surface import collect_module_api_surface
from ..metrics.complexity import risk_level
from ..models import (
    BlockUnit,
    ClassMetrics,
    FileMetrics,
    SegmentUnit,
    SourceStats,
    StructuralFindingGroup,
    Unit,
)
from ..paths import is_test_filepath
from ._module_walk import (
    _build_suppression_index_for_source,
    _collect_dead_candidates,
    _collect_module_walk_data,
)
from .class_metrics import _class_metrics_for_node, _node_line_span
from .fingerprint import _cfg_fingerprint_and_complexity, bucket_loc
from .normalizer import NormalizationConfig, stmt_hashes
from .parser import PARSE_TIMEOUT_SECONDS, _parse_with_limits

__all__ = ["extract_units_and_stats_from_source"]


def _stmt_count(node: ast.AST) -> int:
    body = getattr(node, "body", None)
    return len(body) if isinstance(body, list) else 0


_STMT_COUNT_IMPL = _stmt_count


def _raw_source_hash_for_range(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> str:
    window = "".join(source_lines[start_line - 1 : end_line]).strip()
    no_space = "".join(window.split())
    return _sha1(no_space.encode("utf-8")).hexdigest()


def _eligible_unit_shape(
    node: _qualnames.FunctionNode,
    *,
    min_loc: int,
    min_stmt: int,
) -> tuple[int, int, int, int] | None:
    span = _node_line_span(node)
    if span is None:
        return None
    start, end = span
    if end < start:
        return None
    loc = end - start + 1
    stmt_count = _stmt_count(node)
    if loc < min_loc or stmt_count < min_stmt:
        return None
    return start, end, loc, stmt_count


def extract_units_and_stats_from_source(
    source: str,
    filepath: str,
    module_name: str,
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
) -> tuple[
    list[Unit],
    list[BlockUnit],
    list[SegmentUnit],
    SourceStats,
    FileMetrics,
    list[StructuralFindingGroup],
]:
    try:
        tree = _parse_with_limits(source, PARSE_TIMEOUT_SECONDS)
    except SyntaxError as e:
        raise ParseError(f"Failed to parse {filepath}: {e}") from e
    if not isinstance(tree, ast.Module):
        raise ParseError(f"Failed to parse {filepath}: expected module AST root")

    collector = _qualnames.QualnameCollector()
    collector.visit(tree)
    source_lines = source.splitlines()
    source_line_count = len(source_lines)

    is_test_file = is_test_filepath(filepath)

    # Single-pass AST walk replaces 3 separate functions / 4 walks.
    _walk = _collect_module_walk_data(
        tree=tree,
        module_name=module_name,
        collector=collector,
        collect_referenced_names=not is_test_file,
    )
    import_names = _walk.import_names
    module_deps = _walk.module_deps
    referenced_names = _walk.referenced_names
    referenced_qualnames = _walk.referenced_qualnames
    protocol_symbol_aliases = _walk.protocol_symbol_aliases
    protocol_module_aliases = _walk.protocol_module_aliases

    suppression_index = _build_suppression_index_for_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        collector=collector,
    )
    class_names = frozenset(class_node.name for _, class_node in collector.class_nodes)
    module_import_names = set(import_names)
    module_class_names = set(class_names)
    class_metrics: list[ClassMetrics] = []

    units: list[Unit] = []
    block_units: list[BlockUnit] = []
    segment_units: list[SegmentUnit] = []
    structural_findings: list[StructuralFindingGroup] = []

    for local_name, node in collector.units:
        unit_shape = _eligible_unit_shape(
            node,
            min_loc=min_loc,
            min_stmt=min_stmt,
        )
        if unit_shape is None:
            continue
        start, end, loc, stmt_count = unit_shape

        qualname = f"{module_name}:{local_name}"
        fingerprint, complexity = _cfg_fingerprint_and_complexity(node, cfg, qualname)
        structure_facts = scan_function_structure(
            node,
            filepath,
            qualname,
            collect_findings=collect_structural_findings,
        )
        depth = structure_facts.nesting_depth
        risk = risk_level(complexity)
        raw_hash = _raw_source_hash_for_range(source_lines, start, end)

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
            )
        )

        needs_blocks = (
            not local_name.endswith("__init__")
            and loc >= block_min_loc
            and stmt_count >= block_min_stmt
        )
        needs_segments = loc >= segment_min_loc and stmt_count >= segment_min_stmt

        if needs_blocks or needs_segments:
            body = getattr(node, "body", None)
            hashes: list[str] | None = None
            if isinstance(body, list):
                hashes = stmt_hashes(body, cfg)

            if needs_blocks:
                block_units.extend(
                    extract_blocks(
                        node,
                        filepath=filepath,
                        qualname=qualname,
                        cfg=cfg,
                        block_size=4,
                        max_blocks=15,
                        precomputed_hashes=hashes,
                    )
                )

            if needs_segments:
                segment_units.extend(
                    extract_segments(
                        node,
                        filepath=filepath,
                        qualname=qualname,
                        cfg=cfg,
                        window_size=6,
                        max_segments=60,
                        precomputed_hashes=hashes,
                    )
                )

        if collect_structural_findings:
            structural_findings.extend(structure_facts.structural_findings)

    for class_qualname, class_node in collector.class_nodes:
        class_metric = _class_metrics_for_node(
            module_name=module_name,
            class_qualname=class_qualname,
            class_node=class_node,
            filepath=filepath,
            module_import_names=module_import_names,
            module_class_names=module_class_names,
        )
        if class_metric is not None:
            class_metrics.append(class_metric)

    dead_candidates = _collect_dead_candidates(
        filepath=filepath,
        module_name=module_name,
        collector=collector,
        protocol_symbol_aliases=protocol_symbol_aliases,
        protocol_module_aliases=protocol_module_aliases,
        suppression_rules_by_target=suppression_index,
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
    typing_coverage, docstring_coverage = collect_module_adoption(
        tree=tree,
        module_name=module_name,
        filepath=filepath,
        collector=collector,
        imported_names=import_names,
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

    return (
        units,
        block_units,
        segment_units,
        SourceStats(
            lines=source_line_count,
            functions=collector.function_count,
            methods=collector.method_count,
            classes=collector.class_count,
        ),
        FileMetrics(
            class_metrics=sorted_class_metrics,
            module_deps=module_deps,
            dead_candidates=dead_candidates,
            referenced_names=referenced_names,
            import_names=import_names,
            class_names=class_names,
            referenced_qualnames=referenced_qualnames,
            typing_coverage=typing_coverage,
            docstring_coverage=docstring_coverage,
            api_surface=api_surface,
        ),
        structural_findings,
    )
