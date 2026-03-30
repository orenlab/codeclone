# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from codeclone.contracts import (
    CACHE_VERSION,
    DOCS_URL,
    ISSUES_URL,
    REPORT_SCHEMA_VERSION,
    REPOSITORY_URL,
)
from codeclone.errors import FileProcessingError
from codeclone.html_report import (
    _FileCache,
    _pygments_css,
    _render_code_block,
    _try_pygments,
)
from codeclone.html_report import (
    build_html_report as _core_build_html_report,
)
from codeclone.models import (
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Suggestion,
)
from codeclone.report import build_block_group_facts
from codeclone.report.json_contract import (
    build_report_document,
    clone_group_id,
    structural_group_id,
)
from codeclone.report.serialize import render_json_report_document
from tests._report_fixtures import (
    REPEATED_ASSERT_SOURCE,
    repeated_block_group_key,
)
from tests._report_fixtures import (
    REPEATED_STMT_HASH as _REPEATED_STMT_HASH,
)

_REPEATED_BLOCK_GROUP_KEY = repeated_block_group_key()


def to_json_report(
    func_groups: dict[str, list[dict[str, Any]]],
    block_groups: dict[str, list[dict[str, Any]]],
    segment_groups: dict[str, list[dict[str, Any]]],
) -> str:
    payload = build_report_document(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
    )
    return render_json_report_document(payload)


def build_html_report(
    *,
    func_groups: dict[str, list[dict[str, Any]]],
    block_groups: dict[str, list[dict[str, Any]]],
    segment_groups: dict[str, list[dict[str, Any]]],
    block_group_facts: dict[str, dict[str, str]] | None = None,
    **kwargs: Any,
) -> str:
    resolved_block_group_facts = (
        block_group_facts
        if block_group_facts is not None
        else build_block_group_facts(block_groups)
    )
    return _core_build_html_report(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_group_facts=resolved_block_group_facts,
        **kwargs,
    )


def _assert_html_contains(html: str, *needles: str) -> None:
    for needle in needles:
        assert needle in html


def _coupling_metrics_payload(coupled_classes: list[str]) -> dict[str, object]:
    payload = _metrics_payload(
        health_score=70,
        health_grade="B",
        complexity_max=1,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=1,
        dead_total=0,
        dead_critical=0,
    )
    coupling = payload["coupling"]
    assert isinstance(coupling, dict)
    classes = coupling["classes"]
    assert isinstance(classes, list)
    classes[0]["coupled_classes"] = coupled_classes
    return payload


def _render_metrics_html(payload: dict[str, object]) -> str:
    return build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=payload,
    )


def _dependency_metrics_payload(
    *,
    edge_list: list[dict[str, object]],
    longest_chains: list[list[str]],
    dep_cycles: list[list[str]],
    dep_max_depth: int,
) -> dict[str, object]:
    payload = _metrics_payload(
        health_score=70,
        health_grade="B",
        complexity_max=1,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=dep_cycles,
        dep_max_depth=dep_max_depth,
        dead_total=0,
        dead_critical=0,
    )
    deps = payload["dependencies"]
    assert isinstance(deps, dict)
    deps["edge_list"] = edge_list
    deps["longest_chains"] = longest_chains
    return payload


def _repeated_assert_block_groups(
    tmp_path: Path,
    *,
    qualnames: tuple[str, ...] = ("pkg.mod:f",),
) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    test_file = tmp_path / "test_repeated_asserts.py"
    test_file.write_text(REPEATED_ASSERT_SOURCE, "utf-8")
    return _REPEATED_BLOCK_GROUP_KEY, {
        _REPEATED_BLOCK_GROUP_KEY: [
            {
                "qualname": qualname,
                "filepath": str(test_file),
                "start_line": 2,
                "end_line": 5,
            }
            for qualname in qualnames
        ]
    }


def _build_repeated_assert_block_report(
    tmp_path: Path,
    *,
    qualnames: tuple[str, ...] = ("pkg.mod:f",),
    block_group_facts: dict[str, dict[str, str]] | None = None,
    report_meta: dict[str, Any] | None = None,
) -> tuple[str, str]:
    group_key, block_groups = _repeated_assert_block_groups(
        tmp_path, qualnames=qualnames
    )
    kwargs: dict[str, Any] = {}
    if block_group_facts is not None:
        kwargs["block_group_facts"] = block_group_facts
    if report_meta is not None:
        kwargs["report_meta"] = report_meta
    html = build_html_report(
        func_groups={},
        block_groups=block_groups,
        segment_groups={},
        **kwargs,
    )
    return group_key, html


def test_html_report_empty() -> None:
    html = build_html_report(
        func_groups={}, block_groups={}, segment_groups={}, title="Empty Report"
    )
    assert "<!doctype html>" in html
    assert "Empty Report" in html
    assert "No code clones detected" in html


def test_html_report_requires_block_group_facts_argument() -> None:
    with pytest.raises(TypeError):
        _core_build_html_report(
            func_groups={},
            block_groups={},
            segment_groups={},
        )  # type: ignore[call-arg]


def test_html_report_generation(tmp_path: Path) -> None:
    f1 = tmp_path / "a.py"
    f1.write_text("def f1():\n    pass\n", "utf-8")
    f2 = tmp_path / "b.py"
    f2.write_text("def f2():\n    pass\n", "utf-8")

    func_groups = {
        "hash1": [
            {"qualname": "f1", "filepath": str(f1), "start_line": 1, "end_line": 2},
            {"qualname": "f2", "filepath": str(f2), "start_line": 1, "end_line": 2},
        ]
    }

    html = build_html_report(
        func_groups=func_groups,
        block_groups={},
        segment_groups={},
        title="Test Report",
        context_lines=1,
        max_snippet_lines=10,
    )

    _assert_html_contains(html, "Test Report", "f1", "f2", "codebox")


