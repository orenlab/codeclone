# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import math
import os
import signal
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha1 as _sha1
from typing import Literal

from .blockhash import stmt_hashes
from .blocks import extract_blocks, extract_segments
from .cfg import CFGBuilder
from .errors import ParseError
from .fingerprint import bucket_loc, sha1
from .metrics import (
    cohesion_risk,
    compute_cbo,
    compute_lcom4,
    coupling_risk,
    cyclomatic_complexity,
    risk_level,
)
from .models import (
    BlockUnit,
    ClassMetrics,
    DeadCandidate,
    FileMetrics,
    ModuleDep,
    SegmentUnit,
    SourceStats,
    StructuralFindingGroup,
    Unit,
)
from .normalize import (
    AstNormalizer,
    NormalizationConfig,
    normalized_ast_dump_from_list,
)
from .paths import is_test_filepath
from .structural_findings import scan_function_structure

__all__ = [
    "Unit",
    "_QualnameCollector",
    "extract_units_and_stats_from_source",
]

# =========================
# Helpers
# =========================

PARSE_TIMEOUT_SECONDS = 5


class _ParseTimeoutError(Exception):
    pass


FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _consumed_cpu_seconds(resource_module: object) -> float:
    """Return consumed CPU seconds for the current process."""
    try:
        usage = resource_module.getrusage(  # type: ignore[attr-defined]
            resource_module.RUSAGE_SELF  # type: ignore[attr-defined]
        )
        return float(usage.ru_utime) + float(usage.ru_stime)
    except Exception:
        return 0.0


@contextmanager
def _parse_limits(timeout_s: int) -> Iterator[None]:
    if os.name != "posix" or timeout_s <= 0:
        yield
        return

    old_handler = signal.getsignal(signal.SIGALRM)

    def _timeout_handler(_signum: int, _frame: object) -> None:
        raise _ParseTimeoutError("AST parsing timeout")

    old_limits: tuple[int, int] | None = None
    try:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_s)

        try:
            import resource

            old_limits = resource.getrlimit(resource.RLIMIT_CPU)
            soft, hard = old_limits
            consumed_cpu_s = _consumed_cpu_seconds(resource)
            desired_soft = max(1, timeout_s + math.ceil(consumed_cpu_s))
            if soft == resource.RLIM_INFINITY:
                candidate_soft = desired_soft
            else:
                # Never reduce finite soft limits and avoid immediate SIGXCPU
                # when the process already consumed more CPU than timeout_s.
                candidate_soft = max(soft, desired_soft)
            if hard == resource.RLIM_INFINITY:
                new_soft = candidate_soft
            else:
                new_soft = min(max(1, hard), candidate_soft)
            # Never lower hard limit: raising it back may be disallowed for
            # unprivileged processes and can lead to process termination later.
            resource.setrlimit(resource.RLIMIT_CPU, (new_soft, hard))
        except Exception:
            # If resource is unavailable or cannot be set, rely on alarm only.
            pass

        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_limits is not None:
            try:
                import resource

                resource.setrlimit(resource.RLIMIT_CPU, old_limits)
            except Exception:
                pass


def _parse_with_limits(source: str, timeout_s: int) -> ast.AST:
    try:
        with _parse_limits(timeout_s):
            return ast.parse(source)
    except _ParseTimeoutError as e:
        raise ParseError(str(e)) from e


def _stmt_count(node: ast.AST) -> int:
    body = getattr(node, "body", None)
    return len(body) if isinstance(body, list) else 0


class _QualnameCollector(ast.NodeVisitor):
    __slots__ = (
        "class_count",
        "class_nodes",
        "funcs",
        "function_count",
        "method_count",
        "stack",
        "units",
    )

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.units: list[tuple[str, FunctionNode]] = []
        self.class_nodes: list[tuple[str, ast.ClassDef]] = []
        self.funcs: dict[str, FunctionNode] = {}
        self.class_count = 0
        self.function_count = 0
        self.method_count = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_count += 1
        class_qualname = ".".join([*self.stack, node.name]) if self.stack else node.name
        self.class_nodes.append((class_qualname, node))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def _register_function(self, node: FunctionNode) -> None:
        name = ".".join([*self.stack, node.name]) if self.stack else node.name
        if self.stack:
            self.method_count += 1
        else:
            self.function_count += 1
        self.units.append((name, node))
        self.funcs[name] = node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._register_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._register_function(node)


