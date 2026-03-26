import ast
import json
from collections.abc import Callable, Collection, Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest

import codeclone.report as report_mod
import codeclone.report.merge as merge_mod
import codeclone.report.overview as overview_mod
import codeclone.report.serialize as serialize_mod
from codeclone.contracts import CACHE_VERSION, REPORT_SCHEMA_VERSION
from codeclone.models import (
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Suggestion,
)
from codeclone.report import (
    GroupMap,
    build_block_group_facts,
    build_block_groups,
    build_groups,
    build_segment_groups,
    prepare_block_report_groups,
    prepare_segment_report_groups,
    to_markdown_report,
    to_sarif_report,
)
from codeclone.report.findings import build_structural_findings_html_panel
from codeclone.report.json_contract import build_report_document
from codeclone.report.overview import materialize_report_overview
from codeclone.report.serialize import (
    render_json_report_document,
    render_text_report_document,
)
from tests._assertions import assert_contains_all, assert_mapping_entries
from tests._report_access import (
    report_clone_groups as _clone_groups,
)
from tests._report_access import (
    report_structural_groups as _structural_groups,
)
from tests._report_fixtures import (
    REPEATED_STMT_HASH,
    repeated_block_group_key,
    write_repeated_assert_source,
)


def to_json_report(
    func_groups: GroupMap,
    block_groups: GroupMap,
    segment_groups: GroupMap,
    meta: Mapping[str, object] | None = None,
    inventory: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
) -> str:
    payload = build_report_document(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta=meta,
        inventory=inventory,
        block_facts=block_facts,
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        metrics=metrics,
        suggestions=suggestions or (),
        structural_findings=structural_findings or (),
    )
    return render_json_report_document(payload)


def to_text_report(
    *,
    meta: Mapping[str, object],
    inventory: Mapping[str, object] | None = None,
    func_groups: GroupMap,
    block_groups: GroupMap,
    segment_groups: GroupMap,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
) -> str:
    payload = build_report_document(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta=meta,
        inventory=inventory,
        block_facts=block_facts or {},
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        metrics=metrics,
        suggestions=suggestions or (),
        structural_findings=structural_findings or (),
    )
    return render_text_report_document(payload)


def _clone_group_map(
    payload: dict[str, object],
    kind: str,
) -> dict[str, dict[str, object]]:
    rows = _clone_groups(payload, kind)
    mapping: dict[str, dict[str, object]] = {}
    for row in rows:
        facts = row["facts"]
        assert isinstance(facts, dict)
        mapping[str(facts["group_key"])] = row
    return mapping


def test_build_function_groups() -> None:
    units = [
        {"fingerprint": "abc", "loc_bucket": "20-49", "qualname": "a"},
        {"fingerprint": "abc", "loc_bucket": "20-49", "qualname": "b"},
        {"fingerprint": "zzz", "loc_bucket": "20-49", "qualname": "c"},
    ]

    groups = build_groups(units)
    assert len(groups) == 1
    assert next(iter(groups.values()))[0]["fingerprint"] == "abc"


def test_block_groups_require_multiple_functions() -> None:
    blocks = [
        {"block_hash": "h1", "qualname": "f1"},
        {"block_hash": "h1", "qualname": "f1"},
        {"block_hash": "h1", "qualname": "f2"},
    ]

    groups = build_block_groups(blocks)
    assert len(groups) == 1


def test_prepare_block_report_groups_merges_to_maximal_regions() -> None:
    groups = {
        "h": [
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 20,
                "end_line": 23,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 10,
                "end_line": 13,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 13,
                "end_line": 16,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:g",
                "start_line": 10,
                "end_line": 13,
                "size": 4,
            },
        ]
    }

    prepared = prepare_block_report_groups(groups)
    items = prepared["h"]
    assert len(items) == 3

    assert items[0]["qualname"] == "mod:f"
    assert items[0]["start_line"] == 10
    assert items[0]["end_line"] == 16
    assert items[0]["size"] == 7

    assert items[1]["qualname"] == "mod:f"
    assert items[1]["start_line"] == 20
    assert items[1]["end_line"] == 23
    assert items[1]["size"] == 4

    assert items[2]["qualname"] == "mod:g"
    assert items[2]["start_line"] == 10
    assert items[2]["end_line"] == 13
    assert items[2]["size"] == 4


def test_prepare_block_report_groups_skips_invalid_ranges() -> None:
    groups = {
        "h": [
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": "bad",
                "end_line": 13,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": 30,
                "end_line": 33,
                "size": 4,
            },
        ]
    }
    prepared = prepare_block_report_groups(groups)
    assert len(prepared["h"]) == 1
    assert prepared["h"][0]["start_line"] == 30
    assert prepared["h"][0]["end_line"] == 33


def test_prepare_block_report_groups_all_invalid_ranges_fallback_sorted() -> None:
    groups: GroupMap = {
        "h": [
            {
                "block_hash": "h",
                "filepath": "b.py",
                "qualname": "mod:f",
                "start_line": "bad",
                "end_line": 13,
                "size": 4,
            },
            {
                "block_hash": "h",
                "filepath": "a.py",
                "qualname": "mod:f",
                "start_line": None,
                "end_line": 1,
                "size": 4,
            },
        ]
    }
    prepared = prepare_block_report_groups(groups)
    items = prepared["h"]
    assert len(items) == 2
    assert items[0]["filepath"] == "a.py"
    assert items[1]["filepath"] == "b.py"


def test_prepare_block_report_groups_handles_empty_item_list() -> None:
    groups: GroupMap = {"h": []}
    prepared = prepare_block_report_groups(groups)
    assert prepared["h"] == []


def test_build_block_group_facts_assert_only(tmp_path: Path) -> None:
    group_key = repeated_block_group_key()
    test_file = write_repeated_assert_source(tmp_path / "test_repeated_asserts.py")
    facts = build_block_group_facts(
        {
            group_key: [
                {
                    "qualname": "pkg.mod:f",
                    "filepath": str(test_file),
                    "start_line": 2,
                    "end_line": 5,
                }
            ]
        }
    )
    group = facts[group_key]
    assert group["match_rule"] == "normalized_sliding_window"
    assert group["block_size"] == "4"
    assert group["signature_kind"] == "stmt_hash_sequence"
    assert group["merged_regions"] == "true"
    assert group["pattern"] == "repeated_stmt_hash"
    assert group["pattern_display"] == f"{REPEATED_STMT_HASH[:12]} x4"
    assert group["hint"] == "assert_only"
    assert group["hint_label"] == "Assert-only block"
    assert_mapping_entries(
        group,
        hint_confidence="deterministic",
        assert_ratio="100%",
        consecutive_asserts="4",
        group_display_name="Assert pattern block",
    )
    assert group["group_arity"] == "1"
    assert group["instance_peer_count"] == "0"


def test_build_block_group_facts_deterministic_item_order(tmp_path: Path) -> None:
    group_key = repeated_block_group_key()
    test_file = write_repeated_assert_source(tmp_path / "test_repeated_asserts.py")
    item_a = {
        "qualname": "pkg.mod:f",
        "filepath": str(test_file),
        "start_line": 2,
        "end_line": 5,
    }
    item_b = {
        "qualname": "pkg.mod:f",
        "filepath": str(test_file),
        "start_line": 2,
        "end_line": 5,
    }
    facts_a = build_block_group_facts({group_key: [item_a, item_b]})
    facts_b = build_block_group_facts({group_key: [item_b, item_a]})
    assert facts_a == facts_b


