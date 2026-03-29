# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

import codeclone.report.json_contract as json_contract_mod
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
    _collect_paths_from_metrics,
    _collect_report_file_list,
    _combined_impact_scope,
    _contract_path,
    _count_file_lines,
    _count_file_lines_for_path,
    _csv_values,
    _derive_inventory_code_counts,
    _findings_summary,
    _is_absolute_path,
    _normalize_block_machine_facts,
    _normalize_nested_string_rows,
    _parse_ratio_percent,
    _source_scope_from_filepaths,
    _source_scope_from_locations,
    _structural_group_assessment,
    _suggestion_finding_id,
    build_report_document,
)
from codeclone.report.markdown import (
    render_markdown_report_document,
    to_markdown_report,
)
from codeclone.report.sarif import (
    _baseline_state as _sarif_baseline_state,
)
from codeclone.report.sarif import (
    _location_entry as _sarif_location_entry,
)
from codeclone.report.sarif import (
    _location_message as _sarif_location_message,
)
from codeclone.report.sarif import (
    _logical_locations as _sarif_logical_locations,
)
from codeclone.report.sarif import (
    _partial_fingerprints as _sarif_partial_fingerprints,
)
from codeclone.report.sarif import (
    _result_message as _sarif_result_message,
)
from codeclone.report.sarif import (
    _result_properties as _sarif_result_properties,
)
from codeclone.report.sarif import (
    _rule_name as _sarif_rule_name,
)
from codeclone.report.sarif import (
    _rule_spec as _sarif_rule_spec,
)
from codeclone.report.sarif import (
    _scan_root_uri as _sarif_scan_root_uri,
)
from codeclone.report.sarif import (
    _severity_to_level,
    render_sarif_report_document,
    to_sarif_report,
)
from codeclone.report.sarif import (
    _text as _sarif_text,
)
from codeclone.report.serialize import (
    _append_single_item_findings,
    _append_structural_findings,
    _append_suggestions,
    _append_suppressed_dead_code_items,
    _structural_kind_label,
    render_text_report_document,
)
from tests._assertions import assert_mapping_entries


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
        "codeclone_version": "2.0.0b2",
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
    assert run["originalUriBaseIds"]["%SRCROOT%"]["uri"] == "file:///repo/codeclone/"
    assert run["artifacts"]
    assert run["artifacts"][0]["location"]["uriBaseId"] == "%SRCROOT%"
    assert any("relatedLocations" in result for result in run["results"])
    assert any("baselineState" in result for result in run["results"])
    assert all("help" in rule for rule in run["tool"]["driver"]["rules"])


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
    assert {
        "runtime": runtime_scope["impact_scope"],
        "non_runtime": non_runtime_scope["impact_scope"],
        "mixed_runtime": mixed_runtime_scope["impact_scope"],
        "mixed_other": mixed_scope["impact_scope"],
    } == {
        "runtime": "runtime",
        "non_runtime": "non_runtime",
        "mixed_runtime": "mixed",
        "mixed_other": "mixed",
    }

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

    assert_mapping_entries(
        counts,
        parsed_lines=2,
        scope="mixed",
        functions=9,
        methods=4,
        classes=2,
    )


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


def test_overview_health_snapshot_handles_non_mapping_dimensions() -> None:
    overview = overview_mod.build_report_overview(
        suggestions=(),
        metrics={"health": {"score": 72, "grade": "C", "dimensions": []}},
    )
    health = cast(dict[str, object], overview["health"])
    assert health == {
        "score": 72,
        "grade": "C",
        "strongest_dimension": None,
        "weakest_dimension": None,
    }


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
        artifact_index_map={"code/a.py": 3},
        use_uri_base_id=True,
        message_text="Related occurrence #7",
    )
    related_message = cast(dict[str, object], related["message"])
    related_physical = cast(dict[str, object], related["physicalLocation"])
    related_artifact = cast(dict[str, object], related_physical["artifactLocation"])
    assert (
        related["id"],
        related_message["text"],
        related_artifact["uriBaseId"],
        related_artifact["index"],
    ) == (7, "Related occurrence #7", "%SRCROOT%", 3)
    no_end_line = _sarif_location_entry(
        {"relative_path": "code/a.py", "start_line": 1, "end_line": 0}
    )
    region = cast(dict[str, object], no_end_line["physicalLocation"])["region"]
    assert region == {"startLine": 1}
    logical_only = _sarif_location_entry(
        {"module": "pkg.a"},
        message_text="Cycle member",
    )
    logical_message = cast(dict[str, object], logical_only["message"])
    assert "physicalLocation" not in logical_only
    assert logical_only["logicalLocations"] == [{"fullyQualifiedName": "pkg.a"}]
    assert logical_message["text"] == "Cycle member"


