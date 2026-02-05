"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GroupItem = dict[str, Any]
GroupMap = dict[str, list[GroupItem]]

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


def build_groups(units: list[GroupItem]) -> GroupMap:
    groups: GroupMap = {}
    for u in units:
        key = f"{u['fingerprint']}|{u['loc_bucket']}"
        groups.setdefault(key, []).append(u)
    return {k: v for k, v in groups.items() if len(v) > 1}


def build_block_groups(blocks: list[GroupItem], min_functions: int = 2) -> GroupMap:
    groups: GroupMap = {}
    for b in blocks:
        groups.setdefault(b["block_hash"], []).append(b)

    filtered: GroupMap = {}
    for h, items in groups.items():
        functions = {i["qualname"] for i in items}
        if len(functions) >= min_functions:
            filtered[h] = items

    return filtered


def build_segment_groups(
    segments: list[GroupItem], min_occurrences: int = 2
) -> GroupMap:
    sig_groups: GroupMap = {}
    for s in segments:
        sig_groups.setdefault(s["segment_sig"], []).append(s)

    confirmed: GroupMap = {}
    for items in sig_groups.values():
        if len(items) < min_occurrences:
            continue

        hash_groups: GroupMap = {}
        for item in items:
            hash_groups.setdefault(item["segment_hash"], []).append(item)

        for segment_hash, hash_items in hash_groups.items():
            if len(hash_items) < min_occurrences:
                continue

            by_func: GroupMap = {}
            for it in hash_items:
                by_func.setdefault(it["qualname"], []).append(it)

            for qualname, q_items in by_func.items():
                if len(q_items) >= min_occurrences:
                    confirmed[f"{segment_hash}|{qualname}"] = q_items

    return confirmed


class _QualnameCollector(ast.NodeVisitor):
    __slots__ = ("funcs", "stack")

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        name = ".".join([*self.stack, node.name]) if self.stack else node.name
        self.funcs[name] = node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        name = ".".join([*self.stack, node.name]) if self.stack else node.name
        self.funcs[name] = node


def _merge_segment_items(items: list[GroupItem]) -> list[GroupItem]:
    if not items:
        return []

    items_sorted = sorted(
        items,
        key=lambda i: (
            i.get("filepath", ""),
            i.get("qualname", ""),
            int(i.get("start_line", 0)),
            int(i.get("end_line", 0)),
        ),
    )

    merged: list[GroupItem] = []
    current: GroupItem | None = None

    for item in items_sorted:
        start = int(item.get("start_line", 0))
        end = int(item.get("end_line", 0))
        if start <= 0 or end <= 0:
            continue

        if current is None:
            current = dict(item)
            current["start_line"] = start
            current["end_line"] = end
            current["size"] = max(1, end - start + 1)
            continue

        same_owner = current.get("filepath") == item.get("filepath") and current.get(
            "qualname"
        ) == item.get("qualname")
        if same_owner and start <= int(current["end_line"]) + 1:
            current["end_line"] = max(int(current["end_line"]), end)
            current["size"] = max(
                1, int(current["end_line"]) - int(current["start_line"]) + 1
            )
            continue

        merged.append(current)
        current = dict(item)
        current["start_line"] = start
        current["end_line"] = end
        current["size"] = max(1, end - start + 1)

    if current is not None:
        merged.append(current)

    return merged