def test_report_output_formats(
    report_meta_factory: Callable[..., dict[str, object]],
) -> None:
    groups = {
        "k1": [
            {
                "qualname": "f1",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
        "k2": [
            {
                "qualname": "f2",
                "filepath": "b.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
            },
            {
                "qualname": "f3",
                "filepath": "c.py",
                "start_line": 5,
                "end_line": 6,
                "loc": 2,
            },
        ],
    }
    meta = report_meta_factory(
        codeclone_version="1.3.0",
        baseline_path="/tmp/codeclone.baseline.json",
        baseline_schema_version=1,
        cache_path="/tmp/cache.json",
        scan_root="/repo",
    )
    report_out = to_json_report(groups, groups, {}, meta)
    markdown_out = to_markdown_report(
        meta=meta,
        func_groups=groups,
        block_groups=groups,
        segment_groups={},
    )
    sarif_out = to_sarif_report(
        meta=meta,
        func_groups=groups,
        block_groups=groups,
        segment_groups={},
    )
    text_out = to_text_report(
        meta=meta,
        func_groups=groups,
        block_groups=groups,
        segment_groups={},
    )

    expected_report = [
        '"meta"',
        '"inventory"',
        '"findings"',
        '"integrity"',
        f'"report_schema_version": "{REPORT_SCHEMA_VERSION}"',
        '"report_generated_at_utc": "2026-03-10T12:00:00Z"',
        '"schema_version": "1"',
        f'"payload_sha256": "{"a" * 64}"',
        '"payload_sha256_verified": true',
        f'"schema_version": "{CACHE_VERSION}"',
        '"status": "ok"',
        '"source_io_skipped": 0',
    ]
    expected_text = [
        "REPORT METADATA",
        f"Report schema version: {REPORT_SCHEMA_VERSION}",
        "Python tag: cp313",
        "Report generated (UTC): 2026-03-10T12:00:00Z",
        "Baseline path: codeclone.baseline.json",
        "Baseline schema version: 1",
        "Baseline generator name: codeclone",
        f"Baseline payload sha256: {'a' * 64}",
        "Baseline payload verified: true",
        "Cache path: cache.json",
        f"Cache schema version: {CACHE_VERSION}",
        "Cache status: ok",
        "INVENTORY",
        "source_io_skipped=0",
        "INTEGRITY",
        "FUNCTION CLONES (NEW) (groups=2)",
        "FUNCTION CLONES (KNOWN) (groups=0)",
        "Clone group #1",
    ]
    expected_markdown = [
        "# CodeClone Report",
        "- Markdown schema: 1.0",
        f"- Source report schema: {REPORT_SCHEMA_VERSION}",
        "- Report generated (UTC): 2026-03-10T12:00:00Z",
        '<a id="overview"></a>',
        "## Overview",
        '<a id="clone-findings"></a>',
        "### Clone Findings",
        '<a id="integrity"></a>',
        "## Integrity",
    ]
    sarif_payload = json.loads(sarif_out)
    run = sarif_payload["runs"][0]

    for token in expected_report:
        assert token in report_out
    for token in expected_text:
        assert token in text_out
    for token in expected_markdown:
        assert token in markdown_out
    assert sarif_payload["$schema"].endswith("sarif-2.1.0.json")
    assert sarif_payload["version"] == "2.1.0"
    assert run["tool"]["driver"]["name"] == "codeclone"
    assert run["automationDetails"]["id"] == "codeclone/full"
    assert run["properties"]["reportSchemaVersion"] == REPORT_SCHEMA_VERSION
    assert run["properties"]["reportGeneratedAtUtc"] == "2026-03-10T12:00:00Z"
    assert run["columnKind"] == "utf16CodeUnits"
    assert run["originalUriBaseIds"]["%SRCROOT%"]["uri"] == "file:///repo/"
    assert run["artifacts"]
    assert run["invocations"][0]["workingDirectory"]["uri"] == "file:///repo/"
    assert any(rule["id"] == "CCLONE001" for rule in run["tool"]["driver"]["rules"])
    first_rule = run["tool"]["driver"]["rules"][0]
    assert first_rule["name"].startswith("codeclone.")
    assert "help" in first_rule
    assert "markdown" in first_rule["help"]
    assert first_rule["properties"]["tags"]
    assert any(
        result["fingerprints"]["codecloneFindingId"].startswith("clone:")
        for result in run["results"]
    )


def test_report_sarif_uses_representative_and_related_locations() -> None:
    groups = {
        "k1": [
            {
                "qualname": "pkg.alpha:transform_alpha",
                "filepath": "tests/fixtures/golden_project/alpha.py",
                "start_line": 1,
                "end_line": 10,
                "loc": 10,
                "stmt_count": 6,
                "fingerprint": "fp1",
                "loc_bucket": "1-19",
                "cyclomatic_complexity": 2,
                "nesting_depth": 1,
                "risk": "low",
                "raw_hash": "raw1",
            },
            {
                "qualname": "pkg.beta:transform_beta",
                "filepath": "tests/fixtures/golden_project/beta.py",
                "start_line": 2,
                "end_line": 11,
                "loc": 10,
                "stmt_count": 6,
                "fingerprint": "fp1",
                "loc_bucket": "1-19",
                "cyclomatic_complexity": 2,
                "nesting_depth": 1,
                "risk": "low",
                "raw_hash": "raw2",
            },
        ]
    }
    sarif_payload = json.loads(
        to_sarif_report(
            meta={"codeclone_version": "2.0.0b2", "scan_root": "/repo"},
            func_groups=groups,
            block_groups={},
            segment_groups={},
        )
    )
    run = sarif_payload["runs"][0]
    result = run["results"][0]
    assert result["ruleId"] == "CCLONE001"
    assert result["level"] == "warning"
    assert result["baselineState"] == "new"
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == (
        "tests/fixtures/golden_project/alpha.py"
    )
    assert (
        result["locations"][0]["physicalLocation"]["artifactLocation"]["uriBaseId"]
        == "%SRCROOT%"
    )
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["index"] == 0
    assert result["locations"][0]["logicalLocations"][0]["fullyQualifiedName"] == (
        "pkg.alpha:transform_alpha"
    )
    assert result["locations"][0]["message"]["text"] == "Representative occurrence"
    assert (
        result["relatedLocations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == "tests/fixtures/golden_project/beta.py"
    )
    assert result["relatedLocations"][0]["id"] == 1
    assert result["relatedLocations"][0]["message"]["text"] == "Related occurrence #1"
    assert result["properties"]["cloneType"] == "Type-2"
    assert result["properties"]["groupArity"] == 2
    assert "primaryLocationLineHash" in result["partialFingerprints"]


def test_report_json_deterministic_group_order() -> None:
    groups_a = {
        "b": [
            {
                "qualname": "b",
                "filepath": "b.py",
                "start_line": 2,
                "end_line": 3,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
    }
    groups_b = {"a": groups_a["a"], "b": groups_a["b"]}
    meta = {"codeclone_version": "1.3.0"}
    out_a = to_json_report(groups_a, groups_a, groups_a, meta)
    out_b = to_json_report(groups_b, groups_b, groups_b, meta)
    assert out_a == out_b


def test_report_json_group_order_is_deterministic_by_count_then_id() -> None:
    groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": "b.py",
                "start_line": 2,
                "end_line": 3,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
        "c": [
            {
                "qualname": "c1",
                "filepath": "c.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            },
            {
                "qualname": "c2",
                "filepath": "c.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
            },
        ],
    }
    payload = to_json_report(groups, {}, {}, {"codeclone_version": "1.3.0"})
    report_obj = json.loads(payload)
    assert [row["id"] for row in _clone_groups(report_obj, "functions")] == [
        "clone:function:c",
        "clone:function:a",
        "clone:function:b",
    ]


def test_report_json_deterministic_with_shuffled_units() -> None:
    units_a = [
        {
            "fingerprint": "abc",
            "loc_bucket": "0-19",
            "qualname": "b",
            "filepath": "b.py",
            "start_line": 2,
            "end_line": 3,
            "loc": 2,
        },
        {
            "fingerprint": "abc",
            "loc_bucket": "0-19",
            "qualname": "a",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 2,
            "loc": 2,
        },
    ]
    units_b = list(reversed(units_a))
    groups_a = build_groups(units_a)
    groups_b = build_groups(units_b)
    meta = {"codeclone_version": "1.3.0"}
    out_a = to_json_report(groups_a, {}, {}, meta)
    out_b = to_json_report(groups_b, {}, {}, meta)
    assert out_a == out_b


def test_report_json_compact_v21_contract() -> None:
    groups = {
        "g1": [
            {
                "qualname": "m:a",
                "filepath": "z.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-z",
                "loc_bucket": "0-19",
            },
            {
                "qualname": "m:b",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-a",
                "loc_bucket": "0-19",
            },
        ]
    }
    payload = json.loads(to_json_report(groups, {}, {}, {"codeclone_version": "1.4.0"}))

    assert "report_schema_version" not in payload["meta"]
    assert payload["inventory"]["file_registry"] == {
        "encoding": "relative_path",
        "items": ["a.py", "z.py"],
    }
    clones = payload["findings"]["groups"]["clones"]
    assert set(clones) == {"functions", "blocks", "segments"}
    assert payload["findings"]["summary"]["clones"] == {
        "functions": 1,
        "blocks": 0,
        "segments": 0,
        "new": 1,
        "known": 0,
    }

    function_group = _clone_group_map(payload, "functions")["g1"]
    assert function_group["clone_type"] == "Type-3"
    assert function_group["novelty"] == "new"
    assert function_group["items"] == [
        {
            "relative_path": "a.py",
            "qualname": "m:b",
            "start_line": 1,
            "end_line": 2,
            "loc": 2,
            "stmt_count": 1,
            "fingerprint": "fp-a",
            "loc_bucket": "0-19",
            "cyclomatic_complexity": 1,
            "nesting_depth": 0,
            "risk": "low",
            "raw_hash": "",
        },
        {
            "relative_path": "z.py",
            "qualname": "m:a",
            "start_line": 3,
            "end_line": 4,
            "loc": 2,
            "stmt_count": 1,
            "fingerprint": "fp-z",
            "loc_bucket": "0-19",
            "cyclomatic_complexity": 1,
            "nesting_depth": 0,
            "risk": "low",
            "raw_hash": "",
        },
    ]
    assert set(payload) == {
        "report_schema_version",
        "meta",
        "inventory",
        "findings",
        "metrics",
        "derived",
        "integrity",
    }
    for legacy_key in (
        "files",
        "clones",
        "groups",
        "groups_split",
        "clone_types",
        "suggestions",
        "overview",
        "structural_findings",
    ):
        assert legacy_key not in payload


def test_report_json_block_records_do_not_repeat_group_hash() -> None:
    block_group_key = "hash-a|hash-b|hash-c|hash-d"
    payload = json.loads(
        to_json_report(
            {},
            {
                block_group_key: [
                    {
                        "qualname": "m:f",
                        "filepath": "a.py",
                        "start_line": 10,
                        "end_line": 13,
                        "size": 4,
                    }
                ]
            },
            {},
            {"codeclone_version": "1.4.0"},
        )
    )
    block_group = _clone_group_map(payload, "blocks")[block_group_key]
    assert block_group["items"] == [
        {
            "relative_path": "a.py",
            "qualname": "m:f",
            "start_line": 10,
            "end_line": 13,
            "size": 4,
        }
    ]


def test_report_json_serializes_rich_suggestions_and_overview() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0"},
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
                    subject_key="clone:g1",
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
    )
    suggestion = payload["derived"]["suggestions"][0]
    assert set(suggestion) == {
        "id",
        "finding_id",
        "title",
        "summary",
        "location_label",
        "representative_locations",
        "action",
    }
    assert suggestion["finding_id"] == "clone:function:clone:g1"
    assert suggestion["summary"] == "same parameterized function body"
    assert suggestion["representative_locations"] == []
    assert suggestion["action"] == {
        "effort": "easy",
        "steps": ["Extract shared function"],
    }
    overview = payload["derived"]["overview"]
    assert overview["families"]["clones"] == 0
    assert overview["source_scope_breakdown"] == {}
    assert payload["derived"]["hotlists"]["most_actionable_ids"] == []


def test_report_json_integrity_matches_canonical_sections() -> None:
    payload = json.loads(
        to_json_report(
            {
                "g1": [
                    {
                        "qualname": "m:a",
                        "filepath": "a.py",
                        "start_line": 1,
                        "end_line": 3,
                        "loc": 3,
                        "stmt_count": 2,
                        "fingerprint": "fp-a",
                        "loc_bucket": "0-19",
                    },
                    {
                        "qualname": "m:b",
                        "filepath": "b.py",
                        "start_line": 2,
                        "end_line": 4,
                        "loc": 3,
                        "stmt_count": 2,
                        "fingerprint": "fp-a",
                        "loc_bucket": "0-19",
                    },
                ]
            },
            {},
            {},
            {"codeclone_version": "1.4.0"},
        )
    )
    canonical_payload = {
        "report_schema_version": payload["report_schema_version"],
        "meta": {
            key: value for key, value in payload["meta"].items() if key != "runtime"
        },
        "inventory": payload["inventory"],
        "findings": payload["findings"],
        "metrics": payload["metrics"],
    }
    canonical_json = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert payload["integrity"]["canonicalization"] == {
        "version": "1",
        "scope": "canonical_only",
        "sections": [
            "report_schema_version",
            "meta",
            "inventory",
            "findings",
            "metrics",
        ],
    }
    assert payload["integrity"]["digest"] == {
        "verified": True,
        "algorithm": "sha256",
        "value": sha256(canonical_json).hexdigest(),
    }


def test_report_json_integrity_ignores_derived_changes() -> None:
    base_args: tuple[
        dict[str, list[dict[str, object]]],
        dict[str, list[dict[str, object]]],
        dict[str, list[dict[str, object]]],
        dict[str, object],
    ] = (
        {
            "g1": [
                {
                    "qualname": "m:a",
                    "filepath": "a.py",
                    "start_line": 1,
                    "end_line": 3,
                    "loc": 3,
                    "stmt_count": 2,
                    "fingerprint": "fp-a",
                    "loc_bucket": "0-19",
                },
                {
                    "qualname": "m:b",
                    "filepath": "b.py",
                    "start_line": 2,
                    "end_line": 4,
                    "loc": 3,
                    "stmt_count": 2,
                    "fingerprint": "fp-a",
                    "loc_bucket": "0-19",
                },
            ]
        },
        {},
        {},
        {"codeclone_version": "1.4.0"},
    )
    suggestion_a = Suggestion(
        severity="warning",
        category="clone",
        title="Function clone group (Type-2)",
        location="2 occurrences across 2 files / 2 functions",
        steps=("Extract shared function",),
        effort="easy",
        priority=2.0,
        finding_family="clones",
        subject_key="clone:g1",
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
    )
    suggestion_b = Suggestion(
        severity="warning",
        category="clone",
        title="Refactor duplicated function body",
        location="example location",
        steps=("Extract helper", "Pass parameters"),
        effort="moderate",
        priority=1.5,
        finding_family="clones",
        subject_key="clone:g1",
        fact_kind="Function clone group",
        fact_summary="same parameterized function body",
        fact_count=2,
        spread_files=2,
        spread_functions=2,
        clone_type="Type-2",
        confidence="high",
        source_kind="production",
        source_breakdown=(("production", 2),),
        location_label="example location",
    )
    payload_a = json.loads(to_json_report(*base_args, suggestions=(suggestion_a,)))
    payload_b = json.loads(to_json_report(*base_args, suggestions=(suggestion_b,)))
    assert payload_a["derived"]["suggestions"] != payload_b["derived"]["suggestions"]
    assert payload_a["integrity"]["digest"] == payload_b["integrity"]["digest"]


def test_report_json_integrity_ignores_display_facts_changes() -> None:
    base_args: tuple[
        dict[str, list[dict[str, object]]],
        dict[str, list[dict[str, object]]],
        dict[str, list[dict[str, object]]],
        dict[str, object],
    ] = (
        {},
        {
            "group-a": [
                {
                    "qualname": "pkg:fa",
                    "filepath": "/root/a.py",
                    "start_line": 20,
                    "end_line": 23,
                    "size": 4,
                }
            ]
        },
        {},
        {"codeclone_version": "1.4.0", "scan_root": "/root"},
    )
    payload_a = json.loads(
        to_json_report(
            *base_args,
            block_facts={
                "group-a": {
                    "block_size": "4",
                    "merged_regions": "true",
                    "pattern_display": "abcd1234 x4",
                }
            },
        )
    )
    payload_b = json.loads(
        to_json_report(
            *base_args,
            block_facts={
                "group-a": {
                    "block_size": "4",
                    "merged_regions": "true",
                    "pattern_display": "different display string",
                }
            },
        )
    )
    assert (
        payload_a["findings"]["groups"]["clones"]["blocks"][0]["display_facts"]
        != payload_b["findings"]["groups"]["clones"]["blocks"][0]["display_facts"]
    )
    assert payload_a["integrity"]["digest"] == payload_b["integrity"]["digest"]


def test_report_json_includes_sorted_block_facts() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {
                "group-b": [
                    {
                        "qualname": "pkg:fb",
                        "filepath": "b.py",
                        "start_line": 10,
                        "end_line": 13,
                        "size": 4,
                    }
                ],
                "group-a": [
                    {
                        "qualname": "pkg:fa",
                        "filepath": "a.py",
                        "start_line": 20,
                        "end_line": 23,
                        "size": 4,
                    }
                ],
            },
            {},
            {"codeclone_version": "1.4.0"},
            block_facts={
                "group-b": {"z": "3", "a": "x"},
                "group-a": {"k": "v"},
            },
        )
    )
    block_groups = _clone_group_map(payload, "blocks")
    assert block_groups["group-a"]["facts"] == {
        "group_key": "group-a",
        "group_arity": 1,
    }
    assert block_groups["group-a"]["display_facts"] == {"k": "v"}
    assert block_groups["group-b"]["facts"] == {
        "group_key": "group-b",
        "group_arity": 1,
    }
    assert block_groups["group-b"]["display_facts"] == {"a": "x", "z": "3"}


def test_report_json_block_group_splits_machine_and_display_facts() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {
                "group-a": [
                    {
                        "qualname": "pkg:fa",
                        "filepath": "/root/a.py",
                        "start_line": 20,
                        "end_line": 23,
                        "size": 4,
                    }
                ],
            },
            {},
            {"codeclone_version": "1.4.0", "scan_root": "/root"},
            block_facts={
                "group-a": {
                    "group_arity": "1",
                    "block_size": "4",
                    "merged_regions": "true",
                    "assert_ratio": "25%",
                    "consecutive_asserts": "2",
                    "pattern_display": "abcd1234 x4",
                    "group_compare_note": "display note",
                }
            },
        )
    )
    group = _clone_group_map(payload, "blocks")["group-a"]
    assert group["facts"] == {
        "group_key": "group-a",
        "group_arity": 1,
        "block_size": 4,
        "merged_regions": True,
        "assert_ratio": 0.25,
        "consecutive_asserts": 2,
    }
    assert group["display_facts"] == {
        "assert_ratio": "25%",
        "group_compare_note": "display note",
        "pattern_display": "abcd1234 x4",
    }


