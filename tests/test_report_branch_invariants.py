# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.models import StructuralFindingGroup, StructuralFindingOccurrence
from codeclone.report.explain_contract import (
    BLOCK_HINT_ASSERT_ONLY,
    BLOCK_PATTERN_REPEATED_STMT_HASH,
)
from codeclone.report.findings import (
    _dedupe_items,
    _finding_scope_text,
)
from codeclone.report.html.sections._structural import (
    _finding_matters_html,
    _finding_why_template_html,
    _occurrences_table_html,
)
from codeclone.report.html.widgets.snippets import _FileCache
from codeclone.report.overview import _health_snapshot
from codeclone.report.renderers.markdown import (
    _append_findings_section,
    _append_metric_items,
    _location_text,
)
from codeclone.report.renderers.markdown import (
    _as_float as _markdown_as_float,
)
from codeclone.report.renderers.sarif import _result_properties
from codeclone.report.suggestions import (
    _clone_steps,
    _clone_summary,
    _structural_summary,
    structural_action_steps,
)
from tests._assertions import assert_contains_all


def _occurrence(
    *,
    qualname: str,
    start: int,
    end: int,
    file_path: str = "/repo/codeclone/codeclone/cache.py",
) -> StructuralFindingOccurrence:
    return StructuralFindingOccurrence(
        finding_kind="duplicated_branches",
        finding_key="k",
        file_path=file_path,
        qualname=qualname,
        start=start,
        end=end,
        signature={"stmt_seq": "Expr,Return", "terminal": "return"},
    )


def _group(
    *,
    key: str,
    signature: dict[str, str],
    items: tuple[StructuralFindingOccurrence, ...],
) -> StructuralFindingGroup:
    return StructuralFindingGroup(
        finding_kind="duplicated_branches",
        finding_key=key,
        signature=signature,
        items=items,
    )


def test_clone_summary_and_steps_cover_branch_kinds() -> None:
    assert _clone_summary(kind="function", clone_type="Type-4", facts={}) == (
        "same structural function body"
    )
    assert (
        _clone_summary(
            kind="block",
            clone_type="Type-4",
            facts={"hint": BLOCK_HINT_ASSERT_ONLY},
        )
        == "same assertion template"
    )
    assert (
        _clone_summary(
            kind="block",
            clone_type="Type-4",
            facts={"pattern": BLOCK_PATTERN_REPEATED_STMT_HASH},
        )
        == "same repeated setup/assert pattern"
    )
    assert _clone_steps(
        kind="block",
        clone_type="Type-4",
        facts={"hint": BLOCK_HINT_ASSERT_ONLY},
    )[0].startswith("Collapse the repeated assertion template")


