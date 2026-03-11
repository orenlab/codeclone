# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Unit tests for codeclone.structural_findings (Phase 1: duplicated_branches)."""

from __future__ import annotations

import ast
import sys

import pytest

from codeclone.models import StructuralFindingGroup
from codeclone.structural_findings import (
    scan_function_structure,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_fn(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """Parse a source snippet and return the first function definition."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    raise ValueError("No function found in source")


def _findings(source: str, qualname: str = "mod:fn") -> list[StructuralFindingGroup]:
    fn = _parse_fn(source)
    return list(
        scan_function_structure(
            fn,
            "mod.py",
            qualname,
            collect_findings=True,
        ).structural_findings
    )


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        """
def fn(x):
    if x == 1:
        y = 1
        return y
    elif x == 2:
        y = 2
        return y
""",
        pytest.param(
            """
def fn(x):
    match x:
        case 1:
            y = x
            return y
        case 2:
            y = x
            return y
""",
            marks=pytest.mark.skipif(
                sys.version_info < (3, 10), reason="match/case requires Python 3.10+"
            ),
            id="match_case",
        ),
    ],
    ids=["if_elif_chain", "match_case_chain"],
)
def test_detects_identical_branch_families(source: str) -> None:
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].finding_kind == "duplicated_branches"
    assert len(groups[0].items) == 2


def test_no_finding_single_arm() -> None:
    source = """
def fn(x):
    if x == 1:
        return 1
"""
    groups = _findings(source)
    assert groups == []


def test_no_finding_pass_only_branch() -> None:
    source = """
def fn(x):
    if x == 1:
        pass
    elif x == 2:
        pass
"""
    groups = _findings(source)
    assert groups == []


def test_no_finding_empty_body() -> None:
    source = """
def fn():
    pass
"""
    groups = _findings(source)
    assert groups == []


def test_single_statement_return_branches_are_filtered() -> None:
    source = """
def fn(x):
    if x == 1:
        return 1
    elif x == 2:
        return 2
"""
    groups = _findings(source)
    assert groups == []


def test_single_statement_call_branch_is_filtered_as_trivial() -> None:
    source = """
def fn(x):
    if x == 1:
        warn("a")
    elif x == 2:
        warn("b")
"""
    groups = _findings(source)
    assert groups == []


def test_single_statement_try_branch_still_counts_as_meaningful() -> None:
    source = """
def fn(x):
    if x == 1:
        try:
            warn("a")
        except RuntimeError:
            recover("a")
    elif x == 2:
        try:
            warn("b")
        except RuntimeError:
            recover("b")
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert len(groups[0].items) == 2


def test_multi_statement_guard_exit_branch_still_counts_as_meaningful() -> None:
    source = """
def fn(x):
    if x == 1:
        note("a")
        return None
    elif x == 2:
        note("b")
        return None
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert len(groups[0].items) == 2


def test_homogeneous_trivial_multi_statement_branch_is_filtered() -> None:
    source = """
def fn(x):
    if x == 1:
        left = 1
        right = 2
    elif x == 2:
        left = 3
        right = 4
"""
    groups = _findings(source)
    assert groups == []


def test_single_statement_raise_else_branch_is_filtered() -> None:
    source = """
def fn(x):
    if x > 0:
        raise ValueError("a")
    else:
        raise ValueError("b")
"""
    groups = _findings(source)
    assert groups == []


def test_different_signatures_no_group() -> None:
    """Different branch shapes should NOT form a group."""
    source = """
def fn(x):
    if x == 1:
        return x
    elif x == 2:
        raise ValueError("nope")
"""
    groups = _findings(source)
    assert groups == []


# ---------------------------------------------------------------------------
# Signature components
# ---------------------------------------------------------------------------


def test_terminal_return_none() -> None:
    source = """
def fn(x):
    if x == 1:
        y = 1
        return
    elif x == 2:
        y = 2
        return
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["terminal"] == "return_none"


def test_terminal_return_const() -> None:
    source = """
def fn(x):
    if x == 1:
        y = x
        return 42
    elif x == 2:
        y = x + 1
        return 99
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["terminal"] == "return_const"


def test_terminal_return_name() -> None:
    source = """
def fn(x, y):
    if x:
        z = y
        return y
    elif not x:
        z = y
        return y
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["terminal"] == "return_name"


def test_terminal_return_expr() -> None:
    source = """
def fn(x):
    if x == 1:
        y = x
        return x + 1
    elif x == 2:
        y = x
        return x - 1
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["terminal"] == "return_expr"


def test_nested_if_flag() -> None:
    source = """
def fn(x):
    if x == 1:
        if x > 0:
            pass
        return x
    elif x == 2:
        if x > 0:
            pass
        return x
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["nested_if"] == "1"


def test_has_loop_flag() -> None:
    source = """
def fn(x):
    if x == 1:
        for i in range(x):
            pass
        return x
    elif x == 2:
        for i in range(x):
            pass
        return x
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["has_loop"] == "1"


def test_has_try_flag() -> None:
    source = """
def fn(x):
    if x == 1:
        try:
            pass
        except Exception:
            pass
        return x
    elif x == 2:
        try:
            pass
        except Exception:
            pass
        return x
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["has_try"] == "1"


def test_calls_bucketed_zero() -> None:
    source = """
def fn(x):
    if x == 1:
        y = x + 1
        return y
    elif x == 2:
        y = x - 1
        return y
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["calls"] == "0"


def test_calls_bucketed_one() -> None:
    source = """
def fn(x):
    if x == 1:
        foo()
        return x
    elif x == 2:
        bar()
        return x
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["calls"] == "1"


def test_calls_bucketed_two_plus() -> None:
    source = """
def fn(x):
    if x == 1:
        foo()
        bar()
        return x
    elif x == 2:
        baz()
        qux()
        return x
"""
    groups = _findings(source)
    assert len(groups) == 1
    assert groups[0].signature["calls"] == "2+"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_finding_key_stable() -> None:
    source = """
def fn(x):
    if x == 1:
        y = 1
        return y
    elif x == 2:
        y = 2
        return y
"""
    groups_a = _findings(source)
    groups_b = _findings(source)
    assert groups_a[0].finding_key == groups_b[0].finding_key


def test_ordering_stable() -> None:
    """Groups sorted by (-count, finding_key) — consistent across calls."""
    source = """
def fn(x):
    if x == 1:
        y = 1
        return y
    elif x == 2:
        y = 2
        return y
    elif x == 3:
        y = 3
        return y
"""
    groups_a = _findings(source)
    groups_b = _findings(source)
    assert [g.finding_key for g in groups_a] == [g.finding_key for g in groups_b]


def test_item_line_ranges_correct() -> None:
    source = """
def fn(x):
    if x == 1:
        y = 1
        return y
    elif x == 2:
        y = 2
        return y
"""
    groups = _findings(source)
    assert len(groups) == 1
    items = sorted(groups[0].items, key=lambda o: o.start)
    assert items[0].start > 0
    assert items[1].start > items[0].start


def test_qualname_and_filepath_set() -> None:
    source = """
def fn(x):
    if x == 1:
        y = 1
        return y
    elif x == 2:
        y = 2
        return y
"""
    groups = _findings(source, qualname="mymod:fn")
    assert groups[0].items[0].qualname == "mymod:fn"
    assert groups[0].items[0].file_path == "mod.py"


# ---------------------------------------------------------------------------
# match/case (Python 3.10+)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.version_info < (3, 10), reason="match/case requires Python 3.10+"
)
def test_match_case_no_finding_different_body() -> None:
    source = """
def fn(x):
    match x:
        case 1:
            return 1
        case 2:
            raise ValueError("x")
"""
    groups = _findings(source)
    assert groups == []