def test_report_json_uses_relative_paths_in_canonical_layers() -> None:
    payload = json.loads(
        to_json_report(
            {
                "g1": [
                    {
                        "qualname": "m:a",
                        "filepath": "/root/src/a.py",
                        "start_line": 1,
                        "end_line": 2,
                        "loc": 2,
                        "stmt_count": 1,
                        "fingerprint": "fp-a",
                        "loc_bucket": "0-19",
                    }
                ]
            },
            {},
            {},
            {
                "codeclone_version": "1.4.0",
                "scan_root": "/root",
                "baseline_path": "/root/codeclone.baseline.json",
            },
        )
    )
    assert payload["meta"]["scan_root"] == "."
    assert payload["meta"]["runtime"]["report_generated_at_utc"] is None
    assert payload["meta"]["runtime"]["scan_root_absolute"] == "/root"
    assert payload["meta"]["baseline"]["path"] == "codeclone.baseline.json"
    assert payload["inventory"]["file_registry"]["items"] == ["src/a.py"]
    items = _clone_group_map(payload, "functions")["g1"]["items"]
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["relative_path"] == "src/a.py"


def test_report_json_dead_code_summary_uses_high_confidence_key() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0"},
            metrics={
                "dead_code": {
                    "items": [
                        {
                            "qualname": "pkg.mod:unused",
                            "filepath": "pkg/mod.py",
                            "start_line": 10,
                            "end_line": 12,
                            "kind": "function",
                            "confidence": "high",
                        }
                    ],
                    "summary": {"critical": 1},
                }
            },
        )
    )
    summary = payload["metrics"]["families"]["dead_code"]["summary"]
    assert summary == {"total": 1, "high_confidence": 1, "suppressed": 0}


