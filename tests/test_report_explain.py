# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast
from pathlib import Path

import codeclone.report.explain as explain_mod
from codeclone.report.explain import build_block_group_facts
from tests._report_fixtures import (
    repeated_block_group_key,
    write_repeated_assert_source,
)


def _build_group_facts_for_source(
    *,
    tmp_path: Path,
    filename: str,
    source: str,
    qualname: str = "mod:f",
    start_line: int = 2,
    end_line: int = 4,
) -> dict[str, str]:
    group_key = repeated_block_group_key()
    test_file = tmp_path / filename
    test_file.write_text(source, "utf-8")
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": qualname,
                    "filepath": str(test_file),
                    "start_line": start_line,
                    "end_line": end_line,
                }
            ]
        }
    )
    return facts[group_key]


def test_build_block_group_facts_handles_missing_file() -> None:
    group_key = repeated_block_group_key()
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": "/definitely/missing/file.py",
                    "start_line": 10,
                    "end_line": 20,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["match_rule"] == "normalized_sliding_window"
    assert group["pattern"] == "repeated_stmt_hash"
    assert "hint" not in group
    assert "assert_ratio" not in group


def test_build_block_group_facts_handles_syntax_error_file(tmp_path: Path) -> None:
    group_key = repeated_block_group_key()
    broken = tmp_path / "broken.py"
    broken.write_text("def f(:\n    pass\n", "utf-8")
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(broken),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        }
    )
    assert "hint" not in facts[group_key]


def test_build_block_group_facts_assert_detection_with_calls(tmp_path: Path) -> None:
    group = _build_group_facts_for_source(
        tmp_path=tmp_path,
        filename="test_calls.py",
        source=(
            "def f(checker):\n"
            '    "doc"\n'
            "    assert_ok(checker)\n"
            "    checker.assert_ready(checker)\n"
        ),
        qualname="tests.mod:f",
    )
    assert group["hint"] == "assert_only"
    assert group["assert_ratio"] == "100%"
    assert group["consecutive_asserts"] == "3"


def test_build_block_group_facts_non_assert_breaks_hint(tmp_path: Path) -> None:
    group = _build_group_facts_for_source(
        tmp_path=tmp_path,
        filename="test_mixed.py",
        source=(
            "def f(html):\n"
            "    assert 'a' in html\n"
            "    check(html)\n"
            "    assert 'b' in html\n"
        ),
        qualname="tests.mod:f",
    )
    assert "hint" not in group
    assert group["assert_ratio"] == "67%"
    assert group["consecutive_asserts"] == "1"


def test_build_block_group_facts_non_repeated_signature_has_no_pattern() -> None:
    group_key = (
        "0e8579f84e518d186950d012c9944a40cb872332|"
        "1e8579f84e518d186950d012c9944a40cb872332|"
        "2e8579f84e518d186950d012c9944a40cb872332|"
        "3e8579f84e518d186950d012c9944a40cb872332"
    )
    facts = build_block_group_facts({group_key: []})
    group = facts[group_key]
    assert group["block_size"] == "4"
    assert "pattern" not in group


def test_build_block_group_facts_handles_empty_stmt_range(tmp_path: Path) -> None:
    group_key = repeated_block_group_key()
    test_file = tmp_path / "module.py"
    test_file.write_text("def f():\n    return 1\n", "utf-8")
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "mod:f",
                    "filepath": str(test_file),
                    "start_line": 100,
                    "end_line": 200,
                }
            ]
        }
    )
    group = facts[group_key]
    assert "assert_ratio" not in group
    assert "hint" not in group


def test_build_block_group_facts_non_assert_call_shapes(tmp_path: Path) -> None:
    group = _build_group_facts_for_source(
        tmp_path=tmp_path,
        filename="module.py",
        source=(
            "def f(checker, x):\n    checker.validate(x)\n    (lambda y: y)(x)\n    x\n"
        ),
    )
    assert group["assert_ratio"] == "0%"
    assert group["consecutive_asserts"] == "0"
    assert "hint" not in group


def test_build_block_group_facts_invalid_item_disables_assert_hint() -> None:
    group_key = repeated_block_group_key()
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "mod:f",
                    "filepath": "",
                    "start_line": 0,
                    "end_line": 0,
                }
            ]
        }
    )
    group = facts[group_key]
    assert "hint" not in group
    assert "assert_ratio" not in group


def test_build_block_group_facts_assert_only_without_test_context(
    tmp_path: Path,
) -> None:
    group_key = repeated_block_group_key()
    prod_file = tmp_path / "module.py"
    prod_file.write_text(
        "def f(html):\n"
        "    assert 'a' in html\n"
        "    assert 'b' in html\n"
        "    assert 'c' in html\n"
        "    assert 'd' in html\n",
        "utf-8",
    )
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(prod_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["hint"] == "assert_only"
    assert "hint_context" not in group


def test_build_block_group_facts_n_way_group_compare_facts(tmp_path: Path) -> None:
    group_key = repeated_block_group_key()
    test_file = write_repeated_assert_source(tmp_path / "test_repeated_asserts.py")
    item = {
        "qualname": "pkg.mod:f",
        "filepath": str(test_file),
        "start_line": 2,
        "end_line": 5,
    }
    facts = build_block_group_facts({group_key: [item, item, item]})
    group = facts[group_key]
    assert group["group_arity"] == "3"
    assert group["instance_peer_count"] == "2"
    assert group["group_compare_note"] == (
        "N-way group: each block matches 2 peers in this group."
    )


def test_explain_as_int_variants() -> None:
    assert explain_mod._as_int(True) == 1
    assert explain_mod._as_int("7") == 7
    assert explain_mod._as_int("bad") == 0
    assert explain_mod._as_int(1.5) == 0


def test_parsed_file_tree_cache_and_empty_statement_index_paths(tmp_path: Path) -> None:
    module = tmp_path / "empty_module.py"
    module.write_text("", "utf-8")

    ast_cache: dict[str, ast.AST | None] = {}
    first = explain_mod.parsed_file_tree(str(module), ast_cache=ast_cache)
    second = explain_mod.parsed_file_tree(str(module), ast_cache=ast_cache)
    assert first is second

    stmt_index_cache: dict[str, explain_mod._StatementIndex | None] = {}
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]] = {}
    total, assert_like, consecutive = explain_mod.assert_range_stats(
        filepath=str(module),
        start_line=1,
        end_line=10,
        ast_cache=ast_cache,
        stmt_index_cache=stmt_index_cache,
        range_cache=range_cache,
    )
    assert (total, assert_like, consecutive) == (0, 0, 0)


def test_assert_range_stats_skips_records_outside_requested_end_line(
    tmp_path: Path,
) -> None:
    module = tmp_path / "multiline_stmt.py"
    module.write_text(
        "def f() -> int:\n"
        "    value = (\n"
        "        1 +\n"
        "        2\n"
        "    )\n"
        "    return value\n",
        "utf-8",
    )
    ast_cache: dict[str, ast.AST | None] = {}
    stmt_index_cache: dict[str, explain_mod._StatementIndex | None] = {}
    range_cache: dict[tuple[str, int, int], tuple[int, int, int]] = {}

    total, assert_like, consecutive = explain_mod.assert_range_stats(
        filepath=str(module),
        start_line=2,
        end_line=2,
        ast_cache=ast_cache,
        stmt_index_cache=stmt_index_cache,
        range_cache=range_cache,
    )
    assert (total, assert_like, consecutive) == (0, 0, 0)