def test_html_report_group_and_item_metadata_attrs(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "hash1": [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title="Attrs",
    )
    _assert_html_contains(
        html,
        'data-group-key="hash1"',
        '<div class="group-name">hash1</div>',
        'data-qualname="pkg.mod:f"',
        'data-filepath="',
        'data-start-line="1"',
        'data-end-line="2"',
    )


def test_html_report_renders_novelty_tabs_and_group_flags(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "known-func": [
                {
                    "qualname": "pkg.mod:known",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ],
            "new-func": [
                {
                    "qualname": "pkg.mod:new",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ],
        },
        block_groups={},
        segment_groups={},
        new_function_group_keys={"new-func"},
        report_meta={"baseline_loaded": True, "baseline_status": "ok"},
    )
    _assert_html_contains(
        html,
        "New duplicates",
        "Known duplicates",
        'id="global-novelty-controls"',
        'data-global-novelty="new"',
        'data-global-novelty="known"',
    )
    assert 'data-novelty-filter="functions"' not in html
    _assert_html_contains(
        html,
        'data-group-key="new-func" data-novelty="new"',
        'data-group-key="known-func" data-novelty="known"',
        "Split is based on baseline",
    )


def test_html_report_renders_untrusted_baseline_novelty_note(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "new-func": [
                {
                    "qualname": "pkg.mod:new",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        new_function_group_keys={"new-func"},
        report_meta={"baseline_loaded": False, "baseline_status": "missing"},
    )
    assert "Baseline is not loaded or not trusted" in html
    assert 'data-group-key="new-func" data-novelty="new"' in html


def test_html_report_renders_block_novelty_tabs_and_group_flags(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={},
        block_groups={
            "known-block": [
                {
                    "qualname": "pkg.mod:known",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 4,
                }
            ],
            "new-block": [
                {
                    "qualname": "pkg.mod:new",
                    "filepath": str(f),
                    "start_line": 5,
                    "end_line": 8,
                }
            ],
        },
        segment_groups={},
        new_block_group_keys={"new-block"},
        report_meta={"baseline_loaded": True, "baseline_status": "ok"},
    )
    assert 'section id="blocks"' in html
    assert 'data-section="blocks" data-has-novelty-filter="true"' in html
    assert 'data-group-key="new-block" data-novelty="new"' in html
    assert 'data-group-key="known-block" data-novelty="known"' in html


def test_html_report_exposes_scope_counter_hooks_for_clone_ui(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "known-func": [
                {
                    "qualname": "pkg.mod:known",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ],
            "new-func": [
                {
                    "qualname": "pkg.mod:new",
                    "filepath": str(f),
                    "start_line": 3,
                    "end_line": 4,
                }
            ],
        },
        block_groups={
            "known-block": [
                {
                    "qualname": "pkg.mod:block",
                    "filepath": str(f),
                    "start_line": 5,
                    "end_line": 8,
                }
            ]
        },
        segment_groups={},
        new_function_group_keys={"new-func"},
        report_meta={"baseline_loaded": True, "baseline_status": "ok"},
    )
    _assert_html_contains(
        html,
        "data-main-clones-count",
        'data-clone-tab-count="functions"',
        'data-clone-tab-count="blocks"',
        'data-total-groups="2"',
        "updateCloneScopeCounters",
    )


def test_html_report_structural_findings_tab_uses_normalized_groups() -> None:
    meaningful_sig = {
        "calls": "0",
        "has_loop": "1",
        "has_try": "0",
        "nested_if": "0",
        "raises": "0",
        "stmt_seq": "Expr,For",
        "terminal": "fallthrough",
    }
    trivial_sig = {
        "calls": "2+",
        "has_loop": "0",
        "has_try": "0",
        "nested_if": "0",
        "raises": "0",
        "stmt_seq": "Expr",
        "terminal": "expr",
    }
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        structural_findings=[
            StructuralFindingGroup(
                finding_kind="duplicated_branches",
                finding_key="a" * 40,
                signature=meaningful_sig,
                items=(
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="a" * 40,
                        file_path="/proj/a.py",
                        qualname="mod:fn",
                        start=10,
                        end=12,
                        signature=meaningful_sig,
                    ),
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="a" * 40,
                        file_path="/proj/a.py",
                        qualname="mod:fn",
                        start=20,
                        end=22,
                        signature=meaningful_sig,
                    ),
                ),
            ),
            StructuralFindingGroup(
                finding_kind="duplicated_branches",
                finding_key="b" * 40,
                signature=trivial_sig,
                items=(
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="b" * 40,
                        file_path="/proj/a.py",
                        qualname="mod:fn",
                        start=30,
                        end=30,
                        signature=trivial_sig,
                    ),
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="b" * 40,
                        file_path="/proj/a.py",
                        qualname="mod:fn",
                        start=40,
                        end=40,
                        signature=trivial_sig,
                    ),
                ),
            ),
        ],
    )
    _assert_html_contains(
        html,
        'data-tab="structural-findings"',
        ">1</span>",
        "Repeated non-overlapping branch-body shapes",
        "1 function",
    )
    assert "stmt seq" in html and "Expr,For" in html
    assert "stmt_seq=Expr</span>" not in html


def test_html_report_structural_findings_why_modal_renders_examples(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def fn(x):\n"
        "    if x == 1:\n"
        '        warn("a")\n'
        "        return None\n"
        "    elif x == 2:\n"
        '        warn("b")\n'
        "        return None\n",
        "utf-8",
    )
    sig = {
        "calls": "1",
        "has_loop": "0",
        "has_try": "0",
        "nested_if": "0",
        "raises": "0",
        "stmt_seq": "Expr,Return",
        "terminal": "return_const",
    }
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        structural_findings=[
            StructuralFindingGroup(
                finding_kind="duplicated_branches",
                finding_key="c" * 40,
                signature=sig,
                items=(
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="c" * 40,
                        file_path=str(sample),
                        qualname="pkg.mod:fn",
                        start=3,
                        end=4,
                        signature=sig,
                    ),
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key="c" * 40,
                        file_path=str(sample),
                        qualname="pkg.mod:fn",
                        start=6,
                        end=7,
                        signature=sig,
                    ),
                ),
            )
        ],
        context_lines=0,
        max_snippet_lines=20,
    )
    for needle in (
        'data-finding-why-btn="finding-why-template-cccc',
        'id="finding-why-modal"',
        "Finding Details",
        "Examples",
        "Example A",
        "Example B",
        "warn",
        "codebox",
    ):
        assert needle in html


def test_html_report_finding_cards_expose_stable_anchor_ids(tmp_path: Path) -> None:
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("def alpha():\n    return 1\n", "utf-8")
    f2.write_text("def beta():\n    return 1\n", "utf-8")
    clone_key = "pkg.mod:dup"
    finding_key = "anchor-key"
    html = build_html_report(
        func_groups={
            clone_key: [
                {
                    "qualname": "pkg.mod:alpha",
                    "filepath": str(f1),
                    "start_line": 1,
                    "end_line": 2,
                },
                {
                    "qualname": "pkg.mod:beta",
                    "filepath": str(f2),
                    "start_line": 1,
                    "end_line": 2,
                },
            ]
        },
        block_groups={},
        segment_groups={},
        structural_findings=[
            StructuralFindingGroup(
                finding_kind="duplicated_branches",
                finding_key=finding_key,
                signature={
                    "calls": "1",
                    "has_loop": "0",
                    "has_try": "0",
                    "nested_if": "0",
                    "raises": "0",
                    "stmt_seq": "Expr,Return",
                    "terminal": "return_const",
                },
                items=(
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key=finding_key,
                        file_path=str(f1),
                        qualname="pkg.mod:alpha",
                        start=1,
                        end=2,
                        signature={"stmt_seq": "Expr,Return"},
                    ),
                    StructuralFindingOccurrence(
                        finding_kind="duplicated_branches",
                        finding_key=finding_key,
                        file_path=str(f2),
                        qualname="pkg.mod:beta",
                        start=1,
                        end=2,
                        signature={"stmt_seq": "Expr,Return"},
                    ),
                ),
            )
        ],
    )
    clone_id = clone_group_id("function", clone_key)
    finding_id = structural_group_id("duplicated_branches", finding_key)
    _assert_html_contains(
        html,
        f'id="finding-{clone_id}"',
        f'id="finding-{finding_id}"',
        f'data-finding-id="{finding_id}"',
    )