def test_structural_summary_and_steps_cover_all_terminal_paths() -> None:
    raise_group = _group(
        key="raise",
        signature={"terminal": "raise", "stmt_seq": "Expr,Raise"},
        items=(_occurrence(qualname="pkg:a", start=1, end=2),) * 2,
    )
    return_group = _group(
        key="return",
        signature={"terminal": "return", "stmt_seq": "Expr,Return"},
        items=(_occurrence(qualname="pkg:a", start=3, end=4),) * 2,
    )
    loop_group = _group(
        key="loop",
        signature={"has_loop": "1", "stmt_seq": "For,Expr"},
        items=(_occurrence(qualname="pkg:a", start=5, end=7),) * 2,
    )
    shape_group = _group(
        key="shape",
        signature={"stmt_seq": "Assign,Expr"},
        items=(_occurrence(qualname="pkg:a", start=8, end=9),) * 2,
    )
    fallback_group = _group(
        key="fallback",
        signature={},
        items=(_occurrence(qualname="pkg:a", start=10, end=11),) * 2,
    )
    guard_div_group = StructuralFindingGroup(
        finding_kind="clone_guard_exit_divergence",
        finding_key="guard-div",
        signature={"cohort_id": "fp|20-49"},
        items=(_occurrence(qualname="pkg:a", start=12, end=13),),
    )
    drift_group = StructuralFindingGroup(
        finding_kind="clone_cohort_drift",
        finding_key="cohort-drift",
        signature={"cohort_id": "fp|20-49"},
        items=(_occurrence(qualname="pkg:a", start=14, end=15),),
    )
    continue_group = _group(
        key="continue",
        signature={"terminal": "fallthrough", "stmt_seq": "Continue"},
        items=(_occurrence(qualname="pkg:a", start=16, end=16),) * 2,
    )

    assert _structural_summary(raise_group)[1] == (
        "same repeated guard/validation branch"
    )
    assert _structural_summary(return_group)[1] == "same repeated return branch"
    assert _structural_summary(loop_group)[1] == "same repeated loop branch"
    assert _structural_summary(shape_group)[1] == (
        "same repeated branch shape (Assign,Expr)"
    )
    assert _structural_summary(fallback_group)[1] == "same repeated branch shape"
    assert _structural_summary(guard_div_group)[0] == "Clone guard/exit divergence"
    assert _structural_summary(drift_group)[0] == "Clone cohort drift"

    assert structural_action_steps(raise_group)[0].startswith(
        "Factor the repeated validation/guard path"
    )
    assert structural_action_steps(return_group)[0].startswith(
        "Consolidate the repeated return-path logic"
    )
    assert structural_action_steps(guard_div_group)[0].startswith(
        "Compare divergent clone members"
    )
    assert structural_action_steps(drift_group)[0].startswith(
        "Review whether cohort drift is intentional"
    )
    assert structural_action_steps(continue_group)[0].startswith(
        "Review whether the repeated continue guard can be merged"
    )


def test_findings_occurrence_table_scope_and_dedupe_invariants() -> None:
    duplicate = _occurrence(qualname="pkg.mod:f", start=10, end=12)
    deduped = _dedupe_items(
        (
            duplicate,
            duplicate,
            _occurrence(qualname="pkg.mod:g", start=20, end=22),
        )
    )
    assert len(deduped) == 2

    table_html = _occurrences_table_html(
        (
            _occurrence(qualname="pkg.mod:f", start=1, end=2),
            _occurrence(qualname="pkg.mod:f", start=3, end=4),
            _occurrence(qualname="pkg.mod:f", start=5, end=6),
            _occurrence(qualname="pkg.mod:f", start=7, end=8),
            _occurrence(qualname="pkg.mod:g", start=9, end=10),
        ),
        scan_root="/repo/codeclone",
        visible_limit=4,
    )
    assert "Show 1 more occurrences" in table_html
    assert (
        _finding_scope_text(
            (
                _occurrence(qualname="pkg.mod:f", start=1, end=2),
                _occurrence(qualname="pkg.mod:g", start=3, end=4),
            )
        )
        == "across 2 functions in 1 file"
    )


def test_finding_matters_message_depends_on_scope_and_terminal() -> None:
    cross_function_items = (
        _occurrence(qualname="pkg.mod:f", start=1, end=2),
        _occurrence(qualname="pkg.mod:g", start=3, end=4),
    )
    assert "repeats across 2 functions and 1 files" in _finding_matters_html(
        _group(
            key="cross",
            signature={"terminal": "expr", "stmt_seq": "Expr,Expr"},
            items=cross_function_items,
        ),
        cross_function_items,
    )

    local_items = (
        _occurrence(qualname="pkg.mod:f", start=10, end=12),
        _occurrence(qualname="pkg.mod:f", start=20, end=22),
    )
    assert "repeated guard or validation exits" in _finding_matters_html(
        _group(
            key="raise",
            signature={"terminal": "raise", "stmt_seq": "If,Raise"},
            items=local_items,
        ),
        local_items,
    )
    assert "repeated return-path logic" in _finding_matters_html(
        _group(
            key="return",
            signature={"terminal": "return", "stmt_seq": "Expr,Return"},
            items=local_items,
        ),
        local_items,
    )


