# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import ast
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import _coerce
from .explain_contract import (
    BLOCK_HINT_ASSERT_ONLY,
    BLOCK_HINT_ASSERT_ONLY_LABEL,
    BLOCK_HINT_ASSERT_ONLY_NOTE,
    BLOCK_HINT_CONFIDENCE_DETERMINISTIC,
    BLOCK_PATTERN_REPEATED_STMT_HASH,
    resolve_group_compare_note,
    resolve_group_display_name,
)

if TYPE_CHECKING:
    from .types import GroupItemsLike, GroupMapLike


@dataclass(frozen=True, slots=True)
class _StatementRecord:
    node: ast.stmt
    start_line: int
    end_line: int
    start_col: int
    end_col: int
    type_name: str


_StatementIndex = tuple[tuple[_StatementRecord, ...], tuple[int, ...]]
_EMPTY_ASSERT_RANGE_STATS = (0, 0, 0)


def signature_parts(group_key: str) -> list[str]:
    return [part for part in group_key.split("|") if part]


_as_int = _coerce.as_int


def parsed_file_tree(
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


def _cache_empty_assert_range_stats(
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]],
    cache_key: tuple[str, int, int],
) -> tuple[int, int, int]:
    range_cache[cache_key] = _EMPTY_ASSERT_RANGE_STATS
    return _EMPTY_ASSERT_RANGE_STATS


def _build_statement_index(tree: ast.AST) -> _StatementIndex:
    records = tuple(
        sorted(
            (
                _StatementRecord(
                    node=node,
                    start_line=int(getattr(node, "lineno", 0)),
                    end_line=int(getattr(node, "end_lineno", 0)),
                    start_col=int(getattr(node, "col_offset", 0)),
                    end_col=int(getattr(node, "end_col_offset", 0)),
                    type_name=type(node).__name__,
                )
                for node in ast.walk(tree)
                if isinstance(node, ast.stmt)
            ),
            key=lambda record: (
                record.start_line,
                record.end_line,
                record.start_col,
                record.end_col,
                record.type_name,
            ),
        )
    )
    start_lines = tuple(record.start_line for record in records)
    return records, start_lines


def parsed_statement_index(
    filepath: str,
    *,
    ast_cache: dict[str, ast.AST | None],
    stmt_index_cache: dict[str, _StatementIndex | None],
) -> _StatementIndex | None:
    if filepath in stmt_index_cache:
        return stmt_index_cache[filepath]

    tree = parsed_file_tree(filepath, ast_cache=ast_cache)
    if tree is None:
        stmt_index_cache[filepath] = None
        return None

    index = _build_statement_index(tree)
    stmt_index_cache[filepath] = index
    return index


def is_assert_like_stmt(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Assert):
        return True
    if isinstance(statement, ast.Expr):
        value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return True
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Name):
                return func.id.lower().startswith("assert")
            if isinstance(func, ast.Attribute):
                return func.attr.lower().startswith("assert")
    return False


def assert_range_stats(
    *,
    filepath: str,
    start_line: int,
    end_line: int,
    ast_cache: dict[str, ast.AST | None],
    stmt_index_cache: dict[str, _StatementIndex | None],
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]],
) -> tuple[int, int, int]:
    cache_key = (filepath, start_line, end_line)
    if cache_key in range_cache:
        return range_cache[cache_key]

    statement_index = parsed_statement_index(
        filepath,
        ast_cache=ast_cache,
        stmt_index_cache=stmt_index_cache,
    )
    if statement_index is None:
        return _cache_empty_assert_range_stats(range_cache, cache_key)

    records, start_lines = statement_index
    if not records:
        return _cache_empty_assert_range_stats(range_cache, cache_key)

    left = bisect_left(start_lines, start_line)
    right = bisect_right(start_lines, end_line)
    if left >= right:
        return _cache_empty_assert_range_stats(range_cache, cache_key)

    total, assert_like, max_consecutive, current_consecutive = (0, 0, 0, 0)
    for record in records[left:right]:
        if record.end_line > end_line:
            continue
        total += 1
        if is_assert_like_stmt(record.node):
            assert_like += 1
            current_consecutive += 1
            if current_consecutive > max_consecutive:
                max_consecutive = current_consecutive
        else:
            current_consecutive = 0

    if total == 0:
        return _cache_empty_assert_range_stats(range_cache, cache_key)

    stats = (total, assert_like, max_consecutive)
    range_cache[cache_key] = stats
    return stats


