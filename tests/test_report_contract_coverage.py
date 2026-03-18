from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from codeclone import _coerce
from codeclone.models import (
    ReportLocation,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Suggestion,
)
from codeclone.report import derived as derived_mod
from codeclone.report import overview as overview_mod
from codeclone.report.json_contract import (
    _build_design_groups,
    _clone_group_assessment,
    _combined_impact_scope,
    _contract_path,
    _count_file_lines,
    _count_file_lines_for_path,
    _derive_inventory_code_counts,
    _is_absolute_path,
    _normalize_block_machine_facts,
    _normalize_nested_string_rows,
    _parse_ratio_percent,
    _source_scope_from_filepaths,
    _source_scope_from_locations,
    _suggestion_finding_id,
    build_report_document,
)
from codeclone.report.markdown import (
    render_markdown_report_document,
    to_markdown_report,
)
from codeclone.report.sarif import (
    _location_entry as _sarif_location_entry,
)
from codeclone.report.sarif import (
    _logical_locations as _sarif_logical_locations,
)
from codeclone.report.sarif import (
    _result_message as _sarif_result_message,
)
from codeclone.report.sarif import (
    _rule_spec as _sarif_rule_spec,
)
from codeclone.report.sarif import (
    _severity_to_level,
    render_sarif_report_document,
    to_sarif_report,
)
from codeclone.report.sarif import (
    _text as _sarif_text,
)
from codeclone.report.serialize import render_text_report_document


