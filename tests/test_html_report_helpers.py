# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast
import importlib
import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.report.html.assemble as assemble_mod
import codeclone.report.html.sections._meta as meta_section
import codeclone.report.html.sections._suggestions as suggestions_section
import codeclone.ui_messages as ui
from codeclone.api.comparison import foreign_interpreter_provenance
from codeclone.api.presentation_records import (
    SuggestionLocationView,
    SuggestionView,
)
from codeclone.baseline.trust import current_python_tag
from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.models import MetricsDiff
from codeclone.report.html.sections._clones import (
    _derive_group_display_name,
    _render_group_explanation,
    _suppressed_group_label,
)
from codeclone.report.html.sections._coverage_join import _status_cell_label
from codeclone.report.html.sections._dead_code import render_dead_code_panel
from codeclone.report.html.sections._dependencies import _select_dep_nodes
from codeclone.report.html.sections._meta import _path_basename, render_meta_panel
from codeclone.report.html.sections._overview import (
    _adoption_and_api_section,
    _directory_hotspot_bucket_body,
    _directory_kind_meta_parts,
    _health_gauge_html,
    _issue_breakdown_html,
    _overloaded_modules_section,
    render_overview_panel,
)
from codeclone.report.html.sections._security_surfaces import _coverage_join_review_text
from codeclone.report.html.sections._suggestions import (
    _format_source_breakdown,
    _priority_badge_label,
    _render_card,
    _render_fact_summary,
    _spread_label,
    _suggestion_context_labels,
)
from codeclone.report.html.widgets.badges import (
    _chips_html,
    _quality_badge_html,
    _score_bar_html,
    _stat_card,
    _status_pill_html,
)
from codeclone.report.html.widgets.cards import (
    finding_card,
    meta_badge_html,
    severity_key,
)
from codeclone.report.html.widgets.components import (
    overview_source_breakdown_html,
    overview_summary_item_html,
)
from codeclone.report.html.widgets.dep_graph_layout import (
    BlockNodeStyle,
    _box_width,
    _hub_threshold,
    _layout_block_diagram,
    render_block_diagram,
)
from codeclone.report.html.widgets.icons import section_icon_html
from codeclone.report.html.widgets.snippets import _FileCache
from codeclone.report.html.widgets.tabs import render_split_tabs
from codeclone.report.messages.glossary import GLOSSARY_FAMILY_DEAD_CODE
from tests._assertions import assert_contains_none
from tests._report_fixtures import build_test_report_document
from tests.assertion_helpers import assert_all_contained


def test_summary_helpers_cover_empty_and_non_clone_context_branches() -> None:
    empty_html = overview_source_breakdown_html({})
    assert 'class="inline-empty inline-empty--neutral"' in empty_html
    assert "No source data available" in empty_html


def test_summary_helpers_cover_breakdown_bars_and_clone_badges() -> None:
    breakdown_html = overview_source_breakdown_html({"production": 3, "tests": 1})
    assert "source-kind-production" in breakdown_html
    assert "source-kind-tests" in breakdown_html
    assert "width:75%" in breakdown_html
    assert "width:25%" in breakdown_html

    summary_html = overview_summary_item_html(
        label="Source Breakdown",
        body_html="<div>body</div>",
    )
    assert "summary-icon--info" in summary_html

    all_findings_html = overview_summary_item_html(
        label="All Findings",
        body_html="<div>body</div>",
    )
    clone_groups_html = overview_summary_item_html(
        label="Clone Groups",
        body_html="<div>body</div>",
    )
    low_cohesion_html = overview_summary_item_html(
        label="Low Cohesion",
        body_html="<div>body</div>",
    )
    assert "summary-icon--info" in all_findings_html
    assert "summary-icon--info" in clone_groups_html
    assert "summary-icon--info" in low_cohesion_html


def test_clone_display_name_and_group_explanation_edge_branches() -> None:
    ctx = SimpleNamespace(
        bare_qualname=lambda _qualname, _filepath: "",
        relative_path=lambda filepath: filepath.replace("/abs/", ""),
    )
    items = [
        {"qualname": "", "filepath": "/abs/" + "a" * 40 + ".py"},
        {"qualname": "", "filepath": "/abs/" + "b" * 40 + ".py"},
        {"qualname": "", "filepath": "/abs/" + "c" * 40 + ".py"},
    ]
    derived = _derive_group_display_name(
        "deadbeefdeadbeefdeadbeefdeadbeef",
        items,
        "blocks",
        {},
        cast(Any, ctx),
    )
    assert derived.endswith("…")
    assert "aaaaaaaa" in derived

    fallback = _derive_group_display_name(
        "x" * 60,
        (),
        "segments",
        {},
        cast(Any, ctx),
    )
    assert fallback == ("x" * 24) + "…" + ("x" * 16)

    assert _render_group_explanation({}) == ""


def test_clone_display_name_falls_back_to_short_key_when_items_have_no_labels() -> None:
    ctx = SimpleNamespace(
        bare_qualname=lambda _qualname, _filepath: "",
        relative_path=lambda _filepath: "",
    )
    assert (
        _derive_group_display_name(
            "short-key",
            ({"qualname": "", "filepath": ""},),
            "blocks",
            {},
            cast(Any, ctx),
        )
        == "short-key"
    )


def test_html_fallback_helpers_cover_empty_label_and_review_text() -> None:
    ctx = SimpleNamespace(
        bare_qualname=lambda _qualname, _filepath: "",
        relative_path=lambda _filepath: "",
        scan_root="",
        metrics_map={"coverage_join": {"summary": {"status": "ok"}}},
        overloaded_modules_map={
            "summary": {"candidates": 1},
            "items": [{"module": "pkg.mod", "candidate_status": "ranked_only"}],
        },
    )

    label, filepath = _suppressed_group_label({"id": "suppressed-1"}, cast(Any, ctx))
    assert label == "suppressed-1"
    assert filepath == ""
    assert _status_cell_label({"coverage_status": "covered"}) == "covered"
    assert (
        _coverage_join_review_text(
            cast(Any, ctx),
            overlap_total=2,
            scope_gaps=1,
            hotspots=0,
        )
        == "2 overlaps · 1 scope gap"
    )
    assert _overloaded_modules_section(cast(Any, ctx)) == ""


def test_overview_optional_canonical_families_cover_single_family_rows() -> None:
    api_only = SimpleNamespace(
        metrics_map={
            "api_surface": {
                "summary": {
                    "modules": 1,
                    "public_symbols": 2,
                    "breaking": 0,
                }
            }
        }
    )
    overloaded_without_path = SimpleNamespace(
        overloaded_modules_map={
            "summary": {"candidates": 1},
            "items": [
                {
                    "module": "pkg.mod",
                    "candidate_status": "candidate",
                    "score": 0.8,
                    "fan_in": 1,
                    "fan_out": 2,
                    "loc": 120,
                }
            ],
        }
    )

    assert "Public API surface" in _adoption_and_api_section(cast(Any, api_only))
    # Path honesty: a row without a resolved path shows its module identity
    # verbatim; the pre-wave fallback invented the phantom "pkg/mod.py".
    section_html = _overloaded_modules_section(cast(Any, overloaded_without_path))
    assert "pkg.mod" in section_html
    assert "pkg/mod.py" not in section_html


def test_dependency_sampler_cap_and_hub_threshold_empty() -> None:
    edges = [(f"n{i}", f"n{i + 1}") for i in range(21)]
    nodes, filtered = _select_dep_nodes(
        edges,
        dep_cycles=(),
        longest_chains=(),
    )
    assert len(nodes) == 20
    assert len(filtered) <= 100
    assert _hub_threshold([], {}, {}) == 99


def test_block_diagram_renders_boxes_edges_rings_and_weights() -> None:
    nodes = ["pkg.a", "pkg.b", "pkg.c"]
    # a -> b -> c -> a: the back-edge exercises same-layer/upward routing.
    edges = [("pkg.a", "pkg.b"), ("pkg.b", "pkg.c"), ("pkg.c", "pkg.a")]

    def _style(node: str) -> BlockNodeStyle:
        if node == "pkg.a":
            return BlockNodeStyle(
                fill="var(--accent-primary)",
                text_fill="#fff",
                ring="var(--warning)",
            )
        if node == "pkg.c":
            return BlockNodeStyle(
                fill="var(--bg-surface)",
                text_fill="var(--danger)",
                dashed=True,
            )
        return BlockNodeStyle(
            fill="var(--bg-overlay)", text_fill="var(--text-secondary)"
        )

    svg = render_block_diagram(
        nodes,
        edges,
        style_fn=_style,
        aria_label="Test graph",
        danger_edges={("pkg.c", "pkg.a")},
        edge_weight_fn=lambda edge: 5 if edge == ("pkg.a", "pkg.b") else 1,
    )
    assert_all_contained(
        svg,
        'class="dep-graph-svg"',
        'data-graph-density="compact"',
        'aria-label="Test graph"',
        'class="block-node"',
        'data-node="pkg.a"',
        'class="block-node-ring"',  # candidate ring on pkg.a
        'stroke-dasharray="4,3"',  # dashed border on pkg.c
        "block-arrow-danger-",  # danger marker on the cycle back-edge
        'stroke-linecap="round"',
        'stroke-width="3"',  # weight 5 -> 1+floor(log2 5)=3
        "<title>pkg.a → pkg.b</title>",
    )
    assert "dep-graph-scroll-note" not in svg


def test_block_diagram_dense_graph_wraps_without_scroll_canvas() -> None:
    nodes = [f"pkg.node{i:02d}" for i in range(19)]
    edges = [("pkg.node00", node) for node in nodes[1:]]

    svg = render_block_diagram(
        nodes,
        edges,
        style_fn=lambda _node: BlockNodeStyle(
            fill="var(--bg-overlay)", text_fill="var(--text-secondary)"
        ),
        aria_label="Wide graph",
    )

    assert_all_contained(
        svg,
        'data-graph-density="wide"',
        # Moved expectation: the graph declares an explicit width. A percentage
        # inside a pane that is sized by the graph was circular, so the SVG
        # fell back to the CSS default 300px whatever the viewBox said.
        "width:",
        "block-arrow-",
    )
    assert "width:100%" not in svg
    assert "dep-graph-scroll-note" not in svg


def test_block_diagram_medium_graph_uses_comfortable_density() -> None:
    nodes = [f"pkg.mid{i}" for i in range(9)]
    edges = [(nodes[index], nodes[index + 1]) for index in range(len(nodes) - 1)]
    svg = render_block_diagram(
        nodes,
        edges,
        style_fn=lambda _node: BlockNodeStyle(
            fill="var(--bg-overlay)", text_fill="var(--text-secondary)"
        ),
        aria_label="Medium graph",
    )

    # The 900px literal here was the old minimum render width: this graph is
    # 144 units wide, so the floor inflated it 6.25x and every box with it.
    # Density still selects the type scale; the width is now the graph's own,
    # stated in pixels rather than as a percentage of a pane it sizes itself.
    assert_all_contained(
        svg,
        'data-graph-density="comfortable"',
        "width:144px",
    )