def test_report_json_dead_code_suppressed_items_are_reported_separately() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0", "scan_root": "/root"},
            metrics={
                "dead_code": {
                    "items": [],
                    "suppressed_items": [
                        {
                            "qualname": "pkg.mod:runtime_hook",
                            "filepath": "/root/pkg/mod.py",
                            "start_line": 40,
                            "end_line": 41,
                            "kind": "function",
                            "confidence": "high",
                            "suppressed_by": [
                                {"rule": "dead-code", "source": "inline_codeclone"},
                                {"rule": "dead-code", "source": "inline_codeclone"},
                            ],
                        }
                    ],
                    "summary": {"suppressed": 1},
                }
            },
        )
    )
    dead_code = payload["metrics"]["families"]["dead_code"]
    assert dead_code["summary"] == {"total": 0, "high_confidence": 0, "suppressed": 1}
    suppressed_items = dead_code["suppressed_items"]
    assert suppressed_items == [
        {
            "qualname": "pkg.mod:runtime_hook",
            "relative_path": "pkg/mod.py",
            "start_line": 40,
            "end_line": 41,
            "kind": "function",
            "confidence": "high",
            "suppressed_by": [{"rule": "dead-code", "source": "inline_codeclone"}],
            "suppression_rule": "dead-code",
            "suppression_source": "inline_codeclone",
        }
    ]
    assert payload["findings"]["groups"]["dead_code"]["groups"] == []
    assert payload["findings"]["summary"]["suppressed"] == {"dead_code": 1}


def test_report_json_integrity_ignores_runtime_report_timestamp() -> None:
    payload_a = json.loads(
        to_json_report(
            {},
            {},
            {},
            {
                "codeclone_version": "1.4.0",
                "report_generated_at_utc": "2026-03-10T12:00:00Z",
            },
        )
    )
    payload_b = json.loads(
        to_json_report(
            {},
            {},
            {},
            {
                "codeclone_version": "1.4.0",
                "report_generated_at_utc": "2030-01-01T00:00:00Z",
            },
        )
    )
    assert (
        payload_a["meta"]["runtime"]["report_generated_at_utc"]
        != payload_b["meta"]["runtime"]["report_generated_at_utc"]
    )
    assert payload_a["integrity"]["digest"] == payload_b["integrity"]["digest"]


def test_report_json_hotlists_reference_existing_finding_ids() -> None:
    payload = json.loads(
        to_json_report(
            {
                "g1": [
                    {
                        "qualname": "pkg.mod:a",
                        "filepath": "/root/a.py",
                        "start_line": 1,
                        "end_line": 20,
                        "loc": 20,
                        "stmt_count": 8,
                        "fingerprint": "fp-a",
                        "loc_bucket": "20-49",
                    },
                    {
                        "qualname": "pkg.mod:b",
                        "filepath": "/root/b.py",
                        "start_line": 1,
                        "end_line": 20,
                        "loc": 20,
                        "stmt_count": 8,
                        "fingerprint": "fp-a",
                        "loc_bucket": "20-49",
                    },
                ]
            },
            {},
            {},
            {"codeclone_version": "1.4.0", "scan_root": "/root"},
            metrics={
                "dead_code": {
                    "items": [
                        {
                            "qualname": "pkg.mod:unused",
                            "filepath": "/root/pkg/mod.py",
                            "start_line": 10,
                            "end_line": 12,
                            "kind": "function",
                            "confidence": "high",
                        }
                    ],
                    "summary": {"critical": 1},
                },
                "health": {"score": 80, "grade": "B", "dimensions": {"clones": 80}},
            },
        )
    )
    groups = payload["findings"]["groups"]
    canonical_ids = {
        *(group["id"] for group in groups["clones"]["functions"]),
        *(group["id"] for group in groups["clones"]["blocks"]),
        *(group["id"] for group in groups["clones"]["segments"]),
        *(group["id"] for group in groups["structural"]["groups"]),
        *(group["id"] for group in groups["dead_code"]["groups"]),
        *(group["id"] for group in groups["design"]["groups"]),
    }
    hotlists = payload["derived"]["hotlists"]
    for ids in hotlists.values():
        assert set(ids).issubset(canonical_ids)


def test_report_overview_materializes_source_breakdown_and_hotlist_cards() -> None:
    structural = (
        StructuralFindingGroup(
            finding_kind="duplicated_branches",
            finding_key="k" * 40,
            signature={
                "stmt_seq": "Expr,Return",
                "terminal": "return",
                "raises": "0",
                "has_loop": "0",
            },
            items=(
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="k" * 40,
                    file_path="/repo/pkg/mod.py",
                    qualname="pkg.mod:fn",
                    start=10,
                    end=12,
                    signature={},
                ),
                StructuralFindingOccurrence(
                    finding_kind="duplicated_branches",
                    finding_key="k" * 40,
                    file_path="/repo/pkg/mod.py",
                    qualname="pkg.mod:fn",
                    start=20,
                    end=22,
                    signature={},
                ),
            ),
        ),
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
        structural_findings=structural,
    )

    derived = cast(Mapping[str, object], payload["derived"])
    materialized = materialize_report_overview(
        overview=cast(Mapping[str, object], derived["overview"]),
        hotlists=cast(Mapping[str, object], derived["hotlists"]),
        findings=cast(Mapping[str, object], payload["findings"]),
    )

    assert materialized["source_breakdown"] == {"production": 1, "fixtures": 1}
    assert materialized["highest_spread"]
    assert materialized["production_hotspots"]
    assert materialized["test_fixture_hotspots"]
    production_hotspots = cast(
        Sequence[Mapping[str, object]],
        materialized["production_hotspots"],
    )
    test_fixture_hotspots = cast(
        Sequence[Mapping[str, object]],
        materialized["test_fixture_hotspots"],
    )
    assert production_hotspots[0]["title"] == "Repeated branch family"
    assert test_fixture_hotspots[0]["title"] == "Function clone group (Type-2)"