def test_sarif_private_helper_family_dispatches() -> None:
    clone_function = _sarif_rule_spec({"family": "clone", "category": "function"})
    clone_block = _sarif_rule_spec({"family": "clone", "category": "block"})
    structural_guard = _sarif_rule_spec(
        {
            "family": "structural",
            "kind": "clone_guard_exit_divergence",
        }
    )
    structural_drift = _sarif_rule_spec(
        {
            "family": "structural",
            "kind": "clone_cohort_drift",
        }
    )
    design_cohesion = _sarif_rule_spec({"family": "design", "category": "cohesion"})
    design_complexity = _sarif_rule_spec({"family": "design", "category": "complexity"})
    design_coupling = _sarif_rule_spec({"family": "design", "category": "coupling"})
    design_dependency = _sarif_rule_spec({"family": "design", "category": "dependency"})
    assert clone_function.rule_id == "CCLONE001"
    assert clone_block.rule_id == "CCLONE002"
    assert structural_guard.rule_id == "CSTRUCT002"
    assert structural_drift.rule_id == "CSTRUCT003"
    assert design_cohesion.rule_id == "CDESIGN001"
    assert design_complexity.rule_id == "CDESIGN002"
    assert design_coupling.rule_id == "CDESIGN003"
    assert design_dependency.rule_id == "CDESIGN004"

    assert (
        _sarif_result_message(
            {
                "family": "clone",
                "category": "function",
                "clone_type": "Type-2",
                "count": 3,
                "spread": {"files": 2},
                "items": [{"qualname": "pkg.mod:fn"}],
            }
        )
        == "Function clone group (Type-2), 3 occurrences across 2 files."
    )
    assert (
        _sarif_result_message(
            {
                "family": "dead_code",
                "category": "function",
                "confidence": "medium",
                "items": [{"relative_path": "pkg/mod.py"}],
            }
        )
        == "Unused function with medium confidence: pkg/mod.py."
    )
    assert "LCOM4=4" in _sarif_result_message(
        {
            "family": "design",
            "category": "cohesion",
            "facts": {"lcom4": 4},
            "items": [{"qualname": "pkg.mod:Thing"}],
        }
    )
    assert "CC=25" in _sarif_result_message(
        {
            "family": "design",
            "category": "complexity",
            "facts": {"cyclomatic_complexity": 25},
            "items": [{"qualname": "pkg.mod:run"}],
        }
    )
    assert "CBO=12" in _sarif_result_message(
        {
            "family": "design",
            "category": "coupling",
            "facts": {"cbo": 12},
            "items": [{"qualname": "pkg.mod:Thing"}],
        }
    )
    assert "Dependency cycle" in _sarif_result_message(
        {
            "family": "design",
            "category": "dependency",
            "items": [{"module": "pkg.a"}, {"module": "pkg.b"}],
        }
    )

    clone_props = _sarif_result_properties(
        {
            "family": "clone",
            "novelty": "new",
            "clone_kind": "function",
            "clone_type": "Type-2",
            "count": 2,
        }
    )
    guard_props = _sarif_result_properties(
        {
            "family": "structural",
            "count": 3,
            "signature": {
                "stable": {
                    "family": "clone_guard_exit_divergence",
                    "cohort_id": "cohort-1",
                    "majority_guard_count": 2,
                    "majority_terminal_kind": "return_expr",
                }
            },
        }
    )
    drift_props = _sarif_result_properties(
        {
            "family": "structural",
            "count": 3,
            "signature": {
                "stable": {
                    "family": "clone_cohort_drift",
                    "cohort_id": "cohort-2",
                    "drift_fields": ["guard_exit_profile", "terminal_kind"],
                }
            },
        }
    )
    design_props = _sarif_result_properties(
        {
            "family": "design",
            "facts": {
                "lcom4": 5,
                "method_count": 7,
                "instance_var_count": 2,
                "cbo": 12,
                "cyclomatic_complexity": 25,
                "nesting_depth": 4,
                "cycle_length": 3,
            },
        }
    )
    assert clone_props["groupArity"] == 2
    assert guard_props["cohortId"] == "cohort-1"
    assert drift_props["driftFields"] == [
        "guard_exit_profile",
        "terminal_kind",
    ]
    assert design_props["cycle_length"] == 3

    assert _sarif_location_message({"family": "clone"}) == "Representative occurrence"
    assert (
        _sarif_location_message({"family": "structural"}, related_id=2)
        == "Related occurrence #2"
    )
    assert (
        _sarif_location_message({"family": "dead_code"}, related_id=3)
        == "Related declaration #3"
    )
    assert (
        _sarif_location_message({"family": "design", "category": "dependency"})
        == "Cycle member"
    )
    assert (
        _sarif_location_message(
            {"family": "design", "category": "coupling"},
            related_id=4,
        )
        == "Related location #4"
    )

    line_hash = _sarif_partial_fingerprints(
        rule_id="CDESIGN002",
        group={"id": "design:complexity:pkg.mod:run"},
        primary_item={
            "relative_path": "pkg/mod.py",
            "qualname": "pkg.mod:run",
            "start_line": 10,
            "end_line": 14,
        },
    )
    no_line_hash = _sarif_partial_fingerprints(
        rule_id="CDESIGN001",
        group={"id": "design:cohesion:pkg.mod:Thing"},
        primary_item={"relative_path": "", "qualname": "", "start_line": 0},
    )
    shifted_line_hash = _sarif_partial_fingerprints(
        rule_id="CDESIGN002",
        group={"id": "design:complexity:pkg.mod:run"},
        primary_item={
            "relative_path": "pkg/mod.py",
            "qualname": "pkg.mod:run",
            "start_line": 30,
            "end_line": 34,
        },
    )
    assert "primaryLocationLineHash" in line_hash
    assert "primaryLocationLineHash" not in no_line_hash
    assert set(line_hash) == {"primaryLocationLineHash"}
    assert (
        line_hash["primaryLocationLineHash"].split(":", 1)[0]
        == shifted_line_hash["primaryLocationLineHash"].split(":", 1)[0]
    )