def _rich_report_document() -> dict[str, object]:
    func_groups = {
        "fn-key": [
            {
                "qualname": "pkg.alpha:run",
                "filepath": "/repo/codeclone/codeclone/alpha.py",
                "start_line": 10,
                "end_line": 20,
                "loc": 11,
                "stmt_count": 6,
                "fingerprint": "fp-a",
                "loc_bucket": "1-19",
                "cyclomatic_complexity": 4,
                "nesting_depth": 2,
                "risk": "medium",
                "raw_hash": "rh-a",
            },
            {
                "qualname": "tests.alpha:test_run",
                "filepath": "/repo/codeclone/tests/test_alpha.py",
                "start_line": 12,
                "end_line": 22,
                "loc": 11,
                "stmt_count": 6,
                "fingerprint": "fp-a",
                "loc_bucket": "1-19",
                "cyclomatic_complexity": 2,
                "nesting_depth": 1,
                "risk": "low",
                "raw_hash": "rh-b",
            },
        ]
    }
    block_groups = {
        "blk-key": [
            {
                "block_hash": "blk-key",
                "qualname": "pkg.alpha:run",
                "filepath": "/repo/codeclone/codeclone/alpha.py",
                "start_line": 100,
                "end_line": 104,
                "size": 5,
            },
            {
                "block_hash": "blk-key",
                "qualname": "tests.fixtures.alpha:run_case",
                "filepath": "/repo/codeclone/tests/fixtures/case.py",
                "start_line": 40,
                "end_line": 44,
                "size": 5,
            },
        ]
    }
    segment_groups = {
        "seg-key": [
            {
                "segment_hash": "seg-key",
                "segment_sig": "sig-1",
                "qualname": "pkg.alpha:seg",
                "filepath": "/repo/codeclone/codeclone/alpha.py",
                "start_line": 200,
                "end_line": 205,
                "size": 6,
            },
            {
                "segment_hash": "seg-key",
                "segment_sig": "sig-1",
                "qualname": "pkg.beta:seg",
                "filepath": "/repo/codeclone/codeclone/beta.py",
                "start_line": 210,
                "end_line": 215,
                "size": 6,
            },
        ]
    }
    block_facts = {
        "blk-key": {
            "group_arity": "2",
            "block_size": "5",
            "consecutive_asserts": "1",
            "instance_peer_count": "1",
            "merged_regions": "true",
            "assert_ratio": "75%",
            "match_rule": "structural",
            "pattern": "blk-pattern",
            "signature_kind": "stmt-hash",
            "hint": "same setup pattern",
            "hint_confidence": "high",
            "group_compare_note": "N-way group compare note",
        }
    }
    structural_findings = (
        StructuralFindingGroup(
            finding_kind="duplicated_branches",
            finding_key="sf-1",
            signature={"stmt_seq": "Expr,Return", "terminal": "return_const"},
            items=(
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="sf-1",
                    file_path="/repo/codeclone/codeclone/cache.py",
                    qualname="codeclone.cache:Cache._load_and_validate",
                    start=120,
                    end=124,
                    signature={"stmt_seq": "Expr,Return", "terminal": "return_const"},
                ),
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="sf-1",
                    file_path="/repo/codeclone/codeclone/cache.py",
                    qualname="codeclone.cache:Cache._load_and_validate",
                    start=140,
                    end=144,
                    signature={"stmt_seq": "Expr,Return", "terminal": "return_const"},
                ),
            ),
        ),
    )
    metrics = {
        "complexity": {
            "avg": 3.0,
            "max": 50,
            "functions": [
                {
                    "qualname": "pkg.alpha:hot",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 10,
                    "end_line": 40,
                    "cyclomatic_complexity": 50,
                    "nesting_depth": 3,
                    "risk": "high",
                },
                {
                    "qualname": "pkg.alpha:warm",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 50,
                    "end_line": 70,
                    "cyclomatic_complexity": 25,
                    "nesting_depth": 2,
                    "risk": "medium",
                },
                {
                    "qualname": "pkg.alpha:ok",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 80,
                    "end_line": 90,
                    "cyclomatic_complexity": 10,
                    "nesting_depth": 1,
                    "risk": "low",
                },
            ],
        },
        "coupling": {
            "avg": 2.0,
            "max": 11,
            "classes": [
                {
                    "qualname": "pkg.alpha:HotClass",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 1,
                    "end_line": 40,
                    "cbo": 11,
                    "risk": "high",
                    "coupled_classes": ["X", "X", "Y"],
                },
                {
                    "qualname": "pkg.alpha:ColdClass",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 41,
                    "end_line": 60,
                    "cbo": 2,
                    "risk": "low",
                    "coupled_classes": [],
                },
            ],
        },
        "cohesion": {
            "avg": 2.0,
            "max": 4,
            "classes": [
                {
                    "qualname": "pkg.alpha:LowCohesion",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 1,
                    "end_line": 40,
                    "lcom4": 4,
                    "risk": "high",
                    "method_count": 4,
                    "instance_var_count": 1,
                },
                {
                    "qualname": "pkg.alpha:FineCohesion",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 41,
                    "end_line": 60,
                    "lcom4": 2,
                    "risk": "low",
                    "method_count": 2,
                    "instance_var_count": 1,
                },
            ],
        },
        "dependencies": {
            "module_count": 2,
            "edge_count": 1,
            "cycles": [[], ["pkg.alpha", "pkg.beta"]],
            "max_depth": 5,
            "edges": [
                {
                    "source": "pkg.alpha",
                    "target": "pkg.beta",
                    "import_type": "import",
                    "line": 3,
                }
            ],
            "longest_chains": [["pkg.alpha", "pkg.beta", "pkg.gamma"]],
        },
        "dead_code": {
            "summary": {"count": 2, "critical": 2},
            "items": [
                {
                    "qualname": "pkg.alpha:unused_fn",
                    "filepath": "/repo/codeclone/codeclone/alpha.py",
                    "start_line": 300,
                    "end_line": 305,
                    "kind": "function",
                    "confidence": "high",
                },
                {
                    "qualname": "tests.alpha:unused_test",
                    "filepath": "/repo/codeclone/tests/test_alpha.py",
                    "start_line": 30,
                    "end_line": 33,
                    "kind": "function",
                    "confidence": "medium",
                },
            ],
        },
        "health": {
            "summary": {
                "score": 77,
                "grade": "C",
                "dimensions": {
                    "coverage": 90,
                    "complexity": 40,
                },
            }
        },
    }
    suggestions = (
        Suggestion(
            severity="critical",
            category="clone",
            title="Refactor function clones",
            location="codeclone/alpha.py:10-20",
            steps=("Extract helper", "Parametrize values"),
            effort="moderate",
            priority=3.0,
            finding_family="clones",
            finding_kind="clone_group",
            subject_key="fn-key",
            fact_kind="Function clone group",
            fact_summary="same parameterized body",
            fact_count=2,
            spread_files=2,
            spread_functions=2,
            clone_type="Type-2",
            confidence="high",
            source_kind="production",
            source_breakdown=(("production", 2),),
            representative_locations=(
                ReportLocation(
                    filepath="/repo/codeclone/codeclone/alpha.py",
                    relative_path="codeclone/alpha.py",
                    start_line=10,
                    end_line=20,
                    qualname="pkg.alpha:run",
                    source_kind="production",
                ),
            ),
            location_label="2 occurrences across 2 files / 2 functions",
        ),
        Suggestion(
            severity="warning",
            category="structural",
            title="Consolidate branch family",
            location="codeclone/cache.py:120-124",
            steps=("Extract branch helper",),
            effort="easy",
            priority=2.0,
            finding_family="structural",
            finding_kind="duplicated_branches",
            subject_key="sf-1",
            fact_kind="duplicated_branches",
            fact_summary="same branch sequence",
            fact_count=2,
            spread_files=1,
            spread_functions=1,
            confidence="medium",
            source_kind="production",
            source_breakdown=(("production", 1),),
            representative_locations=(
                ReportLocation(
                    filepath="/repo/codeclone/codeclone/cache.py",
                    relative_path="codeclone/cache.py",
                    start_line=120,
                    end_line=124,
                    qualname="codeclone.cache:Cache._load_and_validate",
                    source_kind="production",
                ),
            ),
            location_label="2 occurrences across 1 file / 1 function",
        ),
        Suggestion(
            severity="warning",
            category="dependency",
            title="Break dependency cycle",
            location="pkg.alpha -> pkg.beta",
            steps=("Split imports",),
            effort="hard",
            priority=1.0,
            finding_family="metrics",
            finding_kind="cycle",
            subject_key="pkg.alpha -> pkg.beta",
            fact_kind="dependency cycle",
            fact_summary="cycle detected",
            fact_count=2,
            spread_files=2,
            spread_functions=0,
            confidence="high",
            source_kind="production",
            source_breakdown=(("production", 2),),
        ),
    )
    meta = {
        "codeclone_version": "2.0.0b1",
        "project_name": "codeclone",
        "scan_root": "/repo/codeclone",
        "python_version": "3.13.11",
        "python_tag": "cp313",
        "analysis_mode": "full",
        "report_mode": "full",
        "baseline_loaded": True,
        "baseline_status": "ok",
        "cache_used": True,
        "cache_status": "ok",
        "report_generated_at_utc": "2026-03-11T10:00:00Z",
    }
    inventory = {
        "files": {"total_found": 4, "analyzed": 4, "cached": 0, "skipped": 0},
        "code": {"parsed_lines": 100, "functions": 4, "methods": 1, "classes": 1},
        "file_list": [
            "/repo/codeclone/codeclone/alpha.py",
            "/repo/codeclone/codeclone/beta.py",
            "/repo/codeclone/tests/test_alpha.py",
            "/repo/codeclone/tests/fixtures/case.py",
            123,  # ignored by collector
        ],
    }

    return build_report_document(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta=meta,
        inventory=inventory,
        block_facts=block_facts,
        new_function_group_keys={"fn-key"},
        new_block_group_keys={"blk-key"},
        new_segment_group_keys={"seg-key"},
        metrics=metrics,
        suggestions=suggestions,
        structural_findings=structural_findings,
    )