def test_report_overview_clone_summary_variants() -> None:
    assert (
        overview_mod._clone_summary_from_group(
            {"category": "function", "clone_type": "Type-1", "facts": {}}
        )
        == "same exact function body"
    )
    assert (
        overview_mod._clone_summary_from_group(
            {"category": "function", "clone_type": "Type-3", "facts": {}}
        )
        == "same structural function body with small identifier changes"
    )
    assert (
        overview_mod._clone_summary_from_group(
            {"category": "function", "clone_type": "Type-4", "facts": {}}
        )
        == "same structural function body"
    )
    assert (
        overview_mod._clone_summary_from_group(
            {
                "category": "block",
                "clone_type": "Type-4",
                "facts": {"hint": "assert_only"},
            }
        )
        == "same assertion template"
    )
    assert (
        overview_mod._clone_summary_from_group(
            {
                "category": "block",
                "clone_type": "Type-4",
                "facts": {"pattern": "repeated_stmt_hash"},
            }
        )
        == "same repeated setup/assert pattern"
    )
    assert (
        overview_mod._clone_summary_from_group(
            {"category": "block", "clone_type": "Type-4", "facts": {}}
        )
        == "same structural sequence with small value changes"
    )
    assert (
        overview_mod._clone_summary_from_group(
            {"category": "segment", "clone_type": "Type-4", "facts": {}}
        )
        == "same structural segment sequence"
    )


def test_report_overview_structural_summary_variants() -> None:
    assert overview_mod._structural_summary_from_group(
        {"category": "clone_guard_exit_divergence"}
    ) == (
        "Clone guard/exit divergence",
        "clone cohort members differ in entry guards or early-exit behavior",
    )
    assert overview_mod._structural_summary_from_group(
        {"category": "clone_cohort_drift"}
    ) == (
        "Clone cohort drift",
        "clone cohort members drift from majority terminal/guard/try profile",
    )
    assert overview_mod._structural_summary_from_group(
        {
            "category": "duplicated_branches",
            "signature": {"stable": {"terminal_kind": "raise"}, "debug": {}},
        }
    ) == ("Repeated branch family", "same repeated guard/validation branch")
    assert overview_mod._structural_summary_from_group(
        {
            "category": "duplicated_branches",
            "signature": {"stable": {"terminal_kind": "return"}, "debug": {}},
        }
    ) == ("Repeated branch family", "same repeated return branch")
    assert overview_mod._structural_summary_from_group(
        {
            "category": "duplicated_branches",
            "signature": {"debug": {"has_loop": "1"}},
        }
    ) == ("Repeated branch family", "same repeated loop branch")
    assert overview_mod._structural_summary_from_group(
        {
            "category": "duplicated_branches",
            "signature": {"debug": {"stmt_seq": "Expr,If"}},
        }
    ) == ("Repeated branch family", "same repeated branch shape (Expr,If)")
    assert overview_mod._structural_summary_from_group(
        {"category": "duplicated_branches", "signature": {}}
    ) == ("Repeated branch family", "same repeated branch shape")


def test_report_overview_location_helpers_cover_edge_cases() -> None:
    assert overview_mod._single_item_location({"module": "pkg.alpha"}) == "pkg.alpha"
    assert overview_mod._single_item_location({}) == "(unknown)"
    assert (
        overview_mod._single_item_location({"relative_path": "pkg/mod.py"})
        == "pkg/mod.py"
    )
    assert (
        overview_mod._single_item_location(
            {"relative_path": "pkg/mod.py", "start_line": 10, "end_line": 12}
        )
        == "pkg/mod.py:10-12"
    )
    assert (
        overview_mod._group_location_label(
            {
                "category": "dependency",
                "items": [{"module": "pkg.a"}, {"module": "pkg.b"}],
                "count": 2,
                "spread": {"files": 2, "functions": 0},
            }
        )
        == "pkg.a -> pkg.b"
    )
    assert (
        overview_mod._group_location_label(
            {
                "category": "function",
                "items": [
                    {"relative_path": "pkg/mod.py", "start_line": 5, "end_line": 5}
                ],
                "count": 1,
                "spread": {"files": 1, "functions": 1},
            }
        )
        == "pkg/mod.py:5"
    )
    assert (
        overview_mod._group_location_label(
            {
                "category": "function",
                "items": [{"relative_path": "pkg/mod.py"}],
                "count": 3,
                "spread": {"files": 2, "functions": 3},
            }
        )
        == "3 occurrences across 2 files / 3 functions"
    )


def test_report_overview_serialize_finding_group_card_covers_families() -> None:
    dead_card = overview_mod.serialize_finding_group_card(
        {
            "family": "dead_code",
            "category": "method",
            "severity": "warning",
            "confidence": "high",
            "count": 1,
            "source_scope": {"dominant_kind": "production"},
            "spread": {"files": 1, "functions": 1},
            "items": [
                {
                    "relative_path": "pkg/mod.py",
                    "qualname": "pkg.mod:C.m",
                    "start_line": 7,
                    "end_line": 8,
                }
            ],
            "facts": {},
        }
    )
    assert dead_card["title"] == "Remove or explicitly keep unused code"
    assert dead_card["summary"] == "method with high confidence"

    complexity_card = overview_mod.serialize_finding_group_card(
        {
            "family": "design",
            "category": "complexity",
            "severity": "warning",
            "confidence": "high",
            "count": 1,
            "source_scope": {"dominant_kind": "production"},
            "spread": {"files": 1, "functions": 1},
            "items": [{"relative_path": "pkg/mod.py", "start_line": 3, "end_line": 9}],
            "facts": {"cyclomatic_complexity": 21, "nesting_depth": 4},
        }
    )
    assert complexity_card["title"] == "Reduce high-complexity function"
    assert complexity_card["summary"] == "cyclomatic_complexity=21, nesting_depth=4"

    coupling_card = overview_mod.serialize_finding_group_card(
        {
            "family": "design",
            "category": "coupling",
            "severity": "warning",
            "confidence": "high",
            "count": 1,
            "source_scope": {"dominant_kind": "production"},
            "spread": {"files": 1, "functions": 1},
            "items": [{"relative_path": "pkg/mod.py", "start_line": 3, "end_line": 9}],
            "facts": {"cbo": 11},
        }
    )
    assert coupling_card["title"] == "Split high-coupling class"
    assert coupling_card["summary"] == "cbo=11"

    cohesion_card = overview_mod.serialize_finding_group_card(
        {
            "family": "design",
            "category": "cohesion",
            "severity": "warning",
            "confidence": "high",
            "count": 1,
            "source_scope": {"dominant_kind": "production"},
            "spread": {"files": 1, "functions": 1},
            "items": [{"relative_path": "pkg/mod.py", "start_line": 3, "end_line": 9}],
            "facts": {"lcom4": 5},
        }
    )
    assert cohesion_card["title"] == "Split low-cohesion class"
    assert cohesion_card["summary"] == "lcom4=5"

    dependency_card = overview_mod.serialize_finding_group_card(
        {
            "family": "design",
            "category": "dependency",
            "severity": "critical",
            "confidence": "high",
            "count": 3,
            "source_scope": {"dominant_kind": "other"},
            "spread": {"files": 3, "functions": 0},
            "items": [{"module": "pkg.a"}, {"module": "pkg.b"}, {"module": "pkg.c"}],
            "facts": {"cycle_length": 3},
        }
    )
    assert dependency_card["title"] == "Break circular dependency"
    assert dependency_card["summary"] == "3 modules participate in this cycle"
    assert dependency_card["location"] == "pkg.a -> pkg.b -> pkg.c"


def test_report_overview_materialize_preserves_existing_cards_and_breakdown() -> None:
    materialized = materialize_report_overview(
        overview={
            "source_breakdown": {"tests": 9},
            "highest_spread": [{"title": "preset"}],
        },
        hotlists={"highest_spread_ids": ["clone:function:abc"]},
        findings={"groups": {}},
    )
    assert materialized["source_breakdown"] == {"tests": 9}
    assert materialized["highest_spread"] == [{"title": "preset"}]