def _collect_file_functions(
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


def _segment_statements(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef, start_line: int, end_line: int
) -> list[ast.stmt]:
    body = getattr(func_node, "body", None)
    if not isinstance(body, list):
        return []
    stmts: list[ast.stmt] = []
    for stmt in body:
        lineno = getattr(stmt, "lineno", None)
        end = getattr(stmt, "end_lineno", None)
        if lineno is None or end is None:
            continue
        if lineno >= start_line and end <= end_line:
            stmts.append(stmt)
    return stmts


def _assign_targets_attribute_only(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assign):
        return all(isinstance(t, ast.Attribute) for t in stmt.targets)
    if isinstance(stmt, ast.AnnAssign):
        return isinstance(stmt.target, ast.Attribute)
    return False


def _analyze_segment_statements(stmts: list[ast.stmt]) -> _SegmentAnalysis | None:
    if not stmts:
        return None

    unique_types = {type(s) for s in stmts}
    has_control_flow = any(isinstance(s, _CONTROL_FLOW_STMTS) for s in stmts)
    has_forbidden = any(isinstance(s, _FORBIDDEN_STMTS) for s in stmts)
    has_call_stmt = any(
        isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) for s in stmts
    )

    assign_stmts = [s for s in stmts if isinstance(s, (ast.Assign, ast.AnnAssign))]
    assign_ratio = len(assign_stmts) / len(stmts)
    assign_attr_only = all(_assign_targets_attribute_only(s) for s in assign_stmts)

    is_boilerplate = (
        assign_ratio >= 0.8
        and assign_attr_only
        and not has_control_flow
        and not has_forbidden
        and not has_call_stmt
    )

    return _SegmentAnalysis(
        unique_stmt_types=len(unique_types),
        has_control_flow=has_control_flow,
        is_boilerplate=is_boilerplate,
    )


def prepare_segment_report_groups(
    segment_groups: GroupMap,
) -> tuple[GroupMap, int]:
    """
    Merge overlapping segment windows and suppress low-value boilerplate groups
    for reporting. Detection hashes remain unchanged.
    """
    suppressed = 0
    filtered: GroupMap = {}
    file_cache: dict[str, dict[str, ast.FunctionDef | ast.AsyncFunctionDef] | None] = {}

    for key, items in segment_groups.items():
        merged_items = _merge_segment_items(items)
        if not merged_items:
            continue

        analyses: list[_SegmentAnalysis] = []
        unknown = False
        for item in merged_items:
            filepath = str(item.get("filepath", ""))
            qualname = str(item.get("qualname", ""))
            start_line = int(item.get("start_line", 0))
            end_line = int(item.get("end_line", 0))
            if not filepath or not qualname or start_line <= 0 or end_line <= 0:
                unknown = True
                break

            if filepath not in file_cache:
                file_cache[filepath] = _collect_file_functions(filepath)
            funcs = file_cache[filepath]
            if not funcs:
                unknown = True
                break

            local_name = qualname.split(":", 1)[1] if ":" in qualname else qualname
            func_node = funcs.get(local_name)
            if func_node is None:
                unknown = True
                break

            stmts = _segment_statements(func_node, start_line, end_line)
            analysis = _analyze_segment_statements(stmts)
            if analysis is None:
                unknown = True
                break
            analyses.append(analysis)

        if unknown:
            filtered[key] = merged_items
            continue

        all_boilerplate = all(a.is_boilerplate for a in analyses)
        all_too_simple = all(
            (not a.has_control_flow)
            and (a.unique_stmt_types < SEGMENT_MIN_UNIQUE_STMT_TYPES)
            for a in analyses
        )
        if all_boilerplate or all_too_simple:
            suppressed += 1
            continue

        filtered[key] = merged_items

    return filtered, suppressed


def to_json(groups: GroupMap) -> str:
    return json.dumps(
        {
            "group_count": len(groups),
            "groups": [
                {"key": k, "count": len(v), "items": v}
                for k, v in sorted(
                    groups.items(), key=lambda kv: len(kv[1]), reverse=True
                )
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def to_json_report(
    func_groups: GroupMap, block_groups: GroupMap, segment_groups: GroupMap
) -> str:
    return json.dumps(
        {"functions": func_groups, "blocks": block_groups, "segments": segment_groups},
        ensure_ascii=False,
        indent=2,
    )


def to_text(groups: GroupMap) -> str:
    lines: list[str] = []
    for i, (_, v) in enumerate(
        sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    ):
        lines.append(f"\n=== Clone group #{i + 1} (count={len(v)}) ===")
        lines.extend(
            [
                f"- {item['qualname']} "
                f"{item['filepath']}:{item['start_line']}-{item['end_line']} "
                f"loc={item.get('loc', item.get('size'))}"
                for item in v
            ]
        )
    return "\n".join(lines).strip() + "\n"