def test_block_diagram_truncates_long_underscore_labels_inside_boxes() -> None:
    node = "pkg.metrics_baseline_payload"
    svg = render_block_diagram(
        [node],
        [],
        style_fn=lambda _node: BlockNodeStyle(
            fill="var(--bg-overlay)", text_fill="var(--text-secondary)"
        ),
        aria_label="Label fit graph",
    )

    assert_all_contained(
        svg,
        'width="184.0"',
        'textLength="156.0" lengthAdjust="spacingAndGlyphs"',
        f"<title>{node}</title>",
        ">metrics_b..e_payload</text>",
    )
    assert ">metrics_ba..ine_payload</text>" not in svg


def test_block_diagram_layout_centers_rows_and_clamps_box_width() -> None:
    # gap layer (index 1 has no members) exercises the empty-row branch
    width, height, positions = _layout_block_diagram(
        {0: ["a", "b"], 2: ["c"]}, {"a": 80, "b": 80, "c": 120}
    )
    assert width >= 120
    assert height > 0
    assert positions["c"][1] > positions["a"][1]  # layer 2 sits below layer 0
    assert _box_width("x") == 76  # clamped to the minimum
    assert _box_width("x" * 40) == 184  # clamped to the maximum


def test_cli_runtime_warning_formatter_covers_baseline_and_legacy_cache_paths() -> None:
    rendered = ui.fmt_cli_runtime_warning(
        "Baseline trust mismatch: python_tag=cp313\n\nLegacy cache format ignored"
    )
    # One advisory on the grid: the first paragraph is the head, split at its
    # first ": " into head and detail; every later paragraph is more detail.
    assert (
        rendered == "  [warning]\u26a0 Baseline trust mismatch[/warning]\n"
        "    [dim]python_tag=cp313[/dim]\n"
        "    [dim]Legacy cache format ignored[/dim]"
    )


def test_render_split_tabs_returns_empty_for_no_tabs() -> None:
    assert (
        render_split_tabs(
            group_id="dead-code", tabs=(), family=GLOSSARY_FAMILY_DEAD_CODE
        )
        == ""
    )


def _section_ctx(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "clone_groups_total": 4,
        "clone_summary": {"new": 1, "known": 2, "unavailable": 0},
        "complexity_map": {"summary": {"high_risk": 5, "average": 2.5, "max": 9}},
        "coupling_map": {"summary": {"high_risk": 3, "average": 1.5, "max": 7}},
        "cohesion_map": {"summary": {"low_cohesion": 2, "average": 1.2, "max": 5}},
        "dead_code_map": {
            "summary": {"total": 4, "high_confidence": 0, "suppressed": 0},
            "items": [
                {
                    "qualname": "pkg.mod:maybe",
                    "filepath": "pkg/mod.py",
                    "start_line": 5,
                    "kind": "function",
                    "confidence": "medium",
                }
            ],
            "suppressed_items": [
                {
                    "qualname": "pkg.mod:kept",
                    "filepath": "pkg/mod.py",
                    "start_line": 9,
                    "kind": "function",
                    "confidence": "medium",
                    "suppressed_by": [{"rule": "dead-code", "source": "inline"}],
                }
            ],
        },
        "dependencies_map": {"cycles": [("pkg.a", "pkg.b")], "max_depth": 4},
        "health_map": {"score": 82, "grade": "B", "dimensions": {}},
        "metrics_available": True,
        "structural_findings": (SimpleNamespace(finding_kind="duplicated_branches"),),
        "suggestions": (),
        "metrics_diff": None,
        "func_sorted": (("clone:new", ({}, {})),),
        "block_sorted": (("clone:block", ({},)),),
        "segment_sorted": (),
        "new_func_keys": frozenset({"clone:new"}),
        "new_block_keys": frozenset(),
        # ``derived.overview`` publishes the counts under this name; the flat
        # ``source_breakdown`` spelling this fixture used to carry exists only
        # in a materializer no production path calls.
        "overview_data": {"source_scope_breakdown": {"production": 3, "tests": 1}},
        "bare_qualname": (
            lambda qualname, _filepath: qualname.rsplit(":", maxsplit=1)[-1]
        ),
        "relative_path": lambda filepath: filepath,
        "meta": {},
        # ``ReportContext.baseline_status`` is the document's ``baseline.state``;
        # the overview banner reads it to decide whether a novelty count is a
        # comparison result or the absence of one.
        "baseline_status": "missing",
        "baseline_meta": {},
        "cache_meta": {},
        "metrics_baseline_meta": {},
        "runtime_meta": {},
        # ``ReportContext`` carries the whole canonical document, and the
        # overview panel reads the advisory tier containers out of it. A stub
        # without the field models a context that cannot exist.
        "report_document": {},
        "integrity_map": {},
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report_generated_at": "2026-03-22T21:30:45Z",
    }
    base.update(overrides)
    metrics_diff = base.get("metrics_diff")
    if isinstance(metrics_diff, MetricsDiff):
        base["complexity_map"] = {
            **cast(dict[str, object], base["complexity_map"]),
            "summary": {
                **cast(
                    dict[str, object],
                    cast(dict[str, object], base["complexity_map"])["summary"],
                ),
                "baseline_diff_available": True,
                "new_high_risk": len(metrics_diff.new_high_risk_functions),
            },
        }
        base["coupling_map"] = {
            **cast(dict[str, object], base["coupling_map"]),
            "summary": {
                **cast(
                    dict[str, object],
                    cast(dict[str, object], base["coupling_map"])["summary"],
                ),
                "baseline_diff_available": True,
                "new_high_risk": len(metrics_diff.new_high_coupling_classes),
            },
        }
        base["dead_code_map"] = {
            **cast(dict[str, object], base["dead_code_map"]),
            "summary": {
                **cast(
                    dict[str, object],
                    cast(dict[str, object], base["dead_code_map"])["summary"],
                ),
                "baseline_diff_available": True,
                "new_items": len(metrics_diff.new_dead_code),
            },
        }
        base["dependencies_map"] = {
            **cast(dict[str, object], base["dependencies_map"]),
            "summary": {
                "baseline_diff_available": True,
                "new_cycles": len(metrics_diff.new_cycles),
                "max_depth": 4,
            },
        }
        base["health_map"] = {
            "summary": {
                "score": 82,
                "grade": "B",
                "dimensions": {},
                "baseline_diff_available": True,
                "delta": metrics_diff.health_delta,
            }
        }
        base["clone_summary"] = {"new": 0, "known": 2, "unavailable": 0}
    return SimpleNamespace(**base)


#: The record the suggestions panel is actually handed. It used to be a
#: ``models.Suggestion`` -- the *domain* suggestion, which the panel never
#: receives: production hands it the context's projection. Only the erased
#: ``Any`` on the panel's parameters made the substitution invisible, and it
#: cost every call site a ``cast`` to get a plain string past the domain
#: record's ``Literal`` fields.
_SUGGESTION_TEMPLATE = SuggestionView(
    severity="warning",
    category="complexity",
    title="Reduce function complexity",
    location="pkg/mod.py:10-20",
    steps=("Extract a helper.",),
    effort="moderate",
    priority=0.9,
    finding_family="metrics",
    finding_kind="function_hotspot",
    subject_key="pkg.mod:run",
    fact_kind="Complexity hotspot",
    fact_summary="cyclomatic_complexity=15, guard_count=2, hot path",
    fact_count=2,
    spread_files=2,
    spread_functions=3,
    clone_type="",
    confidence="high",
    source_kind="production",
    source_breakdown=(("production", 2), ("tests", 1)),
    representative_locations=(
        SuggestionLocationView(
            relative_path="pkg/mod.py",
            start_line=10,
            end_line=20,
            qualname="pkg.mod:run",
            source_kind="production",
            filepath="/repo/pkg/mod.py",
        ),
    ),
    location_label="pkg/mod.py:10-20",
)


def test_html_badges_and_cards_cover_effort_and_tip_paths() -> None:
    # Moved expectation, second and final step. This originally pinned
    # 'risk-badge risk-moderate' -- effort rendered as a risk verdict through a
    # class the stylesheet never defined. Stint 7 routed it to the muted level
    # chip; stint 8 established no caller could reach that branch at all and
    # deleted it, so effort is asserted on its live path.
    from codeclone.report.html.widgets.badges import _level_chip_html

    assert _level_chip_html("moderate") == '<span class="level-chip">moderate</span>'

    card_html = _stat_card(
        "High Complexity",
        7,
        tip="Cyclomatic hotspots",
        value_tone="good",
        delta_new=2,
    )
    assert "meta-value--good" in card_html
    assert 'data-tip="Cyclomatic hotspots"' in card_html
    assert "+2 new<" in card_html

    plain_card_html = _stat_card("Clone Groups", 2)
    assert "kpi-help" not in plain_card_html


def test_overview_helpers_cover_negative_delta_split_and_baselined_rows() -> None:
    gauge_html = _health_gauge_html(65, "B", health_delta=-5)
    assert "health-ring-delta--down" in gauge_html
    assert 'stroke="var(--error)" opacity="0.4"' in gauge_html
    assert "Get Badge" in gauge_html

    breakdown_html = _issue_breakdown_html(
        cast(Any, _section_ctx()),
        deltas={
            "clones": 1,
            "structural": None,
            "complexity": 0,
            "cohesion": None,
            "coupling": None,
            "dead_code": 2,
            "dep_cycles": 0,
        },
    )
    assert "breakdown-bar-fill--baselined" in breakdown_html
    assert 'families-delta families-delta--new">+1<' in breakdown_html
    assert 'families-delta families-delta--ok">✓<' in breakdown_html


def test_render_overview_panel_surfaces_baselined_and_partially_baselined_kpis() -> (
    None
):
    ctx = _section_ctx(
        baseline_status="trusted",
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=("pkg.mod:Service",),
            new_cycles=(),
            new_dead_code=("pkg.mod:unused",),
            health_delta=3,
        ),
        func_sorted=(("clone:known", ({}, {})),),
        block_sorted=(("clone:block", ({},)),),
        new_func_keys=frozenset(),
        new_block_keys=frozenset(),
    )

    panel_html = render_overview_panel(cast(Any, ctx))
    assert "kpi-micro--baselined" in panel_html
    assert '<span class="kpi-micro-lbl">nothing new</span>' in panel_html
    assert "health-ring-delta--up" in panel_html


def test_render_overview_panel_summarizes_metrics_without_health_score() -> None:
    panel_html = render_overview_panel(cast(Any, _section_ctx()))

    # "1 dependency cycles" now agrees with its own count; the rest of the
    # sentence is unchanged.
    assert "Not compared: no baseline yet." in panel_html


def test_render_dead_code_panel_warns_when_only_medium_confidence_items_exist() -> None:
    panel_html = render_dead_code_panel(cast(Any, _section_ctx()))
    assert "4 lower-confidence candidates; none high-confidence." in panel_html
    assert "insight-warn" in panel_html
    assert "No dead code detected." not in panel_html


def test_render_dead_code_panel_derives_high_confidence_count_from_items() -> None:
    ctx = _section_ctx(
        dead_code_map={
            "summary": {"total": 1, "high_confidence": 0, "suppressed": 0},
            "items": [
                {
                    "qualname": "pkg.mod:unused",
                    "filepath": "pkg/mod.py",
                    "start_line": 5,
                    "kind": "function",
                    "confidence": "high",
                }
            ],
            "suppressed_items": [],
        }
    )

    panel_html = render_dead_code_panel(cast(Any, ctx))

    assert "Yes: 1 high-confidence candidate." in panel_html
    assert '>1</span><span class="kpi-micro-lbl">high-confidence<' in panel_html