def test_html_report_block_group_includes_match_basis_and_compact_key() -> None:
    group_key = _REPEATED_BLOCK_GROUP_KEY
    html = build_html_report(
        func_groups={},
        block_groups={
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": __file__,
                    "start_line": 1,
                    "end_line": 4,
                }
            ]
        },
        segment_groups={},
    )
    _assert_html_contains(
        html,
        'data-match-rule="normalized_sliding_window"',
        'data-block-size="4"',
        'data-signature-kind="stmt_hash_sequence"',
        'data-merged-regions="true"',
        'data-pattern="repeated_stmt_hash"',
        f"{_REPEATED_STMT_HASH[:12]} x4",
    )


def test_html_report_block_group_includes_assert_only_explanation(
    tmp_path: Path,
) -> None:
    _group_key, html = _build_repeated_assert_block_report(tmp_path)
    assert 'data-hint="assert_only"' in html
    assert 'data-hint-confidence="deterministic"' in html
    assert 'data-assert-ratio="100%"' in html
    assert 'data-consecutive-asserts="4"' in html
    assert "Assert pattern block" in html
    assert 'data-metrics-btn="blocks-1"' in html


def test_html_report_block_group_n_way_compare_hint(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path,
        qualnames=("pkg.mod:f1", "pkg.mod:f2", "pkg.mod:f3"),
    )
    assert "N-way group: each block matches 2 peers in this group." in html
    assert "instance 1/3 • matches 2 peers" in html
    assert "instance 2/3 • matches 2 peers" in html
    assert "instance 3/3 • matches 2 peers" in html
    assert 'data-group-arity="3"' in html


def test_html_report_uses_core_block_group_facts(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path,
        block_group_facts={
            _REPEATED_BLOCK_GROUP_KEY: {
                "match_rule": "core_contract",
                "block_size": "99",
                "signature_kind": "core_signature",
                "merged_regions": "false",
                "hint": "assert_only",
                "hint_confidence": "deterministic",
                "assert_ratio": "7%",
                "consecutive_asserts": "1",
                "hint_note": "Facts are owned by core.",
            }
        },
    )
    assert 'data-match-rule="core_contract"' in html
    assert 'data-block-size="99"' in html
    assert 'data-signature-kind="core_signature"' in html
    assert 'data-merged-regions="false"' in html
    assert 'data-assert-ratio="7%"' in html
    assert 'data-consecutive-asserts="1"' in html


def test_html_report_uses_core_hint_and_pattern_labels(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path,
        block_group_facts={
            _REPEATED_BLOCK_GROUP_KEY: {
                "pattern": "internal_pattern_id",
                "pattern_label": "readable pattern",
                "hint": "internal_hint_id",
                "hint_label": "readable hint",
            }
        },
    )
    assert "pattern: readable pattern" in html
    assert "hint: readable hint" in html
    assert 'data-pattern-label="readable pattern"' in html
    assert 'data-hint-label="readable hint"' in html


def test_html_report_uses_core_hint_context_label(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path,
        block_group_facts={
            _REPEATED_BLOCK_GROUP_KEY: {
                "hint": "assert_only",
                "hint_context_label": "Likely test boilerplate / repeated asserts",
            }
        },
    )
    assert "Likely test boilerplate / repeated asserts" in html
    assert (
        'data-hint-context-label="Likely test boilerplate / repeated asserts"' in html
    )


def test_html_report_blocks_without_explanation_meta(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path, block_group_facts={}
    )
    assert '<div class="group-explain"' not in html
    assert 'data-group-arity="1"' in html


def test_html_report_respects_sparse_core_block_facts(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path,
        report_meta={
            "baseline_path": "   ",
            "cache_path": "/",
            "baseline_status": "ok",
        },
        block_group_facts={
            _REPEATED_BLOCK_GROUP_KEY: {
                "match_rule": "core_sparse",
                "pattern": "repeated_stmt_hash",
                "hint": "assert_only",
                "hint_confidence": "deterministic",
            }
        },
    )
    assert 'data-match-rule="core_sparse"' in html
    assert 'data-pattern="repeated_stmt_hash"' in html
    assert 'data-block-size="' not in html
    assert 'data-signature-kind="' not in html
    assert 'data-assert-ratio="' not in html
    assert 'data-consecutive-asserts="' not in html


def test_html_report_handles_root_only_baseline_path() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"baseline_path": "/", "cache_path": "/"},
    )
    assert 'data-baseline-file=""' in html


def test_html_report_explanation_without_match_rule(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path,
        block_group_facts={
            _REPEATED_BLOCK_GROUP_KEY: {
                "hint": "assert_only",
                "hint_confidence": "deterministic",
            }
        },
    )
    assert 'data-hint="assert_only"' in html
    assert "match_rule:" not in html


def test_html_report_n_way_group_without_compare_note(tmp_path: Path) -> None:
    _group_key, html = _build_repeated_assert_block_report(
        tmp_path,
        qualnames=("pkg.mod:f1", "pkg.mod:f2", "pkg.mod:f3"),
        block_group_facts={
            _REPEATED_BLOCK_GROUP_KEY: {
                "group_arity": "3",
                "instance_peer_count": "2",
            }
        },
    )
    assert 'data-group-arity="3"' in html
    assert '<div class="group-compare-note">' not in html


def test_html_report_topbar_actions_present() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    assert "Report Provenance" in html
    assert "data-prov-open" in html
    assert 'class="theme-toggle"' in html
    assert 'title="Toggle theme"' in html
    assert "Theme</button>" in html
    assert "Export Report" not in html
    assert "Open Help" not in html
    assert 'id="help-modal"' not in html


def test_html_report_mobile_topbar_reflows_brand_block() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    _assert_html_contains(
        html,
        "@media(max-width:768px){",
        ".topbar{position:static}",
        ".topbar-inner{height:auto;",
        ".brand-meta{display:none}",
        ".main-tabs-wrap{position:sticky;top:0;",
        ".main-tab{flex:none;",
    )