def test_report_document_rich_invariants_and_renderers() -> None:
    payload = _rich_report_document()
    findings = cast(dict[str, object], payload["findings"])
    groups = cast(dict[str, object], findings["groups"])
    design = cast(dict[str, object], groups["design"])["groups"]
    design_groups = cast(list[dict[str, object]], design)
    categories = {str(item["category"]) for item in design_groups}
    assert {"complexity", "coupling", "cohesion", "dependency"}.issubset(categories)

    clones = cast(dict[str, object], groups["clones"])
    block_groups = cast(list[dict[str, object]], clones["blocks"])
    block_group = block_groups[0]
    assert cast(dict[str, object], block_group["facts"])["assert_ratio"] == 0.75
    assert "group_compare_note" in cast(dict[str, object], block_group["display_facts"])

    md = render_markdown_report_document(payload)
    sarif = json.loads(render_sarif_report_document(payload))
    txt = render_text_report_document(payload)
    assert "## Top Risks" in md
    assert "SUGGESTIONS (count=" in txt
    run = sarif["runs"][0]
    rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert {"CCLONE001", "CSTRUCT001", "CDEAD001", "CDESIGN001", "CDESIGN004"}.issubset(
        rule_ids
    )
    assert any("relatedLocations" in result for result in run["results"])


