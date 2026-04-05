# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Unit tests for codeclone.structural_findings (Phase 1: duplicated_branches)."""

from __future__ import annotations

import ast
import sys
from typing import Any, cast

import pytest

import codeclone.structural_findings as sf
from codeclone import _coerce
from codeclone.models import StructuralFindingGroup, StructuralFindingOccurrence
from codeclone.structural_findings import (
    build_clone_cohort_structural_findings,
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


def _assert_single_group(source: str) -> StructuralFindingGroup:
    groups = _findings(source)
    assert len(groups) == 1
    return groups[0]


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


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            """
def fn(x):
    if x == 1:
        return 1
""",
            id="single_arm",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        pass
    elif x == 2:
        pass
""",
            id="pass_only",
        ),
        pytest.param(
            """
def fn():
    pass
""",
            id="empty_body",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        return 1
    elif x == 2:
        return 2
""",
            id="single_return_branches",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        warn("a")
    elif x == 2:
        warn("b")
""",
            id="single_call_branches",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        left = 1
        right = 2
    elif x == 2:
        left = 3
        right = 4
""",
            id="homogeneous_trivial_multi_stmt",
        ),
        pytest.param(
            """
def fn(x):
    if x > 0:
        raise ValueError("a")
    else:
        raise ValueError("b")
""",
            id="single_raise_else",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        return x
    elif x == 2:
        raise ValueError("nope")
""",
            id="different_signatures",
        ),
    ],
)
def test_non_reportable_branch_patterns_do_not_form_groups(source: str) -> None:
    assert _findings(source) == []


@pytest.mark.parametrize(
    ("source", "expected_items"),
    [
        pytest.param(
            """
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
""",
            2,
            id="single_statement_try_branch",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        note("a")
        return None
    elif x == 2:
        note("b")
        return None
""",
            2,
            id="guard_exit_branch",
        ),
    ],
)
def test_meaningful_branch_patterns_are_retained(
    source: str,
    expected_items: int,
) -> None:
    group = _assert_single_group(source)
    assert len(group.items) == expected_items


# ---------------------------------------------------------------------------
# Signature components
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "signature_key", "expected_value"),
    [
        pytest.param(
            """
def fn(x):
    if x == 1:
        y = 1
        return
    elif x == 2:
        y = 2
        return
""",
            "terminal",
            "return_none",
            id="terminal_return_none",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        y = x
        return 42
    elif x == 2:
        y = x + 1
        return 99
""",
            "terminal",
            "return_const",
            id="terminal_return_const",
        ),
        pytest.param(
            """
def fn(x, y):
    if x:
        z = y
        return y
    elif not x:
        z = y
        return y
""",
            "terminal",
            "return_name",
            id="terminal_return_name",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        y = x
        return x + 1
    elif x == 2:
        y = x
        return x - 1
""",
            "terminal",
            "return_expr",
            id="terminal_return_expr",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        if x > 0:
            pass
        return x
    elif x == 2:
        if x > 0:
            pass
        return x
""",
            "nested_if",
            "1",
            id="nested_if",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        for i in range(x):
            pass
        return x
    elif x == 2:
        for i in range(x):
            pass
        return x
""",
            "has_loop",
            "1",
            id="has_loop",
        ),
        pytest.param(
            """
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
""",
            "has_try",
            "1",
            id="has_try",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        y = x + 1
        return y
    elif x == 2:
        y = x - 1
        return y
""",
            "calls",
            "0",
            id="calls_zero",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        foo()
        return x
    elif x == 2:
        bar()
        return x
""",
            "calls",
            "1",
            id="calls_one",
        ),
        pytest.param(
            """
def fn(x):
    if x == 1:
        foo()
        bar()
        return x
    elif x == 2:
        baz()
        qux()
        return x
""",
            "calls",
            "2+",
            id="calls_two_plus",
        ),
    ],
)
def test_signature_components_are_recorded(
    source: str,
    signature_key: str,
    expected_value: str,
) -> None:
    group = _assert_single_group(source)
    assert group.signature[signature_key] == expected_value


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


