# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""CodeClone — structural code quality analysis for Python.

Structural findings extraction layer (Phase 1: duplicated_branches).

This module is report-only: findings do not affect clone detection,
fingerprints, baseline semantics, exit codes, or health scores.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha1
from typing import TYPE_CHECKING

from .domain.findings import (
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
    STRUCTURAL_KIND_DUPLICATED_BRANCHES,
)
from .models import GroupItemLike, StructuralFindingGroup, StructuralFindingOccurrence

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "build_clone_cohort_structural_findings",
    "is_reportable_structural_signature",
    "normalize_structural_finding_group",
    "normalize_structural_findings",
    "scan_function_structure",
]

_FINDING_KIND_BRANCHES = STRUCTURAL_KIND_DUPLICATED_BRANCHES
_FINDING_KIND_CLONE_GUARD_EXIT_DIVERGENCE = STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE
_FINDING_KIND_CLONE_COHORT_DRIFT = STRUCTURAL_KIND_CLONE_COHORT_DRIFT
_TRIVIAL_STMT_TYPES = frozenset(
    {
        "AnnAssign",
        "Assert",
        "Assign",
        "AugAssign",
        "Expr",
        "Raise",
        "Return",
    }
)


@dataclass(frozen=True, slots=True)
class _BranchWalkStats:
    call_count: int
    raise_count: int
    has_nested_if: bool
    has_loop: bool
    has_try: bool


@dataclass(frozen=True, slots=True)
class FunctionStructureFacts:
    nesting_depth: int
    structural_findings: tuple[StructuralFindingGroup, ...]
    entry_guard_count: int
    entry_guard_terminal_profile: str
    entry_guard_has_side_effect_before: bool
    terminal_kind: str
    try_finally_profile: str
    side_effect_order_profile: str


# ---------------------------------------------------------------------------
# Branch signature helpers
# ---------------------------------------------------------------------------


def _stmt_type_sequence(body: list[ast.stmt]) -> str:
    """Comma-joined AST node type names for a statement list."""
    return ",".join(type(s).__name__ for s in body)