def is_assert_only_range(
    *,
    filepath: str,
    start_line: int,
    end_line: int,
    ast_cache: dict[str, ast.AST | None],
    stmt_index_cache: dict[str, _StatementIndex | None],
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]],
) -> bool:
    total, assert_like, _ = assert_range_stats(
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        ast_cache=ast_cache,
        stmt_index_cache=stmt_index_cache,
        range_cache=range_cache,
    )
    return total > 0 and total == assert_like


def base_block_facts(group_key: str) -> dict[str, str]:
    parts = signature_parts(group_key)
    window_size = max(1, len(parts))
    repeated_signature = len(parts) > 1 and all(part == parts[0] for part in parts)
    facts: dict[str, str] = {
        "match_rule": "normalized_sliding_window",
        "block_size": str(window_size),
        "signature_kind": "stmt_hash_sequence",
        "merged_regions": "true",
    }
    if repeated_signature:
        facts["pattern"] = BLOCK_PATTERN_REPEATED_STMT_HASH
        facts["pattern_label"] = BLOCK_PATTERN_REPEATED_STMT_HASH
        facts["pattern_display"] = f"{parts[0][:12]} x{window_size}"
    return facts


def enrich_with_assert_facts(
    *,
    facts: dict[str, str],
    items: GroupItemsLike,
    ast_cache: dict[str, ast.AST | None],
    stmt_index_cache: dict[str, _StatementIndex | None],
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]],
) -> None:
    (
        assert_only,
        total_statements,
        assert_statements,
        max_consecutive_asserts,
    ) = _initial_assert_fact_state()

    if not items:
        assert_only = False

    for item in items:
        filepath = str(item.get("filepath", ""))
        start_line = _as_int(item.get("start_line", 0))
        end_line = _as_int(item.get("end_line", 0))

        range_total = 0
        range_assert = 0
        range_max_consecutive = 0
        if filepath and start_line > 0 and end_line > 0:
            range_total, range_assert, range_max_consecutive = assert_range_stats(
                filepath=filepath,
                start_line=start_line,
                end_line=end_line,
                ast_cache=ast_cache,
                stmt_index_cache=stmt_index_cache,
                range_cache=range_cache,
            )
            total_statements += range_total
            assert_statements += range_assert
            max_consecutive_asserts = max(
                max_consecutive_asserts,
                range_max_consecutive,
            )

        if (
            not filepath
            or start_line <= 0
            or end_line <= 0
            or not is_assert_only_range(
                filepath=filepath,
                start_line=start_line,
                end_line=end_line,
                ast_cache=ast_cache,
                stmt_index_cache=stmt_index_cache,
                range_cache=range_cache,
            )
        ):
            assert_only = False

    if total_statements > 0:
        ratio = round((assert_statements / total_statements) * 100)
        facts["assert_ratio"] = f"{ratio}%"
        facts["consecutive_asserts"] = str(max_consecutive_asserts)

    if assert_only:
        facts["hint"] = BLOCK_HINT_ASSERT_ONLY
        facts["hint_label"] = BLOCK_HINT_ASSERT_ONLY_LABEL
        facts["hint_confidence"] = BLOCK_HINT_CONFIDENCE_DETERMINISTIC
        facts["hint_note"] = BLOCK_HINT_ASSERT_ONLY_NOTE


def _initial_assert_fact_state() -> tuple[bool, int, int, int]:
    return True, 0, 0, 0


def build_block_group_facts(block_groups: GroupMapLike) -> dict[str, dict[str, str]]:
    """
    Build deterministic explainability facts for block clone groups.

    This is the source of truth for report-level block explanations.
    Renderers (HTML/TXT/JSON) should only display these facts.
    """
    ast_cache: dict[str, ast.AST | None] = {}
    stmt_index_cache: dict[str, _StatementIndex | None] = {}
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]] = {}
    facts_by_group: dict[str, dict[str, str]] = {}

    for group_key, items in block_groups.items():
        facts = base_block_facts(group_key)
        enrich_with_assert_facts(
            facts=facts,
            items=items,
            ast_cache=ast_cache,
            stmt_index_cache=stmt_index_cache,
            range_cache=range_cache,
        )
        group_arity = len(items)
        peer_count = max(0, group_arity - 1)
        facts["group_arity"] = str(group_arity)
        facts["instance_peer_count"] = str(peer_count)
        compare_note = resolve_group_compare_note(
            group_arity=group_arity,
            peer_count=peer_count,
        )
        if compare_note is not None:
            facts["group_compare_note"] = compare_note
        group_display_name = resolve_group_display_name(hint_id=facts.get("hint"))
        if group_display_name is not None:
            facts["group_display_name"] = group_display_name
        facts_by_group[group_key] = facts

    return facts_by_group
