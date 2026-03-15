# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..extractor import _QualnameCollector
from .merge import coerce_positive_int, merge_overlapping_items

if TYPE_CHECKING:
    from .types import GroupItem, GroupItemLike, GroupItemsLike, GroupMap, GroupMapLike

SEGMENT_MIN_UNIQUE_STMT_TYPES = 2

_CONTROL_FLOW_STMTS = (
    ast.If,
    ast.For,
    ast.While,
    ast.Try,
    ast.With,
    ast.Match,
    ast.AsyncFor,
    ast.AsyncWith,
)
_FORBIDDEN_STMTS = (ast.Return, ast.Raise, ast.Assert)


@dataclass(frozen=True, slots=True)
class _SegmentAnalysis:
    unique_stmt_types: int
    has_control_flow: bool
    is_boilerplate: bool


def segment_item_sort_key(item: GroupItemLike) -> tuple[str, str, int, int]:
    return (
        str(item.get("filepath", "")),
        str(item.get("qualname", "")),
        coerce_positive_int(item.get("start_line")) or 0,
        coerce_positive_int(item.get("end_line")) or 0,
    )


def merge_segment_items(items: GroupItemsLike) -> list[GroupItem]:
    return merge_overlapping_items(items, sort_key=segment_item_sort_key)


def collect_file_functions(
    filepath: str,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    try:
        source = Path(filepath).read_text("utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    collector = _QualnameCollector()
    collector.visit(tree)
    return collector.funcs


def segment_statements(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, start_line: int, end_line: int
) -> list[ast.stmt]:
    body = getattr(func_node, "body", None)
    if not isinstance(body, list):
        return []

    statements: list[ast.stmt] = []
    for statement in body:
        lineno = getattr(statement, "lineno", None)
        end_lineno = getattr(statement, "end_lineno", None)
        if lineno is None or end_lineno is None:
            continue
        if lineno >= start_line and end_lineno <= end_line:
            statements.append(statement)
    return statements


def assign_targets_attribute_only(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Assign):
        return all(isinstance(target, ast.Attribute) for target in statement.targets)
    if isinstance(statement, ast.AnnAssign):
        return isinstance(statement.target, ast.Attribute)
    return False


def analyze_segment_statements(statements: list[ast.stmt]) -> _SegmentAnalysis | None:
    if not statements:
        return None

    unique_types = {type(statement) for statement in statements}
    has_control_flow = any(
        isinstance(statement, _CONTROL_FLOW_STMTS) for statement in statements
    )
    has_forbidden = any(
        isinstance(statement, _FORBIDDEN_STMTS) for statement in statements
    )
    has_call_statement = any(
        isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
        for statement in statements
    )

    assign_statements = [
        statement
        for statement in statements
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
    ]
    assign_ratio = len(assign_statements) / len(statements)
    assign_attr_only = all(
        assign_targets_attribute_only(statement) for statement in assign_statements
    )

    is_boilerplate = (
        assign_ratio >= 0.8
        and assign_attr_only
        and not has_control_flow
        and not has_forbidden
        and not has_call_statement
    )

    return _SegmentAnalysis(
        unique_stmt_types=len(unique_types),
        has_control_flow=has_control_flow,
        is_boilerplate=is_boilerplate,
    )


def prepare_segment_report_groups(segment_groups: GroupMapLike) -> tuple[GroupMap, int]:
    """
    Merge overlapping segment windows and suppress low-value boilerplate groups
    for reporting. Detection hashes remain unchanged.
    """
    suppressed = 0
    filtered: GroupMap = {}
    file_cache: dict[str, dict[str, ast.FunctionDef | ast.AsyncFunctionDef] | None] = {}

    for key, items in segment_groups.items():
        merged_items = merge_segment_items(items)
        if not merged_items:
            continue

        analyses: list[_SegmentAnalysis] = []
        unknown = False
        for item in merged_items:
            filepath = str(item.get("filepath", ""))
            qualname = str(item.get("qualname", ""))
            start_line = coerce_positive_int(item.get("start_line")) or 0
            end_line = coerce_positive_int(item.get("end_line")) or 0
            if not filepath or not qualname or start_line <= 0 or end_line <= 0:
                unknown = True
                break

            if filepath not in file_cache:
                file_cache[filepath] = collect_file_functions(filepath)
            functions_by_qualname = file_cache[filepath]
            if not functions_by_qualname:
                unknown = True
                break

            local_name = qualname.split(":", 1)[1] if ":" in qualname else qualname
            func_node = functions_by_qualname.get(local_name)
            if func_node is None:
                unknown = True
                break

            statements = segment_statements(func_node, start_line, end_line)
            analysis = analyze_segment_statements(statements)
            if analysis is None:
                unknown = True
                break
            analyses.append(analysis)

        if unknown:
            filtered[key] = merged_items
            continue

        all_boilerplate = all(analysis.is_boilerplate for analysis in analyses)
        all_too_simple = all(
            (not analysis.has_control_flow)
            and (analysis.unique_stmt_types < SEGMENT_MIN_UNIQUE_STMT_TYPES)
            for analysis in analyses
        )
        if all_boilerplate or all_too_simple:
            suppressed += 1
            continue

        filtered[key] = merged_items

    return filtered, suppressed