def _terminal_kind(body: list[ast.stmt]) -> str:
    """Classify the terminal (last) statement of a branch body."""
    if not body:
        return "fallthrough"
    last = body[-1]
    if isinstance(last, ast.Return):
        val = last.value
        if val is None:
            return "return_none"
        if isinstance(val, ast.Constant):
            return "return_const"
        if isinstance(val, ast.Name):
            return "return_name"
        return "return_expr"
    if isinstance(last, ast.Raise):
        return "raise"
    if isinstance(last, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        return "assign"
    if isinstance(last, ast.Expr):
        return "expr"
    return "fallthrough"


def _bucket_calls(call_count: int) -> str:
    """Bucketed count of ast.Call nodes inside a branch body."""
    match call_count:
        case 0:
            return "0"
        case 1:
            return "1"
        case _:
            return "2+"


def _stmt_names_from_signature(signature: Mapping[str, str]) -> tuple[str, ...]:
    stmt_seq = signature.get("stmt_seq", "").strip()
    if not stmt_seq:
        return ()
    return tuple(part for part in stmt_seq.split(",") if part)


def _has_non_trivial_stmt_names(stmt_names: Sequence[str]) -> bool:
    return any(name not in _TRIVIAL_STMT_TYPES for name in stmt_names)


def is_reportable_structural_signature(signature: Mapping[str, str]) -> bool:
    """Return whether a structural signature is meaningful enough to report.

    Current policy intentionally suppresses single-statement boilerplate
    families built from trivial statement kinds such as Expr / Assign / Raise /
    Return. Multi-statement bodies are kept when they carry either structural
    control-flow mass or an explicit terminal exit (`return` / `raise`) that
    makes the branch family meaningfully distinct.
    """
    stmt_names = _stmt_names_from_signature(signature)
    if not stmt_names:
        return False
    if (
        signature.get("nested_if") == "1"
        or signature.get("has_loop") == "1"
        or signature.get("has_try") == "1"
    ):
        return True
    if len(stmt_names) == 1:
        return _has_non_trivial_stmt_names(stmt_names)
    if _has_non_trivial_stmt_names(stmt_names):
        return True
    return "Return" in stmt_names or "Raise" in stmt_names


def _kind_requires_branch_signature(finding_kind: str) -> bool:
    return finding_kind == _FINDING_KIND_BRANCHES


def _kind_min_occurrence_count(finding_kind: str) -> int:
    match finding_kind:
        case kind if kind in {
            _FINDING_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
            _FINDING_KIND_CLONE_COHORT_DRIFT,
        }:
            return 1
        case _:
            return 2


def _normalize_occurrences(
    items: Sequence[StructuralFindingOccurrence],
) -> tuple[StructuralFindingOccurrence, ...]:
    deduped_items = {
        (item.file_path, item.qualname, item.start, item.end): item
        for item in sorted(
            items,
            key=lambda occ: (occ.file_path, occ.qualname, occ.start, -occ.end),
        )
    }
    kept: list[StructuralFindingOccurrence] = []
    for item in deduped_items.values():
        if not kept:
            kept.append(item)
            continue
        previous = kept[-1]
        same_scope = (
            previous.file_path == item.file_path and previous.qualname == item.qualname
        )
        overlaps = item.start <= previous.end
        if same_scope and overlaps:
            # Prefer the earlier / outer range so nested branches do not inflate
            # one finding group with overlapping occurrences.
            continue
        kept.append(item)
    return tuple(kept)


def normalize_structural_finding_group(
    group: StructuralFindingGroup,
) -> StructuralFindingGroup | None:
    """Normalize one structural finding group for stable report/cache output."""
    if _kind_requires_branch_signature(
        group.finding_kind
    ) and not is_reportable_structural_signature(group.signature):
        return None
    normalized_items = _normalize_occurrences(group.items)
    if len(normalized_items) < _kind_min_occurrence_count(group.finding_kind):
        return None
    return StructuralFindingGroup(
        finding_kind=group.finding_kind,
        finding_key=group.finding_key,
        signature=dict(group.signature),
        items=normalized_items,
    )


def normalize_structural_findings(
    groups: Sequence[StructuralFindingGroup],
) -> tuple[StructuralFindingGroup, ...]:
    """Normalize and sort structural findings for deterministic consumers."""
    normalized = [
        candidate
        for candidate in (normalize_structural_finding_group(group) for group in groups)
        if candidate is not None
    ]
    normalized.sort(key=lambda group: (-len(group.items), group.finding_key))
    return tuple(normalized)


def _summarize_branch(body: list[ast.stmt]) -> dict[str, str] | None:
    """Build deterministic structural signature for a meaningful branch body."""
    if not body or all(isinstance(stmt, ast.Pass) for stmt in body):
        return None

    call_count = raise_count = 0
    has_nested_if, has_loop, has_try = False, False, False
    try_star = getattr(ast, "TryStar", None)
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            call_count += 1
        elif isinstance(node, ast.Raise):
            raise_count += 1
        elif isinstance(node, ast.If):
            has_nested_if = True
        elif isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            has_loop = True
        elif isinstance(node, ast.Try) or (
            try_star is not None and isinstance(node, try_star)
        ):
            has_try = True

    stats = _BranchWalkStats(
        call_count=call_count,
        raise_count=raise_count,
        has_nested_if=has_nested_if,
        has_loop=has_loop,
        has_try=has_try,
    )
    signature = {
        "stmt_seq": _stmt_type_sequence(body),
        "terminal": _terminal_kind(body),
        "calls": _bucket_calls(stats.call_count),
        "raises": "0" if stats.raise_count == 0 else "1+",
        "nested_if": "1" if stats.has_nested_if else "0",
        "has_loop": "1" if stats.has_loop else "0",
        "has_try": "1" if stats.has_try else "0",
    }
    if not is_reportable_structural_signature(signature):
        return None
    return signature


def _sig_canonical(sig: dict[str, str]) -> str:
    """Canonical string representation of a signature (sorted keys)."""
    return "|".join(f"{k}={v}" for k, v in sorted(sig.items()))


def _finding_key(qualname: str, sig_canonical: str) -> str:
    """SHA1-based deterministic finding key."""
    raw = f"duplicated_branches|qualname={qualname}|sig={sig_canonical}"
    return sha1(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Branch body collection from ast.If chains
# ---------------------------------------------------------------------------


def _collect_if_branch_bodies(if_node: ast.If) -> list[tuple[list[ast.stmt], int, int]]:
    """Collect all branch bodies from an if/elif/else chain.

    Returns list of (body, start_line, end_line) tuples.
    Traverses elif chains without recursing into nested ifs inside bodies.
    """
    results: list[tuple[list[ast.stmt], int, int]] = []

    current: ast.If | None = if_node
    while current is not None:
        body = current.body
        if body and not all(isinstance(stmt, ast.Pass) for stmt in body):
            start = body[0].lineno
            end = getattr(body[-1], "end_lineno", body[-1].lineno)
            results.append((body, start, end))

        orelse = current.orelse
        if not orelse:
            break
        # elif: orelse contains exactly one ast.If
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            current = orelse[0]
        else:
            # else block
            if orelse and not all(isinstance(stmt, ast.Pass) for stmt in orelse):
                start = orelse[0].lineno
                end = getattr(orelse[-1], "end_lineno", orelse[-1].lineno)
                results.append((orelse, start, end))
            break

    return results


# ---------------------------------------------------------------------------
# Branch body collection from ast.Match (Python 3.10+)
# ---------------------------------------------------------------------------


def _collect_match_branch_bodies(
    match_node: object,
) -> list[tuple[list[ast.stmt], int, int]]:
    """Collect branch bodies from a match/case statement (Python 3.10+)."""
    results: list[tuple[list[ast.stmt], int, int]] = []
    cases = getattr(match_node, "cases", [])
    for case in cases:
        body: list[ast.stmt] = getattr(case, "body", [])
        if body and not all(isinstance(stmt, ast.Pass) for stmt in body):
            start = body[0].lineno
            end = getattr(body[-1], "end_lineno", body[-1].lineno)
            results.append((body, start, end))
    return results


def _is_ignorable_entry_statement(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Pass):
        return True
    if isinstance(statement, ast.Expr):
        value = statement.value
        return isinstance(value, ast.Constant) and isinstance(value.value, str)
    return False


def _expr_has_side_effect(expr: ast.AST) -> bool:
    return any(
        isinstance(node, (ast.Call, ast.Await, ast.Yield, ast.YieldFrom))
        for node in ast.walk(expr)
    )


def _statement_has_side_effect(statement: ast.stmt) -> bool:
    if isinstance(
        statement,
        (
            ast.Assign,
            ast.AnnAssign,
            ast.AugAssign,
            ast.Delete,
            ast.Import,
            ast.ImportFrom,
            ast.With,
            ast.AsyncWith,
            ast.Raise,
            ast.Yield,
            ast.Return,
            ast.Break,
            ast.Continue,
        ),
    ):
        return True
    if isinstance(statement, ast.Expr):
        return _expr_has_side_effect(statement.value)
    return False


def _is_guard_exit_if(statement: ast.stmt) -> tuple[bool, str]:
    if not isinstance(statement, ast.If):
        return False, "none"
    if statement.orelse:
        return False, "none"
    terminal = _terminal_kind(statement.body)
    if terminal.startswith("return") or terminal == "raise":
        return True, terminal
    return False, "none"


def _entry_guard_facts(
    statements: Sequence[ast.stmt],
) -> tuple[int, tuple[str, ...], bool]:
    guard_terminals: list[str] = []
    side_effect_before_first_guard = False
    seen_guard = False

    for statement in statements:
        if _is_ignorable_entry_statement(statement):
            continue
        is_guard, terminal = _is_guard_exit_if(statement)
        if is_guard:
            seen_guard = True
            guard_terminals.append(terminal)
            continue
        if seen_guard:
            break
        if _statement_has_side_effect(statement):
            side_effect_before_first_guard = True

    return (
        len(guard_terminals),
        tuple(guard_terminals),
        side_effect_before_first_guard if guard_terminals else False,
    )


def _guard_profile_text(
    *,
    count: int,
    terminal_profile: str,
) -> str:
    if count <= 0:
        return "none"
    return f"{count}x:{terminal_profile}"


class _FunctionStructureScanner:
    __slots__ = (
        "_collect_findings",
        "_filepath",
        "_has_finally",
        "_has_match",
        "_has_side_effect_any",
        "_has_try",
        "_match_type",
        "_qualname",
        "_sig_to_branches",
        "max_depth",
    )

    def __init__(
        self,
        *,
        filepath: str,
        qualname: str,
        collect_findings: bool,
    ) -> None:
        self._filepath = filepath
        self._qualname = qualname
        self._collect_findings = collect_findings
        self._sig_to_branches: dict[str, list[tuple[dict[str, str], int, int]]] = (
            defaultdict(list)
        )
        self.max_depth = 0
        self._has_try = False
        self._has_finally = False
        self._has_side_effect_any = False
        self._match_type = getattr(ast, "Match", None)
        self._has_match = self._match_type is not None and sys.version_info >= (3, 10)

    def scan(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> FunctionStructureFacts:
        statements = list(node.body)
        self._visit_statements(statements, depth=0)
        guard_count, guard_terminals, side_effect_before_first_guard = (
            _entry_guard_facts(statements)
        )
        guard_terminal_profile = (
            ",".join(guard_terminals) if guard_terminals else "none"
        )
        terminal_kind = _terminal_kind(statements)
        try_finally_profile = (
            "try_finally"
            if self._has_finally
            else ("try_no_finally" if self._has_try else "none")
        )
        if guard_count > 0:
            side_effect_order_profile = (
                "effect_before_guard"
                if side_effect_before_first_guard
                else "guard_then_effect"
            )
        elif self._has_side_effect_any:
            side_effect_order_profile = "effect_only"
        else:
            side_effect_order_profile = "none"

        return FunctionStructureFacts(
            nesting_depth=self.max_depth,
            structural_findings=tuple(self._build_groups()),
            entry_guard_count=guard_count,
            entry_guard_terminal_profile=guard_terminal_profile,
            entry_guard_has_side_effect_before=side_effect_before_first_guard,
            terminal_kind=terminal_kind,
            try_finally_profile=try_finally_profile,
            side_effect_order_profile=side_effect_order_profile,
        )

    def _visit_statements(
        self,
        statements: list[ast.stmt],
        *,
        depth: int,
        suppress_if_chain_head: bool = False,
    ) -> None:
        for idx, statement in enumerate(statements):
            suppress_group = (
                suppress_if_chain_head
                and idx == 0
                and len(statements) == 1
                and isinstance(statement, ast.If)
            )
            self._visit_statement(
                statement,
                depth=depth,
                suppress_if_chain_head=suppress_group,
            )

    def _visit_statement(
        self,
        statement: ast.stmt,
        *,
        depth: int,
        suppress_if_chain_head: bool,
    ) -> None:
        if _statement_has_side_effect(statement):
            self._has_side_effect_any = True

        if isinstance(statement, ast.If):
            next_depth = depth + 1
            self.max_depth = max(self.max_depth, next_depth)
            if not suppress_if_chain_head and self._collect_findings:
                self._record_if_chain(statement)
            self._visit_statements(statement.body, depth=next_depth)
            if statement.orelse:
                self._visit_statements(
                    statement.orelse,
                    depth=next_depth,
                    suppress_if_chain_head=(
                        len(statement.orelse) == 1
                        and isinstance(statement.orelse[0], ast.If)
                    ),
                )
            return

        if (
            self._has_match
            and self._match_type is not None
            and isinstance(statement, self._match_type)
        ):
            next_depth = depth + 1
            self.max_depth = max(self.max_depth, next_depth)
            if self._collect_findings:
                self._record_match(statement)
            for case in getattr(statement, "cases", []):
                body: list[ast.stmt] = getattr(case, "body", [])
                self._visit_statements(body, depth=next_depth)
            return

        if isinstance(
            statement,
            (ast.For, ast.While, ast.AsyncFor, ast.Try, ast.With, ast.AsyncWith),
        ):
            next_depth = depth + 1
            if isinstance(statement, ast.Try):
                self._has_try = True
                if statement.finalbody:
                    self._has_finally = True
            self.max_depth = max(self.max_depth, next_depth)
            for nested in self._iter_nested_statement_lists(statement):
                self._visit_statements(nested, depth=next_depth)
            return

        nested_body = getattr(statement, "body", None)
        if isinstance(nested_body, list):
            self._visit_statements(nested_body, depth=depth)

    def _iter_nested_statement_lists(self, node: ast.AST) -> tuple[list[ast.stmt], ...]:
        if isinstance(node, (ast.For, ast.While, ast.AsyncFor)):
            result = [node.body]
            if node.orelse:
                result.append(node.orelse)
            return tuple(result)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return (node.body,)
        if isinstance(node, ast.Try):
            result = [node.body]
            result.extend(handler.body for handler in node.handlers)
            if node.orelse:
                result.append(node.orelse)
            if node.finalbody:
                result.append(node.finalbody)
            return tuple(result)
        return ()

    def _record_if_chain(self, if_node: ast.If) -> None:
        for body, start, end in _collect_if_branch_bodies(if_node):
            sig = _summarize_branch(body)
            if sig is None:
                continue
            self._sig_to_branches[_sig_canonical(sig)].append((sig, start, end))

    def _record_match(self, match_node: object) -> None:
        for body, start, end in _collect_match_branch_bodies(match_node):
            sig = _summarize_branch(body)
            if sig is None:
                continue
            self._sig_to_branches[_sig_canonical(sig)].append((sig, start, end))

    def _build_groups(self) -> list[StructuralFindingGroup]:
        if not self._collect_findings:
            return []

        groups: list[StructuralFindingGroup] = []
        for sig_key, occurrences in self._sig_to_branches.items():
            deduped_occurrences = {
                (start, end): (sig, start, end) for sig, start, end in occurrences
            }
            if len(deduped_occurrences) < 2:
                continue

            sorted_occurrences = sorted(
                deduped_occurrences.values(),
                key=lambda item: (item[1], item[2]),
            )
            sig_dict = sorted_occurrences[0][0]
            fkey = _finding_key(self._qualname, sig_key)
            raw_group = StructuralFindingGroup(
                finding_kind=_FINDING_KIND_BRANCHES,
                finding_key=fkey,
                signature=sig_dict,
                items=tuple(
                    StructuralFindingOccurrence(
                        finding_kind=_FINDING_KIND_BRANCHES,
                        finding_key=fkey,
                        file_path=self._filepath,
                        qualname=self._qualname,
                        start=start,
                        end=end,
                        signature=sig_dict,
                    )
                    for _, start, end in sorted_occurrences
                ),
            )
            normalized_group = normalize_structural_finding_group(raw_group)
            if normalized_group is None:
                continue
            groups.append(normalized_group)

        groups.sort(key=lambda g: (-len(g.items), g.finding_key))
        return groups


def scan_function_structure(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    filepath: str,
    qualname: str,
    *,
    collect_findings: bool = True,
) -> FunctionStructureFacts:
    """Collect per-function structural facts in one recursive traversal."""
    scanner = _FunctionStructureScanner(
        filepath=filepath,
        qualname=qualname,
        collect_findings=collect_findings,
    )
    return scanner.scan(node)


@dataclass(frozen=True, slots=True)
class _CloneCohortMember:
    file_path: str
    qualname: str
    start: int
    end: int
    entry_guard_count: int
    entry_guard_terminal_profile: str
    entry_guard_has_side_effect_before: bool
    terminal_kind: str
    try_finally_profile: str
    side_effect_order_profile: str

    @property
    def guard_exit_profile(self) -> str:
        return _guard_profile_text(
            count=self.entry_guard_count,
            terminal_profile=self.entry_guard_terminal_profile,
        )


def _as_item_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_item_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _as_item_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        match normalized:
            case "1" | "true" | "yes":
                return True
            case "0" | "false" | "no":
                return False
            case _:
                pass
    return default


def _group_item_sort_key(item: GroupItemLike) -> tuple[str, str, int, int]:
    return (
        _as_item_str(item.get("filepath")),
        _as_item_str(item.get("qualname")),
        _as_item_int(item.get("start_line")),
        _as_item_int(item.get("end_line")),
    )


def _clone_member_sort_key(
    member: _CloneCohortMember,
) -> tuple[str, str, int, int]:
    return (
        member.file_path,
        member.qualname,
        member.start,
        member.end,
    )


def _clone_member_from_item(item: GroupItemLike) -> _CloneCohortMember | None:
    file_path = _as_item_str(item.get("filepath")).strip()
    qualname = _as_item_str(item.get("qualname")).strip()
    start = _as_item_int(item.get("start_line"))
    end = _as_item_int(item.get("end_line"))
    if not file_path or not qualname or start <= 0 or end <= 0:
        return None
    terminal_kind = _as_item_str(item.get("terminal_kind"), "fallthrough").strip()
    try_finally_profile = _as_item_str(item.get("try_finally_profile"), "none").strip()
    side_effect_order_profile = _as_item_str(
        item.get("side_effect_order_profile"),
        "none",
    ).strip()
    entry_guard_terminal_profile = _as_item_str(
        item.get("entry_guard_terminal_profile"),
        "none",
    ).strip()
    return _CloneCohortMember(
        file_path=file_path,
        qualname=qualname,
        start=start,
        end=end,
        entry_guard_count=max(0, _as_item_int(item.get("entry_guard_count"))),
        entry_guard_terminal_profile=(
            entry_guard_terminal_profile if entry_guard_terminal_profile else "none"
        ),
        entry_guard_has_side_effect_before=_as_item_bool(
            item.get("entry_guard_has_side_effect_before"),
            default=False,
        ),
        terminal_kind=terminal_kind if terminal_kind else "fallthrough",
        try_finally_profile=try_finally_profile if try_finally_profile else "none",
        side_effect_order_profile=(
            side_effect_order_profile if side_effect_order_profile else "none"
        ),
    )


def _majority_str(values: Sequence[str], *, default: str) -> str:
    if not values:
        return default
    counts = Counter(values)
    top = max(counts.values())
    winners = sorted(value for value, count in counts.items() if count == top)
    return winners[0] if winners else default


def _majority_int(values: Sequence[int], *, default: int) -> int:
    if not values:
        return default
    counts = Counter(values)
    top = max(counts.values())
    winners = sorted(value for value, count in counts.items() if count == top)
    return winners[0] if winners else default


def _majority_bool(values: Sequence[bool], *, default: bool) -> bool:
    if not values:
        return default
    counts = Counter(values)
    top = max(counts.values())
    winners = sorted(value for value, count in counts.items() if count == top)
    return winners[0] if winners else default


def _cohort_finding_key(kind: str, cohort_id: str) -> str:
    return sha1(f"{kind}|cohort={cohort_id}".encode()).hexdigest()


def _cohort_group_items(
    *,
    finding_kind: str,
    finding_key: str,
    signature: dict[str, str],
    members: Sequence[_CloneCohortMember],
) -> tuple[StructuralFindingOccurrence, ...]:
    return tuple(
        StructuralFindingOccurrence(
            finding_kind=finding_kind,
            finding_key=finding_key,
            file_path=member.file_path,
            qualname=member.qualname,
            start=member.start,
            end=member.end,
            signature=signature,
        )
        for member in sorted(members, key=_clone_member_sort_key)
    )


def _clone_guard_exit_divergence(
    cohort_id: str,
    members: Sequence[_CloneCohortMember],
) -> StructuralFindingGroup | None:
    if len(members) < 3:
        return None
    guard_counts = [member.entry_guard_count for member in members]
    if not any(count > 0 for count in guard_counts):
        return None

    guard_terminal_profiles = [
        member.entry_guard_terminal_profile for member in members
    ]
    terminal_kinds = [member.terminal_kind for member in members]
    side_effect_before_guard_values = [
        member.entry_guard_has_side_effect_before
        for member in members
        if member.entry_guard_count > 0
    ]

    unique_guard_counts = sorted({str(value) for value in guard_counts})
    unique_guard_terminals = sorted(set(guard_terminal_profiles))
    unique_terminal_kinds = sorted(set(terminal_kinds))
    unique_side_effect_before_guard = sorted(
        {"1" if value else "0" for value in side_effect_before_guard_values}
    )
    if (
        len(unique_guard_counts) <= 1
        and len(unique_guard_terminals) <= 1
        and len(unique_terminal_kinds) <= 1
        and len(unique_side_effect_before_guard) <= 1
    ):
        return None

    majority_guard_count = _majority_int(guard_counts, default=0)
    majority_guard_terminal_profile = _majority_str(
        guard_terminal_profiles,
        default="none",
    )
    majority_terminal_kind = _majority_str(terminal_kinds, default="fallthrough")
    majority_side_effect_before_guard = _majority_bool(
        side_effect_before_guard_values,
        default=False,
    )

    divergent_members = [
        member
        for member in members
        if (
            member.entry_guard_count != majority_guard_count
            or member.entry_guard_terminal_profile != majority_guard_terminal_profile
            or member.terminal_kind != majority_terminal_kind
            or (
                member.entry_guard_count > 0
                and member.entry_guard_has_side_effect_before
                != majority_side_effect_before_guard
            )
        )
    ]
    if not divergent_members:
        return None

    finding_key = _cohort_finding_key(
        _FINDING_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
        cohort_id,
    )
    signature = {
        "cohort_id": cohort_id,
        "cohort_arity": str(len(members)),
        "divergent_members": str(len(divergent_members)),
        "majority_guard_count": str(majority_guard_count),
        "majority_guard_terminal_profile": majority_guard_terminal_profile,
        "majority_terminal_kind": majority_terminal_kind,
        "majority_side_effect_before_guard": (
            "1" if majority_side_effect_before_guard else "0"
        ),
        "guard_count_values": ",".join(unique_guard_counts)
        if unique_guard_counts
        else "0",
        "guard_terminal_values": (
            ",".join(unique_guard_terminals) if unique_guard_terminals else "none"
        ),
        "terminal_values": (
            ",".join(unique_terminal_kinds) if unique_terminal_kinds else "fallthrough"
        ),
        "side_effect_before_guard_values": (
            ",".join(unique_side_effect_before_guard)
            if unique_side_effect_before_guard
            else "0"
        ),
    }
    return StructuralFindingGroup(
        finding_kind=_FINDING_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
        finding_key=finding_key,
        signature=signature,
        items=_cohort_group_items(
            finding_kind=_FINDING_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
            finding_key=finding_key,
            signature=signature,
            members=divergent_members,
        ),
    )


def _clone_cohort_drift(
    cohort_id: str,
    members: Sequence[_CloneCohortMember],
) -> StructuralFindingGroup | None:
    if len(members) < 3:
        return None

    value_space: dict[str, list[str]] = {
        "terminal_kind": [member.terminal_kind for member in members],
        "guard_exit_profile": [member.guard_exit_profile for member in members],
        "try_finally_profile": [member.try_finally_profile for member in members],
        "side_effect_order_profile": [
            member.side_effect_order_profile for member in members
        ],
    }
    drift_fields = sorted(
        field for field, values in value_space.items() if len(set(values)) > 1
    )
    if not drift_fields:
        return None

    majority_profile = {
        field: _majority_str(values, default="none")
        for field, values in value_space.items()
    }
    divergent_members = [
        member
        for member in members
        if any(
            _member_profile_value(member, field) != majority_profile[field]
            for field in drift_fields
        )
    ]
    if not divergent_members:
        return None

    finding_key = _cohort_finding_key(_FINDING_KIND_CLONE_COHORT_DRIFT, cohort_id)
    signature = {
        "cohort_id": cohort_id,
        "cohort_arity": str(len(members)),
        "divergent_members": str(len(divergent_members)),
        "drift_fields": ",".join(drift_fields),
        "majority_terminal_kind": majority_profile["terminal_kind"],
        "majority_guard_exit_profile": majority_profile["guard_exit_profile"],
        "majority_try_finally_profile": majority_profile["try_finally_profile"],
        "majority_side_effect_order_profile": majority_profile[
            "side_effect_order_profile"
        ],
    }
    return StructuralFindingGroup(
        finding_kind=_FINDING_KIND_CLONE_COHORT_DRIFT,
        finding_key=finding_key,
        signature=signature,
        items=_cohort_group_items(
            finding_kind=_FINDING_KIND_CLONE_COHORT_DRIFT,
            finding_key=finding_key,
            signature=signature,
            members=divergent_members,
        ),
    )


def _member_profile_value(member: _CloneCohortMember, field: str) -> str:
    match field:
        case "terminal_kind":
            return member.terminal_kind
        case "guard_exit_profile":
            return member.guard_exit_profile
        case "try_finally_profile":
            return member.try_finally_profile
        case "side_effect_order_profile":
            return member.side_effect_order_profile
        case _:
            return ""


def build_clone_cohort_structural_findings(
    *,
    func_groups: Mapping[str, Sequence[GroupItemLike]],
) -> tuple[StructuralFindingGroup, ...]:
    groups: list[StructuralFindingGroup] = []
    for cohort_id in sorted(func_groups):
        rows = func_groups[cohort_id]
        if len(rows) < 3:
            continue
        members = [
            member
            for member in (_clone_member_from_item(row) for row in rows)
            if member is not None
        ]
        if len(members) < 3:
            continue

        guard_exit_group = _clone_guard_exit_divergence(cohort_id, members)
        if guard_exit_group is not None:
            groups.append(guard_exit_group)

        cohort_drift_group = _clone_cohort_drift(cohort_id, members)
        if cohort_drift_group is not None:
            groups.append(cohort_drift_group)

    return normalize_structural_findings(groups)
