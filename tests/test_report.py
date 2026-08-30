# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

import ast
import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import cast

import orjson
import pytest

import codeclone.api.report as report_api_mod
import codeclone.report.merge as merge_mod
import codeclone.report.overview as overview_mod
import codeclone.report.renderers.text as text_renderer_mod
from codeclone.api.report import ReportArtifactFailure, load_report_artifact
from codeclone.baseline.trust import current_python_tag
from codeclone.contracts import CACHE_VERSION, REPORT_SCHEMA_VERSION
from codeclone.findings.clones.grouping import (
    build_block_groups,
    build_groups,
    build_segment_groups,
)
from codeclone.models import (
    LaneTrust,
    ReportDigest,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Suggestion,
    SuppressedCloneGroup,
    TrustVector,
)
from codeclone.report.blocks import prepare_block_report_groups
from codeclone.report.document.integrity import (
    _build_integrity_payload,
    verify_report_integrity,
)
from codeclone.report.explain import build_block_group_facts
from codeclone.report.html.assemble import build_html_report
from codeclone.report.html.sections._structural import (
    _finding_why_template_html,
    build_structural_findings_html_panel,
)
from codeclone.report.html.widgets.snippets import _FileCache
from codeclone.report.messages.sections import METRICS_SKIPPED
from codeclone.report.overview import materialize_report_overview
from codeclone.report.renderers.json import render_json_report_document
from codeclone.report.renderers.markdown import render_markdown_report_document
from codeclone.report.renderers.sarif import render_sarif_report_document
from codeclone.report.renderers.text import render_text_report_document
from codeclone.report.segments import (
    analyze_segment_statements as _analyze_segment_statements,
)
from codeclone.report.segments import (
    assign_targets_attribute_only as _assign_targets_attribute_only,
)
from codeclone.report.segments import (
    collect_file_functions as _collect_file_functions,
)
from codeclone.report.segments import merge_segment_items as _merge_segment_items
from codeclone.report.segments import prepare_segment_report_groups
from codeclone.report.segments import (
    segment_statements as _segment_statements,
)
from codeclone.report.types import GroupMap
from tests._assertions import assert_contains_all, assert_mapping_entries
from tests._report_access import (
    _dict_at,
)
from tests._report_access import (
    report_clone_groups as _clone_groups,
)
from tests._report_access import (
    report_structural_groups as _structural_groups,
)
from tests._report_fixtures import (
    REPEATED_STMT_HASH,
    build_maximal_report_document,
    repeated_block_group_key,
    write_repeated_assert_source,
)
from tests._report_fixtures import (
    build_test_report_document as build_report_document,
)


def _trusted_clone_lanes() -> TrustVector:
    return TrustVector(
        root_verified=True,
        lanes=(
            LaneTrust(
                name="clones.blocks",
                status="trusted",
                reason="compatible",
            ),
            LaneTrust(
                name="clones.functions",
                status="trusted",
                reason="compatible",
            ),
        ),
    )


def test_authority_findings_and_all_renderers_share_canonical_facts() -> None:
    violation = {
        "item_kind": "violation",
        "violation_id": "1" * 64,
        "contract_id": "example.contract/v1",
        "kind": "owner_bypass",
        "sink_identity": "pkg.mod:shadow",
        "canonical_owner": "pkg.mod:owner",
        "authority_status": "shadow",
        "producer_root_ids": ["producer:pkg.mod:shadow"],
        "effect_signature": "2" * 64,
        "resolution_state": "resolved",
        "producers": ["pkg.mod:shadow"],
        "suppressed": False,
        "locations": [
            {
                "relative_path": "pkg/mod.py",
                "start_line": 10,
                "end_line": 12,
                "qualname": "pkg.mod:shadow",
            }
        ],
        "algorithm_revision": "1",
    }
    payload = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/repo"},
        metrics={
            "semantic_authority": {
                "summary": {
                    "enabled": True,
                    "report_only": False,
                    "enforcement_enabled": True,
                    "algorithm_revision": "1",
                    "registry_version": "1",
                    "registry_contracts": 1,
                    "contracts": 2,
                    "sinks": 2,
                    "candidates": 1,
                    "governed_sinks": 2,
                    "violations": 2,
                    "active_violations": 1,
                    "suppressed_violations": 1,
                    "scc_count": 2,
                    "fixpoint_iterations": 1,
                    "sinks_by_status": {"authoritative": 1, "shadow": 1},
                },
                "items": [
                    violation,
                    {
                        **violation,
                        "violation_id": "3" * 64,
                        "suppressed": True,
                    },
                ],
                "registry": [],
                "contract_ir": [],
            }
        },
    )

    findings = cast("dict[str, object]", payload["findings"])
    authority = cast(
        "dict[str, object]",
        cast("dict[str, object]", findings["groups"])["authority"],
    )
    groups = cast("list[dict[str, object]]", authority["groups"])
    assert [group["category"] for group in groups] == ["owner_bypass"]
    assert cast("dict[str, int]", findings["summary"])["total"] == 1
    assert (
        cast(
            "dict[str, int]",
            cast("dict[str, object]", findings["summary"])["suppressed"],
        )["authority"]
        == 1
    )

    markdown = render_markdown_report_document(payload)
    text = render_text_report_document(payload)
    sarif = json.loads(render_sarif_report_document(payload))
    html = build_html_report(report_document=payload)
    assert_contains_all(
        markdown,
        "Authority Findings",
        "example.contract/v1",
        "owner_bypass",
    )
    assert_contains_all(
        text,
        "AUTHORITY FINDINGS",
        "example.contract/v1",
        "owner_bypass",
    )
    assert sarif["runs"][0]["results"][0]["ruleId"] == "CAUTH001"
    assert_contains_all(html, "Authority", "example.contract/v1", "owner_bypass")


def test_report_artifact_door_rejects_foreign_schema_after_shape_validation(
    tmp_path: Path,
) -> None:
    report = tmp_path / "foreign.json"
    document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(tmp_path)},
        inventory={"file_registry": {"items": ["pkg/module.py"]}},
    )
    document["report_schema_version"] = "4.0"
    report.write_text(json.dumps(document), encoding="utf-8")

    result = load_report_artifact(report)

    assert isinstance(result, ReportArtifactFailure)
    assert result.reason == "incompatible_schema"