# =========================
# CFG fingerprinting
# =========================


def _cfg_fingerprint_and_complexity(
    node: FunctionNode,
    cfg: NormalizationConfig,
    qualname: str,
) -> tuple[str, int]:
    """
    Generate a structural fingerprint for a function using CFG analysis.

    The fingerprint is computed by:
    1. Building a Control Flow Graph (CFG) from the function
    2. Normalizing each CFG block's statements (variable names, constants, etc.)
    3. Creating a canonical representation of the CFG structure
    4. Hashing the representation with SHA-1

    Functions with identical control flow and normalized statements will
    produce the same fingerprint, even if they differ in variable names,
    constants, or type annotations.

    Args:
        node: Function AST node to fingerprint
        cfg: Normalization configuration (what to ignore)
        qualname: Qualified name for logging/debugging

    Returns:
        40-character hex SHA-1 hash of the normalized CFG
    """
    builder = CFGBuilder()
    graph = builder.build(qualname, node)
    cfg_normalizer = AstNormalizer(cfg)

    # Use generator to avoid building large list of strings
    parts: list[str] = []
    for block in sorted(graph.blocks, key=lambda b: b.id):
        succ_ids = ",".join(
            str(s.id) for s in sorted(block.successors, key=lambda s: s.id)
        )
        block_dump = normalized_ast_dump_from_list(
            block.statements,
            cfg,
            normalizer=cfg_normalizer,
        )
        parts.append(f"BLOCK[{block.id}]:{block_dump}|SUCCESSORS:{succ_ids}")
    return sha1("|".join(parts)), cyclomatic_complexity(graph)


def _raw_source_hash_for_range(
    source_lines: list[str],
    start_line: int,
    end_line: int,
) -> str:
    window = "".join(source_lines[start_line - 1 : end_line]).strip()
    no_space = "".join(window.split())
    return _sha1(no_space.encode("utf-8")).hexdigest()


def _resolve_import_target(
    module_name: str,
    import_node: ast.ImportFrom,
) -> str:
    if import_node.level <= 0:
        return import_node.module or ""

    parent_parts = module_name.split(".")
    keep = max(0, len(parent_parts) - import_node.level)
    prefix = parent_parts[:keep]
    if import_node.module:
        return ".".join([*prefix, import_node.module])
    return ".".join(prefix)


