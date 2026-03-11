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
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha1

from .models import StructuralFindingGroup, StructuralFindingOccurrence

__all__ = [
    "is_reportable_structural_signature",
    "normalize_structural_finding_group",
    "normalize_structural_findings",
    "scan_function_structure",
]

_FINDING_KIND_BRANCHES = "duplicated_branches"
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
    if call_count == 0:
        return "0"
    if call_count == 1:
        return "1"
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
    if not is_reportable_structural_signature(group.signature):
        return None
    normalized_items = _normalize_occurrences(group.items)
    if len(normalized_items) < 2:
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

    call_count = 0
    raise_count = 0
    has_nested_if = False
    has_loop = False
    has_try = False
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


class _FunctionStructureScanner:
    __slots__ = (
        "_collect_findings",
        "_filepath",
        "_has_match",
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
        self._match_type = getattr(ast, "Match", None)
        self._has_match = self._match_type is not None and sys.version_info >= (3, 10)

    def scan(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> FunctionStructureFacts:
        self._visit_statements(list(node.body), depth=0)
        return FunctionStructureFacts(
            nesting_depth=self.max_depth,
            structural_findings=tuple(self._build_groups()),
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