def test_scan_function_structure_collects_stable_guard_facts() -> None:
    source = """
def fn(x):
    if not x:
        return 0
    if x < 0:
        raise ValueError("x")
    try:
        y = x + 1
    finally:
        y = x
    return y
"""
    facts = scan_function_structure(
        _parse_fn(source),
        "mod.py",
        "pkg.mod:fn",
        collect_findings=True,
    )
    assert facts.entry_guard_count == 2
    assert facts.entry_guard_terminal_profile == "return_const,raise"
    assert facts.entry_guard_has_side_effect_before is False
    assert facts.terminal_kind == "return_name"
    assert facts.try_finally_profile == "try_finally"
    assert facts.side_effect_order_profile == "guard_then_effect"


def test_build_clone_cohort_structural_findings_emits_new_families() -> None:
    func_groups = {
        "fp-a|20-49": [
            {
                "filepath": "pkg/a.py",
                "qualname": "pkg.a:f1",
                "start_line": 10,
                "end_line": 40,
                "entry_guard_count": 2,
                "entry_guard_terminal_profile": "return_const,raise",
                "entry_guard_has_side_effect_before": False,
                "terminal_kind": "return_const",
                "try_finally_profile": "none",
                "side_effect_order_profile": "guard_then_effect",
            },
            {
                "filepath": "pkg/b.py",
                "qualname": "pkg.b:f1",
                "start_line": 11,
                "end_line": 41,
                "entry_guard_count": 2,
                "entry_guard_terminal_profile": "return_const,raise",
                "entry_guard_has_side_effect_before": False,
                "terminal_kind": "return_const",
                "try_finally_profile": "none",
                "side_effect_order_profile": "guard_then_effect",
            },
            {
                "filepath": "pkg/c.py",
                "qualname": "pkg.c:f1",
                "start_line": 12,
                "end_line": 42,
                "entry_guard_count": 2,
                "entry_guard_terminal_profile": "return_const,raise",
                "entry_guard_has_side_effect_before": False,
                "terminal_kind": "return_const",
                "try_finally_profile": "none",
                "side_effect_order_profile": "guard_then_effect",
            },
            {
                "filepath": "pkg/d.py",
                "qualname": "pkg.d:f1",
                "start_line": 13,
                "end_line": 43,
                "entry_guard_count": 1,
                "entry_guard_terminal_profile": "raise",
                "entry_guard_has_side_effect_before": True,
                "terminal_kind": "raise",
                "try_finally_profile": "try_no_finally",
                "side_effect_order_profile": "effect_before_guard",
            },
        ]
    }
    groups = build_clone_cohort_structural_findings(func_groups=func_groups)
    kinds = {group.finding_kind for group in groups}
    assert "clone_guard_exit_divergence" in kinds
    assert "clone_cohort_drift" in kinds


def test_build_clone_cohort_structural_findings_skips_uniform_groups() -> None:
    func_groups = {
        "fp-a|20-49": [
            {
                "filepath": "pkg/a.py",
                "qualname": "pkg.a:f1",
                "start_line": 10,
                "end_line": 40,
                "entry_guard_count": 2,
                "entry_guard_terminal_profile": "return_const,raise",
                "entry_guard_has_side_effect_before": False,
                "terminal_kind": "return_const",
                "try_finally_profile": "none",
                "side_effect_order_profile": "guard_then_effect",
            },
            {
                "filepath": "pkg/b.py",
                "qualname": "pkg.b:f1",
                "start_line": 11,
                "end_line": 41,
                "entry_guard_count": 2,
                "entry_guard_terminal_profile": "return_const,raise",
                "entry_guard_has_side_effect_before": False,
                "terminal_kind": "return_const",
                "try_finally_profile": "none",
                "side_effect_order_profile": "guard_then_effect",
            },
            {
                "filepath": "pkg/c.py",
                "qualname": "pkg.c:f1",
                "start_line": 12,
                "end_line": 42,
                "entry_guard_count": 2,
                "entry_guard_terminal_profile": "return_const,raise",
                "entry_guard_has_side_effect_before": False,
                "terminal_kind": "return_const",
                "try_finally_profile": "none",
                "side_effect_order_profile": "guard_then_effect",
            },
        ]
    }
    groups = build_clone_cohort_structural_findings(func_groups=func_groups)
    assert groups == ()