def test_structural_why_template_covers_new_kind_reasoning_paths() -> None:
    guard_group = StructuralFindingGroup(
        finding_kind="clone_guard_exit_divergence",
        finding_key="guard-div",
        signature={
            "cohort_id": "fp-a|20-49",
            "majority_guard_count": "2",
        },
        items=(
            _occurrence(qualname="pkg.mod:a", start=10, end=12),
            _occurrence(qualname="pkg.mod:b", start=20, end=22),
        ),
    )
    drift_group = StructuralFindingGroup(
        finding_kind="clone_cohort_drift",
        finding_key="cohort-drift",
        signature={
            "cohort_id": "fp-a|20-49",
            "cohort_arity": "4",
            "drift_fields": "terminal_kind,guard_exit_profile",
        },
        items=(
            _occurrence(qualname="pkg.mod:c", start=30, end=33),
            _occurrence(qualname="pkg.mod:d", start=40, end=43),
        ),
    )

    guard_html = _finding_why_template_html(
        guard_group,
        guard_group.items,
        file_cache=_FileCache(),
        context_lines=1,
        max_snippet_lines=20,
    )
    drift_html = _finding_why_template_html(
        drift_group,
        drift_group.items,
        file_cache=_FileCache(),
        context_lines=1,
        max_snippet_lines=20,
    )

    assert_contains_all(
        guard_html,
        "clone cohort members with guard/exit divergence",
        "majority guard count",
    )
    assert_contains_all(
        drift_html,
        "cohort members that drift from majority profile",
        "Drift fields",
    )


def test_markdown_helpers_cover_non_numeric_and_missing_fact_paths() -> None:
    assert _markdown_as_float(object()) == 0.0
    assert (
        _location_text(
            {
                "relative_path": "a.py",
                "start_line": 10,
                "end_line": 10,
                "qualname": "pkg:a",
            }
        )
        == "`a.py:10` :: `pkg:a`"
    )

    lines: list[str] = []
    _append_findings_section(
        lines,
        groups=(
            {
                "id": "clone:function:k",
                "family": "clone",
                "category": "function",
                "kind": "clone_group",
                "severity": "warning",
                "confidence": "high",
                "priority": 1.0,
                "source_scope": {
                    "dominant_kind": "production",
                    "impact_scope": "runtime",
                },
                "spread": {"files": 1, "functions": 1},
                "count": 1,
                "items": [
                    {
                        "relative_path": "code/a.py",
                        "start_line": 1,
                        "end_line": 1,
                        "qualname": "pkg:a",
                    }
                ],
            },
        ),
    )
    rendered = "\n".join(lines)
    assert "Presentation facts" not in rendered

    metric_lines: list[str] = []
    _append_metric_items(
        metric_lines,
        items=({"qualname": "pkg:a", "cyclomatic_complexity": 21},),
        key_order=("qualname", "cyclomatic_complexity"),
    )
    assert "pkg:a" in "\n".join(metric_lines)


def test_overview_and_sarif_branch_invariants() -> None:
    health = _health_snapshot(
        {
            "health": {
                "score": 88,
                "grade": "B",
                "dimensions": {"coverage": 90, "complexity": "bad"},
            }
        }
    )
    assert health["strongest_dimension"] == "coverage"
    assert health["weakest_dimension"] == "coverage"

    props = _result_properties(
        {
            "id": "dead_code:pkg.mod:unused",
            "family": "dead_code",
            "category": "function",
            "kind": "unused_symbol",
            "severity": "warning",
            "confidence": "high",
            "priority": 1.0,
            "source_scope": {"impact_scope": "runtime", "dominant_kind": "production"},
            "spread": {"files": 1, "functions": 1},
            "facts": {},
        }
    )
    assert props["confidence"] == "high"