def test_markdown_and_sarif_reuse_prebuilt_report_document() -> None:
    payload = _rich_report_document()
    md = to_markdown_report(
        report_document=payload,
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    sarif = to_sarif_report(
        report_document=payload,
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    assert md.startswith("# CodeClone Report")
    sarif_payload = json.loads(sarif)
    assert sarif_payload["version"] == "2.1.0"


def test_json_contract_private_helpers_cover_edge_cases(tmp_path: Path) -> None:
    assert _coerce.as_int(True) == 1
    assert _coerce.as_int("x", 9) == 9
    assert _coerce.as_float(True) == 1.0
    assert _coerce.as_float("x", 1.5) == 1.5
    assert _parse_ratio_percent("") is None
    assert _parse_ratio_percent("25%") == 0.25
    assert _parse_ratio_percent("2") == 0.02
    assert _parse_ratio_percent("bad%") is None
    assert _parse_ratio_percent("bad") is None

    machine, display = _normalize_block_machine_facts(
        group_key="k",
        group_arity=2,
        block_facts={"assert_ratio": "not-a-ratio", "merged_regions": "yes"},
    )
    assert machine["merged_regions"] is True
    assert display["assert_ratio"] == "not-a-ratio"

    in_root, scope, original = _contract_path(
        "/repo/codeclone/codeclone/a.py", scan_root="/repo/codeclone"
    )
    assert (in_root, scope, original) == (
        "codeclone/a.py",
        "in_root",
        "/repo/codeclone/codeclone/a.py",
    )
    external, scope_ext, original_ext = _contract_path(
        "/opt/ext/x.py", scan_root="/repo/codeclone"
    )
    assert (external, scope_ext, original_ext) == ("x.py", "external", "/opt/ext/x.py")
    rel, scope_rel, original_rel = _contract_path(
        "codeclone/a.py", scan_root="/repo/codeclone"
    )
    assert (rel, scope_rel, original_rel) == ("codeclone/a.py", "relative", None)
    assert _is_absolute_path("") is False

    runtime_scope = _source_scope_from_filepaths(
        ["/repo/codeclone/codeclone/a.py"],
        scan_root="/repo/codeclone",
    )
    non_runtime_scope = _source_scope_from_filepaths(
        ["/repo/codeclone/tests/test_a.py"],
        scan_root="/repo/codeclone",
    )
    mixed_runtime_scope = _source_scope_from_filepaths(
        ["/repo/codeclone/codeclone/a.py", "/repo/codeclone/tests/test_a.py"],
        scan_root="/repo/codeclone",
    )
    mixed_scope = _source_scope_from_locations(
        [{"source_kind": "production"}, {"source_kind": "strange"}]
    )
    assert runtime_scope["impact_scope"] == "runtime"
    assert non_runtime_scope["impact_scope"] == "non_runtime"
    assert mixed_runtime_scope["impact_scope"] == "mixed"
    assert mixed_scope["impact_scope"] == "mixed"

    assert _normalize_nested_string_rows([["b", "a"], [], ["b", "a"], ["c"]]) == [
        ["c"],
        ["b", "a"],
        ["b", "a"],
    ]
    assert _count_file_lines_for_path(str(tmp_path / "missing.py")) == 0
    existing = tmp_path / "ok.py"
    existing.write_text("a\nb\n", "utf-8")
    assert _count_file_lines_for_path(str(existing)) == 2
    assert _combined_impact_scope([]) == "non_runtime"
    assert (
        _combined_impact_scope([{"source_scope": {"impact_scope": "runtime"}}])
        == "runtime"
    )
    assert (
        _combined_impact_scope(
            [
                {"source_scope": {"impact_scope": "runtime"}},
                {"source_scope": {"impact_scope": "non_runtime"}},
            ]
        )
        == "mixed"
    )
    assert _clone_group_assessment(count=4, clone_type="Type-4")[0] == "critical"

    design_groups = _build_design_groups(
        {"families": {"dependencies": {"cycles": [5]}}},
        scan_root="/repo/codeclone",
    )
    assert design_groups == []


def test_coerce_helper_numeric_branches() -> None:
    assert _coerce.as_int(True) == 1
    assert _coerce.as_int("bad") == 0
    assert _coerce.as_float(True) == 1.0
    assert _coerce.as_float("bad") == 0.0
    assert _coerce.as_mapping("bad") == {}
    assert _coerce.as_sequence("bad") == ()


def test_count_file_lines_aggregates_paths(tmp_path: Path) -> None:
    one = tmp_path / "one.py"
    two = tmp_path / "two.py"
    one.write_text("a\nb\n", "utf-8")
    two.write_text("x\n", "utf-8")
    assert _count_file_lines([str(one), str(two), str(tmp_path / "missing.py")]) == 3


def test_derive_inventory_code_counts_uses_cached_line_scan_fallback(
    tmp_path: Path,
) -> None:
    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n", "utf-8")

    counts = _derive_inventory_code_counts(
        metrics_payload={
            "families": {
                "complexity": {"items": []},
                "cohesion": {"items": []},
            }
        },
        inventory_code={
            "parsed_lines": "unknown",
            "functions": 9,
            "methods": 4,
            "classes": 2,
        },
        file_list=[str(source)],
        cached_files=1,
    )

    assert counts["parsed_lines"] == 2
    assert counts["scope"] == "mixed"
    assert counts["functions"] == 9
    assert counts["methods"] == 4
    assert counts["classes"] == 2


def test_markdown_render_long_list_branches() -> None:
    payload = cast(dict[str, object], json.loads(json.dumps(_rich_report_document())))
    findings = cast(dict[str, object], payload["findings"])
    groups = cast(dict[str, object], findings["groups"])
    clone_groups = cast(dict[str, object], groups["clones"])
    function_groups = cast(list[dict[str, object]], clone_groups["functions"])
    first_group = function_groups[0]
    first_group_items = cast(list[dict[str, object]], first_group["items"])
    base_item = first_group_items[0]
    first_group["items"] = [
        {
            **base_item,
            "start_line": 10 + idx,
            "end_line": 11 + idx,
        }
        for idx in range(7)
    ]

    metrics = cast(dict[str, object], payload["metrics"])
    families = cast(dict[str, object], metrics["families"])
    complexity = cast(dict[str, object], families["complexity"])
    complexity_items = cast(list[dict[str, object]], complexity["items"])
    base_metric = complexity_items[0]
    complexity["items"] = [
        {
            **base_metric,
            "start_line": 100 + idx,
            "end_line": 101 + idx,
            "qualname": f"pkg.alpha:f{idx}",
        }
        for idx in range(12)
    ]

    derived = cast(dict[str, object], payload["derived"])
    suggestions = cast(list[dict[str, object]], derived["suggestions"])
    suggestions[0]["action"] = {"effort": "easy", "steps": []}
    markdown = render_markdown_report_document(payload)
    assert "... and 2 more occurrence(s)" in markdown
    assert "... and 2 more item(s)" in markdown


def test_sarif_helper_level_mapping() -> None:
    assert _severity_to_level("critical") == "error"
    assert _severity_to_level("warning") == "warning"
    assert _severity_to_level("info") == "note"
    assert _severity_to_level("unexpected") == "note"


def test_derived_module_branches() -> None:
    assert derived_mod.relative_report_path("", scan_root="/repo/proj") == ""
    assert (
        derived_mod.relative_report_path("/repo/proj/a.py", scan_root="/repo/proj")
        == "a.py"
    )
    assert (
        derived_mod.relative_report_path("/repo/proj", scan_root="/repo/proj") == "proj"
    )
    assert derived_mod.classify_source_kind(".", scan_root="/repo/proj") == "other"
    assert derived_mod.classify_source_kind("tests/fixtures/x.py") == "fixtures"
    assert derived_mod.classify_source_kind("tests/x.py") == "tests"
    assert derived_mod.combine_source_kinds([]) == "other"
    assert derived_mod.combine_source_kinds(["production", "tests"]) == "mixed"

    loc = derived_mod.report_location_from_group_item(
        {
            "filepath": "/repo/proj/code/a.py",
            "qualname": "pkg:a",
            "start_line": True,
            "end_line": 2,
        },
        scan_root="/repo/proj",
    )
    fallback_loc = derived_mod.report_location_from_group_item(
        {
            "filepath": "/repo/proj/code/b.py",
            "qualname": "pkg:b",
            "start_line": "x",
            "end_line": "y",
        },
        scan_root="/repo/proj",
    )
    assert fallback_loc.start_line == 0
    assert fallback_loc.end_line == 0
    reps = derived_mod.representative_locations([loc, loc], limit=3)
    assert len(reps) == 1
    assert derived_mod.format_group_location_label(reps, total_count=0) == "(unknown)"
    assert derived_mod.format_group_location_label(reps, total_count=1).startswith(
        "code/a.py"
    )


def test_overview_module_branches() -> None:
    suggestion = Suggestion(
        severity="warning",
        category="dead_code",
        title="Remove dead code",
        location="code/a.py:1-2",
        steps=("Delete symbol",),
        effort="easy",
        priority=2.0,
        finding_family="metrics",
        finding_kind="dead_code",
        subject_key="code.a:dead",
        fact_kind="dead code",
        fact_summary="unused function",
        fact_count=1,
        spread_files=1,
        spread_functions=1,
        confidence="high",
        source_kind="production",
    )
    overview = overview_mod.build_report_overview(
        suggestions=(
            suggestion,
            Suggestion(
                severity="warning",
                category="structural",
                title="Structural signal",
                location="code/b.py:3-4",
                steps=("Refactor",),
                effort="moderate",
                priority=2.0,
                finding_family="structural",
                finding_kind="duplicated_branches",
                subject_key="sf",
                fact_kind="duplicated_branches",
                fact_summary="same branch family",
                fact_count=2,
                spread_files=1,
                spread_functions=1,
                confidence="medium",
                source_kind="production",
            ),
            Suggestion(
                severity="critical",
                category="clone",
                title="Fixture clone",
                location="tests/fixtures/x.py:1-4",
                steps=("Extract fixture builder",),
                effort="easy",
                priority=3.0,
                finding_family="clones",
                finding_kind="clone_group",
                subject_key="g",
                fact_kind="Function clone group",
                fact_summary="same body",
                fact_count=2,
                spread_files=1,
                spread_functions=1,
                confidence="high",
                source_kind="fixtures",
            ),
        ),
        metrics={
            "dead_code": {"summary": {"critical": 1}},
            "cohesion": {"summary": {"low_cohesion": 1}},
            "health": {
                "score": 80,
                "grade": "B",
                "dimensions": {
                    "coverage": 90,
                    "complexity": 60,
                },
            },
        },
    )
    families = cast(dict[str, object], overview["families"])
    assert families["dead_code"] == 1
    assert overview["top_risks"]
    health = cast(dict[str, object], overview["health"])
    assert health["strongest_dimension"] == "coverage"
    assert health["weakest_dimension"] == "complexity"
    empty_overview = overview_mod.build_report_overview(suggestions=(), metrics=None)
    assert empty_overview["top_risks"] == []


def test_overview_handles_non_mapping_metric_summaries() -> None:
    suggestion = Suggestion(
        severity="warning",
        category="structural",
        title="Structural signal",
        location="code/b.py:3-4",
        steps=("Refactor",),
        effort="moderate",
        priority=2.0,
        finding_family="structural",
        finding_kind="duplicated_branches",
        subject_key="sf",
        fact_kind="duplicated_branches",
        fact_summary="same branch family",
        fact_count=2,
        spread_files=1,
        spread_functions=1,
        confidence="medium",
        source_kind="production",
    )
    overview = overview_mod.build_report_overview(
        suggestions=(suggestion,),
        metrics={
            "dead_code": {"summary": []},
            "cohesion": {"summary": []},
            "health": {"score": 75, "grade": "C", "dimensions": {"quality": "bad"}},
        },
    )
    assert overview["top_risks"] == ["1 structural finding in production code"]
    health = cast(dict[str, object], overview["health"])
    assert health["strongest_dimension"] is None
    assert health["weakest_dimension"] is None


def test_suggestion_finding_id_fallback_branch() -> None:
    @dataclass
    class _FakeSuggestion:
        finding_family: str
        finding_kind: str
        subject_key: str
        category: str
        title: str

    fake = cast(
        Suggestion,
        _FakeSuggestion(
            finding_family="metrics",
            finding_kind="misc",
            subject_key="",
            category="unmapped_category",
            title="Synthetic title",
        ),
    )
    assert _suggestion_finding_id(fake) == "design:unmapped_category:Synthetic title"


def test_suggestion_finding_id_segment_clone_branch() -> None:
    segment_clone = Suggestion(
        severity="info",
        category="clone",
        title="Segment clone",
        location="code/a.py:1-3",
        steps=(),
        effort="easy",
        priority=1.0,
        finding_family="clones",
        finding_kind="clone_group",
        subject_key="seg-1",
        fact_kind="Segment clone group",
        fact_summary="same segment",
        fact_count=2,
        spread_files=2,
        spread_functions=2,
        confidence="medium",
        source_kind="production",
    )
    assert _suggestion_finding_id(segment_clone) == "clone:segment:seg-1"


def test_suggestion_finding_id_block_clone_branch() -> None:
    block_clone = Suggestion(
        severity="warning",
        category="clone",
        title="Block clone",
        location="code/a.py:10-15",
        steps=(),
        effort="easy",
        priority=1.5,
        finding_family="clones",
        finding_kind="clone_group",
        subject_key="blk-1",
        fact_kind="Block clone group",
        fact_summary="same statement sequence",
        fact_count=2,
        spread_files=2,
        spread_functions=2,
        confidence="high",
        source_kind="production",
    )
    assert _suggestion_finding_id(block_clone) == "clone:block:blk-1"


def test_sarif_private_helper_branches() -> None:
    assert _coerce.as_int(True) == 1
    assert _coerce.as_int("bad") == 0
    assert _coerce.as_float(True) == 1.0
    assert _coerce.as_float("bad") == 0.0
    assert _coerce.as_float(object()) == 0.0
    assert _coerce.as_mapping("bad") == {}
    assert _coerce.as_sequence("bad") == ()
    assert _sarif_text(None) == ""

    dead_class = _sarif_rule_spec({"family": "dead_code", "category": "class"})
    dead_method = _sarif_rule_spec({"family": "dead_code", "category": "method"})
    dead_other = _sarif_rule_spec({"family": "dead_code", "category": "other"})
    assert dead_class.rule_id == "CDEAD002"
    assert dead_method.rule_id == "CDEAD003"
    assert dead_other.rule_id == "CDEAD004"

    dep_message = _sarif_result_message(
        {
            "family": "design",
            "category": "dependency",
            "count": 2,
            "items": [{"module": "pkg.a"}, {"module": "pkg.b"}],
            "spread": {"files": 2},
        }
    )
    assert "Dependency cycle" in dep_message
    structural_without_qualname = _sarif_result_message(
        {
            "family": "structural",
            "category": "duplicated_branches",
            "count": 2,
            "signature": {"stable": {"stmt_shape": "Expr,Return"}},
            "items": [{"relative_path": "code/a.py"}],
        }
    )
    assert "Repeated branch family" in structural_without_qualname

    assert _sarif_logical_locations({"module": "pkg.a"}) == [
        {"fullyQualifiedName": "pkg.a"}
    ]
    related = _sarif_location_entry(
        {"relative_path": "code/a.py", "start_line": 1, "end_line": 2},
        related_id=7,
    )
    assert related["id"] == 7
    no_end_line = _sarif_location_entry(
        {"relative_path": "code/a.py", "start_line": 1, "end_line": 0}
    )
    region = cast(dict[str, object], no_end_line["physicalLocation"])["region"]
    assert region == {"startLine": 1}
