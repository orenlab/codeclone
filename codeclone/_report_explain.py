"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ._report_types import GroupItem, GroupMap


def _signature_parts(group_key: str) -> list[str]:
    return [part for part in group_key.split("|") if part]


def _looks_like_test_path(filepath: str) -> bool:
    normalized = filepath.replace("\\", "/").lower()
    filename = normalized.rsplit("/", maxsplit=1)[-1]
    return "/tests/" in f"/{normalized}/" or filename.startswith("test_")


def _parsed_file_tree(
    filepath: str, *, ast_cache: dict[str, ast.AST | None]
) -> ast.AST | None:
    if filepath in ast_cache:
        return ast_cache[filepath]

    try:
        source = Path(filepath).read_text("utf-8")
        tree = ast.parse(source, filename=filepath)
    except (OSError, SyntaxError):
        tree = None
    ast_cache[filepath] = tree
    return tree


def _is_assert_like_stmt(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assert):
        return True
    if isinstance(stmt, ast.Expr):
        value = stmt.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return True
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Name):
                return func.id.lower().startswith("assert")
            if isinstance(func, ast.Attribute):
                return func.attr.lower().startswith("assert")
    return False


def _assert_range_stats(
    *,
    filepath: str,
    start_line: int,
    end_line: int,
    ast_cache: dict[str, ast.AST | None],
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]],
) -> tuple[int, int, int]:
    cache_key = (filepath, start_line, end_line)
    if cache_key in range_cache:
        return range_cache[cache_key]

    tree = _parsed_file_tree(filepath, ast_cache=ast_cache)
    if tree is None:
        range_cache[cache_key] = (0, 0, 0)
        return 0, 0, 0

    stmts = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.stmt)
        and int(getattr(node, "lineno", 0)) >= start_line
        and int(getattr(node, "end_lineno", 0)) <= end_line
    ]
    if not stmts:
        range_cache[cache_key] = (0, 0, 0)
        return 0, 0, 0

    ordered_stmts = sorted(
        stmts,
        key=lambda stmt: (
            int(getattr(stmt, "lineno", 0)),
            int(getattr(stmt, "end_lineno", 0)),
            int(getattr(stmt, "col_offset", 0)),
            int(getattr(stmt, "end_col_offset", 0)),
            type(stmt).__name__,
        ),
    )

    total = len(ordered_stmts)
    assert_like = 0
    max_consecutive = 0
    current_consecutive = 0
    for stmt in ordered_stmts:
        if _is_assert_like_stmt(stmt):
            assert_like += 1
            current_consecutive += 1
            if current_consecutive > max_consecutive:
                max_consecutive = current_consecutive
        else:
            current_consecutive = 0

    stats = (total, assert_like, max_consecutive)
    range_cache[cache_key] = stats
    return stats


def _is_assert_only_range(
    *,
    filepath: str,
    start_line: int,
    end_line: int,
    ast_cache: dict[str, ast.AST | None],
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]],
) -> bool:
    total, assert_like, _ = _assert_range_stats(
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        ast_cache=ast_cache,
        range_cache=range_cache,
    )
    return total > 0 and total == assert_like


def _base_block_facts(group_key: str) -> dict[str, str]:
    signature_parts = _signature_parts(group_key)
    window_size = max(1, len(signature_parts))
    repeated_signature = len(signature_parts) > 1 and all(
        part == signature_parts[0] for part in signature_parts
    )
    facts: dict[str, str] = {
        "match_rule": "normalized_sliding_window",
        "block_size": str(window_size),
        "signature_kind": "stmt_hash_sequence",
        "merged_regions": "true",
    }
    if repeated_signature:
        facts["pattern"] = "repeated_stmt_hash"
        facts["pattern_display"] = f"{signature_parts[0][:12]} x{window_size}"
    return facts


def _enrich_with_assert_facts(
    *,
    facts: dict[str, str],
    items: list[GroupItem],
    ast_cache: dict[str, ast.AST | None],
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]],
) -> None:
    assert_only = True
    test_like_paths = True
    total_statements = 0
    assert_statements = 0
    max_consecutive_asserts = 0

    if not items:
        assert_only = False
        test_like_paths = False

    for item in items:
        filepath = str(item.get("filepath", ""))
        start_line = int(item.get("start_line", 0))
        end_line = int(item.get("end_line", 0))

        range_total = 0
        range_assert = 0
        range_max_consecutive = 0
        if filepath and start_line > 0 and end_line > 0:
            range_total, range_assert, range_max_consecutive = _assert_range_stats(
                filepath=filepath,
                start_line=start_line,
                end_line=end_line,
                ast_cache=ast_cache,
                range_cache=range_cache,
            )
            total_statements += range_total
            assert_statements += range_assert
            max_consecutive_asserts = max(
                max_consecutive_asserts, range_max_consecutive
            )

        if (
            not filepath
            or start_line <= 0
            or end_line <= 0
            or not _is_assert_only_range(
                filepath=filepath,
                start_line=start_line,
                end_line=end_line,
                ast_cache=ast_cache,
                range_cache=range_cache,
            )
        ):
            assert_only = False

        if not filepath or not _looks_like_test_path(filepath):
            test_like_paths = False

    if total_statements > 0:
        ratio = round((assert_statements / total_statements) * 100)
        facts["assert_ratio"] = f"{ratio}%"
        facts["consecutive_asserts"] = str(max_consecutive_asserts)

    if assert_only:
        facts["hint"] = "assert_only"
        facts["hint_confidence"] = "deterministic"
        if facts.get("pattern") == "repeated_stmt_hash" and test_like_paths:
            facts["hint_context"] = "likely_test_boilerplate"
        facts["hint_note"] = (
            "This block clone consists entirely of assert-only statements. "
            "This often occurs in test suites."
        )


def build_block_group_facts(block_groups: GroupMap) -> dict[str, dict[str, str]]:
    """
    Build deterministic explainability facts for block clone groups.

    This is the source of truth for report-level block explanations.
    Renderers (HTML/TXT/JSON) should only display these facts.
    """
    ast_cache: dict[str, ast.AST | None] = {}
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]] = {}
    facts_by_group: dict[str, dict[str, str]] = {}

    for group_key, items in block_groups.items():
        facts = _base_block_facts(group_key)
        _enrich_with_assert_facts(
            facts=facts,
            items=items,
            ast_cache=ast_cache,
            range_cache=range_cache,
        )
        facts_by_group[group_key] = facts

    return facts_by_group
