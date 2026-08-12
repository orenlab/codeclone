# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import importlib
import json
import re
from collections.abc import Callable, Mapping
from html import unescape
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeclone.baseline.trust import current_python_tag
from codeclone.contracts import (
    CACHE_VERSION,
    DOCS_URL,
    HEALTH_WEIGHTS,
    ISSUES_URL,
    REPORT_SCHEMA_VERSION,
    REPOSITORY_URL,
)
from codeclone.contracts.errors import FileProcessingError
from codeclone.findings.ids import clone_group_id, structural_group_id
from codeclone.models import (
    LaneTrust,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Suggestion,
    SuppressedCloneGroup,
    TrustVector,
)
from codeclone.observability.vocabulary import COUNTER_KEYS, SPAN_NAMES
from codeclone.report.explain import build_block_group_facts
from codeclone.report.html import (
    build_html_report as _core_build_html_report,
)
from codeclone.report.html.assemble import (
    HTML_BUILD_COUNTER_KEYS,
    HTML_BUILD_SPAN_NAMES,
)
from codeclone.report.html.primitives.location import (
    location_file_target,
    relative_location_path,
)
from codeclone.report.html.sections._module_map import render_module_map_panel
from codeclone.report.html.sections._security_surfaces import (
    _coverage_join_review_text,
    _coverage_review_cues,
    _coverage_review_index,
    _coverage_review_item_key,
    _coverage_review_key,
    _pluralize,
    _review_cell_text,
)
from codeclone.report.html.widgets.badges import _tab_empty_info
from codeclone.report.html.widgets.snippets import (
    _FileCache,
    _pygments_css,
    _render_code_block,
    _try_pygments,
)
from codeclone.report.renderers.json import render_json_report_document
from tests._assertions import assert_contains_all
from tests._report_fixtures import (
    REPEATED_ASSERT_SOURCE,
    repeated_block_group_key,
)
from tests._report_fixtures import (
    REPEATED_STMT_HASH as _REPEATED_STMT_HASH,
)
from tests._report_fixtures import (
    build_test_report_document as build_report_document,
)
from tests._tmp_tree import write_files

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
    return render_json_report_document(payload).decode("utf-8")


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
    provided_document = kwargs.pop("report_document", None)
    new_function_group_keys = kwargs.pop("new_function_group_keys", None)
    new_block_group_keys = kwargs.pop("new_block_group_keys", None)
    report_meta = kwargs.pop("report_meta", None)
    metrics = kwargs.pop("metrics", None)
    suggestions = kwargs.pop("suggestions", None)
    structural_findings = kwargs.pop("structural_findings", None)
    kwargs.pop("metrics_diff", None)
    if report_meta is None:
        location_paths = [
            str(item.get("filepath", ""))
            for groups in (func_groups, block_groups, segment_groups)
            for items in groups.values()
            for item in items
            if Path(str(item.get("filepath", ""))).is_absolute()
        ]
        if location_paths:
            report_meta = {"scan_root": str(Path(location_paths[0]).parent)}
    resolved_report_meta = dict(report_meta or {})
    if metrics is not None and "metrics_computed" not in resolved_report_meta:
        resolved_report_meta["metrics_computed"] = sorted(metrics)
    report_meta = resolved_report_meta
    baseline_is_trusted = bool(
        report_meta
        and report_meta.get("baseline_loaded") is True
        and report_meta.get("baseline_status") == "ok"
    )
    baseline_trust = (
        TrustVector(
            root_verified=baseline_is_trusted,
            lanes=(
                LaneTrust(
                    name="clones.blocks",
                    status="trusted" if baseline_is_trusted else "unavailable",
                    reason=(
                        "compatible" if baseline_is_trusted else "required_contract"
                    ),
                ),
                LaneTrust(
                    name="clones.functions",
                    status="trusted" if baseline_is_trusted else "unavailable",
                    reason=(
                        "compatible" if baseline_is_trusted else "required_contract"
                    ),
                ),
            ),
        )
        if new_function_group_keys is not None or new_block_group_keys is not None
        else None
    )
    report_document = (
        provided_document
        if provided_document is not None
        else build_report_document(
            func_groups=func_groups,
            block_groups=block_groups,
            segment_groups=segment_groups,
            block_facts=resolved_block_group_facts,
            new_function_group_keys=new_function_group_keys,
            new_block_group_keys=new_block_group_keys,
            meta=report_meta,
            metrics=metrics,
            suggestions=suggestions,
            structural_findings=structural_findings,
            baseline_trust=baseline_trust,
        )
    )
    return _core_build_html_report(
        report_document=report_document,
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
        "Per-lane baseline trust: 2 trusted, 7 unavailable.",
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
    assert "Per-lane baseline trust: 0 trusted, 9 unavailable." in html
    assert 'data-group-key="new-func" data-novelty="unavailable"' in html


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
        "Suggested action",
        "Review whether the repeated local branch can be simplified in place.",
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
    f1, f2 = write_files(
        tmp_path,
        ("a.py", "def alpha():\n    return 1\n"),
        ("b.py", "def beta():\n    return 1\n"),
    )
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


def test_html_report_mobile_directory_hotspots_wrap_inside_summary_cards() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    _assert_html_contains(
        html,
        "@media(max-width:768px){",
        ".dir-hotspot-head{flex-wrap:wrap;align-items:flex-start}",
        ".dir-hotspot-detail{flex-wrap:wrap;align-items:flex-start}",
        ".dir-hotspot-bar-track{width:min(148px,42%);min-width:96px}",
        ".dir-hotspot-meta{width:100%}",
    )


def test_html_report_table_css_matches_rendered_column_classes() -> None:
    html = build_html_report(func_groups={}, block_groups={}, segment_groups={})
    _assert_html_contains(
        html,
        ".table-wrap{display:block;inline-size:100%;max-inline-size:100%;min-inline-size:0;overflow-x:auto;",
        # Moved expectation: the table used to be sized to its content, which
        # is the defect this wave closed. min-inline-size already held it to
        # the full wrap, so max-content only ever added the sideways scroll.
        ".table{table-layout:fixed;inline-size:100%;max-inline-size:100%;",
        (
            ".table .col-file,.table .col-path{color:var(--text-muted);"
            "max-width:240px;overflow:hidden;"
        ),
        ".table .col-number,.table .col-num{font-family:var(--font-numeric);",
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
    a_file, b_file = write_files(
        tmp_path,
        ("a.py", "def a():\n    return 1\n"),
        ("b.py", "def b():\n    return 2\n"),
    )
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
    import codeclone.report.html.widgets.snippets as snippets

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
    import codeclone.report.html.widgets.snippets as snippets

    def _fake_css(name: str) -> str:
        if name in ("github-dark", "github-light"):
            return ""
        return "x"

    monkeypatch.setattr(snippets, "_pygments_css", _fake_css)
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


def test_html_report_clone_tab_renders_suppressed_golden_fixture_groups(
    tmp_path: Path,
) -> None:
    fixture_file = tmp_path / "tests" / "fixtures" / "golden_project" / "alpha.py"
    fixture_file_2 = tmp_path / "tests" / "fixtures" / "golden_project" / "beta.py"
    fixture_file.parent.mkdir(parents=True, exist_ok=True)
    fixture_file.write_text("def run():\n    return 1\n", "utf-8")
    fixture_file_2.write_text("def run():\n    return 2\n", "utf-8")

    suppressed_group = SuppressedCloneGroup(
        kind="function",
        group_key="tests.fixtures.golden.alpha:run",
        items=(
            {
                "qualname": "tests.fixtures.golden.alpha:run",
                "filepath": str(fixture_file),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-run",
                "loc_bucket": "0-19",
            },
            {
                "qualname": "tests.fixtures.golden.beta:run",
                "filepath": str(fixture_file_2),
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-run",
                "loc_bucket": "0-19",
            },
        ),
        matched_patterns=("tests/fixtures/golden_*",),
        suppression_rule="golden_fixture",
        suppression_source="project_config",
    )
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(tmp_path)},
        suppressed_clone_groups=(suppressed_group,),
    )

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": str(tmp_path)},
        report_document=report_document,
    )

    assert "Suppressed" in html
    assert "golden_fixture@project_config" in html
    assert "tests/fixtures/golden_*" in html
    assert "No code clones detected" not in html


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

    import codeclone.report.html.widgets.snippets as snippets

    monkeypatch.setattr(snippets, "_try_pygments", lambda _text: None)
    cache = _FileCache(maxsize=2)
    snippet = snippets._render_code_block(
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
    dep_avg_depth: object = 2.5,
    dep_p95_depth: object = 3,
    dead_suppressed: object = 0,
) -> dict[str, object]:
    active_total = (
        int(dead_total)
        if isinstance(dead_total, (int, str))
        and not isinstance(dead_total, bool)
        and str(dead_total).isdigit()
        else 0
    )
    high_confidence_total = (
        int(dead_critical)
        if isinstance(dead_critical, (int, str))
        and not isinstance(dead_critical, bool)
        and str(dead_critical).isdigit()
        else 0
    )
    suppressed_total = (
        int(dead_suppressed)
        if isinstance(dead_suppressed, (int, str))
        and not isinstance(dead_suppressed, bool)
        and str(dead_suppressed).isdigit()
        else 0
    )
    dead_items = [
        {
            "qualname": f"pkg.mod:unused_{index}",
            "filepath": "/outside/project/pkg/mod.py",
            "start_line": 50 + index * 2,
            "end_line": 51 + index * 2,
            "kind": "function",
            "confidence": "high" if index < high_confidence_total else "medium",
        }
        for index in range(active_total)
    ]
    suppressed_items: list[dict[str, object]] = [
        {
            "qualname": f"pkg.mod:suppressed_unused_{index}",
            "filepath": "/outside/project/pkg/mod.py",
            "start_line": 70 + index * 2,
            "end_line": 71 + index * 2,
            "kind": "function",
            "confidence": "high",
            "suppressed_by": [{"rule": "dead-code", "source": "inline_codeclone"}],
        }
        for index in range(suppressed_total)
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
            "avg_depth": dep_avg_depth,
            "p95_depth": dep_p95_depth,
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
            "items": dead_items,
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
        "overloaded_modules": {
            "summary": {
                "total": 1,
                "candidates": 0,
                "population_status": "limited",
                "top_score": 0.0,
                "average_score": 0.0,
                "candidate_score_cutoff": 0.0,
            },
            "items": [],
            "detection": {
                "version": "1",
                "scope": "report_only",
                "strategy": "project_relative_composite",
                "minimum_population": 20,
                "size_signals": ["loc", "callable_count", "complexity_total"],
                "dependency_signals": [
                    "fan_in",
                    "fan_out",
                    "total_deps",
                    "import_edges",
                ],
                "shape_signals": ["hub_balance", "reimport_ratio"],
            },
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
    assert "Cycles: 0; avg depth: 2.5; p95 depth: 3; max dependency depth: 9." in html
    assert "pkg.mod.func" in html
    assert "mod.py" in html


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
    assert_contains_all(
        html,
        "insight-risk",
        'stroke="var(--error)"',
        "Cycles: 1; avg depth: 2.5; p95 depth: 3; max dependency depth: 4.",
        "5 candidates total; 2 high-confidence items; "
        "0 unreachable statement region(s); 0 suppressed.",
        '<button class="main-tab" role="tab" data-tab="dead-code"',
        '<svg class="main-tab-icon"',
        '<span class="main-tab-label">Dead Code</span>'
        '<span class="tab-count" title="2 high-confidence dead-code items">2</span>',
    )


def test_html_report_renders_overloaded_modules_in_module_map_and_overview() -> None:
    payload = _metrics_payload(
        health_score=72,
        health_grade="B",
        complexity_max=25,
        complexity_high_risk=1,
        coupling_high_risk=1,
        cohesion_low=1,
        dep_cycles=[],
        dep_max_depth=4,
        dead_total=1,
        dead_critical=1,
    )
    overloaded_modules = payload["overloaded_modules"]
    assert isinstance(overloaded_modules, dict)
    overloaded_modules["summary"] = {
        "total": 3,
        "candidates": 1,
        "population_status": "ok",
        "top_score": 0.93,
        "average_score": 0.42,
        "candidate_score_cutoff": 0.88,
    }
    overloaded_modules["items"] = [
        {
            "module": "pkg.hub",
            "relative_path": "pkg/hub.py",
            "source_kind": "production",
            "loc": 420,
            "functions": 5,
            "methods": 2,
            "classes": 1,
            "callable_count": 7,
            "complexity_total": 31,
            "complexity_max": 12,
            "fan_in": 4,
            "fan_out": 7,
            "total_deps": 11,
            "import_edges": 9,
            "reimport_edges": 2,
            "reimport_ratio": 0.2222,
            "instability": 0.6364,
            "hub_balance": 0.7273,
            "size_score": 0.95,
            "dependency_score": 0.91,
            "shape_score": 0.8,
            "score": 0.93,
            "candidate_status": "candidate",
            "candidate_reasons": [
                "size_pressure",
                "dependency_pressure",
                "hub_like_shape",
            ],
        },
        {
            "module": "pkg.util",
            "relative_path": "pkg/util.py",
            "source_kind": "production",
            "loc": 120,
            "functions": 2,
            "methods": 0,
            "classes": 0,
            "callable_count": 2,
            "complexity_total": 8,
            "complexity_max": 5,
            "fan_in": 1,
            "fan_out": 2,
            "total_deps": 3,
            "import_edges": 3,
            "reimport_edges": 0,
            "reimport_ratio": 0.0,
            "instability": 0.6667,
            "hub_balance": 0.5,
            "size_score": 0.4,
            "dependency_score": 0.35,
            "shape_score": 0.3,
            "score": 0.75,
            "candidate_status": "ranked_only",
            "candidate_reasons": [],
        },
    ]

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=payload,
    )

    _assert_html_contains(
        html,
        "Overloaded Modules",
        "pkg.hub",
        "Top candidates",
        "0.93",
        "Ranked only",
    )
    assert "hub-like shape" not in html
    assert "Candidate cutoff" not in html
    assert "Ranked modules" not in html
    # Overloaded profile now lives in the Module map tab, not Quality.
    module_map_panel = html.split('id="panel-module-map"', 1)[1].split(
        'id="panel-dependencies"', 1
    )[0]
    assert "Overloaded Modules" in module_map_panel
    assert "0.88" in module_map_panel  # candidate score cutoff
    assert "Critical" not in module_map_panel
    quality_panel = html.split('id="panel-quality"', 1)[1].split(
        'id="panel-module-map"', 1
    )[0]
    assert "Overloaded Modules" not in quality_panel
    assert "overloaded-modules" not in quality_panel


def test_html_report_overloaded_modules_fallback_module_path_in_overview() -> None:
    payload = _metrics_payload(
        health_score=72,
        health_grade="B",
        complexity_max=25,
        complexity_high_risk=1,
        coupling_high_risk=1,
        cohesion_low=1,
        dep_cycles=[],
        dep_max_depth=4,
        dead_total=1,
        dead_critical=1,
    )
    overloaded_modules = payload["overloaded_modules"]
    assert isinstance(overloaded_modules, dict)
    overloaded_modules["summary"] = {
        "total": 1,
        "candidates": 1,
        "population_status": "ok",
        "top_score": 0.93,
        "average_score": 0.93,
        "candidate_score_cutoff": 0.88,
    }
    overloaded_modules["items"] = [
        {
            "module": "pkg.hub",
            "source_kind": "production",
            "loc": 420,
            "complexity_total": 31,
            "fan_in": 4,
            "fan_out": 7,
            "score": 0.93,
            "candidate_status": "candidate",
            "candidate_reasons": ["size_pressure"],
        }
    ]

    html = _render_metrics_html(payload)

    # Path honesty: a row without a resolved path shows its module identity
    # verbatim; the pre-wave fallback invented the phantom "pkg/hub.py".
    _assert_html_contains(html, "pkg.hub", "Overloaded Modules")


def test_html_report_overview_helper_branches() -> None:
    from codeclone.report.html.sections._overview import (
        _directory_kind_meta_parts,
        _format_count,
    )

    assert _directory_kind_meta_parts({"func": 3}, total_groups=10) == []
    assert _directory_kind_meta_parts({"func": 5, "block": 2}, total_groups=5) == []
    meta = _directory_kind_meta_parts({"func": 3, "block": 2}, total_groups=10)
    assert len(meta) == 2
    assert _format_count(1234.5) == "1,234.50"


def test_html_report_overview_shows_partial_baselined_clone_badge(
    tmp_path: Path,
) -> None:
    from codeclone.models import MetricsDiff

    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n", "utf-8")
    clone_item = {
        "qualname": "pkg.mod:fn",
        "filepath": str(source),
        "start_line": 1,
        "end_line": 2,
    }
    html = build_html_report(
        func_groups={"known-func": [clone_item], "new-func": [clone_item]},
        block_groups={},
        segment_groups={},
        new_function_group_keys={"new-func"},
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=0,
        ),
        report_meta={"baseline_loaded": True, "baseline_status": "ok"},
    )

    _assert_html_contains(html, "kpi-micro--baselined", "baselined")