def test_html_report_narrow_kpi_cards_keep_badges_inside_card() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    _assert_html_contains(
        html,
        "@media(max-width:520px){",
        (
            ".overview-kpi-cards .meta-item{grid-template-rows:auto auto auto;"
            "align-content:start;"
        ),
        ".overview-kpi-cards .kpi-detail{align-self:start}",
        (
            ".overview-kpi-cards .kpi-micro{max-width:100%;white-space:normal;"
            "overflow-wrap:anywhere}"
        ),
    )


def test_html_report_table_css_matches_rendered_column_classes() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    _assert_html_contains(
        html,
        ".table-wrap{display:block;inline-size:100%;max-inline-size:100%;min-inline-size:0;overflow-x:auto;",
        ".table{inline-size:max-content;min-inline-size:100%;border-collapse:collapse;",
        (
            ".table .col-file,.table .col-path{color:var(--text-muted);"
            "max-width:240px;overflow:hidden;"
        ),
        (
            ".table .col-number,.table .col-num{font-variant-numeric:"
            "tabular-nums;text-align:right;white-space:nowrap}"
        ),
        ".table .col-risk,.table .col-badge,.table .col-cat{white-space:nowrap}",
    )


def test_html_report_footer_links_present() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    assert f'href="{REPOSITORY_URL}"' in html
    assert f'href="{ISSUES_URL}"' in html
    assert f'href="{DOCS_URL}"' in html
    assert 'target="_blank" rel="noopener"' in html


def test_html_report_includes_provenance_metadata(
    tmp_path: Path,
    report_meta_factory: Callable[..., dict[str, object]],
) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": "f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        report_meta=report_meta_factory(
            codeclone_version="1.3.0",
            baseline_schema_version=1,
        ),
    )
    expected = [
        "Report Provenance",
        "CodeClone",
        "Report generated (UTC)",
        "Baseline file",
        "Baseline path",
        "Baseline schema",
        "Baseline generator version",
        "Baseline payload sha256",
        "Baseline payload verified",
        "codeclone.baseline.json",
        'data-baseline-status="ok"',
        'data-baseline-payload-verified="true"',
        'data-baseline-file="codeclone.baseline.json"',
        'data-report-generated-at-utc="2026-03-10T12:00:00Z"',
        "/repo/codeclone.baseline.json",
        'data-cache-used="true"',
        "Cache schema",
        "Cache status",
        f'data-cache-schema-version="{CACHE_VERSION}"',
        'data-cache-status="ok"',
        'data-files-skipped-source-io="0"',
        "Source IO skipped",
    ]
    for token in expected:
        assert token in html
    assert "Generated at 2026-03-10T12:00:00Z" in html
    assert "generated 2026-03-10T12:00:00Z" not in html
    assert "deterministic render" not in html


def test_html_report_provenance_summary_uses_card_like_badges(
    report_meta_factory: Callable[..., dict[str, object]],
) -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta=report_meta_factory(
            baseline_schema_version=2,
            baseline_fingerprint_version=1,
        ),
    )
    _assert_html_contains(
        html,
        'class="prov-badge prov-badge--green"',
        'class="prov-badge prov-badge--neutral"',
        '<span class="prov-badge-val">verified</span>',
        '<span class="prov-badge-lbl">Baseline</span>',
        f'<span class="prov-badge-val">{REPORT_SCHEMA_VERSION}</span>',
        '<span class="prov-badge-lbl">Schema</span>',
        '<span class="prov-badge-val">1</span>',
        '<span class="prov-badge-lbl">Fingerprint</span>',
    )


def test_html_report_escapes_meta_and_title(
    tmp_path: Path,
    report_meta_factory: Callable[..., dict[str, object]],
) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": "f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title='<img src=x onerror="alert(1)">',
        report_meta=report_meta_factory(
            baseline_path='"/><script>alert(1)</script>',
            cache_path='x" onmouseover="alert(1)',
        ),
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert (
        'data-baseline-path="&quot;/&gt;&lt;script&gt;alert(1)&lt;/script&gt;"' in html
    )
    assert 'data-cache-path="x&quot; onmouseover=&quot;alert(1)"' in html


def test_html_report_escapes_script_breakout_payload(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    payload = "</script><script>alert(1)</script>"
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": payload,
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        report_meta={"baseline_path": payload},
        title=payload,
    )
    assert "</script><script>" not in html
    assert "&lt;/script&gt;&lt;script&gt;" in html


def test_html_report_deterministic_group_order(tmp_path: Path) -> None:
    a_file = tmp_path / "a.py"
    b_file = tmp_path / "b.py"
    a_file.write_text("def a():\n    return 1\n", "utf-8")
    b_file.write_text("def b():\n    return 2\n", "utf-8")
    func_groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": str(b_file),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": str(a_file),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
    }
    html = build_html_report(
        func_groups=func_groups,
        block_groups={},
        segment_groups={},
    )
    a_idx = html.find('data-group-key="a"')
    b_idx = html.find('data-group-key="b"')
    assert a_idx != -1
    assert b_idx != -1
    assert a_idx < b_idx


def test_html_and_json_group_order_consistent(tmp_path: Path) -> None:
    a_file = tmp_path / "a.py"
    b_file = tmp_path / "b.py"
    c_file = tmp_path / "c.py"
    a_file.write_text("def a():\n    return 1\n", "utf-8")
    b_file.write_text("def b():\n    return 1\n", "utf-8")
    c_file.write_text("def c():\n    return 1\n", "utf-8")
    groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": str(b_file),
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": str(a_file),
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "c": [
            {
                "qualname": "c1",
                "filepath": str(c_file),
                "start_line": 1,
                "end_line": 2,
            },
            {
                "qualname": "c2",
                "filepath": str(c_file),
                "start_line": 1,
                "end_line": 2,
            },
        ],
    }
    html = build_html_report(func_groups=groups, block_groups={}, segment_groups={})
    json_report = json.loads(to_json_report(groups, {}, {}))
    json_keys = [
        row["id"] for row in json_report["findings"]["groups"]["clones"]["functions"]
    ]
    assert json_keys == ["clone:function:c", "clone:function:a", "clone:function:b"]
    assert html.find('data-group-key="c"') < html.find('data-group-key="a"')
    assert html.find('data-group-key="a"') < html.find('data-group-key="b"')


def test_html_report_escapes_control_chars_in_payload(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n", "utf-8")
    qualname = "q`</div>\u2028\u2029"
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": qualname,
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
    )
    _assert_html_contains(
        html,
        "&lt;/div&gt;",
        "&#96;",
        "&#8232;",
        "&#8233;",
    )


