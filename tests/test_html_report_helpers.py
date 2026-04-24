# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.report.html.assemble as assemble_mod
import codeclone.report.html.sections._suggestions as suggestions_section
import codeclone.ui_messages as ui
from codeclone.baseline.trust import current_python_tag
from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.models import MetricsDiff, ReportLocation, Suggestion
from codeclone.report.html.sections._clones import (
    _derive_group_display_name,
    _render_group_explanation,
)
from codeclone.report.html.sections._dead_code import render_dead_code_panel
from codeclone.report.html.sections._dependencies import (
    _hub_threshold,
    _layout_dep_graph,
    _render_dep_nodes_and_labels,
    _select_dep_nodes,
)
from codeclone.report.html.sections._meta import _path_basename, render_meta_panel
from codeclone.report.html.sections._overview import (
    _directory_hotspot_bucket_body,
    _directory_kind_meta_parts,
    _health_gauge_html,
    _issue_breakdown_html,
    render_overview_panel,
)
from codeclone.report.html.sections._suggestions import (
    _format_source_breakdown,
    _priority_badge_label,
    _render_card,
    _render_fact_summary,
    _spread_label,
    _suggestion_context_labels,
)
from codeclone.report.html.widgets.badges import _quality_badge_html, _stat_card
from codeclone.report.html.widgets.components import (
    overview_source_breakdown_html,
    overview_summary_item_html,
)
from codeclone.report.html.widgets.icons import section_icon_html
from codeclone.report.html.widgets.snippets import _FileCache
from codeclone.report.html.widgets.tabs import render_split_tabs
from tests._assertions import assert_contains_none


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


def test_dependency_helpers_cover_dense_and_empty_branches() -> None:
    edges = [(f"n{i}", f"n{i + 1}") for i in range(21)]
    nodes, filtered = _select_dep_nodes(
        edges,
        dep_cycles=(),
        longest_chains=(),
    )
    assert len(nodes) == 20
    assert len(filtered) <= 100
    assert _hub_threshold([], {}, {}) == 99

    node_svg, label_svg = _render_dep_nodes_and_labels(
        [f"n{i}" for i in range(9)],
        positions={f"n{i}": (float(i), float(i + 1)) for i in range(9)},
        node_radii={f"n{i}": 3.0 for i in range(9)},
        in_degree={f"n{i}": 1 for i in range(9)},
        out_degree={f"n{i}": 1 for i in range(9)},
        cycle_node_set={"n0"},
        hub_threshold=1,
        max_per_layer=9,
        prefer_horizontal=True,
    )
    assert len(node_svg) == 9
    assert len(label_svg) == 9
    assert "rotate(-45)" in label_svg[0]


def test_dependency_layout_covers_horizontal_and_non_rotated_label_paths() -> None:
    layer_groups = {
        0: ["alpha", "beta", "gamma"],
        1: ["delta", "epsilon", "zeta"],
        2: ["eta"],
        3: ["theta"],
        4: ["iota"],
        5: ["kappa"],
    }
    in_degree = {
        "alpha": 0,
        "beta": 1,
        "gamma": 3,
        "delta": 2,
        "epsilon": 1,
        "zeta": 1,
        "eta": 2,
        "theta": 1,
        "iota": 1,
        "kappa": 1,
    }
    out_degree = {
        "alpha": 1,
        "beta": 2,
        "gamma": 4,
        "delta": 2,
        "epsilon": 1,
        "zeta": 1,
        "eta": 2,
        "theta": 1,
        "iota": 1,
        "kappa": 0,
    }
    width, height, max_per_layer, positions = _layout_dep_graph(
        layer_groups,
        in_degree=in_degree,
        out_degree=out_degree,
    )
    assert width > height
    assert max_per_layer == 3
    assert positions["beta"][1] != positions["gamma"][1]
    assert positions["delta"][0] > positions["alpha"][0]

    node_svg, label_svg = _render_dep_nodes_and_labels(
        ["leaf", "hub"],
        positions={"leaf": (10.0, 20.0), "hub": (40.0, 20.0)},
        node_radii={"leaf": 3.0, "hub": 6.0},
        in_degree={"leaf": 0, "hub": 2},
        out_degree={"leaf": 1, "hub": 2},
        cycle_node_set=set(),
        hub_threshold=3,
        max_per_layer=2,
        prefer_horizontal=False,
    )
    assert len(node_svg) == 2
    assert len(label_svg) == 2
    assert 'text-anchor="middle"' in label_svg[0]
    assert 'font-size="8"' in label_svg[0]
    assert 'font-size="10"' in label_svg[1]
    assert "rotate(-45)" not in label_svg[0]


def test_cli_runtime_warning_formatter_covers_baseline_and_legacy_cache_paths() -> None:
    rendered = ui.fmt_cli_runtime_warning(
        "Baseline trust mismatch: python_tag=cp313\n\nLegacy cache format ignored"
    )
    assert (
        rendered == "  [warning]Baseline[/warning] trust mismatch\n"
        "    [dim]python_tag=cp313[/dim]\n\n"
        "  [warning]Cache[/warning] Legacy cache format ignored"
    )


def test_render_split_tabs_returns_empty_for_no_tabs() -> None:
    assert render_split_tabs(group_id="dead-code", tabs=()) == ""