def test_report_artifact_door_rejects_oversize_before_json_parsing(
    tmp_path: Path,
) -> None:
    report = tmp_path / "oversize.json"
    report.write_bytes(b"{}")

    result = load_report_artifact(report, limit_bytes=1)

    assert isinstance(result, ReportArtifactFailure)
    assert result.reason == "too_large"


def test_report_artifact_door_rejects_unreadable_path(tmp_path: Path) -> None:
    result = load_report_artifact(tmp_path / "missing.json")

    assert isinstance(result, ReportArtifactFailure)
    assert result.reason == "unreadable"


def test_report_artifact_door_rejects_invalid_json(tmp_path: Path) -> None:
    report = tmp_path / "invalid.json"
    report.write_bytes(b"\xff")

    result = load_report_artifact(report)

    assert isinstance(result, ReportArtifactFailure)
    assert result.reason == "invalid_json"


def test_report_artifact_door_rejects_authenticated_shape_mismatch(
    tmp_path: Path,
) -> None:
    report = tmp_path / "tampered.json"
    document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(tmp_path)},
    )
    derived = cast(dict[str, object], document["derived"])
    derived["review_queue"] = [{"id": "tampered"}]
    report.write_text(json.dumps(document), encoding="utf-8")

    result = load_report_artifact(report)

    assert isinstance(result, ReportArtifactFailure)
    assert result.reason == "invalid_shape"
    assert result.detail == "report envelope digest mismatch"


def test_report_reader_rejects_non_mapping_model_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NonMappingProjection:
        report_schema_version = REPORT_SCHEMA_VERSION

        @staticmethod
        def model_dump(*, mode: str) -> list[object]:
            assert mode == "json"
            return []

    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "codeclone.report.document.reader.ReportDocumentV3Input.model_validate",
        staticmethod(lambda _decoded: _NonMappingProjection()),
    )

    result = load_report_artifact(report)

    assert isinstance(result, ReportArtifactFailure)
    assert result.reason == "invalid_shape"
    assert result.detail == "report document must be a JSON object"