def test_private_helper_fallbacks_and_defaults_are_deterministic() -> None:
    assert sf._terminal_kind([]) == "fallthrough"
    assert sf._stmt_names_from_signature({"stmt_seq": ""}) == ()
    assert sf.is_reportable_structural_signature({}) is False
    assert (
        sf.is_reportable_structural_signature(
            {"stmt_seq": "Lambda,Assign", "terminal": "assign"},
        )
        is True
    )
    assert sf._kind_min_occurrence_count("unknown_kind") == 2
    assert sf._summarize_branch([]) is None
    assert sf._guard_profile_text(count=0, terminal_profile="raise") == "none"

    if_node = ast.parse("if x:\n    value = 1\n").body[0]
    is_guard, terminal = sf._is_guard_exit_if(if_node)
    assert is_guard is False
    assert terminal == "none"

    signature = {
        "stmt_seq": "Expr",
        "terminal": "expr",
        "calls": "0",
        "raises": "0",
        "nested_if": "0",
        "has_loop": "0",
        "has_try": "0",
    }
    occurrence = StructuralFindingOccurrence(
        finding_kind="unknown_kind",
        finding_key="unknown-key",
        file_path="a.py",
        qualname="mod:fn",
        start=1,
        end=2,
        signature=signature,
    )
    group = StructuralFindingGroup(
        finding_kind="unknown_kind",
        finding_key="unknown-key",
        signature=signature,
        items=(occurrence,),
    )
    assert sf.normalize_structural_finding_group(group) is None


def test_private_member_decoding_and_majority_defaults() -> None:
    assert _coerce.as_int(True) == 1
    assert _coerce.as_int("bad-int") == 0
    assert sf._as_item_bool(1) is True
    assert sf._as_item_bool("yes") is True
    assert sf._as_item_bool("no") is False
    assert sf._clone_member_from_item({}) is None
    assert sf._majority_value([], default="fallback") == "fallback"
    assert sf._majority_value([], default=7) == 7
    assert sf._majority_value([], default=True) is True

    member = sf._CloneCohortMember(
        file_path="pkg/a.py",
        qualname="pkg.a:f",
        start=1,
        end=2,
        entry_guard_count=0,
        entry_guard_terminal_profile="none",
        entry_guard_has_side_effect_before=False,
        terminal_kind="return_const",
        try_finally_profile="none",
        side_effect_order_profile="none",
    )
    assert sf._member_profile_value(member, "unknown-field") == ""


def test_summarize_branch_does_not_descend_into_nested_scopes() -> None:
    body = ast.parse(
        """
if cond:
    def inner():
        while True:
            helper()
    class Inner:
        def method(self):
            raise RuntimeError("boom")
    value = 1
""",
    ).body
    signature = sf._summarize_branch(body)
    assert signature is not None
    assert signature["calls"] == "0"
    assert signature["raises"] == "0"
    assert signature["has_loop"] == "0"