def test_report_json_groups_split_trusted_baseline() -> None:
    func_groups = {
        "func-known": [
            {
                "qualname": "m:fk",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-k",
                "loc_bucket": "0-19",
            }
        ],
        "func-new": [
            {
                "qualname": "m:fn",
                "filepath": "b.py",
                "start_line": 3,
                "end_line": 4,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-n",
                "loc_bucket": "0-19",
            }
        ],
    }
    block_groups = {
        "block-known": [
            {
                "qualname": "m:bk",
                "filepath": "a.py",
                "start_line": 10,
                "end_line": 13,
                "size": 4,
            }
        ],
        "block-new": [
            {
                "qualname": "m:bn",
                "filepath": "b.py",
                "start_line": 20,
                "end_line": 23,
                "size": 4,
            }
        ],
    }
    segment_groups = {
        "segment-new": [
            {
                "qualname": "m:sn",
                "filepath": "b.py",
                "start_line": 30,
                "end_line": 35,
                "size": 6,
                "segment_hash": "seg-h",
                "segment_sig": "seg-s",
            }
        ]
    }
    payload = json.loads(
        to_json_report(
            func_groups,
            block_groups,
            segment_groups,
            {"baseline_loaded": True, "baseline_status": "ok"},
            new_function_group_keys={"func-new"},
            new_block_group_keys={"block-new"},
            new_segment_group_keys={"segment-new"},
        )
    )
    clones = payload["findings"]["groups"]["clones"]
    function_map = _clone_group_map(payload, "functions")
    block_map = _clone_group_map(payload, "blocks")
    segment_map = _clone_group_map(payload, "segments")
    assert function_map["func-new"]["novelty"] == "new"
    assert function_map["func-known"]["novelty"] == "known"
    assert block_map["block-new"]["novelty"] == "new"
    assert block_map["block-known"]["novelty"] == "known"
    assert segment_map["segment-new"]["novelty"] == "new"
    assert payload["findings"]["summary"]["clones"] == {
        "functions": len(clones["functions"]),
        "blocks": len(clones["blocks"]),
        "segments": len(clones["segments"]),
        "new": 3,
        "known": 2,
    }


def test_report_json_groups_split_untrusted_baseline() -> None:
    func_groups = {
        "func-a": [
            {
                "qualname": "m:f",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
                "stmt_count": 1,
                "fingerprint": "fp-a",
                "loc_bucket": "0-19",
            }
        ]
    }
    payload = json.loads(
        to_json_report(
            func_groups,
            {},
            {},
            {"baseline_loaded": False, "baseline_status": "integrity_failed"},
            new_function_group_keys=set(),
        )
    )
    function_map = _clone_group_map(payload, "functions")
    assert function_map["func-a"]["novelty"] == "new"
    assert payload["findings"]["summary"]["clones"] == {
        "functions": 1,
        "blocks": 0,
        "segments": 0,
        "new": 1,
        "known": 0,
    }


def test_text_report_deterministic_group_order() -> None:
    groups = {
        "b": [
            {
                "qualname": "b",
                "filepath": "b.py",
                "start_line": 2,
                "end_line": 3,
                "loc": 2,
            }
        ],
        "a": [
            {
                "qualname": "a",
                "filepath": "a.py",
                "start_line": 1,
                "end_line": 2,
                "loc": 2,
            }
        ],
    }
    text = to_text_report(
        meta={},
        func_groups=groups,
        block_groups={},
        segment_groups={},
    )
    first_idx = text.find("=== Clone group #1 ===")
    a_idx = text.find("a.py:1-2")
    b_idx = text.find("b.py:2-3")
    assert first_idx != -1
    assert a_idx != -1
    assert b_idx != -1
    assert a_idx < b_idx


def test_to_text_report_handles_missing_meta_fields() -> None:
    text_out = to_text_report(
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    assert_contains_all(
        text_out,
        f"Report schema version: {REPORT_SCHEMA_VERSION}",
        "CodeClone version: (none)",
        "Report generated (UTC): (none)",
        "Baseline status: (none)",
        "Cache path: (none)",
        "Cache used: false",
        "INVENTORY",
        "INTEGRITY",
        "Note: baseline is untrusted; all groups are treated as NEW.",
        "FUNCTION CLONES (NEW) (groups=0)\n(none)",
        "FUNCTION CLONES (KNOWN) (groups=0)\n(none)",
        "BLOCK CLONES (NEW) (groups=0)\n(none)",
        "BLOCK CLONES (KNOWN) (groups=0)\n(none)",
        "SEGMENT CLONES (NEW) (groups=0)\n(none)",
        "SEGMENT CLONES (KNOWN) (groups=0)\n(none)",
    )


def test_to_text_report_uses_section_specific_metric_labels() -> None:
    text_out = to_text_report(
        meta={"codeclone_version": "1.4.0"},
        func_groups={
            "f": [
                {
                    "qualname": "pkg:f",
                    "filepath": "a.py",
                    "start_line": 1,
                    "end_line": 10,
                    "loc": 11,
                }
            ]
        },
        block_groups={
            "b": [
                {
                    "qualname": "pkg:b",
                    "filepath": "b.py",
                    "start_line": 20,
                    "end_line": 23,
                    "size": 4,
                }
            ]
        },
        segment_groups={
            "s": [
                {
                    "qualname": "pkg:s",
                    "filepath": "c.py",
                    "start_line": 30,
                    "end_line": 35,
                    "size": 6,
                }
            ]
        },
    )
    assert "loc=11" in text_out
    assert "size=4" in text_out
    assert "size=6" in text_out


def test_to_text_report_trusted_baseline_split_sections() -> None:
    text_out = to_text_report(
        meta={"baseline_loaded": True, "baseline_status": "ok"},
        func_groups={
            "func-known": [
                {
                    "qualname": "pkg:known",
                    "filepath": "a.py",
                    "start_line": 1,
                    "end_line": 2,
                    "loc": 2,
                }
            ],
            "func-new": [
                {
                    "qualname": "pkg:new",
                    "filepath": "b.py",
                    "start_line": 3,
                    "end_line": 4,
                    "loc": 2,
                }
            ],
        },
        block_groups={},
        segment_groups={},
        new_function_group_keys={"func-new"},
    )
    assert "Note: baseline is untrusted" not in text_out
    assert "FUNCTION CLONES (NEW) (groups=1)" in text_out
    assert "FUNCTION CLONES (KNOWN) (groups=1)" in text_out
    assert "pkg:new b.py:3-4 loc=2" in text_out
    assert "pkg:known a.py:1-2 loc=2" in text_out


def test_to_text_report_untrusted_baseline_known_sections_empty() -> None:
    text_out = to_text_report(
        meta={"baseline_loaded": False, "baseline_status": "mismatch_schema_version"},
        func_groups={
            "func-a": [
                {
                    "qualname": "pkg:a",
                    "filepath": "a.py",
                    "start_line": 1,
                    "end_line": 2,
                    "loc": 2,
                }
            ]
        },
        block_groups={},
        segment_groups={},
    )
    assert "Note: baseline is untrusted; all groups are treated as NEW." in text_out
    assert "FUNCTION CLONES (NEW) (groups=1)" in text_out
    assert "FUNCTION CLONES (KNOWN) (groups=0)\n(none)" in text_out


def test_segment_groups_internal_only() -> None:
    segments = [
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 4,
            "size": 4,
        },
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 10,
            "end_line": 13,
            "size": 4,
        },
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:g",
            "filepath": "b.py",
            "start_line": 1,
            "end_line": 4,
            "size": 4,
        },
    ]

    groups = build_segment_groups(segments)
    assert len(groups) == 1
    group_items = next(iter(groups.values()))
    assert all(item["qualname"] == "mod:f" for item in group_items)


def test_segment_groups_filters_small_candidates() -> None:
    segments = [
        {
            "segment_sig": "sig1",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 2,
            "size": 2,
        }
    ]
    groups = build_segment_groups(segments)
    assert groups == {}