def test_report_artifact_door_rejects_unknown_reader_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        report_api_mod,
        "read_report_document_v3",
        lambda *_args, **_kwargs: object(),
    )

    with pytest.raises(
        TypeError,
        match="stored report reader returned an unknown result",
    ):
        load_report_artifact(tmp_path / "report.json")


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
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    baseline_trust: TrustVector | None = None,
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
        suppressed_clone_groups=suppressed_clone_groups,
        metrics=metrics,
        suggestions=suggestions or (),
        structural_findings=structural_findings or (),
        baseline_trust=baseline_trust,
    )
    # The renderer owns bytes; this helper serves tests that assert on report
    # text, so decode once here. The bytes contract itself is pinned by
    # test_json_renderer_emits_bytes_without_a_string_round_trip.
    return render_json_report_document(payload).decode("utf-8")


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
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    baseline_trust: TrustVector | None = None,
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
        suppressed_clone_groups=suppressed_clone_groups,
        metrics=metrics,
        suggestions=suggestions or (),
        structural_findings=structural_findings or (),
        baseline_trust=baseline_trust,
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
    assert [
        (
            item["qualname"],
            item["start_line"],
            item["end_line"],
            item["size"],
        )
        for item in items
    ] == [
        ("mod:f", 10, 16, 7),
        ("mod:f", 20, 23, 4),
        ("mod:g", 10, 13, 4),
    ]


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
    trusted_lanes = _trusted_clone_lanes()
    report_out = to_json_report(
        groups,
        groups,
        {},
        meta,
        new_function_group_keys=set(groups),
        new_block_group_keys=set(groups),
        baseline_trust=trusted_lanes,
    )
    report_document = json.loads(report_out)
    markdown_out = render_markdown_report_document(report_document)
    sarif_out = render_sarif_report_document(report_document)
    text_out = to_text_report(
        meta=meta,
        func_groups=groups,
        block_groups=groups,
        segment_groups={},
        new_function_group_keys=set(groups),
        new_block_group_keys=set(groups),
        baseline_trust=trusted_lanes,
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
        f"Python tag: {current_python_tag()}",
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
    assert run["automationDetails"]["id"] == "codeclone/full/2026-03-10T12:00:00Z"
    assert run["properties"]["reportSchemaVersion"] == REPORT_SCHEMA_VERSION
    assert run["properties"]["reportGeneratedAtUtc"] == "2026-03-10T12:00:00Z"
    assert "columnKind" not in run
    assert run["originalUriBaseIds"]["%SRCROOT%"]["uri"] == "file:///repo/"
    assert run["artifacts"]
    assert run["invocations"][0]["workingDirectory"]["uri"] == "file:///repo/"
    assert "semanticVersion" not in run["tool"]["driver"]
    assert any(rule["id"] == "CCLONE001" for rule in run["tool"]["driver"]["rules"])
    first_rule = run["tool"]["driver"]["rules"][0]
    assert first_rule["name"] == "codeclone.CCLONE001"
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
        render_sarif_report_document(
            build_report_document(
                func_groups=groups,
                block_groups={},
                segment_groups={},
                meta={"codeclone_version": "2.0.0b2", "scan_root": "/repo"},
                new_function_group_keys={"k1"},
                baseline_trust=_trusted_clone_lanes(),
            ),
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
    assert result["kind"] == "fail"
    assert set(result["partialFingerprints"]) == {"primaryLocationLineHash"}
    assert (
        result["properties"]["primaryPath"] == "tests/fixtures/golden_project/alpha.py"
    )
    assert result["properties"]["primaryQualname"] == "pkg.alpha:transform_alpha"
    assert result["properties"]["primaryRegion"] == "1-10"


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
    payload = json.loads(
        to_json_report(
            groups,
            {},
            {},
            {"codeclone_version": "1.4.0"},
            new_function_group_keys={"g1"},
            baseline_trust=_trusted_clone_lanes(),
        )
    )

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
        "instances": 2,
        "new": 1,
        "known": 0,
        "unavailable": 0,
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
        "contracts",
        "source_facts",
        "baseline",
        "evaluation",
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
        "severity",
        "category",
        "location",
        "priority",
        "finding_family",
        "finding_kind",
        "subject_key",
        "fact_kind",
        "fact_count",
        "spread_files",
        "spread_functions",
        "clone_type",
        "confidence",
        "source_kind",
        "source_breakdown",
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
    assert overview["directory_hotspots"]["all"] == {
        "total_directories": 0,
        "returned": 0,
        "has_more": False,
        "items": [],
    }
    assert payload["derived"]["hotlists"]["most_actionable_ids"] == []


def _markdown_integrity_bullets(markdown: str) -> list[tuple[str, str]]:
    """The Integrity block's bullets, as ``(label, rendered value)``."""

    block = markdown.split("## Integrity", 1)[1]
    rows: list[tuple[str, str]] = []
    for line in block.splitlines():
        if not line.startswith("- "):
            continue
        label, _sep, value = line[2:].partition(": ")
        rows.append((label, value))
    return rows


def _text_integrity_fields(text: str, prefix: str) -> dict[str, str]:
    """One ``key=value`` line of the text report's INTEGRITY block.

    Splitting on spaces is safe for exactly this block: every value it prints
    is a single token, and a value that grew a space would show up here as a
    stray field rather than pass unnoticed.
    """

    line = next(row for row in text.splitlines() if row.startswith(prefix))
    fields: dict[str, str] = {}
    for field in line[len(prefix) :].split(" "):
        key, sep, value = field.partition("=")
        if sep:
            fields[key] = value
    return fields


def _html_integrity_labels(html: str) -> list[str]:
    """The row labels of the HTML provenance panel's Integrity section."""

    section = html.split(">Integrity</h3>", 1)[1].split("</section>", 1)[0]
    return re.findall(r'prov-td-label">([^<]+)</td>', section)


def _html_integrity_data_attrs(html: str) -> dict[str, str]:
    """The machine-readable twin of that panel, one attribute per fact."""

    return dict(
        re.findall(r'(data-(?:canonical|digest|envelope)[a-z-]*)="([^"]*)"', html)
    )


def test_every_surface_prints_the_integrity_facts_the_document_carries() -> None:
    """One integrity block, and the document decides what is in it.

    All three surfaces asked the canonicalization block for a ``scope`` and a
    ``sections`` list, and the envelope tier for a ``verified`` flag. The
    document carries none of the three: canonicalization declares ``version``,
    ``serializer`` and ``envelope_null_sentinel``, and the envelope tier
    declares ``kind``/``algorithm``/``digest_version``/``value``. Markdown
    printed the three absences as "(none)" bullets, the text report dropped
    them silently, and every surface omitted the canonicalization facts the
    document does publish.

    The comparison is a multiset equality against the document's own values,
    not a list of expected literals: a fact added to either block and printed
    nowhere fails here, and so does a bullet with nothing behind it.
    """

    document = build_maximal_report_document()
    integrity = cast(dict[str, object], document["integrity"])
    canonicalization = cast(dict[str, str], integrity["canonicalization"])
    envelope = cast(
        dict[str, str],
        cast(dict[str, object], integrity["digests"])["envelope"],
    )
    assert len(canonicalization) + len(envelope) == 7

    text = render_text_report_document(document)
    markdown = render_markdown_report_document(document)
    html = build_html_report(report_document=document)

    assert _text_integrity_fields(text, "Canonicalization: ") == canonicalization
    assert _text_integrity_fields(text, "Digest: ") == envelope

    bullets = _markdown_integrity_bullets(markdown)
    printed = [value for label, value in bullets if label != "Hotlists"]
    assert sorted(printed) == sorted([*canonicalization.values(), *envelope.values()])

    assert _html_integrity_labels(html) == [
        label for label, _value in bullets if label != "Hotlists"
    ]
    # The panel and its data attributes are two renderings of one block, so a
    # withdrawn key coming back in the machine-readable half alone is still a
    # surface disagreeing with the canonical report.
    assert sorted(_html_integrity_data_attrs(html).values()) == sorted(printed)


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
    assert payload["integrity"]["canonicalization"] == {
        "version": "3",
        "serializer": "orjson.OPT_SORT_KEYS",
        "envelope_null_sentinel": "integrity.digests.envelope.value",
    }
    assert set(payload["integrity"]["digests"]) == {
        "observation",
        "analysis_facts",
        "comparison",
        "evaluation",
        "envelope",
    }
    assert verify_report_integrity(payload) is None


def test_report_json_integrity_tiers_change_only_for_declared_inputs() -> None:
    source_facts: Mapping[str, object] = {"facts": ["one"]}
    baseline: Mapping[str, object] = {
        "state": "trusted",
        "baseline_scope_id": "scope-a",
        "root_digest_or_null": "b" * 64,
        "sorted_lane_trust": [],
        "sorted_novelty_facts": [],
    }
    evaluation: Mapping[str, object] = {"outcome": {"exit_code": 0, "reasons": []}}

    def _digests(
        *,
        next_source_facts: Mapping[str, object] = source_facts,
        next_baseline: Mapping[str, object] = baseline,
        next_evaluation: Mapping[str, object] = evaluation,
    ) -> Mapping[str, object]:
        integrity = _build_integrity_payload(
            report_schema_version=REPORT_SCHEMA_VERSION,
            observation_digest="a" * 64,
            source_facts=next_source_facts,
            baseline=next_baseline,
            evaluation=next_evaluation,
        )
        digests = integrity["digests"]
        assert isinstance(digests, dict)
        return digests

    original = _digests()
    source_changed = _digests(next_source_facts={"facts": ["two"]})
    baseline_changed = _digests(next_baseline={**baseline, "state": "untrusted"})
    evaluation_changed = _digests(
        next_evaluation={"outcome": {"exit_code": 3, "reasons": ["gate"]}}
    )

    assert original["observation"] == source_changed["observation"]
    assert original["analysis_facts"] != source_changed["analysis_facts"]
    assert original["analysis_facts"] == baseline_changed["analysis_facts"]
    assert original["comparison"] != baseline_changed["comparison"]
    assert original["comparison"] == evaluation_changed["comparison"]
    assert original["evaluation"] != evaluation_changed["evaluation"]


@pytest.mark.parametrize(
    "value",
    ("f" * 63, "f" * 63 + "G"),
)
def test_report_digest_rejects_noncanonical_sha256(value: str) -> None:
    with pytest.raises(
        ValueError,
        match="report digest values must be 64 lowercase hex characters",
    ):
        ReportDigest(
            kind="comparison",
            algorithm="sha256",
            digest_version="1",
            value=value,
        )


def test_report_digest_accepts_canonical_sha256() -> None:
    digest = ReportDigest(
        kind="comparison",
        algorithm="sha256",
        digest_version="1",
        value="f" * 64,
    )

    assert digest.value == "f" * 64


def test_report_json_envelope_sentinel_authenticates_nonsemantic_fields() -> None:
    payload = json.loads(to_json_report({}, {}, {}, {"codeclone_version": "1.4.0"}))
    changed = deepcopy(payload)
    changed["derived"]["review_queue"] = [{"id": "changed"}]

    assert verify_report_integrity(changed) == "report envelope digest mismatch"


def test_report_json_integrity_rejects_incomplete_or_malformed_digest_tiers() -> None:
    payload = json.loads(to_json_report({}, {}, {}, {"codeclone_version": "1.4.0"}))

    missing_tier = deepcopy(payload)
    del missing_tier["integrity"]["digests"]["evaluation"]
    assert (
        verify_report_integrity(missing_tier)
        == "report digest set must contain exactly five named tiers"
    )

    missing_observation = deepcopy(payload)
    missing_observation["integrity"]["digests"]["observation"]["value"] = None
    assert (
        verify_report_integrity(missing_observation)
        == "report observation digest is missing"
    )

    missing_schema = deepcopy(payload)
    missing_schema["report_schema_version"] = None
    assert verify_report_integrity(missing_schema) == "report schema version is missing"

    mismatched_analysis = deepcopy(payload)
    mismatched_analysis["integrity"]["digests"]["analysis_facts"]["value"] = "0" * 64
    assert (
        verify_report_integrity(mismatched_analysis)
        == "report analysis_facts digest mismatch"
    )


def test_report_json_integrity_has_no_v2_digest_alias() -> None:
    payload = json.loads(to_json_report({}, {}, {}, {"codeclone_version": "1.4.0"}))

    assert "digest" not in payload["integrity"]


def test_report_json_analysis_facts_authenticate_analysis_contract() -> None:
    payload_a = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0", "design_complexity_threshold": 20},
        )
    )
    payload_b = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0", "design_complexity_threshold": 21},
        )
    )

    assert (
        payload_a["source_facts"]["analysis_contract"]
        != payload_b["source_facts"]["analysis_contract"]
    )
    assert (
        payload_a["integrity"]["digests"]["analysis_facts"]
        != payload_b["integrity"]["digests"]["analysis_facts"]
    )