def test_html_report_does_not_alias_legacy_god_modules_key() -> None:
    payload = _metrics_payload(
        health_score=72,
        health_grade="B",
        complexity_max=25,
        complexity_high_risk=1,
        coupling_high_risk=1,
        cohesion_low=1,
        dep_cycles=[],
        dep_max_depth=4,
        dead_total=1,
        dead_critical=1,
    )
    legacy_overloaded_modules = payload.pop("overloaded_modules")
    payload["god_modules"] = legacy_overloaded_modules

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=payload,
    )

    assert "Overloaded Modules" not in html


def test_html_report_renders_run_snapshot_from_canonical_inventory() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo/project", "project_name": "project"},
        metrics=metrics,
        inventory={
            "files": {
                "total_found": 158,
                "analyzed": 120,
                "cached": 38,
                "skipped": 2,
                "source_io_skipped": 1,
            },
            "code": {
                "parsed_lines": 22320,
                "functions": 180,
                "methods": 40,
                "classes": 12,
            },
            "file_list": [
                "/repo/project/pkg/a.py",
                "/repo/project/pkg/b.py",
            ],
        },
    )

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta=report_document["meta"],
        metrics=report_document["metrics"],
        report_document=report_document,
    )

    inventory = cast(dict[str, object], report_document["inventory"])
    files_inventory = cast(dict[str, object], inventory["files"])
    code_inventory = cast(dict[str, object], inventory["code"])
    total_found = cast(int, files_inventory["total_found"])
    parsed_lines = cast(int, code_inventory["parsed_lines"])
    functions = cast(int, code_inventory["functions"])
    methods = cast(int, code_inventory["methods"])
    classes = cast(int, code_inventory["classes"])
    expected_summary = (
        f"{total_found} files \u00b7 "
        f"{parsed_lines:,} lines \u00b7 "
        f"{functions + methods} callables \u00b7 "
        f"{classes} classes"
    )
    _assert_html_contains(
        html,
        "Executive Summary",
        expected_summary,
    )
    assert "Scan scope" not in html


def test_html_report_executive_summary_includes_effective_analysis_profile() -> None:
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={
            "scan_root": "/repo/project",
            "project_name": "project",
            "min_loc": 5,
            "min_stmt": 2,
            "block_min_loc": 8,
            "block_min_stmt": 3,
            "segment_min_loc": 13,
            "segment_min_stmt": 4,
        },
        metrics=_metrics_payload(
            health_score=82,
            health_grade="B",
            complexity_max=12,
            complexity_high_risk=0,
            coupling_high_risk=0,
            cohesion_low=0,
            dep_cycles=[],
            dep_max_depth=2,
            dead_total=0,
            dead_critical=0,
        ),
        inventory={
            "files": {"total_found": 1, "analyzed": 1, "cached": 0, "skipped": 0},
            "code": {"parsed_lines": 20, "functions": 1, "methods": 0, "classes": 0},
            "file_list": ["/repo/project/pkg/a.py"],
        },
    )

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta=report_document["meta"],
        metrics=report_document["metrics"],
        report_document=report_document,
    )

    _assert_html_contains(
        html,
        "Executive Summary",
        "Thresholds: func 5/2 · block 8/3 · seg 13/4",
    )


def test_html_report_overview_includes_adoption_and_api_summary_cluster() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["coverage_adoption"] = {
        "summary": {
            "params_total": 4,
            "params_annotated": 3,
            "param_permille": 750,
            "baseline_diff_available": True,
            "param_delta": 125,
            "returns_total": 2,
            "returns_annotated": 1,
            "return_permille": 500,
            "return_delta": 250,
            "public_symbol_total": 3,
            "public_symbol_documented": 2,
            "docstring_permille": 667,
            "docstring_delta": 167,
            "typing_any_count": 1,
        },
        "items": [],
    }
    metrics["api_surface"] = {
        "summary": {
            "enabled": True,
            "baseline_diff_available": True,
            "modules": 1,
            "public_symbols": 2,
            "added": 1,
            "breaking": 1,
            "strict_types": False,
        },
        "items": [],
    }

    html = _render_metrics_html(metrics)

    _assert_html_contains(
        html,
        "Adoption &amp; API",
        "Adoption coverage",
        "overview-fact-list",
        "Param annotations",
        "75.0%",
        "+12.5pt",
        "Return annotations",
        "50.0%",
        "+25.0pt",
        "Docstrings",
        "66.7%",
        "+16.7pt",
        "Typed as Any",
        "Public API surface",
        "Public symbols",
        "Modules",
        "Breaking changes",
        "Added symbols",
    )


def test_html_report_quality_includes_coverage_join_subtab() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["coverage_join"] = {
        "summary": {
            "status": "ok",
            "source": "/outside/project/coverage.xml",
            "files": 1,
            "units": 2,
            "measured_units": 1,
            "overall_executable_lines": 10,
            "overall_covered_lines": 7,
            "overall_permille": 700,
            "missing_from_report_units": 1,
            "coverage_hotspots": 1,
            "scope_gap_hotspots": 0,
            "hotspot_threshold_percent": 50,
        },
        "items": [
            {
                "relative_path": "pkg/mod.py",
                "qualname": "pkg.mod:run",
                "start_line": 10,
                "end_line": 20,
                "cyclomatic_complexity": 18,
                "risk": "high",
                "executable_lines": 4,
                "covered_lines": 1,
                "coverage_permille": 250,
                "coverage_status": "measured",
                "coverage_hotspot": True,
                "scope_gap_hotspot": False,
            },
            {
                "relative_path": "pkg/other.py",
                "qualname": "pkg.other:skip",
                "start_line": 1,
                "end_line": 4,
                "cyclomatic_complexity": 2,
                "risk": "low",
                "executable_lines": 0,
                "covered_lines": 0,
                "coverage_permille": 0,
                "coverage_status": "missing_from_report",
                "coverage_hotspot": False,
                "scope_gap_hotspot": False,
            },
        ],
    }

    html = _render_metrics_html(metrics)

    _assert_html_contains(
        html,
        'data-subtab-group="quality"',
        'data-clone-tab="coverage-join"',
        "Coverage Join",
        "Status",
        "Joined",
        "Overall coverage",
        "Coverage hotspots",
        "Scope gaps",
        "Measured units",
        "70.0%",
        "coverage.xml",
        "pkg.mod:run",
        "Coverage hotspots: 1; scope gaps: 0.",
    )
    assert (
        '<span class="main-tab-label">Quality</span>'
        '<span class="tab-count" title="1 issues">1</span>' in html
    )


def test_html_report_quality_includes_security_surfaces_subtab() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["security_surfaces"] = {
        "summary": {
            "items": 2,
            "modules": 2,
            "exact_items": 2,
            "category_count": 2,
            "categories": {
                "network_boundary": 1,
                "process_boundary": 1,
            },
            "by_source_kind": {
                "production": 1,
                "tests": 1,
                "fixtures": 0,
                "other": 0,
            },
            "production": 1,
            "tests": 1,
            "fixtures": 0,
            "other": 0,
            "report_only": True,
        },
        "items": [
            {
                "category": "network_boundary",
                "capability": "requests_import",
                "module": "pkg.client",
                "filepath": "pkg/client.py",
                "qualname": "pkg.client",
                "start_line": 1,
                "end_line": 1,
                "source_kind": "production",
                "location_scope": "module",
                "classification_mode": "exact_import",
                "evidence_kind": "import",
                "evidence_symbol": "requests",
            },
            {
                "category": "process_boundary",
                "capability": "subprocess_run",
                "module": "tests.test_cli",
                "filepath": "tests/test_cli.py",
                "qualname": "tests.test_cli:run_case",
                "start_line": 10,
                "end_line": 10,
                "source_kind": "tests",
                "location_scope": "callable",
                "classification_mode": "exact_call",
                "evidence_kind": "call",
                "evidence_symbol": "subprocess.run",
            },
        ],
    }

    html = _render_metrics_html(metrics)

    _assert_html_contains(
        html,
        'data-subtab-group="quality"',
        'data-clone-tab="security-surfaces"',
        '<span class="main-tab-label">Quality</span>'
        '<span class="tab-count" title="2 issues">2</span>',
        "Security Surfaces",
        "How to read",
        "Review order",
        "Security-relevant capability inventory",
        "Surfaces",
        "Categories",
        "Production",
        "Exact items",
        "Network boundary",
        "Process boundary",
        "requests",
        "subprocess.run",
        "pkg/client.py:1",
        "tests/test_cli.py:10",
        "report-only",
        'data-file="/outside/project/pkg/client.py"',
        'data-file="/outside/project/tests/test_cli.py"',
    )


def test_html_report_security_surfaces_add_review_context_and_coverage_overlap() -> (
    None
):
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["security_surfaces"] = {
        "summary": {
            "items": 3,
            "modules": 2,
            "exact_items": 3,
            "category_count": 2,
            "categories": {
                "network_boundary": 1,
                "process_boundary": 2,
            },
            "by_source_kind": {
                "production": 2,
                "tests": 1,
                "fixtures": 0,
                "other": 0,
            },
            "production": 2,
            "tests": 1,
            "fixtures": 0,
            "other": 0,
            "report_only": True,
        },
        "items": [
            {
                "category": "process_boundary",
                "capability": "subprocess_import",
                "module": "pkg.client",
                "filepath": "pkg/client.py",
                "qualname": "pkg.client",
                "start_line": 1,
                "end_line": 1,
                "source_kind": "production",
                "location_scope": "module",
                "classification_mode": "exact_import",
                "evidence_kind": "import",
                "evidence_symbol": "subprocess",
            },
            {
                "category": "process_boundary",
                "capability": "subprocess_run",
                "module": "pkg.client",
                "filepath": "pkg/client.py",
                "qualname": "pkg.client:run_case",
                "start_line": 40,
                "end_line": 44,
                "source_kind": "production",
                "location_scope": "callable",
                "classification_mode": "exact_call",
                "evidence_kind": "call",
                "evidence_symbol": "subprocess.run",
            },
            {
                "category": "network_boundary",
                "capability": "requests_import",
                "module": "tests.test_client",
                "filepath": "tests/test_client.py",
                "qualname": "tests.test_client:exercise_case",
                "start_line": 8,
                "end_line": 12,
                "source_kind": "tests",
                "location_scope": "callable",
                "classification_mode": "exact_import",
                "evidence_kind": "import",
                "evidence_symbol": "requests",
            },
        ],
    }
    metrics["coverage_join"] = {
        "summary": {
            "status": "ok",
            "source": "/outside/project/coverage.xml",
            "files": 1,
            "units": 1,
            "measured_units": 1,
            "overall_executable_lines": 10,
            "overall_covered_lines": 6,
            "overall_permille": 600,
            "missing_from_report_units": 0,
            "coverage_hotspots": 1,
            "scope_gap_hotspots": 0,
            "hotspot_threshold_percent": 50,
        },
        "items": [
            {
                "filepath": "pkg/client.py",
                "qualname": "pkg.client:run_case",
                "start_line": 40,
                "end_line": 44,
                "cyclomatic_complexity": 18,
                "risk": "high",
                "executable_lines": 4,
                "covered_lines": 1,
                "coverage_permille": 250,
                "coverage_status": "measured",
                "coverage_hotspot": True,
                "scope_gap_hotspot": False,
            }
        ],
    }

    html = _render_metrics_html(metrics)

    _assert_html_contains(
        html,
        "How should I review this inventory?",
        "How to read",
        "boundary inventory",
        "exact imports/calls/builtins",
        "inventory, not vulnerability proof",
        "Review order",
        "1 production callable",
        "1 overlap",
        "1 low-coverage overlap",
        "1 module/class inventory row",
        "Review",
        "Module · capability present",
        "Callable · low coverage",
        "Callable · exact evidence",
    )