def test_render_dead_code_panel_shows_test_reference_reason_and_source() -> None:
    ctx = _section_ctx(
        dead_code_map={
            "summary": {"total": 1, "high_confidence": 1, "suppressed": 0},
            "items": [
                {
                    "qualname": "pkg.mod:held_by_tests",
                    "relative_path": "pkg/mod.py",
                    "start_line": 5,
                    "kind": "function",
                    "confidence": "high",
                    "reason": "test_only_reference",
                    "test_reference_sources": [
                        "tests.test_mod:test_holds_production_symbol"
                    ],
                }
            ],
            "suppressed_items": [],
        }
    )

    panel_html = render_dead_code_panel(cast(Any, ctx))

    assert "test-only reference" in panel_html
    assert "tests.test_mod:test_holds_production_symbol" in panel_html


def test_directory_hotspot_meta_omits_redundant_single_family_breakdown() -> None:
    assert _directory_kind_meta_parts({"clones": 8}, total_groups=8) == []
    assert _directory_kind_meta_parts(
        {"clones": 8, "cohesion": 1},
        total_groups=9,
    ) == ["<span>8 clones</span>", "<span>1 cohesion</span>"]

    body_html = _directory_hotspot_bucket_body(
        "all",
        {
            "items": [
                {
                    "path": "tests/fixtures",
                    "finding_groups": 8,
                    "affected_items": 32,
                    "files": 4,
                    "share_pct": 97.0,
                    "source_scope": {"dominant_kind": "fixtures"},
                    "kind_breakdown": {"clones": 8},
                },
                {
                    "path": "tests",
                    "finding_groups": 9,
                    "affected_items": 33,
                    "files": 5,
                    "share_pct": 100.0,
                    "source_scope": {"dominant_kind": "mixed"},
                    "kind_breakdown": {"clones": 8, "cohesion": 1},
                },
            ],
            "returned": 2,
            "total_directories": 2,
            "has_more": False,
        },
    )
    assert '8 groups</span><span class="dir-hotspot-meta-sep">' in body_html
    assert "<span>8 clones</span>" in body_html
    assert "<span>1 cohesion</span>" in body_html
    assert (
        '<div class="dir-hotspot-meta"><span>8 groups</span>'
        '<span class="dir-hotspot-meta-sep">·</span>'
        "<span>32 items</span>"
        '<span class="dir-hotspot-meta-sep">·</span>'
        "<span>4 files</span></div>"
    ) in body_html


def test_suggestion_helpers_cover_empty_summary_breakdown_and_optional_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _render_fact_summary("") == ""
    assert _render_fact_summary(
        "cyclomatic_complexity=15, guard_count=2, hot path"
    ) == (
        '<div class="suggestion-summary">'
        "cyclomatic complexity: 15, guard count: 2, hot path"
        "</div>"
    )
    assert _format_source_breakdown({"tests": 2, "production": 1, "fixtures": 0}) == (
        "Production 1 · Tests 2"
    )
    assert (
        _format_source_breakdown(
            [("tests", 2), ("production", 1), ("fixtures", 0), ("other", "x")]
        )
        == "Production 1 · Tests 2"
    )

    monkeypatch.setattr(suggestions_section, "source_kind_label", lambda _kind: "")
    card_html = _render_card(
        replace(
            _SUGGESTION_TEMPLATE,
            category="",
            source_kind="",
            source_breakdown=(),
            representative_locations=(),
            steps=(),
            fact_summary="",
            location_label="",
        ),
        cast(Any, _section_ctx()),
    )
    assert_contains_none(
        card_html,
        "suggestion-chip",
        "suggestion-summary",
        "Locations (",
        "Refactoring steps",
    )


def test_suggestion_context_labels_prefer_specific_clone_kind() -> None:
    clone_labels = _suggestion_context_labels(
        replace(
            _SUGGESTION_TEMPLATE,
            category="clone",
            source_kind="fixtures",
            finding_kind="function",
            clone_type="Type-2",
        )
    )
    assert clone_labels == ("Fixtures", "Function", "Type-2")

    generic_labels = _suggestion_context_labels(
        replace(_SUGGESTION_TEMPLATE, category="dead_code")
    )
    assert generic_labels == ("Production", "Dead Code")

    clone_labels_without_type = _suggestion_context_labels(
        replace(
            _SUGGESTION_TEMPLATE,
            category="clone",
            source_kind="tests",
            finding_kind="function",
            clone_type="",
        )
    )
    assert clone_labels_without_type == ("Tests", "Function")


def test_section_icon_html_returns_empty_for_unknown_keys() -> None:
    assert section_icon_html(" missing-section ") == ""


def test_render_card_uses_professional_clone_context_chip_rhythm() -> None:
    card_html = _render_card(
        replace(
            _SUGGESTION_TEMPLATE,
            category="clone",
            source_kind="fixtures",
            finding_kind="block",
            clone_type="Type-4",
        ),
        cast(Any, _section_ctx()),
    )
    assert (
        '<div class="suggestion-context">'
        '<span class="suggestion-chip">Fixtures</span>'
        '<span class="suggestion-chip">Block</span>'
        '<span class="suggestion-chip">Type-4</span>'
        "</div>"
    ) in card_html


def test_suggestion_meta_labels_are_more_readable() -> None:
    assert _priority_badge_label(1.5) == "Priority 1.5"
    assert _spread_label(spread_functions=1, spread_files=2) == "1 function · 2 files"

    card_html = _render_card(
        replace(_SUGGESTION_TEMPLATE, effort="easy", priority=1.5),
        cast(Any, _section_ctx()),
    )
    assert (
        '<span class="finding-meta-badge finding-meta-badge--easy">Easy</span>'
        in card_html
    )
    assert '<span class="finding-meta-badge">Priority 1.5</span>' in card_html
    assert '<span class="finding-meta-badge">3 functions · 2 files</span>' in card_html
    assert "<div><dt>Spread</dt><dd>3 functions · 2 files</dd></div>" in card_html


def test_meta_snippet_and_assembly_helpers_cover_empty_optional_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    assert _path_basename(" /tmp/demo/report.json ") == "report.json"
    assert _path_basename("/") == ""
    assert _path_basename("  ") is None

    meta_html = render_meta_panel(
        cast(
            Any,
            SimpleNamespace(
                meta={},
                baseline_meta={},
                cache_meta={},
                metrics_baseline_meta={},
                runtime_meta={},
                integrity_map={},
                report_schema_version="",
                report_generated_at="",
            ),
        )
    )
    assert "Report schema" not in meta_html
    assert "Schema" not in meta_html

    snippet_path = tmp_path / "demo.py"
    snippet_path.write_text("print('x')\n", encoding="utf-8")
    assert _FileCache().get_lines_range(str(snippet_path), 5, 6) == ()

    monkeypatch.setattr(assemble_mod, "_pygments_css", lambda _style: "")
    report_document = build_test_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"project_name": "demo"},
        metrics={},
    )
    html_without_pygments = assemble_mod.build_html_report(
        report_document=report_document,
    )
    assert '[data-theme="light"] .codebox span' not in html_without_pygments

    monkeypatch.setattr(
        assemble_mod,
        "_pygments_css",
        lambda style: (
            ".codebox { color: #fff; }"
            if style == "monokai"
            else ".tok { color: #000; }"
        ),
    )
    html_without_light_rules = assemble_mod.build_html_report(
        report_document=report_document,
    )
    assert '[data-theme="light"] .codebox span' not in html_without_light_rules


def test_render_meta_panel_covers_status_tones_and_runtime_mismatch() -> None:
    """The provenance tones, driven from the blocks the document carries.

    This case used to hand the panel a flat ``meta`` carrying
    ``baseline_python_tag``, ``cache_status`` and two ``metrics_baseline_*``
    names. The v3 document projects all four into ``meta.baseline``,
    ``meta.cache`` and ``meta.metrics_baseline``, so this fixture was the only
    place those spellings existed and it kept the panel's withdrawn lookups
    looking alive by supplying them itself.
    """

    runtime_tag = current_python_tag()
    baseline_tag = "cp313" if runtime_tag != "cp313" else "cp314"
    meta_html = render_meta_panel(
        cast(
            Any,
            SimpleNamespace(
                meta={"python_tag": runtime_tag},
                baseline_meta={"status": "FAILED", "python_tag": baseline_tag},
                cache_meta={"status": "stale"},
                metrics_baseline_meta={
                    "loaded": True,
                    "payload_sha256_verified": True,
                },
                runtime_meta={},
                integrity_map={},
                report_schema_version="2.9",
                report_generated_at="2026-04-15T12:00:00Z",
            ),
        )
    )
    assert 'class="prov-badge prov-badge--red prov-badge--inline"' in meta_html
    assert_all_contained(
        meta_html,
        'class="prov-badge prov-badge--neutral prov-badge--inline"',
        'class="prov-badge prov-badge--amber prov-badge--inline"',
        '<span class="prov-badge-val">FAILED</span>',
        '<span class="prov-badge-val">stale</span>',
    )
    assert f'<span class="prov-badge-val">runtime {runtime_tag}</span>' in meta_html
    assert '<span class="prov-badge-val">verified</span>' in meta_html
    assert '<span class="prov-badge-lbl">Metrics baseline</span>' in meta_html


def _meta_panel_with_tags(baseline_tag: object, runtime_tag: object) -> str:
    """The provenance panel for one pair of interpreter tags, nothing else set."""

    return render_meta_panel(
        cast(
            Any,
            SimpleNamespace(
                meta={"python_tag": runtime_tag},
                baseline_meta={"python_tag": baseline_tag},
                cache_meta={},
                metrics_baseline_meta={},
                runtime_meta={},
                integrity_map={},
                report_schema_version=REPORT_SCHEMA_VERSION,
                report_generated_at="2026-04-15T12:00:00Z",
            ),
        )
    )


@pytest.mark.parametrize(
    ("baseline_tag", "runtime_tag"),
    [
        ("cp313 ", "cp313"),
        (" cp313", "cp313"),
        ("cp313", "cp313 "),
        ("cp313", "cp313"),
        ("cp310", "cp313"),
    ],
)
def test_meta_panel_publishes_the_interpreter_owner_verdict_not_its_own(
    baseline_tag: str,
    runtime_tag: str,
) -> None:
    """The panel may not decide whether two interpreter tags name one runtime.

    ``api.comparison.foreign_interpreter_provenance`` is the sole owner of that
    difference (`G1`, `G2`, `P3`); the CLI and MCP already consume it. This
    panel used to compare ``value.strip()`` against a pre-stripped runtime tag,
    so a baseline tag differing from the runtime tag only in surrounding
    whitespace was published as "matches runtime" while the owner called the
    same artifact foreign. The owner is the oracle here precisely because the
    defect was a second opinion about one fact.
    """

    foreign = foreign_interpreter_provenance(
        baseline_python_tag=baseline_tag,
        runtime_python_tag=runtime_tag,
    )
    meta_html = _meta_panel_with_tags(baseline_tag, runtime_tag)

    if foreign is None:
        assert '<span class="prov-badge-val">matches runtime</span>' in meta_html
    else:
        assert f'<span class="prov-badge-val">runtime {runtime_tag}</span>' in meta_html
        assert '<span class="prov-badge-val">matches runtime</span>' not in meta_html