def test_sarif_private_helper_edge_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _sarif_rule_spec({"family": "clone", "category": "function"})
    assert _sarif_rule_name(spec) == "codeclone.CCLONE001"
    assert (
        _sarif_scan_root_uri({"meta": {"runtime": {"scan_root_absolute": "repo"}}})
        == ""
    )

    path_type = type(Path("/tmp"))
    original_as_uri = path_type.as_uri

    def _broken_as_uri(self: Path) -> str:
        raise ValueError("boom")

    monkeypatch.setattr(path_type, "as_uri", _broken_as_uri)
    try:
        assert (
            _sarif_scan_root_uri(
                {"meta": {"runtime": {"scan_root_absolute": "/repo/project"}}}
            )
            == ""
        )
    finally:
        monkeypatch.setattr(path_type, "as_uri", original_as_uri)

    dead_code_props = _sarif_result_properties(
        {"family": "dead_code", "confidence": "medium"}
    )
    assert dead_code_props["confidence"] == "medium"
    assert _sarif_baseline_state({"novelty": "known"}) == "unchanged"


def test_render_sarif_report_document_without_srcroot_keeps_relative_payload() -> None:
    payload = {
        "report_schema_version": "2.1",
        "meta": {
            "codeclone_version": "2.0.0b2",
            "analysis_mode": "ci",
            "report_mode": "full",
            "runtime": {},
        },
        "integrity": {"digest": {"value": "abc123"}},
        "findings": {
            "groups": {
                "clones": {"functions": [], "blocks": [], "segments": []},
                "dead_code": {"groups": []},
                "structural": {"groups": []},
                "design": {
                    "groups": [
                        {
                            "id": "design:dependency:pkg.a -> pkg.b",
                            "family": "design",
                            "category": "dependency",
                            "kind": "cycle",
                            "severity": "critical",
                            "confidence": "high",
                            "priority": 3.0,
                            "count": 2,
                            "source_scope": {
                                "impact_scope": "runtime",
                                "dominant_kind": "production",
                            },
                            "spread": {"files": 2, "functions": 0},
                            "items": [
                                {"module": "pkg.a", "relative_path": "pkg/a.py"},
                                {"module": "pkg.b", "relative_path": "pkg/b.py"},
                            ],
                            "facts": {"cycle_length": 2},
                        }
                    ]
                },
            }
        },
    }
    sarif = json.loads(render_sarif_report_document(payload))
    run = cast(dict[str, object], sarif["runs"][0])
    assert "originalUriBaseIds" not in run
    invocation = cast(dict[str, object], cast(list[object], run["invocations"])[0])
    assert "workingDirectory" not in invocation
    assert "startTimeUtc" not in invocation
    assert "columnKind" not in run
    result = cast(dict[str, object], cast(list[object], run["results"])[0])
    assert "baselineState" not in result
    assert result["kind"] == "fail"
    primary_location = cast(list[object], result["locations"])[0]
    location_map = cast(dict[str, object], primary_location)
    assert cast(dict[str, object], location_map["message"])["text"] == "Cycle member"
    assert cast(str, cast(dict[str, object], result["message"])["text"]).endswith(".")