def test_clone_cohort_builders_cover_early_exit_paths() -> None:
    base_member = sf._CloneCohortMember(
        file_path="pkg/a.py",
        qualname="pkg.a:f",
        start=1,
        end=2,
        entry_guard_count=1,
        entry_guard_terminal_profile="return_const",
        entry_guard_has_side_effect_before=False,
        terminal_kind="return_const",
        try_finally_profile="none",
        side_effect_order_profile="guard_then_effect",
    )
    no_guard_member = sf._CloneCohortMember(
        file_path="pkg/b.py",
        qualname="pkg.b:f",
        start=2,
        end=3,
        entry_guard_count=0,
        entry_guard_terminal_profile="none",
        entry_guard_has_side_effect_before=False,
        terminal_kind="return_const",
        try_finally_profile="none",
        side_effect_order_profile="effect_only",
    )

    assert sf._clone_guard_exit_divergence("c1", (base_member, base_member)) is None
    assert (
        sf._clone_guard_exit_divergence(
            "c2",
            (no_guard_member, no_guard_member, no_guard_member),
        )
        is None
    )
    assert (
        sf._clone_guard_exit_divergence(
            "c3",
            (base_member, base_member, base_member),
        )
        is None
    )

    assert sf._clone_cohort_drift("c4", (base_member, base_member)) is None
    assert sf._clone_cohort_drift("c5", (base_member, base_member, base_member)) is None


def test_scanner_private_paths_cover_collection_and_normalization_branches() -> None:
    scanner = sf._FunctionStructureScanner(
        filepath="pkg/mod.py",
        qualname="pkg.mod:f",
        collect_findings=True,
    )
    reportable_signature = {
        "stmt_seq": "Assign,Return",
        "terminal": "return_name",
        "calls": "0",
        "raises": "0",
        "nested_if": "0",
        "has_loop": "0",
        "has_try": "0",
    }
    trivial_signature = {
        "stmt_seq": "Expr",
        "terminal": "expr",
        "calls": "0",
        "raises": "0",
        "nested_if": "0",
        "has_loop": "0",
        "has_try": "0",
    }
    scanner._sig_to_branches["single"] = [(reportable_signature, 10, 11)]
    scanner._sig_to_branches["trivial"] = [
        (trivial_signature, 12, 12),
        (trivial_signature, 13, 13),
    ]
    assert scanner._build_groups() == []

    if_chain = ast.parse(
        "if x:\n    a = 1\nelif y:\n    b = 2\nelse:\n    pass\n",
    ).body[0]
    assert isinstance(if_chain, ast.If)
    bodies = sf._collect_if_branch_bodies(if_chain)
    assert len(bodies) == 2

    match_stmt = ast.parse(
        "match x:\n    case 1:\n        pass\n    case 2:\n        value = 2\n",
    ).body[0]
    match_bodies = sf._collect_match_branch_bodies(match_stmt)
    assert len(match_bodies) == 1

    iter_scanner = sf._FunctionStructureScanner(
        filepath="pkg/mod.py",
        qualname="pkg.mod:f",
        collect_findings=False,
    )
    for_stmt = ast.parse("for i in xs:\n    pass\nelse:\n    pass\n").body[0]
    with_stmt = ast.parse("with cm:\n    pass\n").body[0]
    try_stmt = ast.parse(
        "try:\n"
        "    pass\n"
        "except Exception:\n"
        "    pass\n"
        "else:\n"
        "    pass\n"
        "finally:\n"
        "    pass\n",
    ).body[0]
    assign_stmt = ast.parse("value = 1\n").body[0]
    assert len(iter_scanner._iter_nested_statement_lists(for_stmt)) == 2
    assert len(iter_scanner._iter_nested_statement_lists(with_stmt)) == 1
    assert len(iter_scanner._iter_nested_statement_lists(try_stmt)) == 4
    assert iter_scanner._iter_nested_statement_lists(assign_stmt) == ()


def test_scan_function_structure_visits_nested_bodies_and_match_without_findings() -> (
    None
):
    class_body_source = """
def fn():
    class Inner:
        value = 1
    return 1
"""
    class_facts = scan_function_structure(
        _parse_fn(class_body_source),
        "mod.py",
        "pkg.mod:fn",
        collect_findings=False,
    )
    assert class_facts.terminal_kind == "return_const"

    match_source = """
def fn(x):
    match x:
        case 1:
            return 1
        case _:
            return 2
"""
    match_facts = scan_function_structure(
        _parse_fn(match_source),
        "mod.py",
        "pkg.mod:fn",
        collect_findings=False,
    )
    assert match_facts.structural_findings == ()