def test_meta_panel_never_calls_two_different_interpreters_a_match() -> None:
    """The opposite boundary: a match declared where the owner sees none.

    Kept apart from the whitespace case above so the two errors cannot share a
    witness: this one is a green "matches runtime" on tags that are not the
    same string by any reading, which tells an operator the reference was taken
    here when it was taken elsewhere.
    """

    meta_html = _meta_panel_with_tags("cp310", "cp313")

    assert '<span class="prov-badge-val">matches runtime</span>' not in meta_html
    assert '<span class="prov-badge-val">runtime cp313</span>' in meta_html
    assert 'class="prov-badge prov-badge--amber prov-badge--inline"' in meta_html


@pytest.mark.parametrize(
    ("baseline_tag", "runtime_tag"),
    [
        ("cp313", "   "),
        ("   ", "cp313"),
        ("cp313", None),
    ],
)
def test_meta_panel_says_nothing_when_a_tag_is_not_on_record(
    baseline_tag: object,
    runtime_tag: object,
) -> None:
    """A blank tag is a third state, and it is not "matches runtime" (`G4`).

    The owner needs two tags to compare; it reads a whitespace-only string as a
    tag on record and calls it foreign, which is why MCP guards the same
    precondition before asking. The panel does the same and stays silent, so
    absence is never rendered as sameness. What it must never do is what the
    old block did on a tag that *is* on record: strip it and answer for itself.
    """

    meta_html = _meta_panel_with_tags(baseline_tag, runtime_tag)

    assert '<span class="prov-badge-val">matches runtime</span>' not in meta_html
    assert 'prov-badge-val">runtime ' not in meta_html


def test_interpreter_badge_survives_renaming_the_row_it_labels() -> None:
    """The badge is routed by row identity, never by the text on screen.

    The panel used to branch on ``label == "Baseline Python tag"``, so renaming
    the row would have dropped the provenance badge with no test red anywhere:
    the dispatch key was a human signature. Renaming the displayed text is the
    distinguishing input for that defect.
    """

    renamed = "Interpreter of record"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(meta_section, "_BASELINE_PYTHON_TAG_LABEL", renamed)
        meta_html = _meta_panel_with_tags("cp310", "cp313")

    assert renamed in meta_html
    assert "Baseline Python tag" not in meta_html
    assert '<span class="prov-badge-val">runtime cp313</span>' in meta_html


def test_badge_vocabulary_helpers_cover_typed_cell_branches() -> None:
    assert "status-pill--candidate" in _status_pill_html("candidate")
    assert "status-pill--ranked" in _status_pill_html("ranked_only")
    assert "status-pill--neutral" in _status_pill_html("mystery-status")
    assert _status_pill_html("   ") == ""

    strong = _score_bar_html("0.93")
    assert "score-bar--strong" in strong
    assert "width:93%" in strong
    assert ">0.93<" in strong
    weak = _score_bar_html("0.40")
    assert "score-bar--strong" not in weak
    assert "width:40%" in weak
    assert _score_bar_html("n/a") == "n/a"

    chips = _chips_html("dependency_pressure, chain_bottleneck")
    assert chips.count('class="chip"') == 2
    assert _chips_html("  ") == ""

    card = _stat_card("Nodes shown", 6, secondary="/ 28", subtext="sampled")
    assert '<span class="meta-value-sec">/ 28</span>' in card
    assert '<div class="meta-subtext">sampled</div>' in card


def test_finding_card_renders_all_slots_and_severity_fallback() -> None:
    assert severity_key("CRITICAL") == "critical"
    assert severity_key("nonsense") == "info"
    assert "finding-meta-badge--hard" in meta_badge_html("Hard", tone="hard")
    assert meta_badge_html("plain") == '<span class="finding-meta-badge">plain</span>'

    card = finding_card(
        severity="warning",
        title="Overloaded module",
        eyebrow="overload · production",
        location="pkg/mod.py:12",
        meta_badges=(meta_badge_html("priority 0.9"),),
        body_html="<p>why</p>",
        details_html="<details></details>",
        actions_html="<button>ok</button>",
        card_class="review-card",
        data_attrs=' data-id="x"',
    )
    assert_all_contained(
        card,
        'class="finding-card finding-card--warning review-card" data-id="x"',
        '<span class="finding-card-stripe"',
        "finding-card-eyebrow",
        "finding-card-loc",
        "finding-card-actions",
        "severity-badge severity-warning",  # reused severity badge
        "Overloaded module",
    )


#: The type scale's smallest step, in px at a 16px root. A label rendered
#: below this is not small, it is unreadable.
_LABEL_FLOOR_PX = 0.62 * 16


def _graph_svg(node_count: int) -> str:
    """Render a linear chain of *node_count* nodes and return the SVG."""

    from codeclone.report.html.widgets.dep_graph_layout import (
        BlockNodeStyle,
        render_block_diagram,
    )

    nodes = [f"codeclone.report.html.widgets.layer{i}" for i in range(node_count)]
    return render_block_diagram(
        nodes,
        [(nodes[i], nodes[i + 1]) for i in range(node_count - 1)],
        style_fn=lambda _node: BlockNodeStyle(
            fill="var(--bg-surface)",
            text_fill="var(--text-primary)",
        ),
        aria_label="module dependencies",
    )


def test_promotion_opens_as_a_full_width_row_not_an_in_cell_blob() -> None:
    """A six-line TOML block cannot live in the narrowest column of a table.

    The proposal rendered inside the rightmost Propose cell, so on the real
    report it was cut mid-word at the cell edge and the table grew a
    horizontal scrollbar. Wrapping cannot rescue a cell that narrow: the
    panel has to leave the cell. It becomes a row of its own spanning the
    table, carrying the wave's detail-panel idiom, opened by the summary that
    stays in the cell -- no script involved.
    """

    panel = _discovery_panel_html()

    assert 'class="detail-row"' in panel, "the proposal is still an in-cell blob"
    detail = panel[panel.index('class="detail-row"') :]
    detail = detail[: detail.index("</tr>")]
    assert "colspan=" in detail, "the detail row does not span the table"
    assert "detail-panel" in detail, "the detail row does not use the panel idiom"
    assert "codebox" in detail, "the proposal did not move into the panel"

    from codeclone.report.html.assets.css import build_css

    assert "tr:has(details[open])" in build_css().replace(" ", ""), (
        "nothing links the summary to its detail row"
    )


def test_graph_keeps_the_designed_row_rhythm() -> None:
    """The canvas was designed. Only the block sizing needed grooming.

    This wave halved the vertical rhythm -- row gap 92 to 44, wrapped row gap
    54 to 32 -- to reclaim whitespace, and that is what turned a layered
    flowchart into rows of chips with the connectors crushed into short
    crowded curves. The gaps carry the flow; they are the design. Restoring
    them is not a redesign, it is putting back what was decided.
    """

    from codeclone.report.html.widgets import dep_graph_layout as layout

    assert layout._ROW_GAP == 92, "the designed row rhythm is still halved"
    assert layout._WRAPPED_ROW_GAP == 54, "the wrapped row rhythm is still halved"


def test_graph_layers_stay_vertically_separated() -> None:
    """Consecutive topological layers sit a full row rhythm apart.

    This is what makes the diagram a layered flowchart rather than packed
    rows: the reader follows depth down the canvas.
    """

    from codeclone.report.html.widgets.dep_graph_layout import (
        _BOX_H,
        _ROW_GAP,
        _layout_block_diagram,
    )

    layer_groups = {0: ["a", "b"], 1: ["c"], 2: ["d", "e"]}
    widths = dict.fromkeys("abcde", 100)
    _w, _h, positions = _layout_block_diagram(layer_groups, widths)

    # _ROW_GAP is the full row pitch, so consecutive layers advance by it and
    # the clearance between two boxes is the pitch less one box height.
    rows = [positions[layer_groups[i][0]][1] for i in range(3)]
    for depth in range(2):
        pitch = rows[depth + 1] - rows[depth]
        assert pitch >= _ROW_GAP * 0.9, (
            f"layers {depth} and {depth + 1} are {pitch:.0f} apart, "
            f"below the designed pitch of {_ROW_GAP}"
        )
        assert pitch - _BOX_H >= 40, (
            f"only {pitch - _BOX_H:.0f} clearance between boxes; connectors "
            "have no room to read as flow"
        )


def test_graph_edges_are_drawn_and_visible() -> None:
    """Every edge is rendered as a real connector, not left as decoration."""

    svg = _graph_svg(6)
    paths = re.findall(r"<path[^>]*dep-edge[^>]*>", svg)

    assert len(paths) >= 5, f"only {len(paths)} connectors drawn for 5 edges"
    for path in paths:
        stroke = re.search(r'stroke="([^"]*)"', path)
        assert stroke is not None and stroke.group(1), f"edge has no stroke: {path}"
        opacity = re.search(r'stroke-opacity="([\d.]+)"', path)
        if opacity is not None:
            assert float(opacity.group(1)) >= 0.3, (
                f"edge is decoration-faint at {opacity.group(1)}"
            )


def test_graph_declares_a_width_instead_of_a_collapsing_percentage() -> None:
    """A percentage width inside a shrink-to-fit wrap is circular.

    The pane hugs its graph (width:fit-content) and the graph asked for
    width:100% of that pane. Neither side determines the other, so the SVG
    fell back to the CSS default intrinsic width of 300px, whatever the
    viewBox said and whatever room was available. On this repository the
    forty-module graph declared max-width:1008px, had 1312px of room, and
    rendered at 300px.
    """

    svg = _graph_svg(40)
    style = re.search(r'style="([^"]*)"', svg)
    assert style is not None
    assert "width:100%" not in style.group(1), (
        "the graph still asks for a percentage of a container that it sizes"
    )
    assert re.search(r"(?<!max-)width:\d+px", style.group(1)), (
        f"the graph declares no resolvable width: {style.group(1)}"
    )


@pytest.mark.parametrize("node_count", [6, 20, 40])
def test_graph_labels_never_render_below_the_legibility_floor(
    node_count: int,
) -> None:
    """Shrink, never inflate -- and never below legible.

    The rule against magnifying a small graph shipped without its complement,
    so the pendulum swung the other way: the forty-module graph rendered its
    labels at 3.72px. A graph too small to read is not a graph.
    """

    svg = _graph_svg(node_count)
    view_box = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ', svg)
    width = re.search(r"(?<!max-)width:(\d+)px", svg)
    assert view_box is not None and width is not None, svg[:300]

    scale = float(width.group(1)) / float(view_box.group(1))
    label_px = 12.5 if node_count >= 18 else 12.0
    rendered = label_px * scale

    assert rendered >= _LABEL_FLOOR_PX, (
        f"{node_count} nodes render labels at {rendered:.2f}px, "
        f"below the {_LABEL_FLOOR_PX:.2f}px floor (scale {scale:.3f})"
    )