def test_file_cache_reads_ranges(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text("\n".join([f"line{i}" for i in range(1, 21)]), "utf-8")

    cache = _FileCache(maxsize=4)
    lines = cache.get_lines_range(str(f), 5, 8)

    assert lines == ("line5", "line6", "line7", "line8")
    assert cache.cache_info().hits == 0
    lines2 = cache.get_lines_range(str(f), 5, 8)
    assert lines2 == lines
    assert cache.cache_info().hits == 1


def test_file_cache_missing_file(tmp_path: Path) -> None:
    cache = _FileCache(maxsize=2)
    missing = tmp_path / "missing.py"
    with pytest.raises(FileProcessingError):
        cache.get_lines_range(str(missing), 1, 2)


def test_html_report_missing_source_snippet_fallback(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    html = build_html_report(
        func_groups={
            "h1": [
                {
                    "qualname": "f",
                    "filepath": str(missing),
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title="Missing Source",
    )
    assert "Missing Source" in html
    assert "Source file unavailable" in html


def test_file_cache_unicode_fallback(tmp_path: Path) -> None:
    f = tmp_path / "bad.py"
    f.write_bytes(b"\xff\xfe\xff\n")
    cache = _FileCache(maxsize=2)
    lines = cache.get_lines_range(str(f), 1, 2)
    assert len(lines) == 1


def test_file_cache_range_bounds(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", "utf-8")
    cache = _FileCache(maxsize=2)
    lines = cache.get_lines_range(str(f), 0, 0)
    assert lines == ()
    lines2 = cache.get_lines_range(str(f), -3, 1)
    assert len(lines2) == 1


def test_render_code_block_truncate(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("\n".join([f"line{i}" for i in range(1, 50)]), "utf-8")
    html = build_html_report(
        func_groups={
            "h": [
                {
                    "qualname": "f",
                    "filepath": str(f),
                    "start_line": 1,
                    "end_line": 40,
                    "loc": 40,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        title="Truncate",
        context_lines=10,
        max_snippet_lines=5,
    )
    assert "Truncate" in html


def test_pygments_css() -> None:
    css = _pygments_css("default")
    assert ".codebox" in css or css == ""


def test_pygments_css_invalid_style() -> None:
    css = _pygments_css("no-such-style")
    assert isinstance(css, str)


def test_pygments_css_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr(importlib, "import_module", _boom)
    assert _pygments_css("default") == ""


def test_try_pygments_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr(importlib, "import_module", _boom)
    assert _try_pygments("x = 1") is None


def test_try_pygments_ok() -> None:
    result = _try_pygments("x = 1")
    assert result is None or isinstance(result, str)


def test_render_code_block_without_pygments_uses_escaped_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import codeclone._html_snippets as snippets

    src = tmp_path / "a.py"
    src.write_text("x = '<tag>'\n", "utf-8")
    monkeypatch.setattr(snippets, "_try_pygments", lambda _raw: None)
    snippet = _render_code_block(
        filepath=str(src),
        start_line=1,
        end_line=1,
        file_cache=_FileCache(),
        context=0,
        max_lines=10,
    )
    assert "&lt;tag&gt;" in snippet.code_html
    assert 'class="hitline"' in snippet.code_html


def test_html_report_with_blocks(tmp_path: Path) -> None:
    f1 = tmp_path / "a.py"
    f1.write_text("def f1():\n    pass\n", "utf-8")
    f2 = tmp_path / "b.py"
    f2.write_text("def f2():\n    pass\n", "utf-8")

    block_groups = {
        "h1": [
            {
                "qualname": "f1",
                "filepath": str(f1),
                "start_line": 1,
                "end_line": 2,
                "size": 4,
            },
            {
                "qualname": "f2",
                "filepath": str(f2),
                "start_line": 1,
                "end_line": 2,
                "size": 4,
            },
        ]
    }
    html = build_html_report(
        func_groups={},
        block_groups=block_groups,
        segment_groups={},
        title="Blocks",
    )
    assert "Block clones" in html


def test_html_report_pygments_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import codeclone.html_report as hr

    def _fake_css(name: str) -> str:
        if name in ("github-dark", "github-light"):
            return ""
        return "x"

    monkeypatch.setattr(hr, "_pygments_css", _fake_css)
    html = build_html_report(
        func_groups={}, block_groups={}, segment_groups={}, title="Pygments"
    )
    assert "Pygments" in html


def test_html_report_segments_section(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    x = 1\n    y = 2\n", "utf-8")
    segment_groups = {
        "s1|mod:f": [
            {
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            },
            {
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
        ]
    }
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups=segment_groups,
        title="Segments",
    )
    assert "Segment clones" in html


def test_html_report_single_item_group(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("def f():\n    x = 1\n", "utf-8")
    segment_groups = {
        "s1|mod:f": [
            {
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ]
    }
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups=segment_groups,
        title="Segments",
    )
    assert f"{f}:1-2" in html


def test_render_code_block_truncates_and_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "a.py"
    f.write_text("\n".join([f"line{i}" for i in range(1, 30)]), "utf-8")

    import codeclone.html_report as hr

    monkeypatch.setattr(hr, "_try_pygments", lambda _text: None)
    cache = _FileCache(maxsize=2)
    snippet = hr._render_code_block(
        filepath=str(f),
        start_line=1,
        end_line=20,
        file_cache=cache,
        context=5,
        max_lines=5,
    )
    assert "codebox" in snippet.code_html


def test_pygments_css_get_style_defs_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Fmt:
        def get_style_defs(self, _selector: str) -> str:
            raise RuntimeError("nope")

    class _Mod:
        HtmlFormatter = _Fmt

    monkeypatch.setattr(importlib, "import_module", lambda _name: _Mod)
    assert _pygments_css("default") == ""


def test_pygments_css_formatter_init_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Fmt:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError("nope")

    class _Mod:
        HtmlFormatter = _Fmt

    monkeypatch.setattr(importlib, "import_module", lambda _name: _Mod)
    assert _pygments_css("default") == ""


def _metrics_payload(
    *,
    health_score: object,
    health_grade: object,
    complexity_max: object,
    complexity_high_risk: object,
    coupling_high_risk: object,
    cohesion_low: object,
    dep_cycles: list[list[str]],
    dep_max_depth: object,
    dead_total: object,
    dead_critical: object,
    dead_suppressed: object = 0,
) -> dict[str, object]:
    suppressed_items: list[dict[str, object]] = []
    if isinstance(dead_suppressed, int) and dead_suppressed > 0:
        suppressed_items = [
            {
                "qualname": "pkg.mod:suppressed_unused",
                "filepath": "/outside/project/pkg/mod.py",
                "start_line": 70,
                "end_line": 71,
                "kind": "function",
                "confidence": "high",
                "suppressed_by": [{"rule": "dead-code", "source": "inline_codeclone"}],
            }
        ]
    return {
        "complexity": {
            "functions": [
                {
                    "qualname": "pkg.mod.func",
                    "filepath": "/outside/project/pkg/mod.py",
                    "start_line": 10,
                    "end_line": 40,
                    "cyclomatic_complexity": complexity_max,
                    "nesting_depth": 3,
                    "risk": "mystery",
                },
                {
                    "qualname": "",
                    "filepath": "/outside/project/pkg/empty.py",
                    "start_line": 1,
                    "end_line": 1,
                    "cyclomatic_complexity": 1,
                    "nesting_depth": 0,
                    "risk": "low",
                },
            ],
            "summary": {
                "total": 2,
                "average": 2.5,
                "max": complexity_max,
                "high_risk": complexity_high_risk,
            },
        },
        "coupling": {
            "classes": [
                {
                    "qualname": "pkg.mod.Service",
                    "filepath": "/outside/project/pkg/mod.py",
                    "start_line": 1,
                    "end_line": 80,
                    "cbo": 9,
                    "risk": "warning",
                }
            ],
            "summary": {
                "total": 1,
                "average": 9.0,
                "max": 9,
                "high_risk": coupling_high_risk,
            },
        },
        "cohesion": {
            "classes": [
                {
                    "qualname": "pkg.mod.Service",
                    "filepath": "/outside/project/pkg/mod.py",
                    "start_line": 1,
                    "end_line": 80,
                    "lcom4": 4,
                    "risk": "high",
                    "method_count": 5,
                    "instance_var_count": 2,
                }
            ],
            "summary": {
                "total": 1,
                "average": 4.0,
                "max": 4,
                "low_cohesion": cohesion_low,
            },
        },
        "dependencies": {
            "modules": 4,
            "edges": 4,
            "max_depth": dep_max_depth,
            "cycles": dep_cycles,
            "longest_chains": [["pkg.a", "pkg.b", "pkg.c"]],
            "edge_list": [
                {
                    "source": "pkg.a",
                    "target": "pkg.b",
                    "import_type": "import",
                    "line": 1,
                },
                {
                    "source": "pkg.b",
                    "target": "pkg.c",
                    "import_type": "import",
                    "line": 2,
                },
                {
                    "source": "pkg.c",
                    "target": "pkg.d",
                    "import_type": "import",
                    "line": 3,
                },
            ],
        },
        "dead_code": {
            "items": [
                {
                    "qualname": "pkg.mod:unused",
                    "filepath": "/outside/project/pkg/mod.py",
                    "start_line": 50,
                    "end_line": 60,
                    "kind": "function",
                    "confidence": "high",
                }
            ],
            "suppressed_items": suppressed_items,
            "summary": {
                "total": dead_total,
                "critical": dead_critical,
                "suppressed": dead_suppressed,
            },
        },
        "health": {
            "score": health_score,
            "grade": health_grade,
            "dimensions": {"coverage": 99},
        },
    }


def test_html_report_metrics_warn_branches_and_dependency_svg() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/repo"},
        metrics=_metrics_payload(
            health_score=70,
            health_grade="B",
            complexity_max=25,
            complexity_high_risk=1,
            coupling_high_risk=1,
            cohesion_low=0,
            dep_cycles=[],
            dep_max_depth=9,
            dead_total=2,
            dead_critical=0,
        ),
    )
    assert "insight-warn" in html
    assert "dep-graph-svg" in html
    assert "Grade B" in html
    assert "pkg.mod.func" in html
    assert "outside/project/pkg/mod.py" in html


def test_html_report_metrics_risk_branches() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=_metrics_payload(
            health_score="50",
            health_grade="C",
            complexity_max=55,
            complexity_high_risk=3,
            coupling_high_risk=2,
            cohesion_low=2,
            dep_cycles=[["pkg.a", "pkg.b"]],
            dep_max_depth=4,
            dead_total=5,
            dead_critical=2,
        ),
    )
    assert "insight-risk" in html
    assert 'stroke="var(--error)"' in html
    assert "Cycles: 1; max dependency depth: 4." in html
    assert "5 candidates total; 2 high-confidence items; 0 suppressed." in html
    assert 'Dead Code<span class="tab-count">2</span>' in html


def test_html_report_metrics_without_health_score_uses_info_overview() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=_metrics_payload(
            health_score=" ",
            health_grade="n/a",
            complexity_max="bad",
            complexity_high_risk=True,
            coupling_high_risk=False,
            cohesion_low=False,
            dep_cycles=[],
            dep_max_depth="bad",
            dead_total="2",
            dead_critical="0",
        ),
    )
    assert "metrics were skipped for this run" not in html
    assert (
        "clone groups; 2 dead-code items (0 suppressed); 0 dependency cycles." in html
    )
    assert "High Complexity" in html
    assert '<span class="kpi-micro-val">2.5</span>' in html
    assert '<span class="kpi-micro-lbl">avg</span>' in html


def test_html_report_renders_directory_hotspots_from_canonical_report() -> None:
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo/project", "project_name": "project"},
        metrics={
            "dead_code": {
                "summary": {"count": 6, "critical": 6},
                "items": [
                    {
                        "qualname": f"pkg.dir{index}:unused",
                        "filepath": f"/repo/project/dir{index}/mod.py",
                        "start_line": 1,
                        "end_line": 2,
                        "kind": "function",
                        "confidence": "high",
                    }
                    for index in range(1, 7)
                ],
            }
        },
    )
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta=cast("dict[str, Any]", report_document["meta"]),
        metrics=cast("dict[str, Any]", report_document["metrics"]),
        report_document=report_document,
    )
    _assert_html_contains(
        html,
        "Hotspots by Directory",
        "top 5 of 6 directories",
        "<code>dir1</code>",
        "<code>dir5</code>",
    )


def test_html_report_direct_path_skips_directory_hotspots_cluster() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=_metrics_payload(
            health_score=70,
            health_grade="B",
            complexity_max=1,
            complexity_high_risk=0,
            coupling_high_risk=0,
            cohesion_low=0,
            dep_cycles=[],
            dep_max_depth=0,
            dead_total=0,
            dead_critical=0,
        ),
    )
    assert "Hotspots by Directory" not in html


def test_html_report_metrics_bad_health_score_and_dead_code_ok_tone() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=_metrics_payload(
            health_score="bad",
            health_grade="n/a",
            complexity_max=1,
            complexity_high_risk=0,
            coupling_high_risk=0,
            cohesion_low=0,
            dep_cycles=[],
            dep_max_depth=0,
            dead_total=0,
            dead_critical=0,
        ),
    )
    assert "Health 0/100 (n/a);" in html
    assert "0 candidates total; 0 high-confidence items; 0 suppressed." in html
    assert "insight-ok" in html


def test_html_report_metrics_bool_health_score_and_long_dependency_labels() -> None:
    payload = _metrics_payload(
        health_score=True,
        health_grade="F",
        complexity_max=1,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=1,
        dead_total=0,
        dead_critical=0,
    )
    deps = payload["dependencies"]
    assert isinstance(deps, dict)
    deps["edge_list"] = [
        {
            "source": "pkg.really_long_module_name_source",
            "target": "pkg.really_long_module_name_target",
            "import_type": "import",
            "line": 1,
        }
    ]
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=payload,
    )
    assert "really_l..e_target" in html


def test_html_report_renders_dead_code_split_with_suppressed_layer() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=_metrics_payload(
            health_score=90,
            health_grade="A",
            complexity_max=1,
            complexity_high_risk=0,
            coupling_high_risk=0,
            cohesion_low=0,
            dep_cycles=[],
            dep_max_depth=0,
            dead_total=0,
            dead_critical=0,
            dead_suppressed=9,
        ),
    )
    _assert_html_contains(
        html,
        "0 candidates total; 0 high-confidence items; 9 suppressed.",
        'data-subtab-group="dead-code"',
        'data-clone-tab="active" data-subtab-group="dead-code"',
        'data-clone-tab="suppressed" data-subtab-group="dead-code"',
        'Suppressed <span class="tab-count">9</span>',
        "inline_codeclone",
        "dead-code",
    )


def test_html_report_metrics_object_health_score_uses_float_fallback() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=_metrics_payload(
            health_score={"bad": "value"},
            health_grade="n/a",
            complexity_max=1,
            complexity_high_risk=0,
            coupling_high_risk=0,
            cohesion_low=0,
            dep_cycles=[],
            dep_max_depth=1,
            dead_total=0,
            dead_critical=0,
        ),
    )
    assert "Health 0/100 (n/a);" in html


def test_html_report_coupling_coupled_classes_inline_for_three_or_less() -> None:
    html = _render_metrics_html(_coupling_metrics_payload(["Alpha", "Beta", "Gamma"]))
    _assert_html_contains(
        html,
        '<span class="chain-flow">',
        '<span class="chain-node" title="Alpha">Alpha</span>',
        '<span class="chain-node" title="Beta">Beta</span>',
        '<span class="chain-node" title="Gamma">Gamma</span>',
    )
    assert "(+1 more)" not in html


def test_html_report_coupling_coupled_classes_expands_for_more_than_three() -> None:
    html = _render_metrics_html(
        _coupling_metrics_payload(["Alpha", "Beta", "Gamma", "Delta"])
    )
    _assert_html_contains(
        html,
        '<details class="coupled-details">',
        '<summary class="coupled-summary">',
        '<span class="chain-node" title="Alpha">Alpha</span>',
        '<span class="chain-node" title="Beta">Beta</span>',
        '<span class="chain-node" title="Delta">Delta</span>',
        '<span class="chain-node" title="Gamma">Gamma</span>',
    )
    assert "(+1 more)" in html


def test_html_report_coupling_coupled_classes_truncates_long_labels() -> None:
    long_name = "pkg.mod.VeryLongClassNameSegmentXYZ12345"
    html = _render_metrics_html(_coupling_metrics_payload([long_name]))
    label = "VeryLongClassNameSegmentXYZ12345"
    assert f"{label[:8]}..{label[-8:]}" in html


def test_html_report_dependency_graph_handles_rootless_and_disconnected_nodes() -> None:
    html = _render_metrics_html(
        _dependency_metrics_payload(
            edge_list=[
                {
                    "source": "pkg.a",
                    "target": "pkg.b",
                    "import_type": "import",
                    "line": 1,
                },
                {
                    "source": "pkg.c",
                    "target": "pkg.d",
                    "import_type": "import",
                    "line": 2,
                },
                {
                    "source": "pkg.d",
                    "target": "pkg.c",
                    "import_type": "import",
                    "line": 3,
                },
            ],
            longest_chains=[["pkg.a", "pkg.b"]],
            dep_cycles=[["pkg.c", "pkg.d"]],
            dep_max_depth=4,
        )
    )
    _assert_html_contains(
        html,
        'data-node="pkg.c"',
        'data-node="pkg.d"',
        "dep-graph-svg",
    )


def test_html_report_dependency_graph_rootless_fallback_seed() -> None:
    html = _render_metrics_html(
        _dependency_metrics_payload(
            edge_list=[
                {
                    "source": "pkg.c",
                    "target": "pkg.d",
                    "import_type": "import",
                    "line": 1,
                },
                {
                    "source": "pkg.d",
                    "target": "pkg.c",
                    "import_type": "import",
                    "line": 2,
                },
            ],
            longest_chains=[["pkg.c", "pkg.d"]],
            dep_cycles=[["pkg.c", "pkg.d"]],
            dep_max_depth=2,
        )
    )
    _assert_html_contains(html, 'data-node="pkg.c"', 'data-node="pkg.d"')


def test_html_report_provenance_badges_cover_mismatch_and_untrusted_metrics() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={
            "baseline_loaded": False,
            "baseline_payload_sha256_verified": False,
            "baseline_generator_name": "other-generator",
            "metrics_baseline_loaded": True,
            "metrics_baseline_payload_sha256_verified": False,
            "cache_used": None,
            "analysis_mode": "full",
            "report_schema_version": "2.0",
            "baseline_fingerprint_version": "1",
        },
    )
    _assert_html_contains(
        html,
        '<span class="prov-badge-val">missing</span>',
        '<span class="prov-badge-lbl">Baseline</span>',
        '<span class="prov-badge-val">other-generator</span>',
        '<span class="prov-badge-lbl">Generator mismatch</span>',
        '<span class="prov-badge-val">untrusted</span>',
        '<span class="prov-badge-lbl">Metrics baseline</span>',
        '<span class="prov-badge-val">N/A</span>',
        '<span class="prov-badge-lbl">Cache</span>',
    )


def test_html_report_provenance_handles_non_boolean_baseline_loaded() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={
            "baseline_loaded": "unknown",
            "baseline_payload_sha256_verified": False,
            "report_schema_version": "2.0",
        },
    )
    _assert_html_contains(
        html,
        '<span class="prov-badge-val">2.0</span>',
        '<span class="prov-badge-lbl">Schema</span>',
    )
    assert '<span class="prov-badge-lbl">Baseline</span>' not in html