def test_report_json_integrity_ignores_cache_execution_provenance() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {
                "codeclone_version": "1.4.0",
                "cache_used": True,
                "cache_status": "ok",
                "cache_schema_version": CACHE_VERSION,
            },
            inventory={
                "files": {
                    "total_found": 2,
                    "analyzed": 0,
                    "cached": 2,
                    "skipped": 0,
                    "source_io_skipped": 2,
                },
                "code": {
                    "functions": 0,
                    "methods": 0,
                    "classes": 0,
                    "parsed_lines": 12,
                },
            },
        )
    )
    cache_off_payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {
                "codeclone_version": "1.4.0",
                "cache_used": False,
                "cache_status": "disabled",
                "cache_schema_version": CACHE_VERSION,
            },
            inventory={
                "files": {
                    "total_found": 2,
                    "analyzed": 2,
                    "cached": 0,
                    "skipped": 0,
                    "source_io_skipped": 0,
                },
                "code": {
                    "functions": 0,
                    "methods": 0,
                    "classes": 0,
                    "parsed_lines": 12,
                },
            },
        )
    )

    assert payload["inventory"] != cache_off_payload["inventory"]
    assert (
        payload["integrity"]["digests"]["analysis_facts"]
        == cache_off_payload["integrity"]["digests"]["analysis_facts"]
    )
    assert (
        payload["integrity"]["digests"]["envelope"]
        != cache_off_payload["integrity"]["digests"]["envelope"]
    )


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
    assert (
        payload_a["integrity"]["digests"]["analysis_facts"]
        == payload_b["integrity"]["digests"]["analysis_facts"]
    )
    assert (
        payload_a["integrity"]["digests"]["envelope"]
        != payload_b["integrity"]["digests"]["envelope"]
    )


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
    assert (
        payload_a["integrity"]["digests"]["analysis_facts"]
        == payload_b["integrity"]["digests"]["analysis_facts"]
    )
    assert (
        payload_a["integrity"]["digests"]["envelope"]
        != payload_b["integrity"]["digests"]["envelope"]
    )


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
    assert summary == {
        "total": 1,
        "high_confidence": 1,
        "suppressed": 0,
        "baseline_diff_available": False,
        "new_items": 0,
        # 39Y cycle 2b: abstentions ride beside the dead counts, never inside.
        "unresolved_external_override": 0,
        "unreachable_statements": 0,
        "live_roots": 0,
    }