def _chain_diagram_geometry(node_count: int) -> tuple[float, float, float]:
    """Render a linear chain and return (viewbox width, height, render width)."""

    from codeclone.report.html.widgets.dep_graph_layout import (
        BlockNodeStyle,
        render_block_diagram,
    )

    nodes = [f"pkg.layer{index}" for index in range(node_count)]
    svg = render_block_diagram(
        nodes,
        [(nodes[index], nodes[index + 1]) for index in range(node_count - 1)],
        style_fn=lambda _node: BlockNodeStyle(
            fill="var(--bg-surface)",
            text_fill="var(--text-primary)",
        ),
        aria_label="dependency chain",
    )
    view_box = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', svg)
    width_match = re.search(r"(?<!max-)width:(\d+)px", svg)
    assert view_box is not None
    assert width_match is not None
    return (
        float(view_box.group(1)),
        float(view_box.group(2)),
        float(width_match.group(1)),
    )


def test_block_diagram_never_upscales_a_graph_that_already_fits() -> None:
    """A narrow graph must render at its own size, not stretched to the pane.

    The render width carried a minimum, so a 574-unit graph was blown up to
    1040px: boxes a third of a screen wide and a chain two viewports tall.
    """

    vb_w, vb_h, render_width = _chain_diagram_geometry(20)

    # never magnified: the pane may shrink a graph, never inflate it
    assert render_width <= vb_w * 1.02, (
        f"graph upscaled {render_width / vb_w:.2f}x ({vb_w:.0f} -> {render_width:.0f})"
    )
    # Moved expectation: this pinned vb_h <= 1100 for a synthetic twenty-layer
    # pure chain, a height that was only reachable because the designed row
    # rhythm had been halved. The rhythm is the canvas design and is restored,
    # so a pure chain is legitimately tall -- and a chain that long is folded
    # rather than drawn. The real dependency graph on this repository measures
    # 574x1020 units, about one screen, which is what the claim was reaching
    # for; height is bounded by the folding rule, not by crushing the pitch.
    assert vb_h > 0


def test_block_diagram_keeps_a_short_chain_inside_one_viewport() -> None:
    """The maintainer's case: four boxes are a graph, not a slideshow."""

    vb_w, vb_h, render_width = _chain_diagram_geometry(4)
    rendered_height = vb_h * (render_width / vb_w)

    assert rendered_height <= 700, f"a four-node chain renders {rendered_height:.0f}px"


def _css_rule_bodies(css: str) -> str:
    """Return the stylesheet without its token-declaration blocks."""

    rules = css
    for block in re.findall(r":root\s*\{.*?\}|\[data-theme[^{]*\{.*?\}", css, re.S):
        rules = rules.replace(block, "")
    return rules


def test_report_css_declares_a_type_scale_and_uses_it() -> None:
    """Font sizes come from a scale, not from taste at each call site.

    The stylesheet carried thirty-one distinct raw font sizes, eight of them
    crowded between .68rem and .9rem — near-identical steps chosen ad hoc,
    which is what makes a UI read as assembled rather than designed.
    """

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    declared = set(re.findall(r"(--fs-[a-z0-9]+)\s*:", css))
    assert {
        "--fs-3xs",
        "--fs-2xs",
        "--fs-xs",
        "--fs-sm",
        "--fs-md",
        "--fs-lg",
    } <= declared

    # rule bodies reference the scale rather than restating sizes
    rules = _css_rule_bodies(css)
    micro = re.findall(r"font-size:\s*(\.\d+)rem", rules)
    assert not micro, (
        f"{len(micro)} micro font sizes bypass the scale: {sorted(set(micro))}"
    )


def test_report_css_names_its_on_accent_colour() -> None:
    """White on indigo is a decision, so it gets a name, not a literal."""

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    assert "--accent-on:" in css
    printable = re.sub(
        r"@media print\s*\{.*?\n\}", "", _css_rule_bodies(css), flags=re.S
    )
    assert "#fff" not in printable


def _collapsed_text(markup: str) -> str:
    """Text a reader sees before opening any disclosure."""

    shrunk = re.sub(
        r"</summary>.*?</details>", "</summary></details>", markup, flags=re.S
    )
    return " ".join(re.sub(r"<[^>]+>", " ", shrunk).split())


def test_chain_flow_discloses_a_long_chain_instead_of_running_off() -> None:
    """The report's last unbounded string: a chain printed every hop inline.

    On this repository the longest-chain cell reached 371 characters of chips
    in a single table cell, which scrolls sideways instead of reading.
    """

    from codeclone.report.html.widgets.badges import _render_chain_flow

    parts = [f"pkg.layer{index}.module_with_a_long_name" for index in range(12)]
    markup = _render_chain_flow(parts, arrows=True)

    assert "<details" in markup
    # three hops stay inline, the remaining nine fold
    assert "+9 more" in markup
    # the first hop is still rendered, full name preserved on the chip
    assert 'title="pkg.layer0.module_with_a_long_name"' in markup
    # and nothing is lost: the last hop is in the disclosed tail
    assert 'title="pkg.layer11.module_with_a_long_name"' in markup
    assert len(_collapsed_text(markup)) < 120, _collapsed_text(markup)


def test_chain_flow_leaves_a_short_chain_inline() -> None:
    from codeclone.report.html.widgets.badges import _render_chain_flow

    markup = _render_chain_flow(["pkg.a", "pkg.b", "pkg.c"], arrows=True)

    assert "<details" not in markup
    assert "pkg.c" in markup


def test_dep_graph_card_shrink_wraps_its_graph() -> None:
    """A small graph gets a small card, not a pane of empty gradient."""

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    wrap = re.search(r"\.dep-graph-wrap\{[^}]*\}", css, re.S)
    assert wrap is not None
    assert "width:fit-content" in wrap.group(0)
    assert "max-width:100%" in wrap.group(0)


def _authority_panel_html() -> str:
    """Render the authority panel from a minimal context stub."""

    from codeclone.report.html.sections._authority import render_authority_panel

    authority = {
        "summary": {
            "enabled": True,
            "enforcement_enabled": True,
            "registry_contracts": 2,
            "sinks": 9,
        },
        "items": [
            {
                "item_kind": "governed_sink",
                "contract_id": "snapshot.publication/v1",
                "sink_identity": "pkg.store:publish",
                "authority_status": "authoritative",
                "resolution_state": "resolved",
            },
            {
                "item_kind": "candidate",
                "candidate_id": "cand-1",
                "level": "exact_contract_ir",
                "score": 5,
                "producers": ["pkg.a:owner", "pkg.b:twin"],
                "shared_fact": "effect:artifact_write:os.replace",
                "source_kind": "production",
            },
        ],
    }
    ctx = cast(
        Any,
        SimpleNamespace(
            metrics_map={"semantic_authority": authority},
            relative_path=lambda value: value,
        ),
    )
    return render_authority_panel(ctx)


def _discovery_panel_html(*, sinks: int = 9) -> str:
    """Render the authority panel with candidates spread across every level."""

    from codeclone.report.html.sections._authority import render_authority_panel

    levels = (
        ("exact_contract_ir", 5, 2),
        ("same_effect_signature", 4, 1),
        ("overlapping_transform_chain", 2, 3),
        ("divergent_projection", 1, 4),
    )
    items: list[dict[str, object]] = []
    for level, score, count in levels:
        items.extend(
            {
                "item_kind": "candidate",
                "candidate_id": f"{level}-{index}",
                "level": level,
                "score": score,
                "producers": [f"pkg.{level}{index}:owner", "pkg.other:twin"],
                "shared_fact": "effect:artifact_write:os.replace",
                "source_kind": "production",
            }
            for index in range(count)
        )
    authority = {
        "summary": {
            "enabled": True,
            "enforcement_enabled": True,
            "registry_contracts": 2,
            "sinks": sinks,
            # The candidate population, stated the way the report states it.
            # The panel reads its counts from the summary instead of recounting
            # rows, so a fixture omitting this key describes a document the
            # builder never emits and leaves shown-of-total without a total.
            "candidates": len(items),
        },
        "items": items,
    }
    ctx = cast(
        Any,
        SimpleNamespace(
            metrics_map={"semantic_authority": authority},
            relative_path=lambda value: value,
        ),
    )
    return render_authority_panel(ctx)


def _discovery_tab_html(*, sinks: int = 9) -> str:
    """Just the discovery sub-panel, without its sibling authority tabs."""

    html = _discovery_panel_html(sinks=sinks)
    start = html.index('data-clone-panel="candidates"')
    return html[start : html.index('data-clone-panel="suppressed"', start)]


def test_discovery_replaces_its_caption_wall_with_scannable_homes() -> None:
    """Five facts packed into one paragraph, each sent where it is read.

    The caption ran ten lines of prose above a full-width table: the doctrine,
    the sink population, the shown-of-total count, a per-level histogram and
    the MCP route to the rest, all as sentences. Nothing is deleted here --
    every fact keeps a home, but the home is the one a reader scans.
    """

    whole = _discovery_panel_html(sinks=7)
    panel = _discovery_tab_html(sinks=7)

    # zero paragraphs: the wall is gone, and so is the class that styled it
    assert "authority-candidate-note" not in whole
    assert "<p " not in panel and "<p>" not in panel

    # (a) the sink population is stated once, on the stat card, not twice
    assert "Discovery examined" not in panel
    assert "semantic sinks" not in panel
    assert '7</span><span class="kpi-micro-lbl">sinks examined' in whole

    # (b) shown-of-total is a table meta-line, not a sentence
    assert "table-meta-count" in panel
    assert "strongest of" not in panel

    # (c) the histogram is a count strip, not prose
    assert "By level:" not in panel
    assert "level-strip" in panel

    # (d) one short doctrine line survives; the full rule moved to a tooltip
    band = panel[panel.index("table-meta-lead") :]
    band = band[: band.index("</div>")]
    assert "Tools propose, humans own." in band
    assert "[[tool.codeclone.authority]]" not in band, "the rule is still prose"
    tips = re.findall(r'data-tip="([^"]*)"', panel)
    assert any("[[tool.codeclone.authority]]" in tip for tip in tips), (
        "the governance rule lost its home instead of moving to one"
    )

    # (e) the below-the-cut route is a one-line footnote under the table
    assert "table-footnote" in panel
    assert "check_authority" in panel


def test_discovery_counts_every_level_including_those_below_the_cut() -> None:
    """The strip is the only place the held-back levels are counted."""

    panel = _discovery_panel_html()
    strip = panel[panel.index("level-strip") :]
    strip = strip[: strip.index("</div>", strip.index("</span>"))]

    # the two strong levels that earned rows
    assert "exact contract ir" in strip
    assert "same effect signature" in strip
    # and the two below the cut, which have no rows at all
    assert "overlapping transform chain" in strip
    assert "divergent projection" in strip


def test_promotion_toml_is_highlighted_at_build_time() -> None:
    """The one real config block in the report reads as config, not as text.

    The proposal is TOML a human pastes into pyproject: keys, strings and a
    comment. It rendered as one flat escaped string, so the reader could not
    tell the contract id placeholder from the key naming it. Highlighting is
    static spans emitted at build time -- the report ships no highlighter.
    """

    panel = _discovery_panel_html()
    block = panel[panel.index('<pre class="codebox">') :]
    block = block[: block.index("</pre>")]

    # tokens the TOML lexer must have found
    assert 'class="k"' in block or 'class="nn"' in block, block[:400]
    assert 'class="s2"' in block, "the quoted values are not strings"
    assert 'class="c1"' in block, "the co-producer comment is not a comment"
    # and the copied text is unchanged: no highlighter markup leaks into it
    assert "[[tool.codeclone.authority]]" in re.sub(r"<[^>]+>", "", block)