def test_collect_paths_from_metrics_covers_all_metric_families_and_skips_missing() -> (
    None
):
    metrics = {
        "complexity": {
            "functions": [
                {"filepath": "/repo/complexity.py"},
                {"filepath": ""},
                {},
            ]
        },
        "coupling": {
            "classes": [
                {"filepath": "/repo/coupling.py"},
                {"filepath": None},
            ]
        },
        "cohesion": {
            "classes": [
                {"filepath": "/repo/cohesion.py"},
                {},
            ]
        },
        "dead_code": {
            "items": [
                {"filepath": "/repo/dead.py"},
                {"filepath": ""},
            ],
            "suppressed_items": [
                {"filepath": "/repo/suppressed.py"},
                {"filepath": None},
            ],
        },
    }

    assert _collect_paths_from_metrics(metrics) == {
        "/repo/complexity.py",
        "/repo/coupling.py",
        "/repo/cohesion.py",
        "/repo/dead.py",
        "/repo/suppressed.py",
    }


def test_collect_report_file_list_deterministically_merges_all_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Occurrence:
        def __init__(self, file_path: str) -> None:
            self.file_path = file_path

    class _Group:
        def __init__(self, *paths: str) -> None:
            self.items = tuple(_Occurrence(path) for path in paths)

    monkeypatch.setattr(
        json_contract_mod,
        "normalize_structural_findings",
        lambda _findings: [_Group("/repo/struct.py", "")],
    )
    structural_seed = (
        StructuralFindingGroup(
            finding_kind="duplicated_branches",
            finding_key="seed",
            signature={"stmt_seq": "Expr,Return"},
            items=(
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="seed",
                    file_path="/repo/ignored.py",
                    qualname="pkg.mod:fn",
                    start=1,
                    end=2,
                    signature={"stmt_seq": "Expr,Return"},
                ),
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="seed",
                    file_path="/repo/ignored.py",
                    qualname="pkg.mod:fn",
                    start=3,
                    end=4,
                    signature={"stmt_seq": "Expr,Return"},
                ),
            ),
        ),
    )

    files = _collect_report_file_list(
        inventory={"file_list": ["/repo/inventory.py", "", None]},
        func_groups={"f": [{"filepath": "/repo/function.py"}, {"filepath": ""}]},
        block_groups={"b": [{"filepath": "/repo/block.py"}]},
        segment_groups={"s": [{"filepath": None}, {"filepath": "/repo/segment.py"}]},
        metrics={
            "complexity": {"functions": [{"filepath": "/repo/metric.py"}]},
            "coupling": {"classes": []},
            "cohesion": {"classes": []},
            "dead_code": {"items": [], "suppressed_items": []},
        },
        structural_findings=structural_seed,
    )

    assert files == [
        "/repo/block.py",
        "/repo/function.py",
        "/repo/inventory.py",
        "/repo/metric.py",
        "/repo/segment.py",
        "/repo/struct.py",
    ]