def test_report_json_dead_code_preserves_test_reference_reason_and_evidence() -> None:
    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0", "scan_root": "/root"},
            metrics={
                "dead_code": {
                    "items": [
                        {
                            "qualname": "pkg.mod:held_by_tests",
                            "filepath": "/root/pkg/mod.py",
                            "start_line": 10,
                            "end_line": 12,
                            "kind": "function",
                            "confidence": "high",
                            "reason": "test_only_reference",
                            "test_reference_sources": [
                                "tests.test_mod:test_second",
                                "tests.test_mod:test_first",
                                "tests.test_mod:test_second",
                            ],
                        }
                    ],
                }
            },
        )
    )

    item = payload["metrics"]["families"]["dead_code"]["items"][0]
    assert item["reason"] == "test_only_reference"
    assert item["test_reference_sources"] == [
        "tests.test_mod:test_first",
        "tests.test_mod:test_second",
    ]
    finding = payload["findings"]["groups"]["dead_code"]["groups"][0]
    assert finding["facts"]["reason"] == "test_only_reference"
    assert finding["facts"]["test_reference_sources"] == item["test_reference_sources"]


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
    assert dead_code["summary"] == {
        "total": 0,
        "high_confidence": 0,
        "suppressed": 1,
        "baseline_diff_available": False,
        "new_items": 0,
        "unresolved_external_override": 0,
        "unreachable_statements": 0,
        "live_roots": 0,
    }
    suppressed_items = dead_code["suppressed_items"]
    assert suppressed_items == [
        {
            "qualname": "pkg.mod:runtime_hook",
            "relative_path": "pkg/mod.py",
            "start_line": 40,
            "end_line": 41,
            "kind": "function",
            "confidence": "high",
            "reason": "unreferenced",
            "test_reference_sources": [],
            "suppressed_by": [{"rule": "dead-code", "source": "inline_codeclone"}],
            "suppression_rule": "dead-code",
            "suppression_source": "inline_codeclone",
        }
    ]
    assert payload["findings"]["groups"]["dead_code"]["groups"] == []
    assert payload["findings"]["summary"]["suppressed"] == {"dead_code": 1}


def test_report_json_clone_groups_can_include_suppressed_golden_fixture_bucket() -> (
    None
):
    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0", "scan_root": "/root"},
            suppressed_clone_groups=(
                SuppressedCloneGroup(
                    kind="function",
                    group_key="golden-group",
                    items=(
                        {
                            "qualname": "tests.fixtures.golden.a:run",
                            "filepath": "/root/tests/fixtures/golden_project/a.py",
                            "start_line": 10,
                            "end_line": 12,
                            "loc": 3,
                            "stmt_count": 2,
                            "fingerprint": "fp-a",
                            "loc_bucket": "0-19",
                        },
                        {
                            "qualname": "tests.fixtures.golden.b:run",
                            "filepath": "/root/tests/fixtures/golden_project/b.py",
                            "start_line": 10,
                            "end_line": 12,
                            "loc": 3,
                            "stmt_count": 2,
                            "fingerprint": "fp-a",
                            "loc_bucket": "0-19",
                        },
                    ),
                    matched_patterns=("tests/fixtures/golden_*",),
                    suppression_rule="golden_fixture",
                    suppression_source="project_config",
                ),
            ),
        )
    )

    suppressed = payload["findings"]["groups"]["clones"]["suppressed"]
    assert suppressed["functions"][0]["suppression_rule"] == "golden_fixture"
    assert suppressed["functions"][0]["suppression_source"] == "project_config"
    assert suppressed["functions"][0]["matched_patterns"] == ["tests/fixtures/golden_*"]
    assert payload["findings"]["summary"]["clones"]["suppressed"] == 1
    assert payload["findings"]["summary"]["suppressed"] == {
        "dead_code": 0,
        "clones": 1,
    }
    assert (
        "tests/fixtures/golden_project/a.py"
        in payload["inventory"]["file_registry"]["items"]
    )


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
    for name in ("observation", "analysis_facts", "comparison", "evaluation"):
        assert (
            payload_a["integrity"]["digests"][name]
            == payload_b["integrity"]["digests"][name]
        )
    assert (
        payload_a["integrity"]["digests"]["envelope"]
        != payload_b["integrity"]["digests"]["envelope"]
    )


def test_report_json_semantic_digests_ignore_checkout_directory() -> None:
    payload_a = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0", "scan_root": "/checkout/one"},
            inventory={"file_list": ["/checkout/one/pkg/module.py"]},
        )
    )
    payload_b = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0", "scan_root": "/checkout/two"},
            inventory={"file_list": ["/checkout/two/pkg/module.py"]},
        )
    )

    for name in ("observation", "analysis_facts", "comparison", "evaluation"):
        assert (
            payload_a["integrity"]["digests"][name]
            == payload_b["integrity"]["digests"][name]
        )
    assert (
        payload_a["integrity"]["digests"]["envelope"]
        != payload_b["integrity"]["digests"]["envelope"]
    )


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


@pytest.mark.parametrize(
    ("summary_value", "expected"),
    [
        (3, 3),
        ("4", 4),
        ("not-a-count", 0),
        (1.5, 0),
        (True, 1),
        (None, 0),
    ],
)
def test_report_overview_metric_summary_count_uses_contract_coercion(
    summary_value: object,
    expected: int,
) -> None:
    metrics: dict[str, object] = {
        "dead_code": {"summary": {"high_confidence": summary_value}}
    }
    assert (
        overview_mod._metric_summary_count(
            metrics,
            "dead_code",
            "high_confidence",
        )
        == expected
    )


def test_report_overview_metric_summary_count_uses_fallback_key() -> None:
    metrics: dict[str, object] = {"dead_code": {"summary": {"critical": "2"}}}
    assert (
        overview_mod._metric_summary_count(
            metrics,
            "dead_code",
            "high_confidence",
            fallback_key="critical",
        )
        == 2
    )


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

    fallback_dependency_card = overview_mod.serialize_finding_group_card(
        {
            "family": "design",
            "category": "dependency",
            "severity": "warning",
            "confidence": "medium",
            "count": 2,
            "source_scope": {"dominant_kind": "production"},
            "spread": {"files": 2, "functions": 0},
            "items": [{"module": ""}],
            "facts": {},
        }
    )
    assert (
        fallback_dependency_card["location"]
        == "2 occurrences across 2 files / 0 functions"
    )

    unknown_design_card = overview_mod.serialize_finding_group_card(
        {
            "family": "design",
            "category": "unknown",
            "severity": "info",
            "confidence": "low",
            "count": 1,
            "source_scope": {"dominant_kind": "other"},
            "spread": {"files": 1, "functions": 1},
            "items": [{"relative_path": "pkg/mod.py", "start_line": 1, "end_line": 1}],
            "facts": {},
        }
    )
    assert unknown_design_card["title"] == "Finding"
    assert unknown_design_card["summary"] == ""