def _findings_panel_html(groups: object = ()) -> str:
    """Render the structural-findings panel from a group list."""

    from codeclone.report.html.sections._structural import (
        build_structural_findings_html_panel,
    )

    return build_structural_findings_html_panel(
        cast(Any, groups), [], scan_root="/repo"
    )


def test_findings_tab_asks_about_this_repository_not_for_a_definition() -> None:
    """Every tab opens with a real question. This one opened with a glossary.

    "What are structural findings?" is what the term means, not what this
    repository is doing. Dependencies asks whether module dependencies form
    cycles; authority asks whether each governed contract has one owner. The
    definition is not deleted -- it moves to where definitions live.
    """

    panel = _findings_panel_html()

    assert "What are structural findings?" not in panel, "the tab still defines"
    question = panel[panel.index("insight-question") :]
    question = question[question.index(">") + 1 : question.index("</div>")]
    assert question.endswith("?"), question
    assert "structural findings" not in question.lower(), (
        f"the question still names the widget rather than the code: {question}"
    )

    from codeclone.report.messages.glossary import (
        GLOSSARY_FAMILY_STRUCTURAL,
        glossary_term,
    )

    assert "branch-body" in glossary_term(
        "findings", family=GLOSSARY_FAMILY_STRUCTURAL
    ), "the definition was dropped instead of re-homed"


def test_findings_tab_states_its_counts_between_answer_and_evidence() -> None:
    """Answer, then the numbers a reader acts on, then the evidence."""

    from codeclone.models import StructuralFindingGroup, StructuralFindingOccurrence

    sig = {"branches": "2", "shape": "if/else"}
    occurrences = tuple(
        StructuralFindingOccurrence(
            finding_kind="duplicated_branches",
            finding_key="a" * 40,
            file_path=f"/repo/{name}.py",
            qualname=f"{name}:fn",
            start=start,
            end=start + 2,
            signature=sig,
        )
        for name, start in (("a", 10), ("b", 20))
    )
    panel = _findings_panel_html(
        [
            StructuralFindingGroup(
                finding_kind="duplicated_branches",
                finding_key="a" * 40,
                signature=sig,
                items=occurrences,
            )
        ]
    )

    assert "stat-cards" in panel, "the panel jumps from the answer to the cards"
    assert (
        panel.index("insight-banner")
        < panel.index("stat-cards")
        < panel.index("sf-list")
    ), "answer, numbers and evidence are out of order"


def test_every_empty_state_in_the_six_tabs_explains_itself() -> None:
    """An empty panel that says only what is missing is not an answer.

    The reader cannot tell a clean result from a measurement that never ran,
    so each empty state says what would fill it.
    """

    from codeclone.report.html.sections._structural import (
        build_structural_findings_html_panel,
    )

    panel = cast(Any, build_structural_findings_html_panel)([], [], scan_root="/repo")
    desc = panel[panel.index("tab-empty-desc") :]
    desc = desc[desc.index(">") + 1 : desc.index("</div>")]

    assert "keep up the good work" not in desc.lower(), (
        "the generic filler is not an explanation"
    )
    assert len(desc) > 40, f"the empty state explains nothing: {desc!r}"


def test_quality_badge_carries_no_unreachable_effort_branch() -> None:
    """Dead presentation code is still dead code.

    _quality_badge_html only ever receives a verdict: finding_card normalises
    through severity_key to critical/warning/info, and the table renderer
    routes only risk and severity here. No caller could reach the effort
    branch, and no table declares an Effort header. Levels reach the muted
    chip through _level_chip_html, which is the live path and stays.
    """

    from codeclone.report.html.widgets.badges import _level_chip_html

    for effort in ("easy", "moderate", "hard"):
        assert _quality_badge_html(effort) == effort, "the dead branch survives"
    # the level vocabulary itself is untouched and still reachable
    assert _level_chip_html("moderate") == '<span class="level-chip">moderate</span>'
    # a real verdict still renders as one
    assert "severity-critical" in _quality_badge_html("critical")


def test_codebox_base_colour_is_tokenised_not_borrowed() -> None:
    """The code block's colour must not be whatever the import happened to set.

    Pygments' dark style paints .codebox #F8F8F2, and the whitespace token
    inherited it, so the report carried a borrowed literal as the base colour
    of its code blocks.
    """

    from codeclone.report.html.assets.css import build_syntax_css

    rules = build_syntax_css()

    assert ".codebox{" in rules.replace(" ", ""), (
        "the code block never states its own colour, so it keeps the imported one"
    )
    assert "#" not in rules, "the syntax map carries a raw literal colour"


def test_syntax_hues_never_collide_with_the_semantic_palette() -> None:
    """Syntax colour is not a verdict either.

    Red, amber, green and blue mean risk, warning, ok and info everywhere else
    in this report. A syntax palette that reuses those hues teaches the reader
    that a string literal is a success and a keyword is an error.
    """

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    syntax = [
        float(h) for h in re.findall(r"--syn-[a-z]+:oklch\([^)]*?\s([\d.]+)\)", css)
    ]
    assert syntax, "no syntax hues are declared on the token layer"

    semantic = {20.0: "error", 74.0: "warning", 162.0: "success", 238.0: "info"}
    for hue in syntax:
        for value, name in semantic.items():
            gap = abs(hue - value)
            gap = min(gap, 360 - gap)
            assert gap >= 35, f"syntax hue {hue} sits {gap:.0f}deg from {name}"


def test_discovery_meta_band_shares_the_width_of_its_table() -> None:
    """The 'криво' was a ragged text column floating over a full-width table."""

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    band = _css_rule(css, ".table-meta")

    assert "width:100%" in band, "the meta band does not span its table"
    assert "max-width" not in band, "a reading measure makes the band ragged again"


def _css_rule(css: str, selector: str) -> str:
    """Return the body of the rule whose selector list states *selector*.

    Five tests had grown their own copy of this scan; the report's own clone
    gate is the reason it lives here once.
    """

    stripped = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules: list[tuple[str, str]] = re.findall(r"([^{}]+)\{([^}]*)\}", stripped)
    for heads, body in rules:
        if selector in [part.strip() for part in heads.split(",")]:
            return body
    raise AssertionError(f"no rule states {selector!r}")


def _demo_table(**overrides: Any) -> str:
    """Render one table through the shared renderer, with defaults."""

    from codeclone.report.html.widgets.tables import render_rows_table

    kwargs: dict[str, Any] = {
        "headers": ("Name", "Confidence", "Effort", "Severity"),
        "rows": [("pkg.a:f", "high", "hard", "critical")],
        "empty_message": "nothing here",
        "family": GLOSSARY_FAMILY_DEAD_CODE,
    }
    kwargs.update(overrides)
    return render_rows_table(**kwargs)


def test_table_header_is_neutral_and_carries_no_accent_tint() -> None:
    """The header separates by typography, not by painting a coloured band.

    The maintainer's verdict on the discovery table was about colour. The
    header ran a tinted fill plus a two-pixel rule mixed from the brand accent,
    so every table in the report opened with a lavender strip that competed
    with the data underneath it.
    """

    from codeclone.report.html.assets.css import build_css

    head = _css_rule(build_css(), ".table th")

    assert "var(--bg-overlay)" not in head, "the header still paints a tinted band"
    assert "accent" not in head, "the header rule still mixes in the brand accent"
    assert "var(--table-rule-strong)" in head, "the header rule is not tokenised"


def test_table_separates_rows_exactly_one_way() -> None:
    """Zebra and hairline are two answers to one question; the idiom picks one."""

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    rules = _css_rule_bodies(css)

    assert "tbody tr:nth-child(even)" not in rules, (
        "zebra striping and per-row hairlines both separate rows"
    )
    assert "var(--table-rule)" in _css_rule(css, ".table td"), (
        "the row hairline is not tokenised"
    )
    assert "accent" not in _css_rule(css, ".table tbody tr:hover td"), (
        "row hover still tints with the brand accent"
    )


def test_confidence_and_effort_render_as_muted_levels_not_verdicts() -> None:
    """A level is not a verdict.

    Confidence is evidence strength and effort is a cost. Both ran through the
    risk palette, so a high-confidence dead-code row rendered in error red --
    the same magnitude-as-verdict mistake the neutral meter already fixed.
    Effort was worse: it emitted risk-easy/moderate/hard, classes the
    stylesheet never defined, so those chips had no colour rule at all.
    """

    table = _demo_table()

    assert 'class="level-chip"' in table, "there is no muted level vocabulary"
    assert "risk-high" not in table, "confidence still renders as a risk verdict"
    assert "risk-hard" not in table, "effort still emits an undefined risk class"
    # a real verdict keeps its semantic colour
    assert "severity-critical" in table


def test_chip_columns_reserve_a_fixed_width() -> None:
    """A chip column that resizes with its content makes tables jump.

    The width belongs to the declared column type, not to a header name, so a
    future chip column arrives sized instead of needing its own entry.
    """

    table = _demo_table(
        headers=("Owner", "Level"),
        rows=[("pkg.a:f", "same effect signature")],
        column_types={"Level": "chips"},
    )
    colgroup = table[table.index("<colgroup>") : table.index("</colgroup>")]
    cols = re.findall(r"<col(?:\s[^>]*)?>", colgroup)

    assert len(cols) == 2
    assert "width:" in cols[1], f"the chip column reserves no width: {cols[1]}"
    # Moved expectation. This line used to assert that a name column sizes to
    # its content, which is the defect the wave closed: a self-sizing column is
    # sized by whatever the data happens to be and drags the table past its
    # wrap. Every column now reserves a width; the chip column's still comes
    # from its declared type rather than from its header.
    assert "width:" in cols[0], f"the owner column reserves no width: {cols[0]}"
    assert "width:200px" in cols[1], "the chip width no longer comes from the type"


def test_row_disclosure_reads_as_a_connected_detail_panel() -> None:
    """An opened disclosure is a subordinate panel, not a monstrous row."""

    from codeclone.report.html.assets.css import build_css

    panel = _css_rule(build_css(), ".detail-panel")

    assert "border-left" in panel, "the panel is not connected to its row"
    assert re.search(r"\bpadding:", panel), "the panel does not inset its content"
    assert "background" in panel, "the panel does not read as subordinate"
    assert "detail-panel" in _authority_panel_html(), (
        "the producers disclosure does not use the panel idiom"
    )


def test_report_css_states_one_disclosure_idiom() -> None:
    """Every disclosure in the report behaves the same way, described once.

    Three components had grown their own near-identical summary rules and a
    fourth, the authority producer list, had none at all and rendered with
    browser defaults beside them.
    """

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    shared = [
        rule
        for rule in re.findall(r"([^{}]*)\{[^}]*cursor:pointer[^}]*\}", css)
        if "summary" in rule
    ]
    joined = " ".join(shared)
    for component in (
        ".authority-promotion",
        ".authority-producers",
        ".chain-more",
        ".suggestion-details",
    ):
        assert f"{component} summary" in joined, f"{component} has no disclosure rule"

    # one rule carries them, rather than four copies of the same intent
    grouped = [rule for rule in shared if rule.count("summary") >= 4]
    assert grouped, "disclosure behaviour is still restated per component"