def test_html_report_security_surfaces_prefers_report_document_family_paths() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["security_surfaces"] = {
        "summary": {
            "items": 1,
            "modules": 1,
            "exact_items": 1,
            "category_count": 1,
            "categories": {"dynamic_loading": 1},
            "by_source_kind": {
                "production": 1,
                "tests": 0,
                "fixtures": 0,
                "other": 0,
            },
            "production": 1,
            "tests": 0,
            "fixtures": 0,
            "other": 0,
            "report_only": True,
        },
        "items": [
            {
                "category": "dynamic_loading",
                "capability": "importlib_import",
                "module": "pkg.client",
                "filepath": "pkg/client.py",
                "qualname": "pkg.client",
                "start_line": 3,
                "end_line": 3,
                "source_kind": "production",
                "location_scope": "module",
                "classification_mode": "exact_import",
                "evidence_kind": "import",
                "evidence_symbol": "importlib",
            },
        ],
    }
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/outside/project"},
        metrics=metrics,
    )

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_document=report_document,
    )

    _assert_html_contains(
        html,
        "pkg/client.py:3",
        'data-file="/outside/project/pkg/client.py"',
    )


def test_html_security_surface_helper_context_and_location_fallbacks() -> None:
    ctx = cast(
        Any,
        SimpleNamespace(
            scan_root="",
            metrics_map={
                "coverage_join": {
                    "summary": {"status": "ok"},
                    "items": [
                        {
                            "relative_path": "pkg/client.py",
                            "qualname": "pkg.client:run_case",
                            "coverage_hotspot": False,
                            "scope_gap_hotspot": True,
                        },
                        {
                            "relative_path": "pkg/ignored.py",
                            "qualname": "pkg.ignored:run_case",
                            "coverage_hotspot": False,
                            "scope_gap_hotspot": False,
                        },
                    ],
                }
            },
            relative_path=lambda filepath: filepath.replace("/outside/project/", ""),
        ),
    )

    assert relative_location_path(ctx, {"filepath": ""}) == ""
    assert (
        location_file_target(
            ctx,
            {"filepath": "pkg/client.py"},
            relative_path="pkg/client.py",
        )
        == "pkg/client.py"
    )
    assert (
        location_file_target(
            ctx,
            {},
            relative_path="pkg/client.py",
        )
        == "pkg/client.py"
    )
    assert (
        _coverage_join_review_text(
            ctx,
            overlap_total=0,
            scope_gaps=0,
            hotspots=0,
        )
        == "no overlap in current review set"
    )
    assert (
        _coverage_join_review_text(
            cast(
                Any,
                SimpleNamespace(
                    metrics_map={"coverage_join": {"summary": {"status": "missing"}}}
                ),
            ),
            overlap_total=1,
            scope_gaps=1,
            hotspots=0,
        )
        == "unavailable for this run"
    )
    coverage_index = _coverage_review_index(ctx)
    assert (
        _coverage_review_key(ctx, {"relative_path": "", "qualname": "pkg.client"})
        is None
    )
    assert (
        _coverage_review_item_key(
            ctx,
            {
                "relative_path": "pkg/ignored.py",
                "qualname": "pkg.ignored:run_case",
                "coverage_hotspot": False,
                "scope_gap_hotspot": False,
            },
        )
        is None
    )
    assert _coverage_review_cues(
        ctx,
        {"relative_path": "", "qualname": ""},
        coverage_index=coverage_index,
    ) == {
        "overlap": False,
        "coverage_hotspot": False,
        "scope_gap_hotspot": False,
    }
    assert (
        _review_cell_text(
            ctx,
            {
                "relative_path": "pkg/client.py",
                "qualname": "pkg.client",
                "location_scope": "module",
            },
            coverage_index=coverage_index,
        )
        == "Module · capability present"
    )
    assert (
        _review_cell_text(
            ctx,
            {
                "relative_path": "pkg/client.py",
                "qualname": "pkg.client:run_case",
                "location_scope": "callable",
            },
            coverage_index=coverage_index,
        )
        == "Callable · scope gap"
    )
    assert _pluralize(2, "row") == "rows"


def test_html_report_quality_coverage_join_empty_and_invalid_states() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["coverage_join"] = {
        "summary": {
            "status": "invalid",
            "source": "coverage.xml",
            "invalid_reason": "broken xml",
            "hotspot_threshold_percent": 50,
        },
        "items": [],
    }

    invalid_html = _render_metrics_html(metrics)

    _assert_html_contains(
        invalid_html,
        'data-clone-tab="coverage-join"',
        "Coverage Join is unavailable for this run.",
        "Source: coverage.xml",
        "broken xml",
        "Coverage join unavailable.",
    )
    invalid_panel = invalid_html.split('data-clone-panel="coverage-join"', 1)[1]
    invalid_panel = invalid_panel.split(
        '<div class="tab-panel" id="panel-module-map"',
        1,
    )[0]
    assert "Nothing to report - keep up the good work." not in invalid_panel

    metrics["coverage_join"] = {
        "summary": {
            "status": "ok",
            "source": "",
            "measured_units": 0,
            "overall_permille": 0,
            "missing_from_report_units": 0,
            "coverage_hotspots": 0,
            "scope_gap_hotspots": 0,
            "hotspot_threshold_percent": 80,
        },
        "items": [],
    }

    empty_html = _render_metrics_html(metrics)

    _assert_html_contains(
        empty_html,
        'data-clone-tab="coverage-join"',
        "Joined",
        "0.0%",
        "Measured units",
        "No medium/high-risk functions need joined-coverage follow-up.",
        "&lt; 80%",
        (
            "No risky functions were below threshold or missing from the "
            "supplied coverage.xml."
        ),
    )


def test_html_report_quality_coverage_join_edge_states() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["coverage_join"] = {
        "summary": {
            "status": "invalid",
            "source": "",
            "invalid_reason": None,
        },
        "items": [],
    }

    invalid_html = _render_metrics_html(metrics)
    coverage_join_panel = invalid_html.split('data-clone-panel="coverage-join"', 1)[1]
    coverage_join_panel = coverage_join_panel.split(
        '<div class="tab-panel" id="panel-module-map"',
        1,
    )[0]
    assert "Source:" not in coverage_join_panel
    assert "tab-empty-desc" not in coverage_join_panel

    metrics["coverage_join"] = {
        "summary": {
            "status": "ok",
            "source": "/outside/project/coverage.xml",
            "files": 1,
            "units": 1,
            "measured_units": 0,
            "overall_executable_lines": 0,
            "overall_covered_lines": 0,
            "overall_permille": 0,
            "missing_from_report_units": 1,
            "coverage_hotspots": 0,
            "scope_gap_hotspots": 1,
            "hotspot_threshold_percent": 50,
        },
        "items": [
            {
                "filepath": "pkg/mod.py",
                "qualname": "pkg.mod:run",
                "start_line": 10,
                "end_line": 10,
                "cyclomatic_complexity": 12,
                "risk": "high",
                "executable_lines": 0,
                "covered_lines": 0,
                "coverage_permille": 0,
                "coverage_status": "missing_from_report",
                "coverage_hotspot": False,
                "scope_gap_hotspot": True,
            }
        ],
    }

    missing_html = _render_metrics_html(metrics)
    _assert_html_contains(
        missing_html,
        "pkg.mod:run",
        "pkg/mod.py:10",
        "not in coverage.xml",
        "n/a",
        ">high</span>",
    )
    assert "pkg/mod.py:10-10" not in missing_html


def test_html_report_coverage_join_location_falls_back_to_filepath() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["coverage_join"] = {
        "summary": {
            "status": "ok",
            "source": "/outside/project/coverage.xml",
            "files": 1,
            "units": 1,
            "measured_units": 0,
            "overall_executable_lines": 0,
            "overall_covered_lines": 0,
            "overall_permille": 0,
            "missing_from_report_units": 1,
            "coverage_hotspots": 0,
            "scope_gap_hotspots": 1,
            "hotspot_threshold_percent": 50,
        },
        "items": [
            {
                "filepath": "/outside/project/pkg/mod.py",
                "qualname": "pkg.mod:run",
                "start_line": 10,
                "end_line": 12,
                "cyclomatic_complexity": 12,
                "risk": "high",
                "executable_lines": 0,
                "covered_lines": 0,
                "coverage_permille": 0,
                "coverage_status": "missing_from_report",
                "coverage_hotspot": False,
                "scope_gap_hotspot": True,
            }
        ],
    }

    html = _render_metrics_html(metrics)

    _assert_html_contains(
        html,
        "pkg/mod.py:10-12",
        'data-file="/outside/project/pkg/mod.py"',
    )
    assert ">:10-12<" not in html


def test_tab_empty_info_description_and_empty_variants() -> None:
    desc_html = _tab_empty_info(
        "Coverage Join is unavailable for this run.",
        description="Run with --coverage to populate this section.",
    )
    _assert_html_contains(
        desc_html,
        "Coverage Join is unavailable for this run.",
        "Run with --coverage to populate this section.",
        "tab-empty-desc-detail",
    )

    empty_html = _tab_empty_info("Coverage Join is unavailable for this run.")
    _assert_html_contains(empty_html, "Coverage Join is unavailable for this run.")
    assert "tab-empty-desc" not in empty_html


def test_html_report_overview_adoption_and_api_empty_state_branches() -> None:
    metrics = _metrics_payload(
        health_score=82,
        health_grade="B",
        complexity_max=12,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    metrics["coverage_adoption"] = {
        "summary": {
            "param_permille": 1000,
            "return_permille": 1000,
            "docstring_permille": 1000,
            "typing_any_count": 0,
        },
        "items": [],
    }
    metrics["api_surface"] = {"summary": {"enabled": False}, "items": []}

    disabled_html = _render_metrics_html(metrics)

    _assert_html_contains(
        disabled_html,
        "Typed as Any",
        "overview-fact-value--good",
        "Disabled in this run.",
        "Enable via",
        "--api-surface",
    )

    metrics["api_surface"] = {
        "summary": {
            "enabled": True,
            "modules": 1,
            "public_symbols": 2,
            "strict_types": True,
        },
        "items": [],
    }

    strict_html = _render_metrics_html(metrics)
    _assert_html_contains(strict_html, "Strict mode", "enabled")


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
    assert "Health 0/100 (n/a);" in html
    assert "2 dead-code items (0 suppressed); 0 dependency cycles." in html
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
        'title="dir1">dir1</code>',
        'title="dir5">dir5</code>',
    )


def test_html_report_canonical_path_includes_directory_hotspots_cluster() -> None:
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
    assert "Hotspots by Directory" in html


def test_html_report_directory_hotspots_use_test_scope_roots() -> None:
    report_document = build_report_document(
        func_groups={
            "fixture-clone": [
                {
                    "qualname": "tests.fixtures.golden_project.alpha:render_alpha",
                    "filepath": "/repo/project/tests/fixtures/golden_project/alpha.py",
                    "start_line": 1,
                    "end_line": 5,
                    "loc": 5,
                    "stmt_count": 4,
                    "fingerprint": "fixture-fp",
                    "loc_bucket": "0-19",
                },
                {
                    "qualname": "tests.fixtures.golden_project.beta:render_beta",
                    "filepath": "/repo/project/tests/fixtures/golden_project/beta.py",
                    "start_line": 1,
                    "end_line": 5,
                    "loc": 5,
                    "stmt_count": 4,
                    "fingerprint": "fixture-fp",
                    "loc_bucket": "0-19",
                },
                {
                    "qualname": "tests.fixtures.golden_v2.pkg.a:render_a",
                    "filepath": (
                        "/repo/project/tests/fixtures/golden_v2/"
                        "clone_metrics_cycle/pkg/a.py"
                    ),
                    "start_line": 1,
                    "end_line": 5,
                    "loc": 5,
                    "stmt_count": 4,
                    "fingerprint": "fixture-fp",
                    "loc_bucket": "0-19",
                },
                {
                    "qualname": "tests.fixtures.golden_v2.pkg.b:render_b",
                    "filepath": (
                        "/repo/project/tests/fixtures/golden_v2/"
                        "clone_metrics_cycle/pkg/b.py"
                    ),
                    "start_line": 1,
                    "end_line": 5,
                    "loc": 5,
                    "stmt_count": 4,
                    "fingerprint": "fixture-fp",
                    "loc_bucket": "0-19",
                },
            ]
        },
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo/project", "project_name": "project"},
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
        'title="tests/fixtures">tests/fixtures</code>',
    )
    # Directory hotspots (in the Overview panel) collapse to scope roots and must
    # not leak raw fixture paths. The Review queue legitimately surfaces the
    # finding itself, so scope the negative assertion to the Overview panel.
    overview = html.split('id="panel-overview"', 1)[1].split('id="panel-review"', 1)[0]
    assert "golden_project" not in overview
    assert "clone_metrics_cycle" not in overview


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
    assert (
        "0 candidates total; 0 high-confidence items; "
        "0 unreachable statement region(s); 0 suppressed."
    ) in html
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
        (
            "0 candidates total; 0 high-confidence items; "
            "0 unreachable statement region(s); 9 suppressed."
        ),
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