def test_report_findings_template_html_covers_custom_kind_fallback(
    tmp_path: Path,
) -> None:
    snippet_path = tmp_path / "custom.py"
    snippet_path.write_text("value = 1\nvalue = 2\n", encoding="utf-8")
    items = (
        StructuralFindingOccurrence(
            finding_kind="custom_kind",
            finding_key="custom:1",
            file_path=str(snippet_path),
            qualname="pkg.mod:fn",
            start=1,
            end=1,
            signature={"stmt_seq": "Assign", "terminal": "fallthrough"},
        ),
        StructuralFindingOccurrence(
            finding_kind="custom_kind",
            finding_key="custom:1",
            file_path=str(snippet_path),
            qualname="pkg.mod:fn",
            start=2,
            end=2,
            signature={"stmt_seq": "Assign", "terminal": "fallthrough"},
        ),
    )
    html = _finding_why_template_html(
        StructuralFindingGroup(
            finding_kind="custom_kind",
            finding_key="custom:1",
            signature={"stmt_seq": "Assign", "terminal": "fallthrough"},
            items=items,
        ),
        items,
        file_cache=_FileCache(),
        context_lines=0,
        max_snippet_lines=10,
    )
    assert "structurally matching branch bodies" in html
    assert "Showing the first 2 matching branches" in html


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
            baseline_trust=_trusted_clone_lanes(),
        )
    )
    clones = payload["findings"]["groups"]["clones"]
    function_map = _clone_group_map(payload, "functions")
    block_map = _clone_group_map(payload, "blocks")
    segment_map = _clone_group_map(payload, "segments")
    assert {
        "func-new": function_map["func-new"]["novelty"],
        "func-known": function_map["func-known"]["novelty"],
        "block-new": block_map["block-new"]["novelty"],
        "block-known": block_map["block-known"]["novelty"],
    } == {
        "func-new": "new",
        "func-known": "known",
        "block-new": "new",
        "block-known": "known",
    }
    assert segment_map["segment-new"]["novelty"] == "unavailable"
    assert segment_map["segment-new"]["novelty_reason"] == "not_baseline_governed"
    assert payload["findings"]["summary"]["clones"] == {
        "functions": len(clones["functions"]),
        "blocks": len(clones["blocks"]),
        "segments": len(clones["segments"]),
        "instances": 5,
        "new": 2,
        "known": 2,
        "unavailable": 1,
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
    assert function_map["func-a"]["novelty"] == "unavailable"
    assert payload["findings"]["summary"]["clones"] == {
        "functions": 1,
        "blocks": 0,
        "segments": 0,
        "instances": 1,
        "new": 0,
        "known": 0,
        "unavailable": 1,
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
        "Note: unavailable baseline lanes produce UNAVAILABLE novelty, never NEW.",
        "FUNCTION CLONES (NEW) (groups=0)\n(none)",
        "FUNCTION CLONES (KNOWN) (groups=0)\n(none)",
        "FUNCTION CLONES (UNAVAILABLE) (groups=0)\n(none)",
        "BLOCK CLONES (NEW) (groups=0)\n(none)",
        "BLOCK CLONES (KNOWN) (groups=0)\n(none)",
        "BLOCK CLONES (UNAVAILABLE) (groups=0)\n(none)",
        "SEGMENT CLONES (NEW) (groups=0)\n(none)",
        "SEGMENT CLONES (KNOWN) (groups=0)\n(none)",
        "SEGMENT CLONES (UNAVAILABLE) (groups=0)\n(none)",
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
        baseline_trust=_trusted_clone_lanes(),
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
    assert (
        "Note: unavailable baseline lanes produce UNAVAILABLE novelty, never NEW."
        in text_out
    )
    assert "FUNCTION CLONES (NEW) (groups=0)\n(none)" in text_out
    assert "FUNCTION CLONES (KNOWN) (groups=0)\n(none)" in text_out
    assert "FUNCTION CLONES (UNAVAILABLE) (groups=1)" in text_out


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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    filtered, low_value = prepare_segment_report_groups(group)
    assert filtered == {}
    assert low_value == 1


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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    filtered, low_value = prepare_segment_report_groups(group)
    assert filtered == {}
    assert low_value == 1


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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    assert _merge_segment_items([]) == []

    # _merge_segment_items skips invalid lines and still appends trailing current
    merged = _merge_segment_items(
        [
            {"start_line": 0, "end_line": 0},
            {"start_line": 2, "end_line": 3, "filepath": "x", "qualname": "q"},
        ]
    )
    assert len(merged) == 1

    # _assign_targets_attribute_only
    assign_attr = ast.parse("self.x = 1").body[0]
    assert _assign_targets_attribute_only(assign_attr)
    annassign_attr = ast.parse("self.y: int = 2").body[0]
    assert _assign_targets_attribute_only(annassign_attr)
    assign_name = ast.parse("x = 1").body[0]
    assert not _assign_targets_attribute_only(assign_name)
    expr_stmt = ast.parse("pass").body[0]
    assert not _assign_targets_attribute_only(expr_stmt)

    # _analyze_segment_statements empty
    assert _analyze_segment_statements([]) is None

    # _segment_statements handles non-list body and missing lineno
    class Dummy:
        body = None

    dummy = cast(ast.FunctionDef, cast(object, Dummy()))
    assert _segment_statements(dummy, 1, 2) == []

    func = ast.parse("def f():\n    x = 1\n").body[0]
    assert isinstance(func, ast.FunctionDef)
    stmt = func.body[0]
    delattr(stmt, "lineno")
    assert _segment_statements(func, 1, 2) == []


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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    filtered, low_value = prepare_segment_report_groups(group)
    assert low_value == 0
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
    funcs = _collect_file_functions(str(f))
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
    assert text_renderer_mod._as_int(True) == 1
    assert text_renderer_mod._as_int("42") == 42
    assert text_renderer_mod._as_int("bad") == 0
    assert text_renderer_mod._as_int(1.2) == 0

    text_report = to_text_report(
        meta={},
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={"health": {"score": 90}},
    )
    assert "METRICS SUMMARY" in text_report
    assert "health: score=90" in text_report


def test_every_dead_code_surface_reads_one_unreachable_count() -> None:
    """One field, four consumers, no surface counting for itself.

    The statement lane used to reach the findings while the family summary
    named only unreferenced symbols, so text, markdown and HTML each printed
    "0" beside ten published findings. Teaching three renderers to count the
    list themselves would have created three counters that drift; instead the
    count is published once and every surface reads that one field. This test
    asserts each surface shows the published number, so moving the field moves
    all of them together or fails here.
    """

    payload = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": "/root"},
        metrics={
            "dead_code": {
                "items": [],
                "unreachable_statements": [
                    {
                        "qualname": f"pkg.mod:looping{index}",
                        "filepath": "/root/pkg/mod.py",
                        "start_line": 10 + index,
                        "end_line": 11 + index,
                        "reason": "after_terminator",
                        "statement_count": 2,
                        "confidence": "high",
                    }
                    for index in range(3)
                ],
                "summary": {"unreachable_statements": 3},
            }
        },
    )

    published = _dict_at(
        payload,
        "metrics",
        "families",
        "dead_code",
        "summary",
    )["unreachable_statements"]
    assert published == 3

    text = render_text_report_document(payload)
    assert f"unreachable_statements={published}" in text

    markdown = render_markdown_report_document(payload)
    assert f"- unreachable_statements: {published}" in markdown

    html = build_html_report(report_document=payload)
    assert f"{published} unreachable statement" in html


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

    markdown = render_markdown_report_document(payload)
    assert '<a id="dead-code-suppressed"></a>' in markdown
    assert "suppression_rule=dead-code" in markdown


def _declared_families_document(
    metrics_computed: list[str] | None,
) -> dict[str, object]:
    """A populated-families document with an explicit declaration override.

    The builder normalizes every family into the payload, so the only thing
    the override changes is the declaration — exactly the axis these pins
    probe (RP2: absence must stay distinguishable from emptiness).
    """

    meta: dict[str, object] = {"scan_root": "/root"}
    if metrics_computed is not None:
        meta["metrics_computed"] = metrics_computed
    return build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta=meta,
    )