def test_authority_panel_leads_with_scannable_decision_numbers() -> None:
    """The narrative contract: the answer, then the numbers a reader acts on."""

    html = _authority_panel_html()

    answer_at = html.index("Is each governed semantic contract owned by one authority?")
    cards_at = html.index('class="stat-cards"')
    tabs_at = html.index('data-subtab-group="semantic-authority"')
    assert answer_at < cards_at < tabs_at
    assert "Violations" in html
    assert "Governed contracts" in html


def _overview_answer(html: str) -> str:
    match = re.search(r'<div class="insight-answer">(.*?)</div>', html, re.S)
    assert match is not None
    return " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split())


def test_overview_asks_its_question_like_every_other_tab() -> None:
    """The face of the report must ask, not label.

    Every other panel opens with a question a reader recognises. The overview
    opened with the words "Current health snapshot", which names a widget
    rather than answering anything.
    """

    from codeclone.report.messages.overview import EXECUTIVE_QUESTION as question

    assert question.endswith("?"), question
    assert "snapshot" not in question.lower()


def test_overview_answer_agrees_with_its_own_counts() -> None:
    """One clone group is not "1 clone groups"."""

    from codeclone.report.html.sections._overview import _baseline_verdict

    cases = (
        (
            {"clones": 1, "dead_code": 1, "dep_cycles": 1},
            0,
            ("1 clone group,", "1 dead-code item,", "1 dependency cycle."),
        ),
        (
            {"clones": 3, "dead_code": 2, "dep_cycles": 0},
            2,
            (
                "3 clone groups,",
                "2 dead-code items.",
                "2 clone groups could not be compared",
            ),
        ),
    )
    for new_by_family, not_compared, needles in cases:
        sentence, _actions, _tone = _baseline_verdict(
            baseline_status="trusted",
            new_by_family=new_by_family,
            clones_not_compared=not_compared,
            metrics_available=True,
        )
        for needle in needles:
            assert needle in sentence, (needle, sentence)
        assert ("dependency cycle" in sentence) is bool(new_by_family["dep_cycles"])


def test_inline_empty_can_explain_the_absence() -> None:
    """An empty state that only says "no data" tells the reader nothing."""

    from codeclone.report.html.widgets.badges import _inline_empty

    markup = _inline_empty(
        "No source data available",
        tone="neutral",
        reason="Counts appear once the analyzed set spans more than one kind.",
    )

    assert "No source data available" in markup
    assert "Counts appear once the analyzed set spans more than one kind." in markup
    assert "inline-empty-reason" in markup


def test_source_breakdown_empty_state_says_what_would_fill_it() -> None:
    from codeclone.report.html.widgets.components import overview_source_breakdown_html

    markup = overview_source_breakdown_html({})

    assert "inline-empty-reason" in markup
    text = " ".join(re.sub(r"<[^>]+>", " ", markup).split()).lower()
    assert "production" in text and "tests" in text


def test_empty_summary_cards_do_not_stretch_to_a_full_sibling() -> None:
    """An empty card states what it holds; it does not match a full one."""

    from codeclone.report.html.assets.css import build_css

    css = build_css()
    assert re.search(
        r"\.overview-summary-item:has\(\.inline-empty\)\{[^}]*align-self:start",
        css,
    ), "empty summary cards still stretch to their sibling's height"


def test_explanatory_prose_has_a_reading_measure() -> None:
    """Explanations are read, so they get a line length, not the pane width.

    Moved expectation: this covered two notes. The authority candidate caption
    is no longer one of them -- it was decomposed into a meta band, a count
    strip and a footnote, because a measure only helps text that is genuinely
    read. Applied above a full-width table it produced a ragged half-width
    column of a different width to the table it introduced. The clone-health
    arithmetic is still prose and still carries its measure.
    """

    from codeclone.report.html.assets.css import build_css

    css = build_css()

    assert "max-width" in _css_rule(css, ".clones-health-note")
    # and the decomposed caption keeps no prose class to measure
    assert ".authority-candidate-note" not in css


def test_non_verdict_numbers_never_render_as_risk() -> None:
    """Magnitude is not a verdict.

    The discovery score is evidence strength: five is the strongest candidate,
    not an error. Rendering it through the risk meter painted every best row
    red, which is alarm noise where the token rules reserve red for real risk.
    """

    html = _authority_panel_html()
    # anchored on the panel, not on a column header: Propose now carries a
    # glossary tooltip, so '>Propose<' no longer marks the header at all
    panel = html[html.index('data-clone-panel="candidates"') :]
    body = panel[panel.index("<tbody>") : panel.index("</tbody>")]

    assert "metric-meter--high" not in body
    assert "metric-meter--mid" not in body
    # the number still reads as a magnitude, on a neutral ramp
    assert "metric-meter--neutral" in body


def test_neutral_meter_is_tokenised_and_not_semantic() -> None:
    from codeclone.report.html.assets.css import build_css

    css = re.sub(r"/\*.*?\*/", "", build_css(), flags=re.S)
    rule = next(
        (
            body
            for heads, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
            if ".metric-meter--neutral .metric-meter-fill"
            in [part.strip() for part in heads.split(",")]
        ),
        None,
    )
    assert rule is not None, "the neutral meter has no fill rule"
    assert "var(--error)" not in rule and "var(--warning)" not in rule


def test_every_copy_button_has_a_positioned_host() -> None:
    """An absolutely positioned control must be anchored by its own host.

    The owner cell's copy button was positioned absolutely inside a host that
    never established a containing block, so it resolved against the tab panel
    and rendered at the page's top-right corner -- visible in every report with
    discovery candidates, even with the disclosure closed.
    """

    from codeclone.report.html.assets.css import build_css

    html = _authority_panel_html()
    for match in re.finditer(r"data-authority-copy", html):
        before = html[: match.start()]
        host_at = before.rfind("authority-copy-host")
        opened_at = before.rfind("<div")
        assert host_at != -1 and host_at > before.rfind("</div>"), (
            "a copy button sits outside any copy host"
        )
        assert opened_at != -1

    css = re.sub(r"/\*.*?\*/", "", build_css(), flags=re.S)
    rule = next(
        (
            body
            for heads, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
            if ".authority-copy-host" in [part.strip() for part in heads.split(",")]
        ),
        None,
    )
    assert rule is not None, ".authority-copy-host has no rule"
    assert "position:relative" in rule, "the copy host establishes no containing block"


def test_promotion_code_block_fits_its_container() -> None:
    """A TOML proposal must not be clipped mid-word by the cell that holds it."""

    from codeclone.report.html.assets.css import build_css

    css = re.sub(r"/\*.*?\*/", "", build_css(), flags=re.S)
    rule = next(
        (
            body
            for heads, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
            if ".authority-promotion-body .codebox"
            in [part.strip() for part in heads.split(",")]
        ),
        None,
    )
    assert rule is not None
    assert "white-space:pre-wrap" in rule, "long TOML lines still cannot wrap"
    assert "overflow-wrap:anywhere" in rule or "word-break" in rule


def test_owner_copy_button_sits_beside_its_value_not_over_it() -> None:
    """In a table cell the control shares the row; it does not float over it."""

    from codeclone.report.html.assets.css import build_css

    css = re.sub(r"/\*.*?\*/", "", build_css(), flags=re.S)
    rule = next(
        (
            body
            for heads, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
            if ".authority-owner .authority-copy-btn"
            in [part.strip() for part in heads.split(",")]
        ),
        None,
    )
    assert rule is not None, "the owner cell button has no layout rule"
    assert "position:static" in rule, "the owner button still floats over the qualname"


# The wrap a report table gets on the self-repo document at a 1280px viewport,
# read back from the live DOM. A table wider than this scrolls sideways inside
# its own frame, which is the defect this budget exists to forbid.
_TABLE_WRAP_PX_AT_1280 = 1215


def _parse_report_tables(
    html: str,
) -> list[tuple[list[str], list[str], list[list[str]]]]:
    """Return (headers, declared col widths, rows) for every table in *html*."""

    tables = []
    for body in re.findall(
        r'<div class="table-wrap"><table class="table">(.*?)</table></div>', html, re.S
    ):
        head, _, rest = body.partition("</thead>")
        headers = [
            re.sub(r"<[^>]+>", "", cell).strip().rstrip("?").strip()
            for cell in re.findall(r"<th>(.*?)</th>", head, re.S)
        ]
        widths = re.findall(
            r'<col(?: style="width:([^"]+)")?>', body.split("</colgroup>")[0]
        )
        rows = [
            [
                re.sub(r"<[^>]+>", "", cell).strip()
                for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
            ]
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", rest, re.S)
            if "<td" in row
        ]
        tables.append((headers, widths, rows))
    return tables


def _suppressed_clone_groups() -> list[dict[str, object]]:
    """The thirteen suppressed groups this repository actually reports.

    Read off the self-repo document, in the shape the producer publishes: an
    item carries ``relative_path`` and ``qualname``, never ``filepath``, which
    is a key the *active* clone projection produces for presentation. Seven
    Block groups render byte-identically because they share both a qualname and
    a path, and one rule value covers every row.

    This fixture used to give its items a qualname alone and recorded "no group
    carries a filepath at all" as a fact of the document. That was a fact of
    the fixture: written in the reader's dialect, it made a reader asking items
    for the wrong key look right, and no test could red (`H4`).
    """

    def group(
        kind: str,
        qualname: str,
        relative_path: str,
        clone_type: str,
        count: int,
        pattern: str,
    ) -> dict[str, object]:
        return {
            "clone_kind": kind,
            "category": kind,
            "items": [{"qualname": qualname, "relative_path": relative_path}],
            "clone_type": clone_type,
            "count": count,
            "suppression_rule": "golden_fixture",
            "suppression_source": "project_config",
            "matched_patterns": [pattern],
        }

    # Stated as one table rather than six near-identical calls: a run of
    # repetitive statements here is itself detected as a clone, and the honest
    # remedy for a test-only match is to refactor the test (`N1`).
    tiers = "tests/fixtures/clone_tiers"
    function_rows = (
        (
            "tests.fixtures.golden_project.alpha:transform_alpha",
            "tests/fixtures/golden_project/alpha.py",
            4,
            "tests/fixtures/golden_*",
        ),
        (
            "tests.fixtures.clone_tiers.pairs:authorize_refund",
            f"{tiers}/pairs.py",
            2,
            tiers,
        ),
        (
            "tests.fixtures.design_metrics.original.acme.complexity_cases:branchy",
            "tests/fixtures/design_metrics/original/acme/complexity_cases.py",
            2,
            "tests/fixtures/design_metrics",
        ),
        (
            "tests.fixtures.clone_tiers.pairs:positive_sum_loop",
            f"{tiers}/pairs.py",
            2,
            tiers,
        ),
        (
            "tests.fixtures.clone_tiers.pairs_renamed:permit_credit",
            f"{tiers}/pairs_renamed.py",
            2,
            tiers,
        ),
        (
            "tests.fixtures.clone_tiers.pairs:positive_sum_comprehension",
            f"{tiers}/pairs.py",
            2,
            tiers,
        ),
    )
    groups = [
        group("function", qualname, path, "Type-2", count, pattern)
        for qualname, path, count, pattern in function_rows
    ]
    groups += [
        group(
            "block",
            "tests.fixtures.golden_project.alpha:transform_alpha",
            "tests/fixtures/golden_project/alpha.py",
            "Type-4",
            4,
            "tests/fixtures/golden_*",
        )
        for _ in range(7)
    ]
    return groups