def test_html_report_dependency_hubs_deterministic_tie_order() -> None:
    html = _render_metrics_html(
        _dependency_metrics_payload(
            edge_list=[
                {
                    "source": "mod.gamma",
                    "target": "mod.hub",
                    "import_type": "import",
                    "line": 1,
                },
                {
                    "source": "mod.alpha",
                    "target": "mod.hub",
                    "import_type": "import",
                    "line": 2,
                },
                {
                    "source": "mod.beta",
                    "target": "mod.hub",
                    "import_type": "import",
                    "line": 3,
                },
            ],
            longest_chains=[["mod.alpha", "mod.hub"]],
            dep_cycles=[],
            dep_max_depth=2,
        )
    )
    hub_pos = html.find('dep-hub-name">hub</span><span class="dep-hub-deg">3')
    alpha_pos = html.find('dep-hub-name">alpha</span><span class="dep-hub-deg">1')
    beta_pos = html.find('dep-hub-name">beta</span><span class="dep-hub-deg">1')
    gamma_pos = html.find('dep-hub-name">gamma</span><span class="dep-hub-deg">1')
    assert hub_pos != -1
    assert alpha_pos != -1
    assert beta_pos != -1
    assert gamma_pos != -1
    assert hub_pos < alpha_pos < beta_pos < gamma_pos