def test_text_declared_empty_families_speak_absence_not_zeros() -> None:
    """Declared-empty text renders one absence line and no family section."""

    text = render_text_report_document(_declared_families_document([]))

    assert METRICS_SKIPPED in text
    assert "health: score=0" not in text
    assert "dependencies: modules=0" not in text
    assert "OVERLOADED MODULES (top 10)" not in text
    assert "SECURITY SURFACES (top 10)" not in text
    assert "SUPPRESSED DEAD CODE (items=0)" not in text


def test_text_partial_declaration_prints_only_declared_families() -> None:
    """A non-empty declaration filters text sections strictly to its names."""

    text = render_text_report_document(_declared_families_document(["cohesion"]))

    assert METRICS_SKIPPED not in text
    assert "cohesion: total=0" in text
    assert "complexity: total=0" not in text
    assert "dependencies: modules=0" not in text
    assert "SUPPRESSED DEAD CODE (items=0)" not in text


def test_markdown_declared_empty_families_speak_absence_not_zeros() -> None:
    """Declared-empty markdown renders one absence line and no family section."""

    markdown = render_markdown_report_document(_declared_families_document([]))

    assert METRICS_SKIPPED in markdown
    assert "- score: 0" not in markdown
    assert "- cycles: 0" not in markdown
    assert "### Complexity" not in markdown
    assert "### Suppressed Dead Code" not in markdown


def test_markdown_partial_declaration_prints_only_declared_families() -> None:
    """A non-empty declaration filters markdown sections strictly to its names."""

    markdown = render_markdown_report_document(
        _declared_families_document(["cohesion"])
    )

    assert METRICS_SKIPPED not in markdown
    assert "### Cohesion" in markdown
    assert "### Complexity" not in markdown
    assert "### Dependencies" not in markdown
    assert "### Suppressed Dead Code" not in markdown


def test_text_and_markdown_report_include_suppressed_golden_fixture_clones() -> None:
    suppressed_group = SuppressedCloneGroup(
        kind="function",
        group_key="golden-group",
        items=(
            {
                "qualname": "tests.fixtures.golden.a:run",
                "filepath": "/root/tests/fixtures/golden_project/a.py",
                "start_line": 10,
                "end_line": 12,
                "loc": 3,
                "stmt_count": 2,
                "fingerprint": "fp-a",
                "loc_bucket": "0-19",
            },
            {
                "qualname": "tests.fixtures.golden.b:run",
                "filepath": "/root/tests/fixtures/golden_project/b.py",
                "start_line": 10,
                "end_line": 12,
                "loc": 3,
                "stmt_count": 2,
                "fingerprint": "fp-a",
                "loc_bucket": "0-19",
            },
        ),
        matched_patterns=("tests/fixtures/golden_*",),
        suppression_rule="golden_fixture",
        suppression_source="project_config",
    )

    text = to_text_report(
        meta={"codeclone_version": "1.4.0", "scan_root": "/root"},
        func_groups={},
        block_groups={},
        segment_groups={},
        suppressed_clone_groups=(suppressed_group,),
    )
    markdown = render_markdown_report_document(
        build_report_document(
            func_groups={},
            block_groups={},
            segment_groups={},
            meta={"codeclone_version": "1.4.0", "scan_root": "/root"},
            suppressed_clone_groups=(suppressed_group,),
        ),
    )

    assert_contains_all(
        text,
        "SUPPRESSED FUNCTION CLONES (groups=1)",
        "suppressed_by=golden_fixture@project_config",
        "tests/fixtures/golden_*",
    )
    assert_contains_all(
        markdown,
        "Suppressed Golden Fixture Clone Groups",
        "Suppression Rule: golden_fixture",
    )


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

    sarif = json.loads(render_sarif_report_document(payload))
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