def test_json_contract_private_helper_edge_branches() -> None:
    assert _csv_values("") == []
    assert _csv_values("  , ,  ") == []
    assert _csv_values("b, a, b") == ["a", "b"]

    severity, priority = _structural_group_assessment(
        finding_kind="clone_guard_exit_divergence",
        count=3,
        spread_functions=1,
    )
    assert severity == "critical"
    assert priority > 0

    severity, priority = _structural_group_assessment(
        finding_kind="clone_cohort_drift",
        count=1,
        spread_functions=2,
    )
    assert severity == "critical"
    assert priority > 0

    summary = _findings_summary(
        clone_functions=(
            {
                "severity": "mystery",
                "novelty": "new",
                "source_scope": {"impact_scope": "alien"},
            },
        ),
        clone_blocks=(),
        clone_segments=(),
        structural_groups=(),
        dead_code_groups=(),
        design_groups=(),
        dead_code_suppressed=-4,
    )
    assert summary["severity"] == {
        "critical": 0,
        "warning": 0,
        "info": 0,
    }
    assert summary["impact_scope"] == {
        "runtime": 0,
        "non_runtime": 0,
        "mixed": 0,
    }
    assert cast(dict[str, int], summary["clones"])["new"] == 1
    assert cast(dict[str, int], summary["suppressed"])["dead_code"] == 0


def test_build_report_document_suppressed_dead_code_accepts_empty_bindings() -> None:
    payload = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo"},
        metrics={
            "complexity": {"summary": {}, "functions": []},
            "coupling": {"summary": {}, "classes": []},
            "cohesion": {"summary": {}, "classes": []},
            "dependencies": {"cycles": [], "edge_list": [], "longest_chains": []},
            "dead_code": {
                "summary": {"total": 0, "high_confidence": 0, "suppressed": 1},
                "items": [],
                "suppressed_items": [
                    {
                        "qualname": "pkg.mod:kept",
                        "filepath": "/repo/pkg/mod.py",
                        "start_line": 10,
                        "end_line": 12,
                        "kind": "function",
                        "confidence": "high",
                        "suppressed_by": [{"rule": "", "source": "   "}, {}],
                    }
                ],
            },
            "health": {"score": 100, "grade": "A", "dimensions": {}},
        },
    )

    dead_code = cast(
        dict[str, object],
        cast(dict[str, object], payload["metrics"])["families"],
    )["dead_code"]
    dead_code_map = cast(dict[str, object], dead_code)
    suppressed_item = cast(list[dict[str, object]], dead_code_map["suppressed_items"])[
        0
    ]
    assert suppressed_item["suppressed_by"] == []
    assert suppressed_item["suppression_rule"] == ""
    assert suppressed_item["suppression_source"] == ""