def test_html_report_dependency_graph_keeps_chain_and_cycle_nodes_when_truncated() -> (
    None
):
    edge_list: list[dict[str, object]] = []
    line = 1
    for index in range(18):
        edge_list.append(
            {
                "source": "hub.alpha",
                "target": f"a.leaf{index:02d}",
                "import_type": "import",
                "line": line,
            }
        )
        line += 1
    for index in range(18):
        edge_list.append(
            {
                "source": "hub.beta",
                "target": f"b.leaf{index:02d}",
                "import_type": "import",
                "line": line,
            }
        )
        line += 1

    chain_nodes = [
        "z.chain.start",
        "z.chain.one",
        "z.chain.two",
        "z.chain.three",
        "z.chain.four",
        "z.chain.end",
    ]
    for source, target in pairwise(chain_nodes):
        edge_list.append(
            {
                "source": source,
                "target": target,
                "import_type": "import",
                "line": line,
            }
        )
        line += 1

    cycle_nodes = ["z.cycle.left", "z.cycle.right"]
    edge_list.extend(
        [
            {
                "source": cycle_nodes[0],
                "target": cycle_nodes[1],
                "import_type": "import",
                "line": line,
            },
            {
                "source": cycle_nodes[1],
                "target": cycle_nodes[0],
                "import_type": "import",
                "line": line + 1,
            },
        ]
    )
    payload = _dependency_metrics_payload(
        edge_list=edge_list,
        longest_chains=[chain_nodes],
        dep_cycles=[cycle_nodes],
        dep_max_depth=len(chain_nodes),
    )
    deps = payload["dependencies"]
    assert isinstance(deps, dict)
    deps["modules"] = len(
        {part for edge in edge_list for part in (edge["source"], edge["target"])}
    )
    deps["edges"] = len(edge_list)

    html = _render_metrics_html(payload)

    _assert_html_contains(
        html,
        'data-node="z.chain.start"',
        'data-node="z.chain.three"',
        'data-node="z.chain.end"',
        'data-node="z.cycle.left"',
        'data-node="z.cycle.right"',
    )
    view_box = re.search(
        r'<svg viewBox="(-?\d+) (-?\d+) (\d+) (\d+)" class="dep-graph-svg"',
        html,
    )
    assert view_box is not None
    assert int(view_box.group(1)) < 0
    assert int(view_box.group(3)) > 0
    assert int(view_box.group(4)) > 0
    # Block-diagram nodes are boxes with the label inside (no rotated scatter text)
    assert re.search(r'<rect class="block-node" data-node="z\.chain\.three"', html)
    assert re.search(
        r'<text class="block-node-label" data-node="z\.chain\.three"', html
    )
    assert "rotate(-45)" not in html


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
        '<span class="prov-badge-val">miss</span>',
        '<span class="prov-badge-lbl">Cache</span>',
    )


def test_html_report_provenance_table_values_use_unified_badges() -> None:
    runtime_tag = current_python_tag()
    baseline_tag = "cp313" if runtime_tag != "cp313" else "cp314"
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={
            "python_tag": runtime_tag,
            "baseline_python_tag": baseline_tag,
            "baseline_loaded": False,
            "baseline_status": "missing",
            "baseline_payload_sha256_verified": False,
            "metrics_baseline_loaded": True,
            "metrics_baseline_status": "missing",
            "metrics_baseline_payload_sha256_verified": False,
            "cache_status": "ok",
            "cache_used": True,
        },
    )
    _assert_html_contains(
        html,
        'class="prov-badge prov-badge--amber prov-badge--inline"',
        'class="prov-badge prov-badge--red prov-badge--inline"',
        'class="prov-badge prov-badge--green prov-badge--inline"',
        '<span class="prov-badge-val">missing</span>',
        '<span class="prov-badge-val">not loaded</span>',
        '<span class="prov-badge-val">unverified</span>',
        '<span class="prov-badge-val">ok</span>',
        '<span class="prov-badge-val">hit</span>',
        f'<span class="prov-badge-val">runtime {runtime_tag}</span>',
    )
    assert 'class="meta-status' not in html
    assert 'class="meta-bool' not in html
    assert 'class="prov-match' not in html


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
        f'<span class="prov-badge-val">{REPORT_SCHEMA_VERSION}</span>',
        '<span class="prov-badge-lbl">Schema</span>',
    )
    assert '<span class="prov-badge-val">untrusted</span>' in html


def test_html_report_footer_uses_report_issue_link_text() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    _assert_html_contains(html, ">Docs</a> · ", ">Report Issue</a>")
    assert ">Issues</a>" not in html


def test_html_report_uses_numeric_font_for_overview_card_values() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    numeric_font_stack = (
        '--font-numeric:"JetBrains Mono",ui-monospace,'
        'SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;'
    )
    _assert_html_contains(
        html,
        numeric_font_stack,
        ".health-ring-score{font-family:var(--font-numeric);",
        ".meta-item .meta-value{font-family:var(--font-numeric);",
        ".overview-stat-value{font-family:var(--font-numeric);",
    )


def test_html_report_uses_jetbrains_mono_for_stat_card_content() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    _assert_html_contains(
        html,
        ".meta-item{padding:var(--sp-3) var(--sp-4);",
        "font-family:var(--font-mono)}",
        ".kpi-micro{display:inline-flex;align-items:center;gap:3px;",
        "font-family:var(--font-sans)}",
        ".kpi-micro-val{font-family:var(--count-font);font-weight:var(--count-weight);",
        ".overview-summary-item{background:var(--bg-surface);",
        "border:1px solid color-mix(in srgb,var(--border) 78%,transparent);",
        "padding:var(--sp-4)}",
        ".overview-summary-label{display:flex;align-items:center;gap:var(--sp-2);",
        ("border-bottom:1px solid color-mix(in srgb,var(--border) 58%,transparent);"),
        "font-family:var(--font-display)}",
        (
            ".overview-summary-item > :not(.overview-summary-label)"
            "{font-family:var(--font-mono)}"
        ),
    )


def test_html_report_jetbrains_links_preserve_path_separators_for_line_navigation() -> (
    None
):
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )

    _assert_html_contains(
        html,
        "function jetbrainsReferencePath(f,l)",
        ".replace(/%2F/gi,'/')",
        "+':'+lineNo(l);",
        "'jetbrains://pycharm/navigate/reference?project='",
        "'&path='+jetbrainsReferencePath(f,l)",
    )
    assert "encodeURIComponent(relPath(f))+':'+l" not in html


def test_html_report_uses_jetbrains_mono_for_health_radar_labels() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    _assert_html_contains(
        html,
        ".health-radar text{font-size:10.5px;font-family:var(--font-mono);",
        ".health-radar .radar-score{font-weight:600;font-variant-numeric:tabular-nums;",
    )


def test_html_report_empty_states_use_ui_font_stack() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    _assert_html_contains(
        html,
        ".tab-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;",
        "font-family:var(--font-sans)}",
        ".tab-empty-title{font-size:1rem;font-weight:600;color:var(--text-primary);margin-bottom:var(--sp-1);",
        "font-family:var(--font-display)}",
        # Size moved onto the type scale; the assertion follows the token so
        # it keeps testing the font stack, not a hardcoded size.
        ".tab-empty-desc{font-size:var(--fs-sm);color:var(--text-muted);max-width:320px;font-family:var(--font-sans)}",
        ".inline-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;",
        "font-family:var(--font-sans)}",
    )


def test_html_report_uses_shared_card_micro_interactions() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    _assert_html_contains(
        html,
        ".meta-item,.overview-row,.overview-summary-item,.group,.suggestion-card,.sf-card,.prov-section{",
        "--card-hover-accent:var(--accent-primary);",
        "@media (hover:hover) and (pointer:fine){",
        "transform:translateY(-2px);",
        (
            "border-color:color-mix(in oklch,var(--card-hover-accent) "
            "22%,var(--border-strong));"
        ),
        "@media (prefers-reduced-motion:reduce){",
        "transform:none}",
    )


def test_html_report_dead_code_cards_do_not_render_negative_active_count() -> None:
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
            dead_suppressed=1,
        ),
    )
    _assert_html_contains(
        html,
        '<span class="kpi-micro-val">0</span><span class="kpi-micro-lbl">active</span>',
    )
    assert (
        '<span class="kpi-micro-val">-1</span><span class="kpi-micro-lbl">active</span>'
        not in html
    )


def test_html_report_findings_empty_state_keeps_intro_banner() -> None:
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    # Moved expectation: the banner still survives an empty result, which is
    # what this test is for. What it pinned was the definition -- the tab spent
    # its question slot explaining its own title. It now asks about the code,
    # answers in the clean case, and the definition lives in the glossary.
    _assert_html_contains(
        html,
        "Which functions repeat their own shape?",
        "No function repeats a branch body.",
        "No structural findings detected.",
    )
    assert "insight-ok" in html, "a clean result no longer reads as clean"


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
        'families-count">1</span>',
        # Structural findings use the shared finding_card chrome (Stage 4)
        "finding-card finding-card--info sf-card",
        'data-sf-group="true"',
        "data-finding-why-btn",
    ):
        assert needle in html
    # Bespoke sf-card chrome was fully replaced by the shared component
    assert '<article class="sf-card"' not in html
    assert '<div class="overview-summary-value">n/a</div>' not in html
    # Issue breakdown replaces old hotspot sections
    assert "Issue breakdown" in html


# ---------------------------------------------------------------------------
# Module map panel (Phase 32)
# ---------------------------------------------------------------------------


def _mm_node(
    node_id: str,
    fan_in: int,
    fan_out: int,
    *,
    in_cycle: bool = False,
    status: str = "non_candidate",
    reasons: tuple[str, ...] = (),
    kinds: tuple[str, ...] = ("production",),
) -> dict[str, object]:
    return {
        "id": node_id,
        "label": node_id,
        "fan_in": fan_in,
        "fan_out": fan_out,
        "total_degree": fan_in + fan_out,
        "source_kinds": list(kinds),
        "in_cycle": in_cycle,
        "overloaded": {
            "score": 0.9,
            "candidate_status": status,
            "candidate_reasons": list(reasons),
        },
    }


def _mm_graph(
    *,
    zoom: str,
    package_depth: object,
    nodes: list[dict[str, object]],
    edges: list[dict[str, object]],
    truncated: bool,
) -> dict[str, object]:
    return {
        "zoom": zoom,
        "package_depth": package_depth,
        "truncation": {
            "truncated": truncated,
            "node_universe_count": 40 if truncated else len(nodes),
            "node_shown_count": len(nodes),
            "edge_universe_count": 30 if truncated else len(edges),
            "edge_shown_count": len(edges),
            "seed_policy": "cycles_then_chains_then_degree",
        },
        "nodes": nodes,
        "edges": edges,
    }


def _module_map_payload(
    *,
    truncated: bool = False,
    default_zoom: str = "packages",
    population_status: str = "ok",
    with_unwind: bool = True,
    packages_nodes: bool = True,
) -> dict[str, object]:
    nodes = [
        _mm_node(
            "pkg.core", 12, 8, status="candidate", reasons=("dependency_pressure",)
        ),
        _mm_node("pkg.api", 6, 2, in_cycle=True),
        _mm_node("pkg.svc", 2, 2),
        _mm_node("pkg.util", 2, 1, kinds=("tests",)),
        _mm_node("pkg.leaf", 0, 1),
    ]
    edges = [
        {"source": "pkg.api", "target": "pkg.core", "weight": 5},
        {"source": "pkg.core", "target": "pkg.util", "weight": 1},
        {"source": "pkg.leaf", "target": "pkg.core", "weight": 2},
        {"source": "pkg.svc", "target": "pkg.core", "weight": 3},
    ]
    unwind = (
        [
            {
                "module": "pkg.core",
                "filepath": "pkg/core.py",
                "source_kind": "production",
                "fan_in": 12,
                "fan_out": 8,
                "score": 0.9,
                "dependency_score": 0.95,
                "candidate_status": "candidate",
                "signals": ["dependency_pressure", "chain_bottleneck"],
            }
        ]
        if with_unwind
        else []
    )
    return {
        "schema_version": "1",
        "scope": "report_only",
        "default_zoom": default_zoom,
        "summary": {
            "available": True,
            "module_count": 5,
            "package_count_depth2": 5,
            "edge_count": 4,
            "unwind_candidate_count": len(unwind),
            "overloaded_candidate_count": 1,
            "overloaded_population_status": population_status,
        },
        "graph_packages": _mm_graph(
            zoom="packages",
            package_depth=2,
            nodes=nodes if packages_nodes else [],
            edges=edges if packages_nodes else [],
            truncated=truncated,
        ),
        "graph_modules": _mm_graph(
            zoom="modules",
            package_depth=None,
            nodes=nodes,
            edges=edges,
            truncated=False,
        ),
        "unwind_candidates": unwind,
    }