def test_document_carries_opaque_dynamic_sites_as_their_own_section() -> None:
    document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        metrics={
            "dependencies": {
                "observations": [
                    {
                        "source": {
                            "file": {"path": "pkg/loader.py"},
                            "python_module": {
                                "module": "pkg.loader",
                                "package": "pkg",
                                "is_package": False,
                                "mount_path": "pkg/loader.py",
                                "origin": "analyzed",
                                "node_kind": "module",
                            },
                        },
                        "syntax_kind": "import",
                        "resolution": "unresolved_dynamic",
                        "resolved_target": None,
                    },
                    {
                        "source": {
                            "file": {"path": "pkg/module.py"},
                            "python_module": None,
                        },
                        "syntax_kind": "from_import",
                        "resolution": "analyzed",
                        "resolved_target": "pkg.loader",
                    },
                ],
            },
        },
    )

    dependencies = _dict_at(document, "metrics", "families", "dependencies")
    sites = dependencies["dynamic_boundaries"]
    assert isinstance(sites, list)

    # The section must be populated, not merely present: an always-empty key
    # would let every consumer stay green while reporting nothing.
    assert len(sites) == 1
    assert sites[0]["source"]["file"]["path"] == "pkg/loader.py"
    assert sites[0]["source"]["python_module"]["module"] == "pkg.loader"
    assert sites[0]["reason"] == "dynamic_load_argument_opaque"
    # Resolved edges are ordinary dependencies and never become boundaries.
    assert all(site["source"]["file"]["path"] != "pkg/module.py" for site in sites)


def test_json_renderer_emits_bytes_without_a_string_round_trip() -> None:
    """The JSON lane must never materialize the document as `str`.

    The JSON report is by far the largest artifact CodeClone emits. Decoding
    orjson's bytes to `str`, re-encoding them only to measure a length, and
    encoding again at write time held the same payload three extra times, all
    at the process high-water mark. The renderer therefore owns bytes and the
    pipeline carries them unchanged to disk.
    """

    payload: dict[str, object] = {
        "report_schema_version": "3.0",
        "meta": {"codeclone_version": "1.3.0"},
        "findings": {"groups": {}, "summary": {"total": 0}},
    }

    rendered = render_json_report_document(payload)

    assert isinstance(rendered, bytes)
    assert rendered == orjson.dumps(payload, option=orjson.OPT_INDENT_2)


def test_report_json_inventory_carries_unsupported_construct_witnesses() -> None:
    """The report attributes wire-refused skips: count plus per-file witness.

    Python 3.15 probe, G1b: «N files not analyzed: unsupported syntax X» must
    be readable from the report itself, naming the construct and the file,
    without diffing inventories.
    """

    payload = json.loads(
        to_json_report(
            {},
            {},
            {},
            {"codeclone_version": "1.4.0"},
            inventory={
                "files": {
                    "total_found": 2,
                    "analyzed": 1,
                    "cached": 0,
                    "skipped": 1,
                    "source_io_skipped": 0,
                    "unsupported_construct_skipped": 1,
                    "unsupported_constructs": [
                        {
                            "path": "pkg/module.py",
                            "construct": "unsupported fields on Import: is_lazy",
                        }
                    ],
                },
                "code": {
                    "functions": 0,
                    "methods": 0,
                    "classes": 0,
                    "parsed_lines": 12,
                },
            },
        )
    )

    files = payload["inventory"]["files"]
    assert files["skipped"] == 1
    assert files["unsupported_construct_skipped"] == 1
    assert files["unsupported_constructs"] == [
        {
            "path": "pkg/module.py",
            "construct": "unsupported fields on Import: is_lazy",
        }
    ]


def test_text_and_markdown_inventory_carry_the_unsupported_construct_count() -> None:
    inventory = {
        "files": {
            "total_found": 3,
            "analyzed": 2,
            "cached": 0,
            "skipped": 1,
            "source_io_skipped": 0,
            "unsupported_construct_skipped": 1,
            "unsupported_constructs": [
                {
                    "path": "pkg/module.py",
                    "construct": "unsupported fields on Import: is_lazy",
                }
            ],
        },
        "code": {"functions": 0, "methods": 0, "classes": 0, "parsed_lines": 9},
    }
    text_out = to_text_report(
        meta={"codeclone_version": "1.4.0"},
        inventory=inventory,
        func_groups={},
        block_groups={},
        segment_groups={},
    )
    assert "unsupported_construct_skipped=1" in text_out

    document = json.loads(
        to_json_report({}, {}, {}, {"codeclone_version": "1.4.0"}, inventory=inventory)
    )
    markdown_out = render_markdown_report_document(document)
    assert "unsupported_construct_skipped=1" in markdown_out


def test_report_reader_parses_the_stored_document_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One artifact, one parse.

    The reader scanned the raw bytes for duplicate keys with ``json.loads`` and
    then handed the same bytes to ``model_validate_json``, so every stored
    report was decoded twice and two full object graphs were alive at the
    process high-water mark. On the artifact this repository emits that is two
    parses of a document already measured at 3.08x the reader's own byte limit;
    the cost is paid by ``memory init`` and by every API caller.

    The duplicate-key scan already produces the mapping, so validating that
    mapping is the same contract for one decode instead of two. Counting the
    decodes is the honest pin: asserting only that the read still succeeds
    stays green with the second parse restored.
    """

    document = build_report_document(
        func_groups={},
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(tmp_path)},
    )
    report = tmp_path / "report.json"
    report.write_text(json.dumps(document), encoding="utf-8")

    decodes: list[str] = []
    real_loads = json.loads

    def counting_loads(*args: object, **kwargs: object) -> object:
        decodes.append("json.loads")
        return real_loads(*args, **kwargs)  # type: ignore[arg-type]

    def refuse_validate_json(*_args: object, **_kwargs: object) -> object:
        decodes.append("model_validate_json")
        raise AssertionError("the raw bytes must not be decoded a second time")

    monkeypatch.setattr("codeclone.report.document.reader.json.loads", counting_loads)
    monkeypatch.setattr(
        "codeclone.report.document.reader.ReportDocumentV3Input.model_validate_json",
        staticmethod(refuse_validate_json),
    )

    result = load_report_artifact(report)

    assert not isinstance(result, ReportArtifactFailure), getattr(
        result, "detail", result
    )
    assert decodes == ["json.loads"]