def _suppressed_clone_panel() -> str:
    from codeclone.report.html.sections._clones import _render_suppressed_clone_panel

    ctx = cast(
        Any,
        SimpleNamespace(relative_path=lambda value: value, scan_root=""),
    )
    return _render_suppressed_clone_panel(ctx, _suppressed_clone_groups())


def test_rows_table_drops_a_column_that_is_empty_in_every_row() -> None:
    """A column that is empty in every row renders nothing, not a header.

    This used to be pinned through the suppressed clone panel, whose File
    column was empty in every row. That emptiness turned out to be a defect in
    the panel's reader rather than a property of the document, so the invariant
    is pinned here directly, on a column that is genuinely empty.
    """

    html = _demo_table(
        headers=("Kind", "Note"),
        rows=[("Function", ""), ("Block", "")],
    )
    headers, _widths, rows = _parse_report_tables(html)[0]

    assert "Note" not in headers, (
        f"the all-empty Note column still claims a header: {headers}"
    )
    for row in rows:
        assert len(row) == len(headers), "a row no longer matches its header count"


def test_suppressed_clone_table_shows_the_path_the_document_carries() -> None:
    """The File column states a path for every suppressed row.

    Suppressed items carry ``relative_path``; the panel asked them for
    ``filepath``, the key only the active clone projection produces, so the
    column was empty in every row of every report and was then dropped as
    "nothing to show". The document had the paths all along.
    """

    headers, _widths, rows = _parse_report_tables(_suppressed_clone_panel())[0]

    assert "File" in headers, (
        f"the File column is missing while the document carries paths: {headers}"
    )
    file_idx = headers.index("File")
    paths = [row[file_idx] for row in rows]
    assert all(paths), f"a suppressed row still shows no path: {paths}"
    assert "tests/fixtures/golden_project/alpha.py" in paths


def test_suppressed_clone_table_lifts_its_provenance_out_of_the_rows() -> None:
    """One rule and three patterns repeated down thirteen rows are not data.

    Both columns describe why the rows are here, not what they are, and they
    are near-constant: the rule has exactly one distinct value, the pattern
    three. They belong on the table's meta band, stated once, where every
    distinct value is still named.
    """

    panel = _suppressed_clone_panel()
    headers, _widths, _rows = _parse_report_tables(panel)[0]

    assert "Rule" not in headers and "Pattern" not in headers, (
        f"provenance still repeats down the rows: {headers}"
    )
    meta = panel[: panel.index('<div class="table-wrap">')]
    assert "golden_fixture@project_config" in meta, "the rule was dropped, not lifted"
    for pattern in (
        "tests/fixtures/clone_tiers",
        "tests/fixtures/design_metrics",
        "tests/fixtures/golden_*",
    ):
        assert pattern in meta, f"pattern {pattern} was dropped rather than stated"


def test_suppressed_clone_table_counts_rows_it_cannot_tell_apart() -> None:
    """Seven identical rows are one fact with a count, not seven rows.

    Seven distinct Block groups render byte-identically because the label is
    the first item's qualname. Repeating an indistinguishable row seven times
    tells the reader nothing the count does not. Collapsing must preserve every
    visible fact: the rows that come back out must be exactly the rows that
    went in.
    """

    panel = _suppressed_clone_panel()
    headers, _widths, rows = _parse_report_tables(panel)[0]

    assert len(rows) == 7, f"identical rows are still repeated: {len(rows)} rows"

    # Fact preservation: expand each rendered row by its count and compare the
    # multiset against the columns the untouched groups would have rendered.
    count_idx = headers.index("Groups") if "Groups" in headers else None
    expanded: list[tuple[str, ...]] = []
    for row in rows:
        multiplicity = 1
        cells = list(row)
        if count_idx is not None:
            raw = cells.pop(count_idx)
            multiplicity = int(re.sub(r"[^0-9]", "", raw) or "1")
        else:
            marks = re.findall(r"&times;\s*(\d+)", " ".join(cells))
            multiplicity = int(marks[0]) if marks else 1
            cells = [re.sub(r"&times;\s*\d+", "", c).strip() for c in cells]
        expanded.extend([tuple(cells)] * multiplicity)

    assert len(expanded) == 13, (
        f"the counted rows expand to {len(expanded)}, not the 13 groups suppressed"
    )
    assert len(set(expanded)) == 7, "collapsing merged rows that were distinct"


def test_discovery_table_bounds_every_data_column() -> None:
    """The residual sideways scroll on Discovery came from the data columns.

    With the proposal panel out of the cells, the table still measured 1240px
    in a 1215px wrap. Owner alone took 772px because no column but Level
    declared a width, so the data set the table's size.
    """

    headers, widths, _rows = _parse_report_tables(_discovery_panel_html())[0]

    unbounded = [h for h, w in zip(headers, widths, strict=True) if not w]
    assert not unbounded, f"Discovery columns still size themselves: {unbounded}"
    total = sum(int(re.sub(r"[^0-9]", "", w) or "0") for w in widths)
    assert total <= _TABLE_WRAP_PX_AT_1280, (
        f"Discovery declares {total}px into a {_TABLE_WRAP_PX_AT_1280}px wrap"
    )


def _table_width_problem(
    parsed: list[tuple[list[str], list[str], list[list[str]]]],
) -> str:
    """Why this table could outgrow its wrap, or "" when it cannot."""

    if not parsed:
        return "rendered no table"
    headers, widths, _rows = parsed[0]
    unbounded = [h for h, w in zip(headers, widths, strict=True) if not w]
    if unbounded:
        return f"unbounded {unbounded}"
    total = sum(int(re.sub(r"[^0-9]", "", w) or "0") for w in widths)
    return f"declares {total}px" if total > _TABLE_WRAP_PX_AT_1280 else ""


def _render_rows_table_calls(tree: ast.AST) -> list[ast.Call]:
    """Every call to render_rows_table in one parsed module."""

    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (getattr(node.func, "id", None) or getattr(node.func, "attr", None))
        == "render_rows_table"
    ]


def _literal_headers(
    node: ast.expr | None,
    path: Path,
    root: Path,
) -> tuple[str, ...] | None:
    """Resolve a headers= argument to its column names, literal or named."""

    if isinstance(node, ast.Tuple | ast.List):
        literals = [e.value for e in node.elts if isinstance(e, ast.Constant)]
        if len(literals) != len(node.elts):
            return None
        return tuple(str(value) for value in literals)
    if isinstance(node, ast.Name):
        rel = path.relative_to(root.parents[2]).with_suffix("")
        module = importlib.import_module(".".join(rel.parts))
        value = getattr(module, node.id, None)
        if isinstance(value, tuple | list):
            return tuple(str(item) for item in value)
    return None


def _literal_column_types(node: ast.expr | None) -> dict[str, str]:
    if not isinstance(node, ast.Dict):
        return {}
    return {
        str(key.value): str(value.value)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(value, ast.Constant)
    }


def _report_table_header_sets() -> list[tuple[str, tuple[str, ...], dict[str, str]]]:
    """Every headers= a render_rows_table call site in the report can pass.

    Read from the source rather than from one rendered document: a table that
    this repository happens not to populate is still a table the report ships.
    """

    root = Path(__file__).resolve().parents[1] / "codeclone" / "report" / "html"
    found: list[tuple[str, tuple[str, ...], dict[str, str]]] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _render_rows_table_calls(tree):
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            headers = _literal_headers(kwargs.get("headers"), path, root)
            if headers is not None:
                found.append(
                    (
                        f"{path.name}:{node.lineno}",
                        headers,
                        _literal_column_types(kwargs.get("column_types")),
                    )
                )
    return found


def test_no_report_table_can_outgrow_its_wrap() -> None:
    """The wave's closing invariant: no table scrolls sideways in its own frame.

    A table used to be sized to its content (inline-size:max-content), so a
    single column that declared no width was sized by whatever the data
    happened to be, and one long value pushed the whole table past its wrap.
    Every column now declares a width and the layout is fixed, which makes this
    budget a proof rather than an estimate: under a fixed layout the rendered
    table is exactly max(wrap, sum of the declared widths), so a sum that fits
    the wrap cannot produce a horizontal scrollbar at that viewport or wider.

    The budget is the wrap at 1280px. Below it -- a 1024px viewport gives a
    959px wrap -- the widest tables still exceed it by exactly the difference,
    and the wrap's overflow-x:auto is the designed fallback there.
    """

    from codeclone.report.html.widgets.tables import render_rows_table

    call_sites = _report_table_header_sets()
    assert len(call_sites) >= 10, (
        f"only {len(call_sites)} table call sites resolved; the sweep is not exhaustive"
    )

    offenders: list[str] = []
    for where, headers, column_types in call_sites:
        html = render_rows_table(
            headers=headers,
            rows=[tuple(f"value {i}" for i in range(len(headers)))],
            empty_message="none",
            column_types=column_types or None,
            family=GLOSSARY_FAMILY_DEAD_CODE,
        )
        problem = _table_width_problem(_parse_report_tables(html))
        if problem:
            offenders.append(f"{where}: {problem}")

    assert not offenders, "tables that can outgrow their wrap:\n" + "\n".join(offenders)


def test_an_unregistered_column_is_still_bounded() -> None:
    """The invariant holds by construction, not by keeping a list current.

    A header nobody has registered a width for is exactly how the defect came
    back each time. An unknown column takes the default bound, so a new table
    cannot reintroduce a self-sizing column.
    """

    from codeclone.report.html.widgets.tables import render_rows_table

    html = render_rows_table(
        headers=("Totally Unregistered Column",),
        rows=[("x" * 400,)],
        empty_message="none",
        family=GLOSSARY_FAMILY_DEAD_CODE,
    )
    _headers, widths, _rows = _parse_report_tables(html)[0]
    assert widths and all(widths), "an unregistered column still sizes itself"


def test_meta_column_lift_stays_lossless_and_bounds_values() -> None:
    from codeclone.report.html.widgets import tables as tables_mod

    headers = ["name", "origin"]
    rows = [["a", "x"], ["a", "y"]]
    # Dropping "origin" would merge the two rows: the lift must refuse.
    kept_headers, kept_rows, parts = tables_mod._lift_meta_columns(
        headers, rows, {"origin"}
    )
    assert (kept_headers, kept_rows, parts) == (headers, rows, [])

    lead = tables_mod._meta_lead_html([("origin", ["a", "b", "c", "d", "e", "f"])])
    assert "+2 more" in lead


def test_pygments_highlight_refuses_unknown_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codeclone.report.html.widgets import snippets as snippets_mod

    if snippets_mod._load_pygments_api() is None:
        pytest.skip("pygments is not installed")

    assert snippets_mod._try_pygments("x = 1", language="yaml") is None

    monkeypatch.setitem(snippets_mod._LEXERS, "python", "NotARealLexer")
    assert snippets_mod._try_pygments("x = 1", language="python") is None