def _section_ctx(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "clone_groups_total": 4,
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
        "overview_data": {"source_breakdown": {"production": 3, "tests": 1}},
        "bare_qualname": (
            lambda qualname, _filepath: qualname.rsplit(":", maxsplit=1)[-1]
        ),
        "relative_path": lambda filepath: filepath,
        "meta": {},
        "baseline_meta": {},
        "cache_meta": {},
        "metrics_baseline_meta": {},
        "runtime_meta": {},
        "integrity_map": {},
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "report_generated_at": "2026-03-22T21:30:45Z",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_suggestion(**overrides: object) -> Suggestion:
    payload: dict[str, object] = {
        "severity": "warning",
        "category": "complexity",
        "title": "Reduce function complexity",
        "location": "pkg/mod.py:10-20",
        "steps": ("Extract a helper.",),
        "effort": "moderate",
        "priority": 0.9,
        "finding_family": "metrics",
        "finding_kind": "function_hotspot",
        "subject_key": "pkg.mod:run",
        "fact_kind": "Complexity hotspot",
        "fact_summary": "cyclomatic_complexity=15, guard_count=2, hot path",
        "fact_count": 2,
        "spread_files": 2,
        "spread_functions": 3,
        "clone_type": "",
        "confidence": "high",
        "source_kind": "production",
        "source_breakdown": (("production", 2), ("tests", 1)),
        "representative_locations": (
            ReportLocation(
                filepath="/repo/pkg/mod.py",
                relative_path="pkg/mod.py",
                start_line=10,
                end_line=20,
                qualname="pkg.mod:run",
                source_kind="production",
            ),
        ),
        "location_label": "pkg/mod.py:10-20",
    }
    payload.update(overrides)
    return Suggestion(**cast(Any, payload))


def test_html_badges_and_cards_cover_effort_and_tip_paths() -> None:
    assert 'risk-badge risk-moderate">moderate<' in _quality_badge_html("moderate")

    card_html = _stat_card(
        "High Complexity",
        7,
        tip="Cyclomatic hotspots",
        value_tone="good",
        delta_new=2,
    )
    assert "meta-value--good" in card_html
    assert 'data-tip="Cyclomatic hotspots"' in card_html
    assert "+2<" in card_html

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
    assert '<span class="kpi-micro-lbl">baselined</span>' in panel_html
    assert "health-ring-delta--up" in panel_html


def test_render_dead_code_panel_warns_when_only_medium_confidence_items_exist() -> None:
    panel_html = render_dead_code_panel(cast(Any, _section_ctx()))
    assert "2 candidates total" not in panel_html
    assert "4 candidates total" in panel_html
    assert "No dead code detected." not in panel_html


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
        _make_suggestion(
            category=cast(Any, ""),
            source_kind=cast(Any, ""),
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
        _make_suggestion(
            category=cast(Any, "clone"),
            source_kind=cast(Any, "fixtures"),
            finding_kind="function",
            clone_type="Type-2",
        )
    )
    assert clone_labels == ("Fixtures", "Function", "Type-2")

    generic_labels = _suggestion_context_labels(
        _make_suggestion(category=cast(Any, "dead_code"))
    )
    assert generic_labels == ("Production", "Dead Code")

    clone_labels_without_type = _suggestion_context_labels(
        _make_suggestion(
            category=cast(Any, "clone"),
            source_kind=cast(Any, "tests"),
            finding_kind="function",
            clone_type="",
        )
    )
    assert clone_labels_without_type == ("Tests", "Function")


def test_section_icon_html_returns_empty_for_unknown_keys() -> None:
    assert section_icon_html(" missing-section ") == ""


def test_render_card_uses_professional_clone_context_chip_rhythm() -> None:
    card_html = _render_card(
        _make_suggestion(
            category=cast(Any, "clone"),
            source_kind=cast(Any, "fixtures"),
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
        _make_suggestion(effort="easy", priority=1.5), cast(Any, _section_ctx())
    )
    assert (
        '<span class="suggestion-meta-badge suggestion-effort--easy">Easy</span>'
        in card_html
    )
    assert '<span class="suggestion-meta-badge">Priority 1.5</span>' in card_html
    assert (
        '<span class="suggestion-meta-badge">3 functions · 2 files</span>' in card_html
    )
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
    html_without_pygments = assemble_mod.build_html_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        block_group_facts={},
        report_meta={"project_name": "demo"},
        metrics={},
        report_document={},
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
        func_groups={},
        block_groups={},
        segment_groups={},
        block_group_facts={},
        report_meta={"project_name": "demo"},
        metrics={},
        report_document={},
    )
    assert '[data-theme="light"] .codebox span' not in html_without_light_rules


def test_render_meta_panel_covers_status_tones_and_runtime_mismatch() -> None:
    runtime_tag = current_python_tag()
    baseline_tag = "cp313" if runtime_tag != "cp313" else "cp314"
    meta_html = render_meta_panel(
        cast(
            Any,
            SimpleNamespace(
                meta={
                    "python_tag": runtime_tag,
                    "baseline_python_tag": baseline_tag,
                    "cache_status": "stale",
                    "metrics_baseline_loaded": True,
                    "metrics_baseline_payload_sha256_verified": True,
                },
                baseline_meta={"status": "FAILED"},
                cache_meta={},
                metrics_baseline_meta={},
                runtime_meta={},
                integrity_map={},
                report_schema_version="2.9",
                report_generated_at="2026-04-15T12:00:00Z",
            ),
        )
    )
    assert 'class="prov-badge prov-badge--red prov-badge--inline"' in meta_html
    assert 'class="prov-badge prov-badge--neutral prov-badge--inline"' in meta_html
    assert 'class="prov-badge prov-badge--amber prov-badge--inline"' in meta_html
    assert '<span class="prov-badge-val">FAILED</span>' in meta_html
    assert '<span class="prov-badge-val">stale</span>' in meta_html
    assert f'<span class="prov-badge-val">runtime {runtime_tag}</span>' in meta_html
    assert '<span class="prov-badge-val">verified</span>' in meta_html
    assert '<span class="prov-badge-lbl">Metrics baseline</span>' in meta_html