def test_html_report_dependency_chain_columns_render_html() -> None:
    payload = _metrics_payload(
        health_score=70,
        health_grade="B",
        complexity_max=1,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[["pkg.a", "pkg.b", "pkg.c"]],
        dep_max_depth=3,
        dead_total=0,
        dead_critical=0,
    )
    deps = payload["dependencies"]
    assert isinstance(deps, dict)
    deps["longest_chains"] = [["pkg.root", "pkg.mid", "pkg.leaf"]]

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=payload,
    )
    assert '<span class="chain-flow">' in html
    assert "&lt;span class=&quot;chain-flow&quot;&gt;" not in html


def test_html_report_bare_qualname_keeps_non_python_path_prefix() -> None:
    html = build_html_report(
        func_groups={
            "q1": [
                {
                    "qualname": "pkg.mod.txt.",
                    "filepath": "/repo/pkg/mod.txt",
                    "start_line": 1,
                    "end_line": 1,
                }
            ]
        },
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/repo"},
    )
    assert "pkg.mod.txt." in html


def test_html_report_suggestions_cards_split_facts_assessment_and_action() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/repo"},
        suggestions=(
            Suggestion(
                severity="info",
                category="clone",
                title="Refactor duplicate block",
                location="/repo/pkg/mod.py",
                steps=("Extract helper",),
                effort="easy",
                priority=0.5,
                finding_family="clones",
                fact_kind="Block clone group",
                fact_summary="same repeated setup/assert pattern",
                fact_count=4,
                spread_files=1,
                spread_functions=1,
                clone_type="Type-4",
                confidence="high",
                source_kind="production",
                source_breakdown=(("production", 4),),
            ),
        ),
    )
    assert "Facts" in html
    assert "Assessment" in html
    assert "Suggestion" in html
    assert "Source breakdown" in html
    assert "Refactor duplicate block" in html


