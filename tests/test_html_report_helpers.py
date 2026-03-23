from types import SimpleNamespace
from typing import Any, cast

from codeclone._html_report._components import (
    overview_row_html,
    overview_source_breakdown_html,
    overview_summary_item_html,
    overview_summary_list_html,
)
from codeclone._html_report._sections._clones import (
    _derive_group_display_name,
    _render_group_explanation,
)
from codeclone._html_report._sections._dependencies import (
    _hub_threshold,
    _render_dep_nodes_and_labels,
    _select_dep_nodes,
)
from codeclone._html_report._sections._overview import _top_risk_label
from codeclone._html_report._tabs import render_split_tabs


def test_summary_helpers_cover_empty_and_non_clone_context_branches() -> None:
    assert overview_summary_list_html(("", "   ")) == (
        '<div class="overview-summary-value">none</div>'
    )
    assert overview_source_breakdown_html({}) == (
        '<div class="overview-summary-value">n/a</div>'
    )

    row_html = overview_row_html(
        {
            "severity": "warning",
            "source_kind": "production",
            "category": "complexity",
            "title": "Large renderer",
            "summary": "Needs extraction",
            "confidence": "high",
            "location": "pkg/mod.py:10",
            "count": 2,
            "spread": {"files": 1, "functions": 2},
        }
    )
    assert "severity-warning" in row_html
    assert "Production" in row_html
    assert "2 fn / 1 files" in row_html
    assert "clone_type" not in row_html


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

    row_html = overview_row_html(
        {
            "severity": "critical",
            "source_kind": "tests",
            "title": "Function clone group (Type-2)",
            "summary": "same parameterized function body",
            "clone_type": "Type-2",
            "count": 4,
            "spread": {"files": 4, "functions": 4},
        }
    )
    assert "clone-type-badge" in row_html
    assert "4 occurrences" in row_html
    assert "severity-critical" in row_html


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


def test_dependency_helpers_cover_dense_and_empty_branches() -> None:
    edges = [(f"n{i}", f"n{i + 1}") for i in range(21)]
    nodes, filtered = _select_dep_nodes(edges)
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
    )
    assert len(node_svg) == 9
    assert len(label_svg) == 9
    assert "rotate(-45)" in label_svg[0]


def test_top_risk_label_handles_structured_and_string_edge_cases() -> None:
    assert _top_risk_label({"family": "dead_code", "count": 3, "scope": "tests"}) == (
        "3 dead code (tests)"
    )
    assert _top_risk_label({"family": "complexity"}) == "complexity"
    assert _top_risk_label("{opaque}") == ""


def test_render_split_tabs_returns_empty_for_no_tabs() -> None:
    assert render_split_tabs(group_id="dead-code", tabs=()) == ""