def _module_map_unavailable_payload() -> dict[str, object]:
    empty = {
        "truncated": False,
        "node_universe_count": 0,
        "node_shown_count": 0,
        "edge_universe_count": 0,
        "edge_shown_count": 0,
        "seed_policy": "cycles_then_chains_then_degree",
    }
    graph: dict[str, object] = {
        "zoom": "packages",
        "package_depth": None,
        "truncation": empty,
        "nodes": [],
        "edges": [],
    }
    return {
        "schema_version": "1",
        "scope": "report_only",
        "default_zoom": "packages",
        "summary": {
            "available": False,
            "reason": "dependencies_skipped",
            "module_count": 0,
            "package_count_depth2": 0,
            "edge_count": 0,
            "unwind_candidate_count": 0,
            "overloaded_candidate_count": 0,
            "overloaded_population_status": "limited",
        },
        "graph_packages": graph,
        "graph_modules": {**graph, "zoom": "modules"},
        "unwind_candidates": [],
    }


def _module_map_base_metrics() -> dict[str, object]:
    return _metrics_payload(
        health_score=80,
        health_grade="B",
        complexity_max=1,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )


def _module_map_metrics() -> dict[str, object]:
    metrics = _module_map_base_metrics()
    metrics["overloaded_modules"] = {
        "summary": {"candidates": 1, "population_status": "ok"},
        "items": [
            {
                "module": "pkg.core",
                "score": 0.9,
                "fan_in": 12,
                "fan_out": 8,
                "candidate_status": "candidate",
            },
            {
                "module": "pkg.api",
                "score": 0.4,
                "fan_in": 6,
                "fan_out": 2,
                "candidate_status": "ranked_only",
            },
        ],
    }
    return metrics


def _render_module_map_report(
    module_map: dict[str, object],
    *,
    metrics: dict[str, object] | None = None,
) -> str:
    resolved_metrics = metrics if metrics is not None else _module_map_metrics()
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={
            "scan_root": "/outside/project",
            "metrics_computed": sorted(resolved_metrics),
        },
        metrics=resolved_metrics,
    )
    derived = dict(cast(dict[str, object], report_document["derived"]))
    derived["module_map"] = module_map
    report_document["derived"] = derived
    return _core_build_html_report(report_document=report_document)


def _module_map_panel_slice(html: str) -> str:
    panel = html.split('id="panel-module-map"', 1)[1]
    return panel.split('id="panel-dependencies"', 1)[0]


def test_html_report_renders_module_map_panel() -> None:
    html = _render_module_map_report(_module_map_payload())
    _assert_html_contains(
        html,
        "Module map",
        'id="panel-module-map"',
        "dep-graph-svg",
        'class="block-node"',
        "block-node-ring",
        'data-subtab-group="module-map-zoom"',
        "Report-only import-graph signals for refactor triage.",
        "Unwind candidates",
        "Overloaded Modules",
        "Complexity total",
        "dependency_pressure",
    )
    panel = _module_map_panel_slice(html)
    assert "pkg.core" in panel
    assert 'stroke-width="3"' in panel  # weight=5 edge -> 1+floor(log2 5)=3
    assert 'stroke-dasharray="4,3"' in panel  # tests / in-cycle dashed box border
    assert 'stroke="var(--danger)"' in panel  # in-cycle node danger border
    # overloaded table rows in items order: pkg.core before pkg.api
    overloaded = panel.split("Overloaded Modules", 1)[1]
    assert overloaded.index("pkg.core") < overloaded.index("pkg.api")


def test_module_map_truncation_notice_when_sampled() -> None:
    html = _render_module_map_report(_module_map_payload(truncated=True))
    panel = _module_map_panel_slice(html)
    _assert_html_contains(
        panel, "mm-truncation-notice", "Showing", "deterministic sample"
    )


def test_module_map_panel_unavailable_when_skipped() -> None:
    # Real skip-dependencies runs drop both the graph and the overloaded family.
    metrics = _module_map_base_metrics()
    metrics.pop("overloaded_modules", None)
    html = _render_module_map_report(_module_map_unavailable_payload(), metrics=metrics)
    panel = _module_map_panel_slice(html)
    assert "Dependency graph is not available." in panel
    assert "dep-graph-svg" not in panel
    assert 'data-subtab-group="module-map-zoom"' not in panel
    assert "Overloaded Modules" not in panel


def test_module_map_panel_metrics_skipped_insight() -> None:
    ctx = cast(
        Any,
        SimpleNamespace(
            derived_map={},
            overloaded_modules_map={},
            metrics_available=False,
        ),
    )
    html = render_module_map_panel(ctx)
    assert "Metrics are skipped for this run." in html
    assert "Dependency graph is not available." in html


def test_module_map_panel_modules_zoom_and_limited_population() -> None:
    payload = _module_map_payload(
        default_zoom="modules",
        population_status="limited",
        with_unwind=False,
        packages_nodes=False,
    )
    html = _render_module_map_report(payload, metrics=_module_map_base_metrics())
    panel = _module_map_panel_slice(html)
    # overloaded family present but empty -> section heading + empty-profile message
    assert "Overloaded Modules" in panel
    assert "Overloaded-module profiling is not available." in panel
    assert "No unwind candidates detected." in panel
    # modules graph (active) renders an SVG; empty packages graph shows the message
    assert "dep-graph-svg" in panel
    assert "Dependency graph is not available." in panel


def _review_queue_payload(*, with_items: bool = True) -> dict[str, object]:
    items: list[dict[str, object]] = []
    if with_items:
        items = [
            {
                "id": "clone:a",
                "finding_id": "clone:a",
                "family": "clones",
                "category": "function",
                "severity": "critical",
                "priority": 0.91,
                "novelty": "new",
                "source_kind": "production",
                "has_action": True,
                "title": "Duplicated branch logic",
                "summary": "3 near-identical branches",
                "location": "pkg/a.py:12",
                "representative_locations": [],
                "effort": "hard",
                "steps": ["extract a handler"],
            },
            {
                "id": "struct:b",
                "finding_id": "struct:b",
                "family": "structural",
                "category": "duplicated_branches",
                "severity": "warning",
                "priority": 0.6,
                "novelty": "known",
                "source_kind": "tests",
                "has_action": True,
                "title": "Repeated assertions",
                "summary": "repeated assert template",
                "location": "tests/test_b.py:30",
                "representative_locations": [],
                "effort": "easy",
                "steps": ["collapse"],
            },
            {
                "id": "dead:c",
                "finding_id": "dead:c",
                "family": "dead_code",
                "category": "function",
                "severity": "info",
                "priority": 0.3,
                "novelty": "known",
                "source_kind": "production",
                "has_action": False,
                "title": "Unused function: pkg.mod:helper",
                "summary": "1 occurrence · production",
                "location": "pkg/mod.py:40",
                "representative_locations": [],
                "effort": "",
                "steps": [],
            },
        ]
    return {
        "schema_version": "2",
        "scope": "report_only",
        "summary": {
            "total": len(items),
            "reviewed": 0,
            "actionable": 2 if with_items else 0,
            "by_severity": {
                "critical": 1 if with_items else 0,
                "warning": 1 if with_items else 0,
                "info": 1 if with_items else 0,
            },
            "by_family": (
                {"clones": 1, "dead_code": 1, "structural": 1} if with_items else {}
            ),
            "by_novelty": {"new": 1, "known": 2}
            if with_items
            else {"new": 0, "known": 0},
            "top_priority": 0.91 if with_items else 0.0,
        },
        "items": items,
    }


def _render_review_report(review_queue: dict[str, object]) -> str:
    metrics = _metrics_payload(
        health_score=80,
        health_grade="B",
        complexity_max=1,
        complexity_high_risk=0,
        coupling_high_risk=0,
        cohesion_low=0,
        dep_cycles=[],
        dep_max_depth=2,
        dead_total=0,
        dead_critical=0,
    )
    return build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/outside/project"},
        metrics=metrics,
        report_document={"derived": {"review_queue": review_queue}},
    )


def test_html_report_renders_review_panel() -> None:
    html = _render_review_report(_review_queue_payload())
    _assert_html_contains(
        html,
        '<span class="main-tab-label">Review</span>',
        'id="panel-review"',
        "data-review-panel",
        "data-review-progress-bar",
        "What needs review, and in what order?",
    )
    panel = html.split('id="panel-review"', 1)[1].split('id="panel-clones"', 1)[0]
    _assert_html_contains(
        panel,
        'data-review-card="true"',
        'data-finding-id="clone:a"',
        'data-severity="critical"',
        'data-family="clones"',
        "finding-card--critical",
        "data-review-toggle",
        "Duplicated branch logic",
        # shared filter system (Filters popover + selects), not bespoke chips
        # shared filter system, inline density: one-click toggle chips
        'class="filter-chip',
        'data-filter-dim="severity"',
        'data-filter-value="critical"',
        'data-filter-dim="family"',
        "data-filter-reset",
        "data-review-count",
        "data-review-body",
        # novelty marker on the new finding
        'data-novelty="new"',
        "finding-meta-badge--new",
        # cross-family findings (incl. a no-action dead-code item) are reviewable
        'data-family="dead_code"',
        'data-finding-id="dead:c"',
        "Unused function: pkg.mod:helper",
    )
    # priority order preserved (input order): critical clone before warning struct
    assert panel.index("Duplicated branch logic") < panel.index("Repeated assertions")


def test_review_panel_empty_when_no_items() -> None:
    html = _render_review_report(_review_queue_payload(with_items=False))
    panel = html.split('id="panel-review"', 1)[1].split('id="panel-clones"', 1)[0]
    assert "No findings to review." in panel
    assert "data-review-card" not in panel
    # tab badge hidden when zero
    assert (
        '<span class="main-tab-label">Review</span><span class="tab-count"' not in html
    )


def test_overview_launchpad_links_to_review() -> None:
    html = _render_review_report(_review_queue_payload())
    overview = html.split('id="panel-overview"', 1)[1].split('id="panel-review"', 1)[0]
    _assert_html_contains(
        overview,
        "review-launchpad",
        'data-goto-tab="review"',
        "3 findings ready to review",
        "Start review",
        "launchpad-sev--critical",
    )
    # JS cross-tab jump handler shipped
    assert "gotoTab" in html


def test_overview_launchpad_absent_when_queue_empty() -> None:
    html = _render_review_report(_review_queue_payload(with_items=False))
    overview = html.split('id="panel-overview"', 1)[1].split('id="panel-review"', 1)[0]
    assert "review-launchpad" not in overview
    assert "data-goto-tab" not in overview


def test_render_rows_table_meter_column_self_scales() -> None:
    from codeclone.report.html.widgets.tables import render_rows_table

    html = render_rows_table(
        headers=("Name", "CC"),
        rows=[("alpha", "20"), ("beta", "10"), ("gamma", "5")],
        empty_message="none",
        column_types={"CC": "meter"},
    )
    assert "metric-meter" in html
    # column max (20) fills 100% and reads as the high band
    assert 'style="width:100%"' in html
    assert "metric-meter--high" in html
    # half the max (10) fills 50% and reads as the mid band
    assert 'style="width:50%"' in html
    assert "metric-meter--mid" in html
    # the underlying numbers are preserved verbatim
    assert ">20</span>" in html and ">5</span>" in html


def test_render_rows_table_meter_handles_non_numeric() -> None:
    from codeclone.report.html.widgets.tables import render_rows_table

    html = render_rows_table(
        headers=("Name", "CC"),
        rows=[("alpha", "n/a")],
        empty_message="none",
        column_types={"CC": "meter"},
    )
    assert "n/a" in html
    assert "metric-meter-fill" not in html


def test_render_rows_table_source_kind_column_renders_badge() -> None:
    from codeclone.report.html.widgets.tables import render_rows_table

    html = render_rows_table(
        headers=("Name", "Source"),
        rows=[("x", "production"), ("y", "tests")],
        empty_message="none",
        column_types={"Source": "source_kind"},
    )
    assert "source-kind-badge" in html
    assert "source-kind-production" in html
    assert "source-kind-tests" in html


def test_render_rows_table_code_column_renders_code_chip() -> None:
    from codeclone.report.html.widgets.tables import render_rows_table

    html = render_rows_table(
        headers=("Name", "Rule"),
        rows=[("x", "golden_fixture@project_config"), ("y", "-")],
        empty_message="none",
        column_types={"Rule": "code"},
    )
    assert '<code class="code-chip">golden_fixture@project_config</code>' in html
    # the placeholder dash stays plain, not chipped
    assert '<code class="code-chip">-</code>' not in html