def test_serialize_private_helpers_cover_structural_and_suppression_paths() -> None:
    assert _structural_kind_label("custom_kind") == "custom_kind"
    assert _structural_kind_label("") == "(none)"

    structural_lines: list[str] = []
    _append_structural_findings(
        structural_lines,
        [
            {
                "id": "structural:custom:1",
                "kind": "custom_kind",
                "severity": "warning",
                "confidence": "medium",
                "count": 4,
                "spread": {"files": 1, "functions": 1},
                "source_scope": {
                    "dominant_kind": "production",
                    "impact_scope": "runtime",
                },
                "signature": {
                    "stable": {
                        "family": "custom",
                        "stmt_shape": "Expr,Return",
                        "terminal_kind": "return",
                        "control_flow": {
                            "has_loop": "0",
                            "has_try": "0",
                            "nested_if": "0",
                        },
                    }
                },
                "facts": {"calls": 2},
                "items": [
                    {
                        "qualname": "pkg.mod:fn",
                        "relative_path": "pkg/mod.py",
                        "start_line": 1,
                        "end_line": 1,
                    },
                    {
                        "qualname": "pkg.mod:fn",
                        "relative_path": "pkg/mod.py",
                        "start_line": 2,
                        "end_line": 2,
                    },
                    {
                        "qualname": "pkg.mod:fn",
                        "relative_path": "pkg/mod.py",
                        "start_line": 3,
                        "end_line": 3,
                    },
                    {
                        "qualname": "pkg.mod:fn",
                        "relative_path": "pkg/mod.py",
                        "start_line": 4,
                        "end_line": 4,
                    },
                ],
            }
        ],
    )
    assert any(line.startswith("facts: ") for line in structural_lines)
    assert any("... and 1 more occurrences" in line for line in structural_lines)
    assert structural_lines[-1] != ""

    finding_lines: list[str] = []
    _append_single_item_findings(
        finding_lines,
        title="DESIGN FINDINGS",
        groups=[
            {
                "id": "design:complexity:pkg.mod:fn",
                "category": "complexity",
                "kind": "function_hotspot",
                "severity": "warning",
                "confidence": "high",
                "source_scope": {
                    "dominant_kind": "production",
                    "impact_scope": "runtime",
                },
                "facts": {"cyclomatic_complexity": 25},
                "items": [
                    {
                        "qualname": "pkg.mod:fn",
                        "relative_path": "pkg/mod.py",
                        "start_line": 10,
                        "end_line": 14,
                    }
                ],
            }
        ],
        fact_keys=("cyclomatic_complexity",),
    )
    assert any(line.startswith("facts: ") for line in finding_lines)
    assert finding_lines[-1] != ""

    suppressed_lines: list[str] = []
    _append_suppressed_dead_code_items(
        suppressed_lines,
        items=[
            {
                "kind": "function",
                "confidence": "high",
                "relative_path": "pkg/mod.py",
                "qualname": "pkg.mod:kept",
                "start_line": 20,
                "end_line": 22,
                "suppression_rule": "dead-code",
                "suppression_source": "inline_codeclone",
            }
        ],
    )
    assert any(
        "suppressed_by=dead-code@inline_codeclone" in line for line in suppressed_lines
    )
    assert suppressed_lines[-1] != ""

    suppressed_none_lines: list[str] = []
    _append_suppressed_dead_code_items(
        suppressed_none_lines,
        items=[
            {
                "kind": "function",
                "confidence": "medium",
                "relative_path": "pkg/mod.py",
                "qualname": "pkg.mod:unknown",
                "start_line": 30,
                "end_line": 31,
            }
        ],
    )
    assert any("suppressed_by=(none)" in line for line in suppressed_none_lines)

    suggestion_lines: list[str] = []
    _append_suggestions(
        suggestion_lines,
        suggestions=[
            {
                "title": "Investigate repeated flow",
                "finding_id": "missing:finding",
                "summary": "",
                "location_label": "pkg/mod.py:10-12",
                "representative_locations": [],
                "action": {"effort": "easy", "steps": []},
            }
        ],
        findings={
            "groups": {
                "clones": {"functions": [], "blocks": [], "segments": []},
                "structural": {"groups": []},
                "dead_code": {"groups": []},
                "design": {"groups": []},
            }
        },
    )
    assert any("Investigate repeated flow" in line for line in suggestion_lines)
    assert not any(line.lstrip().startswith("summary:") for line in suggestion_lines)