def test_html_report_overview_includes_hotspot_sections_without_quick_views() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/repo"},
        metrics=_metrics_payload(
            health_score=87,
            health_grade="B",
            complexity_max=21,
            complexity_high_risk=1,
            coupling_high_risk=0,
            cohesion_low=1,
            dep_cycles=[],
            dep_max_depth=2,
            dead_total=1,
            dead_critical=1,
        ),
        suggestions=(
            Suggestion(
                severity="warning",
                category="clone",
                title="Function clone group (Type-2)",
                location="2 occurrences across 2 files / 2 functions",
                steps=("Extract shared function",),
                effort="easy",
                priority=2.0,
                finding_family="clones",
                fact_kind="Function clone group",
                fact_summary="same parameterized function body",
                fact_count=2,
                spread_files=2,
                spread_functions=2,
                clone_type="Type-2",
                confidence="high",
                source_kind="production",
                source_breakdown=(("production", 2),),
                location_label="2 occurrences across 2 files / 2 functions",
            ),
        ),
    )
    _assert_html_contains(
        html,
        "Executive Summary",
        "Issue breakdown",
        "Source breakdown",
        "Health Profile",
    )
    assert "Most Actionable" not in html
    assert 'data-quick-view="' not in html
    assert 'class="suggestion-context"' in html


def test_html_report_overview_uses_canonical_report_overview_hotlists() -> None:
    structural = (
        StructuralFindingGroup(
            finding_kind="duplicated_branches",
            finding_key="z" * 40,
            signature={
                "stmt_seq": "Expr,Return",
                "terminal": "return",
                "raises": "0",
                "has_loop": "0",
            },
            items=(
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="z" * 40,
                    file_path="/repo/pkg/mod.py",
                    qualname="pkg.mod:fn",
                    start=10,
                    end=12,
                    signature={},
                ),
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="z" * 40,
                    file_path="/repo/pkg/mod.py",
                    qualname="pkg.mod:fn",
                    start=20,
                    end=22,
                    signature={},
                ),
            ),
        ),
    )
    metrics = _metrics_payload(
        health_score=84,
        health_grade="B",
        complexity_max=20,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    payload = build_report_document(
        func_groups={
            "g1": [
                {
                    "qualname": "tests.fixtures.sample:a",
                    "filepath": "/repo/tests/fixtures/sample/a.py",
                    "start_line": 1,
                    "end_line": 20,
                    "loc": 20,
                    "stmt_count": 8,
                    "fingerprint": "fp-a",
                    "loc_bucket": "20-49",
                },
                {
                    "qualname": "tests.fixtures.sample:b",
                    "filepath": "/repo/tests/fixtures/sample/b.py",
                    "start_line": 1,
                    "end_line": 20,
                    "loc": 20,
                    "stmt_count": 8,
                    "fingerprint": "fp-a",
                    "loc_bucket": "20-49",
                },
            ]
        },
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo"},
        metrics=metrics,
        structural_findings=structural,
    )

    html = build_html_report(
        func_groups={
            "g1": [
                {
                    "qualname": "tests.fixtures.sample:a",
                    "filepath": "/repo/tests/fixtures/sample/a.py",
                    "start_line": 1,
                    "end_line": 20,
                    "loc": 20,
                    "stmt_count": 8,
                    "fingerprint": "fp-a",
                    "loc_bucket": "20-49",
                },
                {
                    "qualname": "tests.fixtures.sample:b",
                    "filepath": "/repo/tests/fixtures/sample/b.py",
                    "start_line": 1,
                    "end_line": 20,
                    "loc": 20,
                    "stmt_count": 8,
                    "fingerprint": "fp-a",
                    "loc_bucket": "20-49",
                },
            ]
        },
        block_groups={},
        segment_groups={},
        report_meta=payload["meta"],
        metrics=payload["metrics"],
        structural_findings=structural,
        report_document=payload,
    )

    for needle in (
        "Executive Summary",
        'class="overview-kpi-cards"',
        "Findings",
        "Suggestions",
        "source-kind-badge source-kind-fixtures",
        "source-kind-badge source-kind-production",
        'breakdown-count">1</span>',
    ):
        assert needle in html
    assert '<div class="overview-summary-value">n/a</div>' not in html
    # Issue breakdown replaces old hotspot sections
    assert "Issue breakdown" in html