def _clone_health_metrics_payload(*, clones_score: object) -> dict[str, object]:
    payload = _metrics_payload(
        health_score=88,
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
    health = payload["health"]
    assert isinstance(health, dict)
    health["dimensions"] = {"clones": clones_score, "coverage": 99}
    return payload


def _clone_health_item(
    tmp_path: Path,
    *,
    module: str,
    qualname: str,
    fingerprint: str,
) -> dict[str, Any]:
    path = tmp_path / f"{module}.py"
    if not path.exists():
        path.write_text("def f():\n    return 1\n", "utf-8")
    return {
        "qualname": qualname,
        "filepath": str(path),
        "start_line": 1,
        "end_line": 2,
        "loc": 2,
        "stmt_count": 1,
        "size": 2,
        "fingerprint": fingerprint,
        "loc_bucket": "0-19",
    }


def _clone_health_report_html(tmp_path: Path, *, clones_score: int = 97) -> str:
    """Render a report whose clone health arithmetic is fully determined.

    Two function groups plus one block group are the scored population; the
    segment group is reported but never scored, and ``pkg.a:f1`` participates in
    two groups so a naive participant count (8) differs from the deduplicated
    one (7).
    """

    item = _clone_health_item
    func_groups = {
        "g1": [
            item(tmp_path, module="a", qualname="pkg.a:f1", fingerprint="fp1"),
            item(tmp_path, module="b", qualname="pkg.b:f1", fingerprint="fp1"),
        ],
        "g2": [
            item(tmp_path, module="a", qualname="pkg.a:f2", fingerprint="fp2"),
            item(tmp_path, module="c", qualname="pkg.c:f2", fingerprint="fp2"),
        ],
    }
    block_groups = {
        "bk1|pkg.a:f1": [
            item(tmp_path, module="a", qualname="pkg.a:f1", fingerprint="fp3"),
            item(tmp_path, module="d", qualname="pkg.d:f3", fingerprint="fp3"),
        ]
    }
    segment_groups = {
        "sk1|pkg.e:f4": [
            item(tmp_path, module="e", qualname="pkg.e:f4", fingerprint="fp4"),
            item(tmp_path, module="f", qualname="pkg.f:f5", fingerprint="fp4"),
        ]
    }
    suppressed_group = SuppressedCloneGroup(
        kind="function",
        group_key="pkg.golden:run",
        items=(
            item(
                tmp_path,
                module="golden_a",
                qualname="pkg.golden_a:run",
                fingerprint="fp5",
            ),
            item(
                tmp_path,
                module="golden_b",
                qualname="pkg.golden_b:run",
                fingerprint="fp5",
            ),
        ),
        matched_patterns=("tests/fixtures/golden_*",),
        suppression_rule="golden_fixture",
        suppression_source="project_config",
    )
    report_document = build_report_document(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta={"scan_root": str(tmp_path)},
        inventory={
            "files": {
                "total_found": 12,
                "analyzed": 8,
                "cached": 2,
                "skipped": 2,
                "source_io_skipped": 0,
            }
        },
        metrics=_clone_health_metrics_payload(clones_score=clones_score),
        suppressed_clone_groups=(suppressed_group,),
    )
    return build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": str(tmp_path)},
        report_document=report_document,
    )


def _clone_contribution_text(score: int) -> str:
    """Build the expected contribution phrase from the contract weight itself."""

    weight = HEALTH_WEIGHTS["clones"]
    return (
        f"Clones health {score}/100: {score} \u00d7 {weight * 100:g}% = "
        f"{score * weight:g} of {100 * weight:g} health points."
    )


def test_html_report_clones_panel_explains_health_arithmetic(tmp_path: Path) -> None:
    html = _clone_health_report_html(tmp_path)

    assert_contains_all(
        html,
        # score -> health points, derived from HEALTH_WEIGHTS, not hardcoded
        _clone_contribution_text(97),
        # density: scored groups are function + block groups only
        (
            "Density: 3 active groups (functions and blocks) across 10 analyzed "
            "files — a density, not a share of files."
        ),
        # participants are deduplicated: 8 fragments, 7 distinct callables
        "Instances: 8 duplicated fragments; 7 unique callables participate.",
        # segments are reported but do not feed the dimension
        "Segment groups reported but not scored: 1.",
        # the suppressed channel is stated once, in the insight line, and
        # counted on its own card -- not repeated a third time in the note
        "1 suppressed golden-fixture group is excluded from active review.",
    )
    assert "Accepted groups excluded by suppression policy" not in html
    assert "golden-fixture groups are excluded" not in html
    # statistical honesty: duplication is never presented as a share of files
    assert "% of files" not in html
    assert "% of callables" not in html


def test_html_report_clones_health_card_shows_contribution(tmp_path: Path) -> None:
    weight = HEALTH_WEIGHTS["clones"]
    html = _clone_health_report_html(tmp_path)

    assert_contains_all(
        html,
        "Health points",
        f'<div class="meta-value">{97 * weight:g}'
        f'<span class="meta-value-sec">of {100 * weight:g}</span></div>',
        "Excluded groups",
    )