def _collect_module_facts(
    *,
    tree: ast.AST,
    module_name: str,
    collect_referenced_names: bool,
) -> tuple[frozenset[str], tuple[ModuleDep, ...], frozenset[str]]:
    import_names: set[str] = set()
    deps: list[ModuleDep] = []
    referenced: set[str] = set()

    if collect_referenced_names:
        referenced_add = referenced.add
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                line = int(getattr(node, "lineno", 0))
                for alias in node.names:
                    alias_name = alias.asname or alias.name.split(".", 1)[0]
                    import_names.add(alias_name)
                    deps.append(
                        ModuleDep(
                            source=module_name,
                            target=alias.name,
                            import_type="import",
                            line=line,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_import_target(module_name, node)
                if target:
                    import_names.add(target.split(".", 1)[0])
                    deps.append(
                        ModuleDep(
                            source=module_name,
                            target=target,
                            import_type="from_import",
                            line=int(getattr(node, "lineno", 0)),
                        )
                    )

            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                referenced_add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                referenced_add(node.attr)
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                line = int(getattr(node, "lineno", 0))
                for alias in node.names:
                    alias_name = alias.asname or alias.name.split(".", 1)[0]
                    import_names.add(alias_name)
                    deps.append(
                        ModuleDep(
                            source=module_name,
                            target=alias.name,
                            import_type="import",
                            line=line,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                target = _resolve_import_target(module_name, node)
                if target:
                    import_names.add(target.split(".", 1)[0])
                    deps.append(
                        ModuleDep(
                            source=module_name,
                            target=target,
                            import_type="from_import",
                            line=int(getattr(node, "lineno", 0)),
                        )
                    )

    deps_sorted = tuple(
        sorted(
            deps,
            key=lambda dep: (dep.source, dep.target, dep.import_type, dep.line),
        )
    )
    return frozenset(import_names), deps_sorted, frozenset(referenced)


def _collect_dead_candidates(
    *,
    filepath: str,
    module_name: str,
    collector: _QualnameCollector,
) -> tuple[DeadCandidate, ...]:
    candidates: list[DeadCandidate] = []
    for local_name, node in collector.units:
        start = int(getattr(node, "lineno", 0))
        end = int(getattr(node, "end_lineno", 0))
        if start <= 0 or end <= 0:
            continue
        kind: Literal["method", "function"] = (
            "method" if "." in local_name else "function"
        )
        candidates.append(
            DeadCandidate(
                qualname=f"{module_name}:{local_name}",
                local_name=node.name,
                filepath=filepath,
                start_line=start,
                end_line=end,
                kind=kind,
            )
        )

    for class_qualname, class_node in collector.class_nodes:
        start = int(getattr(class_node, "lineno", 0))
        end = int(getattr(class_node, "end_lineno", 0))
        if start <= 0 or end <= 0:
            continue
        candidates.append(
            DeadCandidate(
                qualname=f"{module_name}:{class_qualname}",
                local_name=class_node.name,
                filepath=filepath,
                start_line=start,
                end_line=end,
                kind="class",
            )
        )

    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
            ),
        )
    )


# =========================
# Public API
# =========================


def extract_units_and_stats_from_source(
    source: str,
    filepath: str,
    module_name: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
    *,
    collect_structural_findings: bool = True,
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

    collector = _QualnameCollector()
    collector.visit(tree)
    source_lines = source.splitlines()
    source_line_count = len(source_lines)

    is_test_file = is_test_filepath(filepath)
    import_names, module_deps, referenced_names = _collect_module_facts(
        tree=tree,
        module_name=module_name,
        collect_referenced_names=not is_test_file,
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
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)

        if not start or not end or end < start:
            continue

        loc = end - start + 1
        stmt_count = _stmt_count(node)

        if loc < min_loc or stmt_count < min_stmt:
            continue

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

        # Function-level unit (including __init__)
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
            )
        )

        # Block-level and segment-level units share statement hashes
        needs_blocks = (
            not local_name.endswith("__init__") and loc >= 40 and stmt_count >= 10
        )
        needs_segments = loc >= 30 and stmt_count >= 12

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

        # Structural findings extraction (report-only, no re-parse)
        if collect_structural_findings:
            structural_findings.extend(structure_facts.structural_findings)

    for class_qualname, class_node in collector.class_nodes:
        start = int(getattr(class_node, "lineno", 0))
        end = int(getattr(class_node, "end_lineno", 0))
        if start <= 0 or end <= 0:
            continue
        cbo, coupled_classes = compute_cbo(
            class_node,
            module_import_names=module_import_names,
            module_class_names=module_class_names,
        )
        lcom4, method_count, instance_var_count = compute_lcom4(class_node)
        class_metrics.append(
            ClassMetrics(
                qualname=f"{module_name}:{class_qualname}",
                filepath=filepath,
                start_line=start,
                end_line=end,
                cbo=cbo,
                lcom4=lcom4,
                method_count=method_count,
                instance_var_count=instance_var_count,
                risk_coupling=coupling_risk(cbo),
                risk_cohesion=cohesion_risk(lcom4),
                coupled_classes=coupled_classes,
            )
        )

    dead_candidates = _collect_dead_candidates(
        filepath=filepath,
        module_name=module_name,
        collector=collector,
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
        ),
        structural_findings,
    )
