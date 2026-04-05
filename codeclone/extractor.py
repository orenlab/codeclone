# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
import io
import math
import os
import signal
import tokenize
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha1 as _sha1
from typing import TYPE_CHECKING, Literal, NamedTuple

from . import qualnames as _qualnames
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
    stmt_hashes,
)
from .paths import is_test_filepath
from .structural_findings import scan_function_structure
from .suppressions import (
    DeclarationTarget,
    bind_suppressions_to_declarations,
    build_suppression_index,
    extract_suppression_directives,
    suppression_target_key,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from .suppressions import SuppressionTargetKey

__all__ = [
    "Unit",
    "extract_units_and_stats_from_source",
]

# =========================
# Helpers
# =========================

PARSE_TIMEOUT_SECONDS = 5


class _ParseTimeoutError(Exception):
    pass


# Any named declaration: function, async function, or class.
_NamedDeclarationNode = _qualnames.FunctionNode | ast.ClassDef
# Unique key for a declaration's token index: (start_line, end_line, qualname).
_DeclarationTokenIndexKey = tuple[int, int, str]
_DECLARATION_TOKEN_STRINGS = frozenset({"def", "async", "class"})


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


def _source_tokens(source: str) -> tuple[tokenize.TokenInfo, ...]:
    try:
        return tuple(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return ()


def _declaration_token_name(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async"
    return "def"


def _declaration_token_index(
    *,
    source_tokens: tuple[tokenize.TokenInfo, ...],
    start_line: int,
    start_col: int,
    declaration_token: str,
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None,
) -> int | None:
    if source_token_index is not None:
        return source_token_index.get((start_line, start_col, declaration_token))
    for idx, token in enumerate(source_tokens):
        if token.start != (start_line, start_col):
            continue
        if token.type == tokenize.NAME and token.string == declaration_token:
            return idx
    return None


def _build_declaration_token_index(
    source_tokens: tuple[tokenize.TokenInfo, ...],
) -> Mapping[_DeclarationTokenIndexKey, int]:
    indexed: dict[_DeclarationTokenIndexKey, int] = {}
    for idx, token in enumerate(source_tokens):
        if token.type == tokenize.NAME and token.string in _DECLARATION_TOKEN_STRINGS:
            indexed[(token.start[0], token.start[1], token.string)] = idx
    return indexed


def _scan_declaration_colon_line(
    *,
    source_tokens: tuple[tokenize.TokenInfo, ...],
    start_index: int,
) -> int | None:
    nesting = 0
    for token in source_tokens[start_index + 1 :]:
        if token.type == tokenize.OP:
            if token.string in "([{":
                nesting += 1
                continue
            if token.string in ")]}":
                if nesting > 0:
                    nesting -= 1
                continue
            if token.string == ":" and nesting == 0:
                return token.start[0]
        if token.type == tokenize.NEWLINE and nesting == 0:
            return None
    return None


def _fallback_declaration_end_line(node: ast.AST, *, start_line: int) -> int:
    body = getattr(node, "body", None)
    if not isinstance(body, list) or not body:
        return start_line

    first_body_line = int(getattr(body[0], "lineno", 0))
    if first_body_line <= 0 or first_body_line == start_line:
        return start_line
    return max(start_line, first_body_line - 1)


def _declaration_end_line(
    node: ast.AST,
    *,
    source_tokens: tuple[tokenize.TokenInfo, ...],
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None,
) -> int:
    start_line = int(getattr(node, "lineno", 0))
    start_col = int(getattr(node, "col_offset", 0))
    if start_line <= 0:
        return 0

    declaration_token = _declaration_token_name(node)
    start_index = _declaration_token_index(
        source_tokens=source_tokens,
        start_line=start_line,
        start_col=start_col,
        declaration_token=declaration_token,
        source_token_index=source_token_index,
    )
    if start_index is None:
        return _fallback_declaration_end_line(node, start_line=start_line)

    colon_line = _scan_declaration_colon_line(
        source_tokens=source_tokens,
        start_index=start_index,
    )
    if colon_line is not None:
        return colon_line
    return _fallback_declaration_end_line(node, start_line=start_line)


# =========================
# CFG fingerprinting
# =========================


def _cfg_fingerprint_and_complexity(
    node: _qualnames.FunctionNode,
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


_PROTOCOL_MODULE_NAMES = frozenset({"typing", "typing_extensions"})


@dataclass(slots=True)
class _ModuleWalkState:
    import_names: set[str] = field(default_factory=set)
    deps: list[ModuleDep] = field(default_factory=list)
    referenced_names: set[str] = field(default_factory=set)
    imported_symbol_bindings: dict[str, set[str]] = field(default_factory=dict)
    imported_module_aliases: dict[str, str] = field(default_factory=dict)
    name_nodes: list[ast.Name] = field(default_factory=list)
    attr_nodes: list[ast.Attribute] = field(default_factory=list)
    protocol_symbol_aliases: set[str] = field(default_factory=lambda: {"Protocol"})
    protocol_module_aliases: set[str] = field(
        default_factory=lambda: set(_PROTOCOL_MODULE_NAMES)
    )


def _append_module_dep(
    *,
    module_name: str,
    target: str,
    import_type: Literal["import", "from_import"],
    line: int,
    state: _ModuleWalkState,
) -> None:
    state.deps.append(
        ModuleDep(
            source=module_name,
            target=target,
            import_type=import_type,
            line=line,
        )
    )


def _collect_import_node(
    *,
    node: ast.Import,
    module_name: str,
    state: _ModuleWalkState,
    collect_referenced_names: bool,
) -> None:
    line = int(getattr(node, "lineno", 0))
    for alias in node.names:
        alias_name = alias.asname or alias.name.split(".", 1)[0]
        state.import_names.add(alias_name)
        _append_module_dep(
            module_name=module_name,
            target=alias.name,
            import_type="import",
            line=line,
            state=state,
        )
        if collect_referenced_names:
            state.imported_module_aliases[alias_name] = alias.name
        if alias.name in _PROTOCOL_MODULE_NAMES:
            state.protocol_module_aliases.add(alias_name)


def _dotted_expr_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        prefix = _dotted_expr_name(expr.value)
        if prefix is None:
            return None
        return f"{prefix}.{expr.attr}"
    return None


def _collect_import_from_node(
    *,
    node: ast.ImportFrom,
    module_name: str,
    state: _ModuleWalkState,
    collect_referenced_names: bool,
) -> None:
    target = _resolve_import_target(module_name, node)
    if target:
        state.import_names.add(target.split(".", 1)[0])
        _append_module_dep(
            module_name=module_name,
            target=target,
            import_type="from_import",
            line=int(getattr(node, "lineno", 0)),
            state=state,
        )

    if node.module in _PROTOCOL_MODULE_NAMES:
        for alias in node.names:
            if alias.name == "Protocol":
                state.protocol_symbol_aliases.add(alias.asname or alias.name)

    if not collect_referenced_names or not target:
        return

    for alias in node.names:
        if alias.name == "*":
            continue
        alias_name = alias.asname or alias.name
        state.imported_symbol_bindings.setdefault(alias_name, set()).add(
            f"{target}:{alias.name}"
        )


def _is_protocol_class(
    class_node: ast.ClassDef,
    *,
    protocol_symbol_aliases: frozenset[str],
    protocol_module_aliases: frozenset[str],
) -> bool:
    for base in class_node.bases:
        base_name = _dotted_expr_name(base)
        if base_name is None:
            continue
        if base_name in protocol_symbol_aliases:
            return True
        if "." in base_name and base_name.rsplit(".", 1)[-1] == "Protocol":
            module_alias = base_name.rsplit(".", 1)[0]
            if module_alias in protocol_module_aliases:
                return True
    return False


def _is_non_runtime_candidate(node: _qualnames.FunctionNode) -> bool:
    for decorator in node.decorator_list:
        name = _dotted_expr_name(decorator)
        if name is None:
            continue
        terminal = name.rsplit(".", 1)[-1]
        if terminal in {"overload", "abstractmethod"}:
            return True
    return False


def _node_line_span(node: ast.AST) -> tuple[int, int] | None:
    start = int(getattr(node, "lineno", 0))
    end = int(getattr(node, "end_lineno", 0))
    if start <= 0 or end <= 0:
        return None
    return start, end


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


def _class_metrics_for_node(
    *,
    module_name: str,
    class_qualname: str,
    class_node: ast.ClassDef,
    filepath: str,
    module_import_names: set[str],
    module_class_names: set[str],
) -> ClassMetrics | None:
    span = _node_line_span(class_node)
    if span is None:
        return None
    start, end = span
    cbo, coupled_classes = compute_cbo(
        class_node,
        module_import_names=module_import_names,
        module_class_names=module_class_names,
    )
    lcom4, method_count, instance_var_count = compute_lcom4(class_node)
    return ClassMetrics(
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


def _dead_candidate_kind(local_name: str) -> Literal["function", "method"]:
    return "method" if "." in local_name else "function"


def _should_skip_dead_candidate(
    local_name: str,
    node: _qualnames.FunctionNode,
    *,
    protocol_class_qualnames: set[str],
) -> bool:
    if _is_non_runtime_candidate(node):
        return True
    if "." not in local_name:
        return False
    owner_qualname = local_name.rsplit(".", 1)[0]
    return owner_qualname in protocol_class_qualnames


def _build_dead_candidate(
    *,
    module_name: str,
    local_name: str,
    node: _NamedDeclarationNode,
    filepath: str,
    kind: Literal["class", "function", "method"],
    suppression_index: Mapping[SuppressionTargetKey, tuple[str, ...]],
    start_line: int,
    end_line: int,
) -> DeadCandidate:
    qualname = f"{module_name}:{local_name}"
    return DeadCandidate(
        qualname=qualname,
        local_name=node.name,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        kind=kind,
        suppressed_rules=suppression_index.get(
            suppression_target_key(
                filepath=filepath,
                qualname=qualname,
                start_line=start_line,
                end_line=end_line,
                kind=kind,
            ),
            (),
        ),
    )


def _dead_candidate_for_unit(
    *,
    module_name: str,
    local_name: str,
    node: _qualnames.FunctionNode,
    filepath: str,
    suppression_index: Mapping[SuppressionTargetKey, tuple[str, ...]],
    protocol_class_qualnames: set[str],
) -> DeadCandidate | None:
    span = _node_line_span(node)
    if span is None:
        return None
    if _should_skip_dead_candidate(
        local_name,
        node,
        protocol_class_qualnames=protocol_class_qualnames,
    ):
        return None
    start, end = span
    return _build_dead_candidate(
        module_name=module_name,
        local_name=local_name,
        node=node,
        filepath=filepath,
        kind=_dead_candidate_kind(local_name),
        suppression_index=suppression_index,
        start_line=start,
        end_line=end,
    )


def _collect_load_reference_node(
    *,
    node: ast.AST,
    state: _ModuleWalkState,
) -> None:
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        state.referenced_names.add(node.id)
        state.name_nodes.append(node)
        return
    if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
        state.referenced_names.add(node.attr)
        state.attr_nodes.append(node)


def _resolve_referenced_qualnames(
    *,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    state: _ModuleWalkState,
) -> frozenset[str]:
    top_level_class_by_name = {
        class_qualname: class_qualname
        for class_qualname, _class_node in collector.class_nodes
        if "." not in class_qualname
    }
    local_method_qualnames = frozenset(
        f"{module_name}:{local_name}"
        for local_name, _node in collector.units
        if "." in local_name
    )

    resolved: set[str] = set()
    for name_node in state.name_nodes:
        for qualname in state.imported_symbol_bindings.get(name_node.id, ()):
            resolved.add(qualname)

    for attr_node in state.attr_nodes:
        base = attr_node.value
        if isinstance(base, ast.Name):
            imported_module = state.imported_module_aliases.get(base.id)
            if imported_module is not None:
                resolved.add(f"{imported_module}:{attr_node.attr}")
            else:
                class_qualname = top_level_class_by_name.get(base.id)
                if class_qualname is not None:
                    local_method_qualname = (
                        f"{module_name}:{class_qualname}.{attr_node.attr}"
                    )
                    if local_method_qualname in local_method_qualnames:
                        resolved.add(local_method_qualname)

    return frozenset(resolved)


class _ModuleWalkResult(NamedTuple):
    import_names: frozenset[str]
    module_deps: tuple[ModuleDep, ...]
    referenced_names: frozenset[str]
    referenced_qualnames: frozenset[str]
    protocol_symbol_aliases: frozenset[str]
    protocol_module_aliases: frozenset[str]


def _collect_module_walk_data(
    *,
    tree: ast.AST,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    collect_referenced_names: bool,
) -> _ModuleWalkResult:
    """Single ast.walk that collects imports, deps, names, qualnames & protocol aliases.

    Reduces the hot path to one tree walk plus one local qualname resolution phase.
    """
    state = _ModuleWalkState()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            _collect_import_node(
                node=node,
                module_name=module_name,
                state=state,
                collect_referenced_names=collect_referenced_names,
            )
        elif isinstance(node, ast.ImportFrom):
            _collect_import_from_node(
                node=node,
                module_name=module_name,
                state=state,
                collect_referenced_names=collect_referenced_names,
            )
        elif collect_referenced_names:
            _collect_load_reference_node(node=node, state=state)

    deps_sorted = tuple(
        sorted(
            state.deps,
            key=lambda dep: (dep.source, dep.target, dep.import_type, dep.line),
        )
    )
    resolved = (
        _resolve_referenced_qualnames(
            module_name=module_name,
            collector=collector,
            state=state,
        )
        if collect_referenced_names
        else frozenset()
    )

    return _ModuleWalkResult(
        import_names=frozenset(state.import_names),
        module_deps=deps_sorted,
        referenced_names=frozenset(state.referenced_names),
        referenced_qualnames=resolved,
        protocol_symbol_aliases=frozenset(state.protocol_symbol_aliases),
        protocol_module_aliases=frozenset(state.protocol_module_aliases),
    )


def _collect_dead_candidates(
    *,
    filepath: str,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    protocol_symbol_aliases: frozenset[str] = frozenset({"Protocol"}),
    protocol_module_aliases: frozenset[str] = frozenset(
        {"typing", "typing_extensions"}
    ),
    suppression_rules_by_target: Mapping[SuppressionTargetKey, tuple[str, ...]]
    | None = None,
) -> tuple[DeadCandidate, ...]:
    protocol_class_qualnames = {
        class_qualname
        for class_qualname, class_node in collector.class_nodes
        if _is_protocol_class(
            class_node,
            protocol_symbol_aliases=protocol_symbol_aliases,
            protocol_module_aliases=protocol_module_aliases,
        )
    }

    candidates: list[DeadCandidate] = []
    suppression_index = (
        suppression_rules_by_target if suppression_rules_by_target is not None else {}
    )
    for local_name, node in collector.units:
        candidate = _dead_candidate_for_unit(
            module_name=module_name,
            local_name=local_name,
            node=node,
            filepath=filepath,
            suppression_index=suppression_index,
            protocol_class_qualnames=protocol_class_qualnames,
        )
        if candidate is not None:
            candidates.append(candidate)

    for class_qualname, class_node in collector.class_nodes:
        span = _node_line_span(class_node)
        if span is not None:
            start, end = span
            candidates.append(
                _build_dead_candidate(
                    module_name=module_name,
                    local_name=class_qualname,
                    node=class_node,
                    filepath=filepath,
                    kind="class",
                    suppression_index=suppression_index,
                    start_line=start,
                    end_line=end,
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


def _collect_declaration_targets(
    *,
    filepath: str,
    module_name: str,
    collector: _qualnames.QualnameCollector,
    source_tokens: tuple[tokenize.TokenInfo, ...] = (),
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None,
    include_inline_lines: bool = False,
) -> tuple[DeclarationTarget, ...]:
    declarations: list[DeclarationTarget] = []
    declaration_specs: list[
        tuple[str, ast.AST, Literal["function", "method", "class"]]
    ] = [
        (
            local_name,
            node,
            "method" if "." in local_name else "function",
        )
        for local_name, node in collector.units
    ]
    declaration_specs.extend(
        (class_qualname, class_node, "class")
        for class_qualname, class_node in collector.class_nodes
    )

    for qualname_suffix, node, kind in declaration_specs:
        start = int(getattr(node, "lineno", 0))
        end = int(getattr(node, "end_lineno", 0))
        if start > 0 and end > 0:
            declaration_end_line = (
                _declaration_end_line(
                    node,
                    source_tokens=source_tokens,
                    source_token_index=source_token_index,
                )
                if include_inline_lines
                else None
            )
            declarations.append(
                DeclarationTarget(
                    filepath=filepath,
                    qualname=f"{module_name}:{qualname_suffix}",
                    start_line=start,
                    end_line=end,
                    kind=kind,
                    declaration_end_line=declaration_end_line,
                )
            )

    return tuple(
        sorted(
            declarations,
            key=lambda item: (
                item.filepath,
                item.start_line,
                item.end_line,
                item.qualname,
                item.kind,
            ),
        )
    )


def _build_suppression_index_for_source(
    *,
    source: str,
    filepath: str,
    module_name: str,
    collector: _qualnames.QualnameCollector,
) -> Mapping[SuppressionTargetKey, tuple[str, ...]]:
    suppression_directives = extract_suppression_directives(source)
    if not suppression_directives:
        return {}

    needs_inline_binding = any(
        directive.binding == "inline" for directive in suppression_directives
    )
    source_tokens: tuple[tokenize.TokenInfo, ...] = ()
    source_token_index: Mapping[_DeclarationTokenIndexKey, int] | None = None
    if needs_inline_binding:
        source_tokens = _source_tokens(source)
        if source_tokens:
            source_token_index = _build_declaration_token_index(source_tokens)

    declaration_targets = _collect_declaration_targets(
        filepath=filepath,
        module_name=module_name,
        collector=collector,
        source_tokens=source_tokens,
        source_token_index=source_token_index,
        include_inline_lines=needs_inline_binding,
    )
    suppression_bindings = bind_suppressions_to_declarations(
        directives=suppression_directives,
        declarations=declaration_targets,
    )
    return build_suppression_index(suppression_bindings)


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
    block_min_loc: int = 20,
    block_min_stmt: int = 8,
    segment_min_loc: int = 20,
    segment_min_stmt: int = 10,
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
        ),
        structural_findings,
    )