def test_structural_helper_branches_cover_empty_if_chain_and_bool_defaults() -> None:
    if_chain = ast.parse("if flag:\n    pass\n").body[0]
    assert isinstance(if_chain, ast.If)
    assert sf._collect_if_branch_bodies(if_chain) == []
    assert sf._as_item_bool("maybe", default=True) is True
    assert sf._as_item_bool(object(), default=True) is True
    assert sf._group_item_sort_key(
        {
            "filepath": "pkg/mod.py",
            "qualname": "pkg.mod:fn",
            "start_line": 3,
            "end_line": 4,
        }
    ) == ("pkg/mod.py", "pkg.mod:fn", 3, 4)


def test_clone_cohort_findings_skip_invalid_filtered_members() -> None:
    member = {
        "filepath": "pkg/mod.py",
        "qualname": "pkg.mod:fn",
        "start_line": 10,
        "end_line": 12,
        "entry_guard_count": 1,
        "entry_guard_terminal_profile": "return_const",
        "entry_guard_has_side_effect_before": False,
        "terminal_kind": "return_const",
        "try_finally_profile": "none",
        "side_effect_order_profile": "guard_then_effect",
    }
    findings = sf.build_clone_cohort_structural_findings(
        func_groups={
            "cohort-a": (
                member,
                {**member, "qualname": "pkg.mod:fn2", "start_line": 0},
                {**member, "qualname": "pkg.mod:fn3", "end_line": 0},
            )
        }
    )
    assert findings == ()


def test_clone_cohort_guard_and_drift_defensive_none_branches() -> None:
    class _FlakyGuardMember:
        def __init__(self, first_count: int, *, qualname: str) -> None:
            self.file_path = "pkg/mod.py"
            self.qualname = qualname
            self.start = 1
            self.end = 2
            self.entry_guard_terminal_profile = "return_const"
            self.entry_guard_has_side_effect_before = False
            self.terminal_kind = "return_const"
            self.try_finally_profile = "none"
            self.side_effect_order_profile = "guard_then_effect"
            self._first_count = first_count
            self._reads = 0

        @property
        def entry_guard_count(self) -> int:
            self._reads += 1
            return self._first_count if self._reads == 1 else 2

    guard_members = (
        cast(Any, _FlakyGuardMember(1, qualname="pkg.mod:a")),
        cast(Any, _FlakyGuardMember(2, qualname="pkg.mod:b")),
        cast(Any, _FlakyGuardMember(2, qualname="pkg.mod:c")),
    )
    assert sf._clone_guard_exit_divergence("cohort-guard", guard_members) is None

    class _FlakyDriftMember:
        def __init__(self, first_terminal: str, *, qualname: str) -> None:
            self.file_path = "pkg/mod.py"
            self.qualname = qualname
            self.start = 1
            self.end = 2
            self.entry_guard_count = 1
            self.entry_guard_terminal_profile = "return_const"
            self.entry_guard_has_side_effect_before = False
            self.try_finally_profile = "none"
            self.side_effect_order_profile = "guard_then_effect"
            self._first_terminal = first_terminal
            self._reads = 0

        @property
        def terminal_kind(self) -> str:
            self._reads += 1
            return self._first_terminal if self._reads == 1 else "return_const"

        @property
        def guard_exit_profile(self) -> str:
            return "1x:return_const"

    drift_members = (
        cast(Any, _FlakyDriftMember("raise", qualname="pkg.mod:a")),
        cast(Any, _FlakyDriftMember("return_const", qualname="pkg.mod:b")),
        cast(Any, _FlakyDriftMember("return_const", qualname="pkg.mod:c")),
    )
    assert sf._clone_cohort_drift("cohort-drift", drift_members) is None


def test_collect_if_branch_bodies_returns_empty_for_none_like_input() -> None:
    assert sf._collect_if_branch_bodies(cast(Any, None)) == []