def test_html_report_clone_health_contribution_follows_contract_weight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rendered contribution must move with HEALTH_WEIGHTS, not a literal."""

    from codeclone.report.messages import clone_health

    monkeypatch.setattr(
        clone_health,
        "HEALTH_WEIGHTS",
        {**HEALTH_WEIGHTS, "clones": 0.5},
    )
    html = _clone_health_report_html(tmp_path)

    assert "Clones health 97/100: 97 \u00d7 50% = 48.5 of 50 health points." in html


def test_html_report_health_profile_repeats_clone_contribution(tmp_path: Path) -> None:
    html = _clone_health_report_html(tmp_path)

    legend = re.search(r'<div class="health-radar-legend">(.*?)</div>', html, re.S)
    assert legend is not None
    assert _clone_contribution_text(97) in legend.group(1)
    assert "3 active groups (functions and blocks) across 10 analyzed files" in (
        legend.group(1)
    )


def test_html_report_clone_health_note_absent_without_metrics(tmp_path: Path) -> None:
    """No health dimension means no arithmetic to explain, and none is invented."""

    html = build_html_report(
        func_groups={
            "g1": [
                _clone_health_item(
                    tmp_path, module="a", qualname="pkg.a:f1", fingerprint="fp1"
                ),
                _clone_health_item(
                    tmp_path, module="b", qualname="pkg.b:f1", fingerprint="fp1"
                ),
            ]
        },
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": str(tmp_path)},
    )

    assert "Clone groups" in html
    assert "health points." not in html


def test_clone_health_sentences_absent_without_clones_dimension() -> None:
    from codeclone.report.messages.clone_health import (
        clone_health_note_sentences,
        clone_health_summary_sentence,
    )

    document = {
        "metrics": {"families": {"health": {"summary": {"dimensions": {}}}}},
        "findings": {"summary": {"clones": {}}, "groups": {"clones": {}}},
        "inventory": {"files": {"analyzed": 4}},
    }

    assert clone_health_note_sentences(document) == ()
    assert clone_health_summary_sentence(document) == ""


def test_clone_health_note_sentences_omit_unavailable_facts() -> None:
    from codeclone.report.messages.clone_health import clone_health_note_sentences

    sentences = clone_health_note_sentences(
        {
            "metrics": {
                "families": {"health": {"summary": {"dimensions": {"clones": 40}}}}
            },
            "findings": {
                "summary": {"clones": {"functions": 1, "blocks": 0, "instances": 2}},
                "groups": {"clones": {"functions": [{"items": [{"qualname": ""}]}]}},
            },
            "inventory": {"files": {}},
        }
    )

    assert sentences[0].startswith("Clones health 40/100:")
    # no analyzed files -> no density claim, no unique-callable claim
    assert not any(sentence.startswith("Density:") for sentence in sentences)
    assert sentences[1] == "Instances: 2 duplicated fragments."
    assert not any("Segment groups" in sentence for sentence in sentences)
    assert not any("Accepted groups" in sentence for sentence in sentences)


def test_html_report_authority_panel_reports_the_configured_registry(
    tmp_path: Path,
) -> None:
    """A configured registry must never be rendered as an absent one.

    The panel reads the semantic_authority family, and the HTML context drops
    families the run did not declare. Declaring the families the way production
    declares them is therefore part of this assertion, not a fixture detail.
    """

    payload = _metrics_payload(
        health_score=88,
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
    payload["semantic_authority"] = {
        "summary": {
            "enabled": True,
            "report_only": False,
            "enforcement_enabled": True,
            "registry_version": "1",
            "registry_contracts": 5,
            "governed_sinks": 1,
            "violations": 0,
            "active_violations": 0,
            "suppressed_violations": 0,
        },
        "items": [
            {
                "item_kind": "governed_sink",
                "contract_id": "baseline.publication/v1",
                "sink_identity": "pkg.mod:publish",
                "authority_status": "authoritative",
                "resolution_state": "resolved",
                "relative_path": "pkg/mod.py",
            }
        ],
    }
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={
            "scan_root": str(tmp_path),
            "metrics_computed": sorted(payload),
        },
        metrics=payload,
    )

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": str(tmp_path)},
        report_document=report_document,
    )

    assert "0 active violations across 5 governed contracts" in html
    assert "no registry is configured" not in html


def _ordering_metrics_payload() -> dict[str, object]:
    """Quality rows whose alphabetical order is the reverse of their urgency."""

    return {
        "complexity": {
            "functions": [
                {
                    "qualname": "aaa.helper:tiny",
                    "filepath": "/repo/aaa/helper.py",
                    "start_line": 1,
                    "end_line": 3,
                    "cyclomatic_complexity": 2,
                    "nesting_depth": 1,
                    "risk": "low",
                },
                {
                    "qualname": "mmm.mid:moderate",
                    "filepath": "/repo/mmm/mid.py",
                    "start_line": 1,
                    "end_line": 40,
                    "cyclomatic_complexity": 14,
                    "nesting_depth": 3,
                    "risk": "medium",
                },
                {
                    "qualname": "zzz.core:monster",
                    "filepath": "/repo/zzz/core.py",
                    "start_line": 1,
                    "end_line": 200,
                    "cyclomatic_complexity": 61,
                    "nesting_depth": 7,
                    "risk": "high",
                },
                {
                    "qualname": "zzz.core:heavy",
                    "filepath": "/repo/zzz/core.py",
                    "start_line": 210,
                    "end_line": 300,
                    "cyclomatic_complexity": 33,
                    "nesting_depth": 5,
                    "risk": "high",
                },
            ],
            "summary": {"total": 4, "average": 27.5, "max": 61, "high_risk": 2},
        },
        "coupling": {
            "classes": [
                {
                    "qualname": "aaa.helper:Small",
                    "filepath": "/repo/aaa/helper.py",
                    "start_line": 1,
                    "end_line": 10,
                    "cbo": 1,
                    "risk": "low",
                },
                {
                    "qualname": "zzz.core:Hub",
                    "filepath": "/repo/zzz/core.py",
                    "start_line": 1,
                    "end_line": 80,
                    "cbo": 27,
                    "risk": "high",
                },
            ],
            "summary": {"total": 2, "average": 14.0, "max": 27, "high_risk": 1},
        },
        "cohesion": {
            "classes": [
                {
                    "qualname": "aaa.helper:Small",
                    "filepath": "/repo/aaa/helper.py",
                    "start_line": 1,
                    "end_line": 10,
                    "lcom4": 1,
                    "risk": "low",
                    "method_count": 2,
                    "instance_var_count": 2,
                },
                {
                    "qualname": "zzz.core:Hub",
                    "filepath": "/repo/zzz/core.py",
                    "start_line": 1,
                    "end_line": 80,
                    "lcom4": 6,
                    "risk": "high",
                    "method_count": 9,
                    "instance_var_count": 1,
                },
            ],
            "summary": {"total": 2, "average": 3.5, "max": 6, "low_cohesion": 1},
        },
        "dead_code": {
            "items": [
                {
                    "qualname": "aaa.helper:maybe_unused",
                    "filepath": "/repo/aaa/helper.py",
                    "start_line": 20,
                    "end_line": 22,
                    "kind": "function",
                    "confidence": "medium",
                },
                {
                    "qualname": "zzz.core:definitely_unused",
                    "filepath": "/repo/zzz/core.py",
                    "start_line": 400,
                    "end_line": 402,
                    "kind": "function",
                    "confidence": "high",
                },
            ],
            "suppressed_items": [],
            "summary": {"total": 2, "critical": 1, "suppressed": 0},
        },
        "health": {"score": 70, "grade": "B", "dimensions": {"coverage": 99}},
    }


def _ordering_document() -> dict[str, Any]:
    return build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo", "metrics_computed": ["complexity"]},
        metrics=_ordering_metrics_payload(),
    )


def _family_items(document: Mapping[str, Any], family: str) -> list[Mapping[str, Any]]:
    families = document["metrics"]["families"]
    return list(families[family]["items"])


def test_document_orders_quality_rows_by_operational_rank() -> None:
    """The worst row must be first: risk, then the metric that earned it.

    Ordered by file path, the first complexity row of this repository was a
    low-risk script with CC 2 while high-risk functions sat far below the
    fifty-row cut the report renders.
    """

    document = _ordering_document()

    complexity = _family_items(document, "complexity")
    assert [item["qualname"] for item in complexity] == [
        "zzz.core:monster",
        "zzz.core:heavy",
        "mmm.mid:moderate",
        "aaa.helper:tiny",
    ]
    assert [item["qualname"] for item in _family_items(document, "coupling")] == [
        "zzz.core:Hub",
        "aaa.helper:Small",
    ]
    assert [item["qualname"] for item in _family_items(document, "cohesion")] == [
        "zzz.core:Hub",
        "aaa.helper:Small",
    ]
    assert [item["qualname"] for item in _family_items(document, "dead_code")] == [
        "zzz.core:definitely_unused",
        "aaa.helper:maybe_unused",
    ]


def test_html_quality_table_renders_document_order_as_is() -> None:
    """Renderers present the canonical order; they never re-decide it."""

    document = _ordering_document()
    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": "/repo"},
        report_document=document,
    )

    expected = [item["qualname"] for item in _family_items(document, "complexity")]
    # Read the complexity table body itself, not the summary cards above it.
    table = html[html.index("<th>Nesting") :]
    body = table[table.index("<tbody>") : table.index("</tbody>")]
    rendered = re.findall(r'<td class="col-name">([^<]+)</td>', body)
    assert rendered == expected


def _authority_report_html(
    tmp_path: Path,
    *,
    governed: list[dict[str, object]],
    active_violations: int = 0,
    candidates: list[dict[str, object]] | None = None,
    sinks: int = 0,
    enforcement_enabled: bool = True,
) -> str:
    payload = _metrics_payload(
        health_score=88,
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
    violations = [
        {
            "item_kind": "violation",
            "violation_id": f"v{index}",
            "contract_id": "baseline.publication/v1",
            "kind": "duplicate_responsibility",
            "sink_identity": f"pkg.mod:rogue{index}",
            "canonical_owner": "pkg.mod:publish",
            "suppressed": False,
        }
        for index in range(active_violations)
    ]
    sink_items = [
        {
            "item_kind": "sink",
            "sink_identity": f"pkg.mod:sink{index}",
            "authority_status": "unavailable",
            "resolution_state": "unavailable",
        }
        for index in range(sinks)
    ]
    payload["semantic_authority"] = {
        "summary": {
            "enabled": True,
            "report_only": not enforcement_enabled,
            "enforcement_enabled": enforcement_enabled,
            "registry_version": "1",
            "registry_contracts": len(governed),
            "governed_sinks": len(governed),
            "candidates": len(candidates or ()),
            "sinks": sinks,
            "violations": active_violations,
            "active_violations": active_violations,
            "suppressed_violations": 0,
        },
        "items": [*governed, *violations, *(candidates or ()), *sink_items],
    }
    report_document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={
            "scan_root": str(tmp_path),
            "metrics_computed": sorted(payload),
        },
        metrics=payload,
    )
    return build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_meta={"scan_root": str(tmp_path)},
        report_document=report_document,
    )


def _governed_sink(
    *,
    contract: str,
    sink: str,
    status: str,
    resolution: str,
    unresolved_reasons: list[str] | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "item_kind": "governed_sink",
        "contract_id": contract,
        "sink_identity": sink,
        "authority_status": status,
        "resolution_state": resolution,
        "relative_path": "pkg/mod.py",
    }
    if unresolved_reasons is not None:
        item["unresolved_reasons"] = unresolved_reasons
    return item


def test_html_authority_row_states_why_it_abstained(tmp_path: Path) -> None:
    """An abstaining row must carry its reason, not just the word unavailable."""

    html = _authority_report_html(
        tmp_path,
        governed=[
            _governed_sink(
                contract="baseline.publication/v1",
                sink="pkg.mod:publish",
                status="unavailable",
                resolution="unavailable",
                unresolved_reasons=["unresolved_call", "unresolved_flow"],
            )
        ],
    )

    assert "unresolved call" in html
    assert "unresolved flow" in html


def test_html_authority_insight_states_abstention_not_zero_violations(
    tmp_path: Path,
) -> None:
    """Zero violations over an unresolved population is not a clean result.

    Counting violations that could never have been found reads as green; the
    panel must say it cannot see instead of reporting an empty set.
    """

    html = _authority_report_html(
        tmp_path,
        governed=[
            _governed_sink(
                contract=f"contract.{index}/v1",
                sink=f"pkg.mod:owner{index}",
                status="unavailable",
                resolution="unavailable",
                unresolved_reasons=["unresolved_flow"],
            )
            for index in range(5)
        ],
    )

    assert (
        "Authority cannot be asserted: 5 of 5 governed owners are unresolved." in html
    )
    assert "0 active violations across 5 governed contracts" not in html
    # the abstention must not be dressed as a clean result in its own block
    question = "Is each governed semantic contract owned by one authority?"
    block_start = html.rindex('<div class="insight-banner', 0, html.index(question))
    assert "insight-ok" not in html[block_start : block_start + 200]


def test_html_authority_insight_reports_violations_before_abstention(
    tmp_path: Path,
) -> None:
    html = _authority_report_html(
        tmp_path,
        governed=[
            _governed_sink(
                contract="baseline.publication/v1",
                sink="pkg.mod:owner",
                status="unavailable",
                resolution="unavailable",
                unresolved_reasons=["unresolved_flow"],
            )
        ],
        active_violations=1,
    )

    assert "1 active violations across 1 governed contracts" in html
    assert "Authority cannot be asserted" not in html


def test_html_authority_insight_stays_clean_when_everything_resolved(
    tmp_path: Path,
) -> None:
    html = _authority_report_html(
        tmp_path,
        governed=[
            _governed_sink(
                contract="baseline.publication/v1",
                sink="pkg.mod:owner",
                status="authoritative",
                resolution="resolved",
            )
        ],
    )

    assert "0 active violations across 1 governed contracts" in html
    assert "Authority cannot be asserted" not in html


def _candidate(
    *,
    level: str,
    score: int,
    producers: list[str],
    shared_fact: str = "effect:artifact_write:os.replace",
) -> dict[str, object]:
    return {
        "item_kind": "candidate",
        "candidate_id": f"{level}-{score}-{'-'.join(producers) or 'none'}",
        "level": level,
        "score": score,
        "producers": producers,
        "shared_fact": shared_fact,
        "independence": True,
        "semantic_divergence": False,
        "sink_statuses": ["unavailable"],
    }


_CANDIDATE_LEVELS = (
    ("exact_contract_ir", 5),
    ("same_effect_signature", 4),
    ("same_output_fact_and_input_family", 3),
    ("overlapping_transform_chain", 2),
    ("divergent_projection", 1),
)


def _all_level_candidates() -> list[dict[str, object]]:
    """One candidate per level, deliberately supplied worst-score-first."""

    return [
        _candidate(
            level=level,
            score=score,
            producers=[f"pkg.{level}:owner", f"pkg.{level}:twin"],
        )
        for level, score in reversed(_CANDIDATE_LEVELS)
    ]


def _promotion_text(html: str) -> str:
    """The proposal exactly as a human copies it: markup stripped, entities back.

    The block is highlighted TOML, so its lines are split across token spans.
    Highlighting is allowed to change how the proposal looks and forbidden to
    change what it says.
    """

    block = html[html.index('<pre class="codebox">') :]
    block = block[: block.index("</pre>")]
    return unescape(re.sub(r"<[^>]+>", "", block))


def _candidate_rows_html(html: str) -> str:
    """The discovery table's rows, anchored on the panel that owns them.

    Six tests used to slice from the literal '>Propose<'. A column header is
    not an anchor: the moment Propose earned a glossary tooltip the marker
    moved and every one of those slices silently addressed the wrong region.
    """

    start = html.index('data-clone-panel="candidates"')
    panel = html[start : html.index('data-clone-panel="suppressed"', start)]
    return panel[panel.index("<tbody>") : panel.index("</tbody>")]


def test_html_authority_renders_discovery_candidates(tmp_path: Path) -> None:
    """Computed candidates must reach the panel, not be dropped by the renderer.

    The payload emits four item kinds; the panel consumed two, so discovery
    candidates were computed, carried in the document and silently dropped.
    """

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=_all_level_candidates(),
        enforcement_enabled=False,
    )

    assert "Candidates" in html
    for level, _score in _CANDIDATE_LEVELS:
        # every level is accounted for, in the table or in the histogram
        assert level.replace("_", " ") in html
    body = _candidate_rows_html(html)
    for level, score in _CANDIDATE_LEVELS:
        if level in _STRONG_LEVELS:
            assert f"pkg.{level}:owner" in body
            # the closed vocabulary keeps its integer rank in the row
            assert f">{score}<" in body
        else:
            assert f"pkg.{level}:owner" not in body


def test_html_authority_candidate_offers_a_paste_ready_promotion(
    tmp_path: Path,
) -> None:
    """Tools propose, humans own: the promotion path is copy-paste, not a write."""

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=[
            _candidate(
                level="exact_contract_ir",
                score=5,
                producers=["pkg.alpha:publish", "pkg.beta:publish"],
            )
        ],
        enforcement_enabled=False,
    )

    # Moved expectation: the proposal is now highlighted TOML, so the line is
    # split across token spans. What must not change is the text a human
    # copies, so that is what this asserts -- tags stripped, the block reads
    # exactly as before.
    assert "[[tool.codeclone.authority]]" in _promotion_text(html)
    assert 'canonical_owner = "pkg.alpha:publish"' in _promotion_text(html)
    assert "contract_id" in html
    # the other producer is offered as an alternative, never auto-selected
    assert "pkg.beta:publish" in html
    assert "tools propose, humans own" in html.lower()


def test_html_authority_report_only_insight_counts_candidates(
    tmp_path: Path,
) -> None:
    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=_all_level_candidates(),
        enforcement_enabled=False,
    )

    assert "5 discovery candidates found" in html


def test_html_authority_states_the_unrendered_sink_population(
    tmp_path: Path,
) -> None:
    """The discovery population is stated, so no item kind drops in silence.

    Moved expectation: this pinned the caption sentence "7 semantic sinks".
    The population is still stated and still exactly once -- on the Discovery
    stat card, which always carried it. The caption was the second copy, and
    saying a number twice is not the same as accounting for it.
    """

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=_all_level_candidates(),
        sinks=7,
        enforcement_enabled=False,
    )

    assert '>7</span><span class="kpi-micro-lbl">sinks examined<' in html
    # the caption's second copy is gone (the governed table's empty message
    # legitimately says "No governed semantic sinks.", which is not a count)
    assert "Discovery examined" not in html


def test_document_orders_authority_candidates_by_score() -> None:
    """Ordering is decided in the document builder, worst-first by score."""

    payload = _metrics_payload(
        health_score=88,
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
    payload["semantic_authority"] = {
        "summary": {"enabled": True, "enforcement_enabled": False},
        "items": _all_level_candidates(),
    }
    document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo", "metrics_computed": sorted(payload)},
        metrics=payload,
    )

    items = _family_items(cast(Mapping[str, Any], document), "semantic_authority")
    scores = [item["score"] for item in items if item["item_kind"] == "candidate"]
    assert scores == [5, 4, 3, 2, 1]


def test_html_authority_promotion_handles_lone_and_absent_producers(
    tmp_path: Path,
) -> None:
    """A single producer needs no alternatives line; none at all proposes nothing."""

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=[
            _candidate(level="exact_contract_ir", score=5, producers=["pkg.only:one"]),
            _candidate(level="divergent_projection", score=1, producers=[]),
        ],
        enforcement_enabled=False,
    )

    # Moved expectation: highlighted TOML, so this asserts the copied text.
    assert 'canonical_owner = "pkg.only:one"' in _promotion_text(html)
    assert "other producers sharing this fact" not in html


_STRONG_LEVELS = (
    "exact_contract_ir",
    "same_effect_signature",
    "same_output_fact_and_input_family",
)
_WEAK_LEVELS = ("overlapping_transform_chain", "divergent_projection")


def _ranked_candidate_payload() -> dict[str, object]:
    payload = _metrics_payload(
        health_score=88,
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
    payload["semantic_authority"] = {
        "summary": {"enabled": True, "enforcement_enabled": False},
        # Producer names are chosen so identifier order is the exact reverse of
        # the required rank: passing this cannot be an alphabetical accident.
        "items": [
            _candidate(
                level="same_effect_signature",
                score=4,
                producers=["tests.test_thing:twin_a", "tests.test_thing:twin_b"],
            ),
            _candidate(
                level="same_effect_signature",
                score=4,
                producers=["zzz_pkg.alpha:owner", "zzz_pkg.beta:own"],
            ),
            _candidate(
                level="same_effect_signature",
                score=4,
                producers=[
                    "zzz_pkg.wide:one",
                    "zzz_pkg.wide:two",
                    "zzz_pkg.wide:three",
                ],
            ),
            _candidate(
                level="exact_contract_ir",
                score=5,
                producers=["tests.test_exact:twin"],
            ),
        ],
    }
    return payload


def _ranked_document() -> Mapping[str, Any]:
    return cast(
        Mapping[str, Any],
        build_report_document(
            func_groups={},
            block_groups={},
            segment_groups={},
            meta={"scan_root": "/repo", "metrics_computed": ["semantic_authority"]},
            metrics=_ranked_candidate_payload(),
        ),
    )


def test_document_ranks_candidates_by_level_then_production_then_breadth() -> None:
    """Level stays primary; production leads its level; breadth breaks the tie."""

    items = _family_items(_ranked_document(), "semantic_authority")
    candidates = [item for item in items if item["item_kind"] == "candidate"]
    producers = [tuple(item["producers"]) for item in candidates]

    # level 5 first, even though its only producer is a test
    assert producers[0] == ("tests.test_exact:twin",)
    # inside level 4: production before tests, and the broader group first
    assert producers[1] == (
        "zzz_pkg.wide:one",
        "zzz_pkg.wide:three",
        "zzz_pkg.wide:two",
    )
    assert producers[2] == ("zzz_pkg.alpha:owner", "zzz_pkg.beta:own")
    assert producers[3] == ("tests.test_thing:twin_a", "tests.test_thing:twin_b")


def test_document_records_the_candidate_source_kind_it_ranked_on() -> None:
    items = _family_items(_ranked_document(), "semantic_authority")
    kinds = {
        next(iter(item["producers"])): item["source_kind"]
        for item in items
        if item["item_kind"] == "candidate"
    }
    assert kinds["zzz_pkg.wide:one"] == "production"
    assert kinds["tests.test_exact:twin"] == "tests"


def test_html_authority_table_cuts_weak_levels_to_a_histogram(
    tmp_path: Path,
) -> None:
    """The iceberg is visible as numbers, not as thousands of DOM rows."""

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=[
            _candidate(
                level="exact_contract_ir",
                score=5,
                producers=["codeclone.strong:owner"],
            ),
            _candidate(
                level="overlapping_transform_chain",
                score=2,
                producers=["codeclone.weak:owner"],
            ),
            _candidate(
                level="divergent_projection",
                score=1,
                producers=["codeclone.weaker:owner"],
            ),
        ],
        enforcement_enabled=False,
    )

    body = _candidate_rows_html(html)
    assert "codeclone.strong:owner" in body
    assert "codeclone.weak:owner" not in body
    assert "codeclone.weaker:owner" not in body
    # Moved expectation: the counts were prose ("overlapping transform chain
    # 1"). A distribution is scanned, not read, so it is now a count strip --
    # value first, then the level it counts. Nothing is hidden either way.
    strip = html[html.index('class="level-strip"') :]
    strip = strip[: strip.index("</div>")]
    for level in ("overlapping transform chain", "divergent projection"):
        assert f'>1</span><span class="kpi-micro-lbl">{level}<' in strip
    # and the cut still names the route to the levels that earn no row
    assert "check_authority" in html


def test_html_authority_promotion_is_collapsed_and_copyable(tmp_path: Path) -> None:
    """Fifty open TOML blocks must be impossible by construction."""

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=[
            _candidate(
                level="exact_contract_ir", score=5, producers=["codeclone.a:owner"]
            )
        ],
        enforcement_enabled=False,
    )

    assert '<details class="authority-promotion">' in html
    assert "<summary" in html
    assert "data-authority-copy" in html
    # collapsed by construction: no open attribute on the proposal
    assert '<details class="authority-promotion" open' not in html


def test_html_authority_candidate_without_producers_proposes_nothing(
    tmp_path: Path,
) -> None:
    """A candidate with no producers has no owner to propose."""

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=[_candidate(level="exact_contract_ir", score=5, producers=[])],
        enforcement_enabled=False,
    )

    body = _candidate_rows_html(html)
    assert "[[tool.codeclone.authority]]" not in body
    assert "authority-promotion" not in body


def test_html_build_span_and_counter_names_are_reviewed() -> None:
    """HTML build instrumentation is product telemetry, not a debug probe.

    The observer validates every span name and counter key against a reviewed
    allowlist, so instrumentation that is not registered raises at runtime on
    exactly the profiled run it was added to explain.
    """

    assert set(HTML_BUILD_SPAN_NAMES) <= SPAN_NAMES, (
        f"unreviewed HTML span names: {sorted(set(HTML_BUILD_SPAN_NAMES) - SPAN_NAMES)}"
    )
    assert set(HTML_BUILD_COUNTER_KEYS) <= COUNTER_KEYS, (
        "unreviewed HTML counter keys: "
        f"{sorted(set(HTML_BUILD_COUNTER_KEYS) - COUNTER_KEYS)}"
    )


def _authority_producers(count: int) -> list[str]:
    return [
        f"pkg.module{index:02d}:producer_with_a_long_qualname" for index in range(count)
    ]


def test_html_authority_row_never_dumps_an_unbounded_producer_string(
    tmp_path: Path,
) -> None:
    """A cell is not a place to paste a thousand qualnames.

    The panel dumped every producer comma-joined into one cell: forty thousand
    characters on this repository, unreadable and unclickable.
    """

    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=[
            _candidate(
                level="exact_contract_ir",
                score=5,
                producers=_authority_producers(40),
            )
        ],
        enforcement_enabled=False,
    )

    body = _candidate_rows_html(html)
    row = re.findall(r"<tr>(.*?)</tr>", body, re.S)[0]
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    visible = [" ".join(re.sub(r"<[^>]+>", " ", cell).split()) for cell in cells]

    # the owner leads the row, on its own, and is the thing users take away
    assert visible[0].startswith("pkg.module00:producer_with_a_long_qualname")
    assert "data-authority-copy" in cells[0]
    # the rest are disclosed, not dumped: summary states the count only
    producers_cell = next(cell for cell in cells if "authority-producers" in cell)
    summary = re.search(r"<summary[^>]*>(.*?)</summary>", producers_cell, re.S)
    assert summary is not None
    assert "39 more" in summary.group(1)
    assert "<details" in producers_cell
    # nothing is an endless string when collapsed: measure what the row shows
    # before any disclosure is opened
    collapsed = [
        " ".join(
            re.sub(
                r"<[^>]+>",
                " ",
                re.sub(
                    r"</summary>.*?</details>", "</summary></details>", cell, flags=re.S
                ),
            ).split()
        )
        for cell in cells
    ]
    assert max(len(cell) for cell in collapsed) < 120, collapsed


def test_html_authority_lone_producer_needs_no_disclosure(tmp_path: Path) -> None:
    html = _authority_report_html(
        tmp_path,
        governed=[],
        candidates=[
            _candidate(level="exact_contract_ir", score=5, producers=["pkg.only:one"])
        ],
        enforcement_enabled=False,
    )

    body = _candidate_rows_html(html)
    assert "authority-producers" not in body


def test_html_authority_tabs_speak_product_language(tmp_path: Path) -> None:
    """Tab labels name what a user looks for, with the domain term on hover."""

    html = _authority_report_html(
        tmp_path,
        governed=[
            _governed_sink(
                contract="baseline.publication/v1",
                sink="pkg.mod:owner",
                status="authoritative",
                resolution="resolved",
            )
        ],
        candidates=[
            _candidate(level="exact_contract_ir", score=5, producers=["pkg.a:owner"])
        ],
    )

    nav = html[html.index('data-subtab-group="semantic-authority"') :][:1200]
    assert ">Contracts " in nav
    assert ">Discovery " in nav
    # the jargon is demoted, not deleted: never the label, always the tooltip
    assert ">Governed sinks " not in nav
    assert 'title="Governed sinks' in nav


def test_html_report_every_main_tab_renders_an_icon() -> None:
    """No tab may ship as bare text while its siblings carry icons.

    Authority was the only main tab without one. The invariant is written over
    every tab rather than that one, so the next tab added cannot arrive naked.
    """

    html = build_html_report(
        func_groups={}, block_groups={}, segment_groups={}, title="Icons"
    )

    buttons = re.findall(
        r'<button class="main-tab"[^>]*data-tab="([a-z-]+)"[^>]*>(.*?)</button>',
        html,
        re.S,
    )
    assert buttons, "no main tabs rendered"
    naked = [tab for tab, markup in buttons if "main-tab-icon" not in markup]
    assert not naked, f"main tabs rendered without an icon: {naked}"


def test_location_paths_resolve_against_scan_root(tmp_path: Path) -> None:
    root = str(tmp_path)
    ctx = cast(
        "Any",
        SimpleNamespace(
            scan_root=root,
            relative_path=lambda filepath: filepath.removeprefix(f"{root}/"),
        ),
    )
    # An item with only an absolute filepath is relativized by the context.
    assert relative_location_path(ctx, {"filepath": f"{root}/pkg/a.py"}) == "pkg/a.py"
    # A relative filepath resolves under the scan root.
    assert location_file_target(
        ctx, {"filepath": "pkg/a.py"}, relative_path="pkg/a.py"
    ) == str((tmp_path / "pkg" / "a.py").resolve())
    # Without a filepath, the relative path resolves under the scan root.
    assert location_file_target(ctx, {}, relative_path="pkg/b.py") == str(
        (tmp_path / "pkg" / "b.py").resolve()
    )


def _stat_card(html: str, label: str) -> str:
    """The markup of exactly one named stat card, and nothing around it.

    Scoped to a single ``meta-item`` on purpose: a pattern allowed to run over
    the whole document can satisfy itself from another card's digits and report
    a pass that means nothing.

    The label is matched without its tooltip. ``glossary_tip`` returns an empty
    string for a label the glossary does not carry, so a locator that required
    the ``kpi-help`` span made these pins depend on the glossary rather than on
    the figure they exist to check -- and failed intermittently in the full
    suite while passing in isolation.
    """

    match = re.search(rf'<div class="meta-label">{re.escape(label)} ?<', html)
    assert match is not None, f"no stat card labelled {label!r}"
    start = match.start()
    card_start = html.rfind('<div class="meta-item">', 0, start)
    end = html.find('<div class="meta-item">', start)
    return html[card_start : end if end != -1 else len(html)]


def _stat_card_value(html: str, label: str) -> str:
    """The value the HTML report prints on one named stat card."""

    match = re.search(r'<div class="meta-value[^"]*">([^<]*)', _stat_card(html, label))
    assert match is not None, f"card {label!r} has no value"
    return match.group(1)


def _stat_card_badge(html: str, label: str, badge: str) -> str:
    """The figure printed on one named micro-badge of one named stat card."""

    match = re.search(
        r'<span class="kpi-micro-val">([^<]*)</span>'
        rf'<span class="kpi-micro-lbl">{re.escape(badge)}</span>',
        _stat_card(html, label),
    )
    assert match is not None, f"card {label!r} has no {badge!r} badge"
    return match.group(1)


def _contradictory_coupling_document() -> dict[str, Any]:
    """One document whose summary and rows deliberately disagree.

    A consumer that reports the document's own figure is indifferent to the
    rows; a consumer that re-derives the figure from the rows answers with the
    other number. Agreement between the two on an honest document proves
    nothing, which is exactly how the divergence below survived: on this
    repository the report said ``average 1.41`` and the HTML card said ``2.9``,
    and both looked plausible next to a table nobody totalled by hand.
    """

    return build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={
            "coupling": {
                "summary": {"average": 1.41, "max": 12, "high_risk": 1},
                "classes": [
                    {
                        "qualname": "pkg.a:A",
                        "relative_path": "pkg/a.py",
                        "cbo": 12,
                        "risk": "high",
                    },
                    {
                        "qualname": "pkg.b:B",
                        "relative_path": "pkg/b.py",
                        "cbo": 0,
                        "risk": "low",
                    },
                    {
                        "qualname": "pkg.c:C",
                        "relative_path": "pkg/c.py",
                        "cbo": 0,
                        "risk": "low",
                    },
                ],
            }
        },
    )


def test_html_average_card_reports_the_document_figure_not_a_recount() -> None:
    """The HTML must not answer a metric question differently from the report.

    ``Avg CBO`` was computed in the renderer over rows with a positive value,
    so it divided by the classes that happen to be coupled instead of by the
    measured population. Text, Markdown, SARIF and the CLI all print
    ``metrics.summary.coupling.average``; the HTML printed its own number under
    the same name.
    """

    document = _contradictory_coupling_document()
    coupling_summary = document["metrics"]["families"]["coupling"]["summary"]

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_document=document,
    )

    assert coupling_summary["average"] == 1.41
    assert _stat_card_value(html, "Avg CBO") == "1.4"


def test_html_population_badge_reports_the_measured_total() -> None:
    """The population badge counts the measured classes, not the coupled ones.

    Same defect, second face: the badge beside the average showed the length of
    the filtered row list, so a document measuring three classes advertised
    one.
    """

    document = _contradictory_coupling_document()

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_document=document,
    )

    assert document["metrics"]["families"]["coupling"]["summary"]["total"] == 3
    assert _stat_card_badge(html, "Avg CBO", "classes") == "3"


def test_html_authority_counts_come_from_the_summary_not_from_the_rows() -> None:
    """Authority figures are read, not recounted, on a contradictory document.

    Five counts on this panel were re-derived by filtering ``items``. The sink
    count was the worst of them: ``sum(1 for ...) or summary["sinks"]`` reads
    as a fallback but is a silent substitution, and it is the shape that would
    quietly survive a projection that stops emitting sink rows.

    The document below says one thing in its summary and another in its rows.
    A renderer that reports the summary is unmoved by the rows; a renderer that
    recounts answers with the row figures, so each recount dies here.

    Every kind carries a non-zero row count that differs from its summary
    figure, and that is load-bearing rather than decoration. An earlier version
    of this fixture left ``items`` empty, which made ``sum(...) or
    summary["sinks"]`` fall through to the summary and return the right number
    for the wrong reason -- the mutation restoring that expression survived.
    The pin was reproducing the coincidence that hid the defect instead of
    excluding it.
    """

    document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={
            "semantic_authority": {
                "summary": {
                    "enabled": True,
                    "enforcement_enabled": True,
                    "registry_contracts": 9,
                    "sinks": 77,
                    "candidates": 55,
                    "governed_sinks": 33,
                    "active_violations": 11,
                    "suppressed_violations": 22,
                },
                "items": [
                    {"item_kind": "sink", "sink_identity": "pkg.a:one"},
                    {"item_kind": "sink", "sink_identity": "pkg.a:two"},
                    {
                        "item_kind": "governed_sink",
                        "contract_id": "c1",
                        "sink_identity": "pkg.a:one",
                        "authority_status": "resolved",
                    },
                    {
                        "item_kind": "violation",
                        "contract_id": "c1",
                        "kind": "duplicate_authority",
                        "sink_identity": "pkg.a:one",
                        "suppressed": False,
                    },
                    {
                        "item_kind": "violation",
                        "contract_id": "c1",
                        "kind": "duplicate_authority",
                        "sink_identity": "pkg.a:two",
                        "suppressed": True,
                    },
                    {
                        "item_kind": "candidate",
                        "candidate_id": "cand-1",
                        "level": "exact_contract_ir",
                        "score": 90,
                        "producers": ["pkg.a:one"],
                    },
                    {
                        "item_kind": "candidate",
                        "candidate_id": "cand-2",
                        "level": "exact_contract_ir",
                        "score": 80,
                        "producers": ["pkg.a:two"],
                    },
                    {
                        "item_kind": "candidate",
                        "candidate_id": "cand-3",
                        "level": "exact_contract_ir",
                        "score": 70,
                        "producers": ["pkg.a:three"],
                    },
                ],
            }
        },
    )

    html = build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        report_document=document,
    )

    assert _stat_card_value(html, "Violations") == "11"
    assert _stat_card_badge(html, "Violations", "suppressed") == "22"
    assert _stat_card_badge(html, "Governed contracts", "owners") == "33"
    assert _stat_card_value(html, "Discovery") == "55"
    assert _stat_card_badge(html, "Discovery", "sinks examined") == "77"