def test_segment_groups_merge_overlaps(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    if True:",
            "        x = 1",
            "    y = 2",
            "    z = 3",
            "    w = 4",
            "    t = 5",
            "    u = 6",
            "    v = 7",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 4,
                "end_line": 6,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 8,
                "end_line": 9,
                "size": 2,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    items = filtered["seg|mod:f"]
    assert len(items) == 2
    assert items[0]["start_line"] == 2
    assert items[0]["end_line"] == 6
    assert items[1]["start_line"] == 8
    assert items[1]["end_line"] == 9


def test_segment_groups_suppress_boilerplate(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.a = 1",
            "    self.b = 2",
            "    self.c = 3",
            "    self.d = factory()",
            "    self.e = 5",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 6,
                "size": 5,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 6,
                "size": 5,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert filtered == {}
    assert suppressed == 1


def test_segment_groups_keep_call_statement(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.x = 1",
            "    init()",
            "    self.y = 2",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_groups_suppress_rhs_call_assigns(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.x = init()",
            "    self.y = factory()",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert filtered == {}
    assert suppressed == 1


def test_segment_groups_keep_control_flow(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.a = 1",
            "    if flag:",
            "        self.b = 2",
            "    self.c = 3",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 5,
                "size": 4,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 5,
                "size": 4,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_groups_keep_min_unique_types(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    self.a = 1",
            "    x += 1",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 3,
                "size": 2,
            },
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_groups_deterministic(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "def f():",
            "    if flag:",
            "        x = 1",
            "    y = 2",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": 2,
                "end_line": 4,
                "size": 3,
            },
        ]
    }
    first = prepare_segment_report_groups(group)
    second = prepare_segment_report_groups(group)
    assert first == second


def test_segment_helpers_cover_edge_cases(tmp_path: Path) -> None:
    # _merge_segment_items empty
    assert report_mod._merge_segment_items([]) == []

    # _merge_segment_items skips invalid lines and still appends trailing current
    merged = report_mod._merge_segment_items(
        [
            {"start_line": 0, "end_line": 0},
            {"start_line": 2, "end_line": 3, "filepath": "x", "qualname": "q"},
        ]
    )
    assert len(merged) == 1

    # _assign_targets_attribute_only
    assign_attr = ast.parse("self.x = 1").body[0]
    assert report_mod._assign_targets_attribute_only(assign_attr)
    annassign_attr = ast.parse("self.y: int = 2").body[0]
    assert report_mod._assign_targets_attribute_only(annassign_attr)
    assign_name = ast.parse("x = 1").body[0]
    assert not report_mod._assign_targets_attribute_only(assign_name)
    expr_stmt = ast.parse("pass").body[0]
    assert not report_mod._assign_targets_attribute_only(expr_stmt)

    # _analyze_segment_statements empty
    assert report_mod._analyze_segment_statements([]) is None

    # _segment_statements handles non-list body and missing lineno
    class Dummy:
        body = None

    dummy = cast(ast.FunctionDef, cast(object, Dummy()))
    assert report_mod._segment_statements(dummy, 1, 2) == []

    func = ast.parse("def f():\n    x = 1\n").body[0]
    assert isinstance(func, ast.FunctionDef)
    stmt = func.body[0]
    delattr(stmt, "lineno")
    assert report_mod._segment_statements(func, 1, 2) == []


def test_segment_prepare_unknown_paths(tmp_path: Path) -> None:
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "",
                "filepath": "missing.py",
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_segment_prepare_empty_merge() -> None:
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": "x.py",
                "start_line": 0,
                "end_line": 0,
                "size": 0,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert filtered == {}


def test_segment_prepare_missing_file(tmp_path: Path) -> None:
    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(tmp_path / "missing.py"),
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


@pytest.mark.parametrize(
    ("case", "start_line", "end_line"),
    [
        ("syntax_error", 1, 2),
        ("missing_function", 1, 2),
        ("empty_range", 10, 12),
    ],
)
def test_segment_prepare_unresolvable_cases(
    tmp_path: Path, case: str, start_line: int, end_line: int
) -> None:
    if case == "syntax_error":
        f = tmp_path / "bad.py"
        f.write_text("def f(:\n    pass\n", "utf-8")
    elif case == "missing_function":
        f = tmp_path / "a.py"
        f.write_text("def g():\n    return 1\n", "utf-8")
    else:
        f = tmp_path / "a.py"
        f.write_text("def f():\n    x = 1\n", "utf-8")

    group = {
        "seg|mod:f": [
            {
                "segment_sig": "sig",
                "segment_hash": "hash",
                "qualname": "mod:f",
                "filepath": str(f),
                "start_line": start_line,
                "end_line": end_line,
                "size": 2,
            }
        ]
    }
    filtered, suppressed = prepare_segment_report_groups(group)
    assert suppressed == 0
    assert "seg|mod:f" in filtered


def test_collect_file_functions_class_and_async(tmp_path: Path) -> None:
    src = "\n".join(
        [
            "class C:",
            "    async def a(self):",
            "        return 1",
        ]
    )
    f = tmp_path / "a.py"
    f.write_text(src, "utf-8")
    funcs = report_mod._collect_file_functions(str(f))
    assert funcs is not None
    assert "C.a" in funcs

    segments = [
        {
            "segment_sig": "sig2",
            "segment_hash": "h1",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 1,
            "end_line": 2,
            "size": 2,
        },
        {
            "segment_sig": "sig2",
            "segment_hash": "h2",
            "qualname": "mod:f",
            "filepath": "a.py",
            "start_line": 3,
            "end_line": 4,
            "size": 2,
        },
    ]
    groups = build_segment_groups(segments)
    assert groups == {}


def test_report_serialize_helpers_and_text_metrics_section() -> None:
    assert merge_mod.coerce_positive_int(True) == 1
    assert serialize_mod._as_int(True) == 1
    assert serialize_mod._as_int("42") == 42
    assert serialize_mod._as_int("bad") == 0
    assert serialize_mod._as_int(1.2) == 0

    text_report = to_text_report(
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={"health": {"score": 90}},
    )
    assert "METRICS SUMMARY" in text_report
    assert "health: score=90" in text_report


def test_text_and_markdown_report_include_suppressed_dead_code_sections() -> None:
    payload = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/root"},
        metrics={
            "dead_code": {
                "items": [],
                "suppressed_items": [
                    {
                        "qualname": "pkg.mod:runtime_hook",
                        "filepath": "/root/pkg/mod.py",
                        "start_line": 5,
                        "end_line": 6,
                        "kind": "function",
                        "confidence": "high",
                        "suppressed_by": [
                            {"rule": "dead-code", "source": "inline_codeclone"}
                        ],
                    }
                ],
                "summary": {"suppressed": 1},
            }
        },
    )
    text = render_text_report_document(payload)
    assert_contains_all(
        text,
        "dead_code: total=0 high_confidence=0 suppressed=1",
        "SUPPRESSED DEAD CODE (items=1)",
        "suppressed_by=dead-code@inline_codeclone",
    )

    markdown = to_markdown_report(
        report_document=payload,
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    assert '<a id="dead-code-suppressed"></a>' in markdown
    assert "suppression_rule=dead-code" in markdown


# ---------------------------------------------------------------------------
# Structural findings serialization
# ---------------------------------------------------------------------------


def _make_sf_group() -> StructuralFindingGroup:
    """Build a StructuralFindingGroup for serialization tests."""
    sig = {
        "calls": "1",
        "has_loop": "1",
        "has_try": "0",
        "nested_if": "0",
        "raises": "0",
        "stmt_seq": "Expr,For",
        "terminal": "fallthrough",
    }
    occ1 = StructuralFindingOccurrence(
        finding_kind="duplicated_branches",
        finding_key="abc" * 13 + "a",
        file_path="/proj/a.py",
        qualname="mod:fn",
        start=5,
        end=6,
        signature=sig,
    )
    occ2 = StructuralFindingOccurrence(
        finding_kind="duplicated_branches",
        finding_key="abc" * 13 + "a",
        file_path="/proj/a.py",
        qualname="mod:fn",
        start=8,
        end=9,
        signature=sig,
    )
    return StructuralFindingGroup(
        finding_kind="duplicated_branches",
        finding_key="abc" * 13 + "a",
        signature=sig,
        items=(occ1, occ2),
    )


def _make_guard_divergence_group() -> StructuralFindingGroup:
    sig = {
        "cohort_id": "fp-a|20-49",
        "cohort_arity": "4",
        "divergent_members": "1",
        "majority_guard_count": "2",
        "majority_guard_terminal_profile": "return_const,raise",
        "majority_terminal_kind": "return_const",
        "majority_side_effect_before_guard": "0",
        "guard_count_values": "1,2",
        "guard_terminal_values": "raise,return_const,raise",
        "terminal_values": "raise,return_const",
        "side_effect_before_guard_values": "0,1",
    }
    occ = StructuralFindingOccurrence(
        finding_kind="clone_guard_exit_divergence",
        finding_key="guard-div",
        file_path="/proj/b.py",
        qualname="mod:drift_fn",
        start=40,
        end=60,
        signature=sig,
    )
    return StructuralFindingGroup(
        finding_kind="clone_guard_exit_divergence",
        finding_key="guard-div",
        signature=sig,
        items=(occ,),
    )


def _make_cohort_drift_group() -> StructuralFindingGroup:
    sig = {
        "cohort_id": "fp-a|20-49",
        "cohort_arity": "4",
        "divergent_members": "1",
        "drift_fields": "terminal_kind,guard_exit_profile",
        "majority_terminal_kind": "return_const",
        "majority_guard_exit_profile": "2x:return_const,raise",
        "majority_try_finally_profile": "none",
        "majority_side_effect_order_profile": "guard_then_effect",
    }
    occ = StructuralFindingOccurrence(
        finding_kind="clone_cohort_drift",
        finding_key="cohort-drift",
        file_path="/proj/c.py",
        qualname="mod:drift_fn",
        start=70,
        end=90,
        signature=sig,
    )
    return StructuralFindingGroup(
        finding_kind="clone_cohort_drift",
        finding_key="cohort-drift",
        signature=sig,
        items=(occ,),
    )


def test_json_includes_structural_findings_when_non_empty() -> None:
    group = _make_sf_group()
    report_str = to_json_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        structural_findings=[group],
    )
    payload = json.loads(report_str)
    sf = payload["findings"]["groups"]["structural"]
    assert len(sf["groups"]) == 1
    g = sf["groups"][0]
    assert g["kind"] == "duplicated_branches"
    assert g["count"] == 2
    assert g["spread"]["files"] == 1
    assert g["items"][0] == {
        "relative_path": "a.py",
        "qualname": "mod:fn",
        "start_line": 5,
        "end_line": 6,
    }


def test_json_includes_clone_guard_exit_divergence_structural_group() -> None:
    group = _make_guard_divergence_group()
    payload = json.loads(
        to_json_report(
            func_groups={},
            block_groups={},
            segment_groups={},
            structural_findings=[group],
        )
    )
    finding = _structural_groups(payload)[0]
    assert finding["kind"] == "clone_guard_exit_divergence"
    assert finding["count"] == 1
    assert finding["confidence"] == "high"
    signature = cast(dict[str, object], finding["signature"])
    stable = cast(dict[str, object], signature["stable"])
    assert stable["family"] == "clone_guard_exit_divergence"
    facts = cast(dict[str, object], finding["facts"])
    assert facts["cohort_id"] == "fp-a|20-49"
    assert facts["divergent_members"] == 1


def test_json_includes_clone_cohort_drift_structural_group() -> None:
    group = _make_cohort_drift_group()
    payload = json.loads(
        to_json_report(
            func_groups={},
            block_groups={},
            segment_groups={},
            structural_findings=[group],
        )
    )
    finding = _structural_groups(payload)[0]
    assert finding["kind"] == "clone_cohort_drift"
    signature = cast(dict[str, object], finding["signature"])
    stable = cast(dict[str, object], signature["stable"])
    assert stable["family"] == "clone_cohort_drift"
    assert stable["drift_fields"] == ["guard_exit_profile", "terminal_kind"]


def test_text_and_sarif_renderers_cover_new_structural_kinds() -> None:
    payload = json.loads(
        to_json_report(
            func_groups={},
            block_groups={},
            segment_groups={},
            structural_findings=[
                _make_guard_divergence_group(),
                _make_cohort_drift_group(),
            ],
        )
    )
    text = render_text_report_document(payload)
    assert_contains_all(
        text,
        "Clone guard/exit divergence",
        "Clone cohort drift",
        "majority_guard_count",
        "drift_fields",
    )

    sarif = json.loads(
        to_sarif_report(
            report_document=payload,
            meta={},
            func_groups={},
            block_groups={},
            segment_groups={},
        )
    )
    run = sarif["runs"][0]
    rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert "CSTRUCT002" in rule_ids
    assert "CSTRUCT003" in rule_ids
    messages = [result["message"]["text"] for result in run["results"]]
    assert any("guard/exit divergence" in message for message in messages)
    assert any("cohort drift" in message for message in messages)


def test_json_structural_findings_deduplicates_occurrences() -> None:
    group = _make_sf_group()
    duplicate_group = StructuralFindingGroup(
        finding_kind=group.finding_kind,
        finding_key=group.finding_key,
        signature=group.signature,
        items=(group.items[0], group.items[0], group.items[1]),
    )
    payload = json.loads(
        to_json_report(
            func_groups={},
            block_groups={},
            segment_groups={},
            structural_findings=[duplicate_group],
        )
    )
    finding = _structural_groups(payload)[0]
    assert finding["count"] == 2
    assert finding["items"] == [
        {
            "relative_path": "a.py",
            "qualname": "mod:fn",
            "start_line": 5,
            "end_line": 6,
        },
        {
            "relative_path": "a.py",
            "qualname": "mod:fn",
            "start_line": 8,
            "end_line": 9,
        },
    ]


def test_json_structural_findings_sorts_signature_keys() -> None:
    signature = {
        "stmt_seq": "Expr,Return",
        "terminal": "return_const",
        "calls": "1",
        "raises": "0",
    }
    group = StructuralFindingGroup(
        finding_kind="duplicated_branches",
        finding_key="sig-order",
        signature=signature,
        items=(
            StructuralFindingOccurrence(
                finding_kind="duplicated_branches",
                finding_key="sig-order",
                file_path="/proj/a.py",
                qualname="mod:fn",
                start=5,
                end=6,
                signature=signature,
            ),
            StructuralFindingOccurrence(
                finding_kind="duplicated_branches",
                finding_key="sig-order",
                file_path="/proj/a.py",
                qualname="mod:fn",
                start=8,
                end=9,
                signature=signature,
            ),
        ),
    )
    payload = json.loads(
        to_json_report(
            func_groups={},
            block_groups={},
            segment_groups={},
            structural_findings=[group],
        )
    )
    finding = _structural_groups(payload)[0]
    finding_signature = finding["signature"]
    assert isinstance(finding_signature, dict)
    debug = finding_signature["debug"]
    assert isinstance(debug, dict)
    assert list(debug) == [
        "calls",
        "raises",
        "stmt_seq",
        "terminal",
    ]


def test_json_structural_findings_prunes_overlapping_occurrences() -> None:
    group = _make_sf_group()
    overlapping_group = StructuralFindingGroup(
        finding_kind=group.finding_kind,
        finding_key=group.finding_key,
        signature=group.signature,
        items=(
            group.items[0],
            StructuralFindingOccurrence(
                finding_kind=group.finding_kind,
                finding_key=group.finding_key,
                file_path="/proj/a.py",
                qualname="mod:fn",
                start=6,
                end=6,
                signature=group.signature,
            ),
            group.items[1],
        ),
    )
    payload = json.loads(
        to_json_report(
            func_groups={},
            block_groups={},
            segment_groups={},
            structural_findings=[overlapping_group],
        )
    )
    finding = _structural_groups(payload)[0]
    assert finding["count"] == 2
    assert finding["items"] == [
        {
            "relative_path": "a.py",
            "qualname": "mod:fn",
            "start_line": 5,
            "end_line": 6,
        },
        {
            "relative_path": "a.py",
            "qualname": "mod:fn",
            "start_line": 8,
            "end_line": 9,
        },
    ]


def test_json_structural_findings_filters_trivial_groups() -> None:
    sig = {
        "calls": "2+",
        "has_loop": "0",
        "has_try": "0",
        "nested_if": "0",
        "raises": "0",
        "stmt_seq": "Expr",
        "terminal": "expr",
    }
    trivial_group = StructuralFindingGroup(
        finding_kind="duplicated_branches",
        finding_key="def" * 13 + "d",
        signature=sig,
        items=(
            StructuralFindingOccurrence(
                finding_kind="duplicated_branches",
                finding_key="def" * 13 + "d",
                file_path="/proj/a.py",
                qualname="mod:fn",
                start=5,
                end=5,
                signature=sig,
            ),
            StructuralFindingOccurrence(
                finding_kind="duplicated_branches",
                finding_key="def" * 13 + "d",
                file_path="/proj/a.py",
                qualname="mod:fn",
                start=8,
                end=8,
                signature=sig,
            ),
        ),
    )
    payload = json.loads(
        to_json_report(
            func_groups={},
            block_groups={},
            segment_groups={},
            structural_findings=[trivial_group],
        )
    )
    assert _structural_groups(payload) == []


def test_json_no_structural_findings_key_when_empty() -> None:
    report_str = to_json_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        structural_findings=[],
    )
    payload = json.loads(report_str)
    assert _structural_groups(payload) == []


def test_structural_findings_json_deterministic() -> None:
    group = _make_sf_group()
    r1 = to_json_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        structural_findings=[group],
    )
    r2 = to_json_report(
        func_groups={},
        block_groups={},
        segment_groups={},
        structural_findings=[group],
    )
    assert r1 == r2


def test_txt_includes_structural_findings_block() -> None:
    group = _make_sf_group()
    report_str = to_text_report(
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
        structural_findings=[group],
    )
    assert "STRUCTURAL FINDINGS" in report_str
    assert "Duplicated branches" in report_str


def test_html_panel_explains_local_non_overlapping_structural_findings() -> None:
    group = _make_sf_group()
    html = build_structural_findings_html_panel([group], ["/proj/a.py"])
    assert "Repeated non-overlapping branch-body shapes" in html
    assert "local, report-only refactoring hints" in html
    assert "Occurrences (2)" in html
    assert "All occurrences belong to 1 function in 1 file." in html
