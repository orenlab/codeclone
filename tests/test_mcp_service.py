# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import json
import subprocess
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeclone import mcp_service as mcp_service_mod
from codeclone._cli_config import ConfigValidationError
from codeclone.cache import Cache
from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.mcp_service import (
    CodeCloneMCPService,
    DetailLevel,
    MCPAnalysisRequest,
    MCPFindingNotFoundError,
    MCPGateRequest,
    MCPGitDiffError,
    MCPRunNotFoundError,
    MCPRunRecord,
    MCPServiceContractError,
    MCPServiceError,
)
from codeclone.models import MetricsDiff


def _write_clone_fixture(root: Path, relative_dir: str = "pkg") -> None:
    fixture_dir = root.joinpath(relative_dir)
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir.joinpath("__init__.py").write_text("", "utf-8")
    fixture_dir.joinpath("dup.py").write_text(
        (
            "def alpha(value: int) -> int:\n"
            "    total = value + 1\n"
            "    total += 2\n"
            "    total += 3\n"
            "    total += 4\n"
            "    total += 5\n"
            "    total += 6\n"
            "    total += 7\n"
            "    total += 8\n"
            "    return total\n\n"
            "def beta(value: int) -> int:\n"
            "    total = value + 1\n"
            "    total += 2\n"
            "    total += 3\n"
            "    total += 4\n"
            "    total += 5\n"
            "    total += 6\n"
            "    total += 7\n"
            "    total += 8\n"
            "    return total\n"
        ),
        "utf-8",
    )


def _write_quality_fixture(root: Path) -> None:
    pkg = root.joinpath("pkg")
    pkg.mkdir(exist_ok=True)
    pkg.joinpath("__init__.py").write_text("", "utf-8")
    pkg.joinpath("quality.py").write_text(
        (
            "class SplitByConcern:\n"
            "    def __init__(self) -> None:\n"
            "        self.alpha = 1\n"
            "        self.beta = 2\n"
            "        self.gamma = 3\n\n"
            "    def sync(self, flag: int) -> int:\n"
            "        total = 0\n"
            "        for item in range(flag):\n"
            "            if item % 2 == 0:\n"
            "                total += item\n"
            "            elif item % 3 == 0:\n"
            "                total -= item\n"
            "            elif item % 5 == 0:\n"
            "                total += item * 2\n"
            "            elif item % 7 == 0:\n"
            "                total -= item * 2\n"
            "            else:\n"
            "                total += 1\n"
            "        if total > 20:\n"
            "            return total\n"
            "        if total < -20:\n"
            "            return -total\n"
            "        return total + self.alpha\n\n"
            "    def render(self) -> str:\n"
            "        return f'{self.beta}:{self.gamma}'\n\n"
            "def unused_helper() -> int:\n"
            "    return 42\n"
        ),
        "utf-8",
    )


def _write_clone_variant_fixture(
    root: Path,
    *,
    relative_dir: str,
    module_name: str,
    seed: int,
) -> None:
    fixture_dir = root.joinpath(relative_dir)
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir.joinpath("__init__.py").write_text("", "utf-8")
    fixture_dir.joinpath(module_name).write_text(
        (
            "def gamma(value: int) -> int:\n"
            f"    total = value * {seed}\n"
            f"    total -= {seed + 1}\n"
            f"    total *= {seed + 2}\n"
            f"    total -= {seed + 3}\n"
            f"    total *= {seed + 4}\n"
            f"    total -= {seed + 5}\n"
            f"    total *= {seed + 6}\n"
            f"    total -= {seed + 7}\n"
            "    return total\n\n"
            "def delta(value: int) -> int:\n"
            f"    total = value * {seed}\n"
            f"    total -= {seed + 1}\n"
            f"    total *= {seed + 2}\n"
            f"    total -= {seed + 3}\n"
            f"    total *= {seed + 4}\n"
            f"    total -= {seed + 5}\n"
            f"    total *= {seed + 6}\n"
            f"    total -= {seed + 7}\n"
            "    return total\n"
        ),
        "utf-8",
    )


def _dummy_run_record(root: Path, run_id: str) -> MCPRunRecord:
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        comparison_settings=(),
        report_document={},
        summary={"run_id": run_id, "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )


def _two_clone_fixture_roots(tmp_path: Path) -> tuple[Path, Path]:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    _write_clone_fixture(first_root)
    _write_clone_fixture(second_root)
    return first_root, second_root


def _assert_comparable_comparison(
    comparison: dict[str, object],
    *,
    verdict: str,
) -> None:
    assert comparison["verdict"] == verdict
    assert comparison["comparable"] is True
    assert "reason" not in comparison
    assert "run health delta" in str(comparison["summary"])


def _assert_incomparable_comparison(
    comparison: dict[str, object],
    *,
    reason: str,
) -> None:
    assert comparison["comparable"] is False
    assert comparison["reason"] == reason
    assert comparison["health_delta"] is None
    assert comparison["verdict"] == "incomparable"
    assert comparison["regressions"] == []
    assert comparison["improvements"] == []
    assert comparison["unchanged"] is None


def _build_quality_service(root: Path) -> CodeCloneMCPService:
    _write_clone_fixture(root)
    _write_quality_fixture(root)
    service = CodeCloneMCPService(history_limit=4)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    return service


def _analyze_quality_repository(
    root: Path,
) -> tuple[CodeCloneMCPService, dict[str, object]]:
    _write_clone_fixture(root)
    _write_quality_fixture(root)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    return service, summary


def _file_registry(payload: dict[str, object]) -> dict[str, object]:
    inventory = cast("dict[str, object]", payload["inventory"])
    return cast("dict[str, object]", inventory["file_registry"])


def _mapping_child(
    payload: dict[str, object] | Mapping[str, object],
    key: str,
) -> dict[str, object]:
    return cast("dict[str, object]", payload[key])


def test_mcp_service_analyze_repository_registers_latest_run(tmp_path: Path) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)

    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    latest = service.get_run_summary()
    assert summary["run_id"] == latest["run_id"]
    assert len(str(summary["run_id"])) == 8
    assert summary["mode"] == "full"
    assert summary["schema"] == REPORT_SCHEMA_VERSION


def test_mcp_service_help_returns_bounded_semantic_guidance() -> None:
    service = CodeCloneMCPService(history_limit=4)

    compact = service.get_help(topic="workflow")
    normal = service.get_help(topic="workflow", detail="normal")

    assert compact == {
        "topic": "workflow",
        "detail": "compact",
        "summary": (
            "CodeClone MCP is triage-first and budget-aware. Start with compact "
            "summary or production triage, then narrow through hotspots or "
            "focused checks before opening one finding in detail."
        ),
        "key_points": [
            "Recommended first pass: analyze_repository or analyze_changed_paths.",
            (
                "Use get_run_summary or get_production_triage before broad "
                "finding enumeration."
            ),
            (
                "Prefer list_hotspots or focused check_* tools over "
                "list_findings on medium or noisy repositories."
            ),
            (
                "Use get_finding and get_remediation only after selecting a "
                "specific issue."
            ),
            (
                "get_report_section(section='all') is an exception path, not "
                "a default exploration step."
            ),
        ],
        "recommended_tools": [
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "get_production_triage",
            "list_hotspots",
            "check_clones",
            "check_dead_code",
            "get_finding",
            "get_remediation",
        ],
        "doc_links": [
            {
                "title": "MCP interface contract",
                "url": "https://orenlab.github.io/codeclone/book/20-mcp-interface/",
            },
            {
                "title": "MCP usage guide",
                "url": "https://orenlab.github.io/codeclone/mcp/",
            },
        ],
    }
    assert normal["topic"] == "workflow"
    assert normal["detail"] == "normal"
    assert normal["summary"] == compact["summary"]
    assert normal["recommended_tools"] == compact["recommended_tools"]
    assert normal["doc_links"] == compact["doc_links"]
    assert cast("list[str]", normal["warnings"]) == [
        (
            "Broad list_findings calls can burn context quickly on large or "
            "noisy repositories."
        ),
        (
            "Prefer generate_pr_summary(format='markdown') unless machine JSON "
            "is explicitly needed."
        ),
    ]
    assert cast("list[str]", normal["anti_patterns"]) == [
        "Starting exploration with list_findings on a noisy repository.",
        "Using get_report_section(section='all') as the default first step.",
        (
            "Escalating detail on larger lists instead of opening one finding "
            "with get_finding."
        ),
    ]


def test_mcp_service_help_validates_topic_and_detail() -> None:
    service = CodeCloneMCPService(history_limit=4)

    with pytest.raises(MCPServiceContractError, match="Invalid value for topic"):
        service.get_help(topic="gates")  # type: ignore[arg-type]

    with pytest.raises(MCPServiceContractError, match="Invalid value for detail"):
        service.get_help(topic="baseline", detail="full")  # type: ignore[arg-type]


def test_mcp_service_summary_inventory_is_compact_and_report_inventory_stays_canonical(
    tmp_path: Path,
) -> None:
    service, repository_summary = _analyze_quality_repository(tmp_path)
    changed_summary = service.analyze_changed_paths(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            changed_paths=("pkg/dup.py",),
        )
    )
    stored_summary = service.get_run_summary(run_id=str(repository_summary["run_id"]))
    report_inventory = service.get_report_section(
        run_id=str(repository_summary["run_id"]),
        section="inventory",
    )

    assert cast("dict[str, object]", repository_summary["inventory"]) == cast(
        "dict[str, object]",
        stored_summary["inventory"],
    )
    assert set(cast("dict[str, object]", repository_summary["inventory"])) == {
        "files",
        "lines",
        "functions",
        "classes",
    }
    assert "inventory" not in changed_summary
    assert cast(int, changed_summary["changed_files"]) == 1
    assert isinstance(
        cast("dict[str, object]", report_inventory["file_registry"])["items"],
        list,
    )


def test_mcp_service_lists_findings_and_hotspots(tmp_path: Path) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    findings = service.list_findings(family="clone")
    assert findings["run_id"] == summary["run_id"]
    findings_total = cast(int, findings["total"])
    assert findings_total >= 1
    first = cast("list[dict[str, object]]", findings["items"])[0]
    assert str(first["id"]).startswith("fn:")
    assert first["kind"] == "function_clone"

    finding = service.get_finding(finding_id=str(first["id"]))
    assert finding["id"] == first["id"]
    assert "remediation" in finding

    hotspots = service.list_hotspots(kind="highest_spread")
    assert hotspots["run_id"] == summary["run_id"]
    assert cast(int, hotspots["total"]) >= 1


def test_mcp_service_hotspot_resources_and_triage_are_production_first(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    _write_clone_variant_fixture(
        tmp_path,
        relative_dir="tests",
        module_name="test_dup.py",
        seed=20,
    )
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    production_hotspots = service.list_hotspots(
        kind="production_hotspots",
        detail_level="summary",
    )
    test_fixture_hotspots = service.list_hotspots(
        kind="test_fixture_hotspots",
        detail_level="summary",
    )
    triage = service.get_production_triage(max_hotspots=2, max_suggestions=2)
    latest_triage = json.loads(service.read_resource("codeclone://latest/triage"))

    assert production_hotspots["run_id"] == summary["run_id"]
    assert cast(int, production_hotspots["total"]) >= 1
    assert cast(int, test_fixture_hotspots["total"]) >= 1

    triage_findings = _mapping_child(triage, "findings")
    triage_suggestions = _mapping_child(triage, "suggestions")
    findings_breakdown = cast("dict[str, int]", triage_findings["by_source_kind"])
    suggestions_breakdown = cast(
        "dict[str, int]",
        triage_suggestions["by_source_kind"],
    )
    top_hotspots = _mapping_child(triage, "top_hotspots")
    top_suggestions = _mapping_child(triage, "top_suggestions")
    production_items = cast("list[dict[str, object]]", production_hotspots["items"])

    assert triage["run_id"] == summary["run_id"]
    assert _mapping_child(triage, "cache")["freshness"] == "fresh"
    assert findings_breakdown["production"] >= 1
    assert findings_breakdown["tests"] >= 1
    assert cast(int, triage_findings["outside_focus"]) >= 1
    assert suggestions_breakdown["production"] >= 1
    assert suggestions_breakdown["tests"] >= 1
    assert cast(int, triage_suggestions["outside_focus"]) >= 1
    assert top_hotspots["kind"] == "production_hotspots"
    assert top_hotspots["available"] == production_hotspots["total"]
    assert cast(int, top_hotspots["returned"]) >= 1
    assert all(
        str(item["id"]) in {str(row["id"]) for row in production_items}
        for item in cast("list[dict[str, object]]", top_hotspots["items"])
    )
    assert cast(int, top_suggestions["available"]) >= 1
    assert all(
        str(item["source_kind"]) == "production"
        for item in cast("list[dict[str, object]]", top_suggestions["items"])
    )
    assert latest_triage["run_id"] == summary["run_id"]
    with pytest.raises(
        MCPServiceContractError,
        match="only as codeclone://latest/triage",
    ):
        service.read_resource(f"codeclone://runs/{summary['run_id']}/triage")


def test_mcp_service_changed_runs_remediation_and_review_flow(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    pkg.joinpath("__init__.py").write_text("", "utf-8")
    pkg.joinpath("base.py").write_text(
        "def baseline_only(value: int) -> int:\n    return value + 1\n",
        "utf-8",
    )
    service = CodeCloneMCPService(history_limit=4)

    before = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    _write_clone_fixture(tmp_path)
    after = service.analyze_changed_paths(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            changed_paths=("pkg/dup.py",),
        )
    )

    changed = service.get_report_section(
        run_id=str(after["run_id"]),
        section="changed",
    )
    assert changed["run_id"] == after["run_id"]
    assert changed["changed_paths"] == ["pkg/dup.py"]
    assert cast(int, changed["total"]) >= 1

    comparison = service.compare_runs(
        run_id_before=str(before["run_id"]),
        run_id_after=str(after["run_id"]),
        focus="clones",
    )
    _assert_comparable_comparison(comparison, verdict="regressed")
    assert cast("list[dict[str, object]]", comparison["regressions"])

    findings = service.list_findings(
        family="clone",
        detail_level="summary",
        changed_paths=("pkg/dup.py",),
        sort_by="priority",
    )
    assert findings["changed_paths"] == ["pkg/dup.py"]
    clone_items = cast("list[dict[str, object]]", findings["items"])
    first_id = str(clone_items[0]["id"])

    remediation = service.get_remediation(
        finding_id=first_id,
        detail_level="summary",
    )
    remediation_payload = cast("dict[str, object]", remediation["remediation"])
    assert remediation["finding_id"] == first_id
    assert remediation_payload["shape"]
    assert remediation_payload["why_now"]

    reviewed = service.mark_finding_reviewed(
        finding_id=first_id,
        note="handled in current session",
    )
    assert reviewed["reviewed"] is True

    reviewed_items = service.list_reviewed_findings(run_id=str(after["run_id"]))
    assert reviewed_items["reviewed_count"] == 1

    unreviewed = service.list_findings(
        run_id=str(after["run_id"]),
        family="clone",
        exclude_reviewed=True,
        detail_level="summary",
    )
    assert cast(int, unreviewed["total"]) < cast(int, findings["total"])


def test_mcp_service_granular_checks_pr_summary_and_resources(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    _write_quality_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)

    summary = service.analyze_changed_paths(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            changed_paths=("pkg/dup.py", "pkg/quality.py"),
            complexity_threshold=1,
        )
    )
    run_id = str(summary["run_id"])
    report_document = service.get_report_section(run_id=run_id, section="all")
    design_thresholds = cast(
        "dict[str, dict[str, object]]",
        cast(
            "dict[str, object]",
            cast("dict[str, object]", report_document["meta"])["analysis_thresholds"],
        )["design_findings"],
    )
    assert design_thresholds == {
        "complexity": {
            "metric": "cyclomatic_complexity",
            "operator": ">",
            "value": 1,
        },
        "coupling": {
            "metric": "cbo",
            "operator": ">",
            "value": 10,
        },
        "cohesion": {
            "metric": "lcom4",
            "operator": ">=",
            "value": 4,
        },
    }
    finding_groups = cast(
        "dict[str, object]",
        cast("dict[str, object]", report_document["findings"])["groups"],
    )
    design_groups = cast(
        "list[dict[str, object]]",
        cast("dict[str, object]", finding_groups["design"])["groups"],
    )
    record = service._runs.get(run_id)
    canonical_design_ids = {
        service._short_finding_id(record, str(group["id"])) for group in design_groups
    }
    listed_design_ids = {
        str(item["id"])
        for item in cast(
            "list[dict[str, object]]",
            service.list_findings(
                run_id=run_id,
                family="design",
                detail_level="summary",
            )["items"],
        )
    }
    assert listed_design_ids == canonical_design_ids

    clones = service.check_clones(
        run_id=run_id,
        path="pkg/dup.py",
        detail_level="summary",
    )
    summary_health = cast(
        "dict[str, object]",
        service.get_run_summary(run_id=run_id)["health"],
    )
    summary_dimensions = cast("dict[str, object]", summary_health["dimensions"])
    assert clones["check"] == "clones"
    assert cast(int, clones["total"]) >= 1

    complexity = service.check_complexity(
        run_id=run_id,
        path="pkg/quality.py",
        min_complexity=1,
        detail_level="summary",
    )
    assert complexity["check"] == "complexity"
    assert "items" in complexity

    dead_code = service.check_dead_code(
        run_id=run_id,
        path="pkg/quality.py",
        detail_level="summary",
    )
    assert dead_code["check"] == "dead_code"

    coupling = service.check_coupling(run_id=run_id, detail_level="summary")
    cohesion = service.check_cohesion(run_id=run_id, detail_level="summary")
    assert coupling["check"] == "coupling"
    assert cohesion["check"] == "cohesion"
    for dimension, payload in (
        ("clones", clones),
        ("complexity", complexity),
        ("dead_code", dead_code),
        ("coupling", coupling),
        ("cohesion", cohesion),
    ):
        check_health = cast("dict[str, object]", payload["health"])
        assert check_health["score"] == summary_health["score"]
        assert check_health["grade"] == summary_health["grade"]
        assert cast("dict[str, object]", check_health["dimensions"]) == {
            dimension: summary_dimensions[dimension]
        }

    gate_result = service.evaluate_gates(
        MCPGateRequest(run_id=run_id, fail_threshold=0)
    )
    latest_gates = json.loads(service.read_resource("codeclone://latest/gates"))
    latest_health = json.loads(service.read_resource("codeclone://latest/health"))
    latest_changed = json.loads(service.read_resource("codeclone://latest/changed"))
    schema = json.loads(service.read_resource("codeclone://schema"))

    assert latest_gates["run_id"] == gate_result["run_id"]
    summary_health = cast("dict[str, object]", summary["health"])
    assert latest_health["score"] == summary_health["score"]
    assert latest_changed["run_id"] == run_id
    assert schema["title"] == "CodeCloneCanonicalReport"
    schema_properties = cast("dict[str, object]", schema["properties"])
    assert "report_schema_version" in schema_properties

    markdown_summary = service.generate_pr_summary(
        run_id=run_id,
        changed_paths=("pkg/dup.py",),
        format="markdown",
    )
    json_summary = service.generate_pr_summary(
        run_id=run_id,
        changed_paths=("pkg/dup.py",),
        format="json",
    )
    assert markdown_summary["format"] == "markdown"
    assert "## CodeClone Summary" in str(markdown_summary["content"])
    assert json_summary["run_id"] == run_id
    assert json_summary["changed_files"] == 1


def test_mcp_service_granular_checks_require_existing_run_by_default(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)

    with pytest.raises(
        MCPRunNotFoundError, match="analyze_repository\\(root='/path/to/repo'\\)"
    ):
        service.check_clones(detail_level="summary")

    with pytest.raises(
        MCPRunNotFoundError,
        match=f"analyze_repository\\(root='{tmp_path}'\\)",
    ):
        service.check_dead_code(root=str(tmp_path), detail_level="summary")


def test_mcp_service_granular_checks_reject_incompatible_run_modes(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            analysis_mode="clones_only",
        )
    )

    with pytest.raises(MCPServiceContractError, match="not compatible"):
        service.check_dead_code(
            run_id=str(summary["run_id"]),
            detail_level="summary",
        )


def test_mcp_service_clones_only_health_is_marked_unavailable(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            analysis_mode="clones_only",
        )
    )

    stored_summary = service.get_run_summary(run_id=str(summary["run_id"]))
    triage = service.get_production_triage(run_id=str(summary["run_id"]))
    latest_health = json.loads(service.read_resource("codeclone://latest/health"))
    expected = {"available": False, "reason": "metrics_skipped"}

    assert summary["health"] == expected
    assert stored_summary["health"] == expected
    assert triage["health"] == expected
    assert latest_health == expected


def test_mcp_service_summary_reuses_canonical_meta_for_cache_and_health(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)

    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="reuse",
        )
    )

    report_meta = service.get_report_section(
        run_id=str(summary["run_id"]),
        section="meta",
    )
    report_metrics = service.get_report_section(
        run_id=str(summary["run_id"]),
        section="metrics",
    )
    cache_summary = _mapping_child(summary, "cache")
    cache_meta = _mapping_child(report_meta, "cache")
    health_summary = _mapping_child(summary, "health")
    metrics_summary = _mapping_child(report_metrics, "summary")
    metrics_health = _mapping_child(metrics_summary, "health")

    assert cache_summary["used"] == cache_meta["used"]
    assert cache_summary["freshness"] in {"fresh", "mixed", "reused"}
    assert health_summary == metrics_health
    assert "families" not in report_metrics


def test_mcp_service_effective_freshness_classifies_summary_cache_usage() -> None:
    service = CodeCloneMCPService(history_limit=4)

    assert (
        service._effective_freshness(
            {
                "cache": {"used": False},
                "inventory": {"files": {"analyzed": 2, "cached": 0}},
            }
        )
        == "fresh"
    )
    assert (
        service._effective_freshness(
            {
                "cache": {"used": True},
                "inventory": {"files": {"analyzed": 0, "cached": 2}},
            }
        )
        == "reused"
    )
    assert (
        service._effective_freshness(
            {
                "cache": {"used": True},
                "inventory": {"files": {"analyzed": 1, "cached": 2}},
            }
        )
        == "mixed"
    )


def test_mcp_service_metrics_sections_split_summary_and_detail(
    tmp_path: Path,
) -> None:
    service, summary = _analyze_quality_repository(tmp_path)
    run_id = str(summary["run_id"])

    metrics_summary = service.get_report_section(run_id=run_id, section="metrics")
    metrics_detail = service.get_report_section(
        run_id=run_id,
        section="metrics_detail",
    )
    metrics_detail_page = service.get_report_section(
        run_id=run_id,
        section="metrics_detail",
        family="complexity",
        limit=5,
    )

    assert set(cast("dict[str, object]", metrics_summary["summary"])) >= {
        "complexity",
        "coupling",
        "cohesion",
        "dependencies",
        "dead_code",
        "overloaded_modules",
        "health",
    }
    assert "families" not in metrics_summary
    assert len(json.dumps(metrics_summary, ensure_ascii=False, sort_keys=True)) < 5000
    assert set(metrics_detail) == {"summary", "_hint"}
    assert "family" in metrics_detail_page
    assert cast("list[dict[str, object]]", metrics_detail_page["items"])
    overloaded_modules_page = service.get_report_section(
        run_id=run_id,
        section="metrics_detail",
        family="overloaded_modules",
        limit=5,
    )
    assert overloaded_modules_page["family"] == "overloaded_modules"
    overloaded_modules_items = cast(
        "list[dict[str, object]]", overloaded_modules_page["items"]
    )
    assert overloaded_modules_items
    overloaded_modules_alias_page = service.get_report_section(
        run_id=run_id,
        section="metrics_detail",
        family="god_modules",
        limit=5,
    )
    assert overloaded_modules_alias_page["family"] == "overloaded_modules"
    assert (
        cast("list[dict[str, object]]", overloaded_modules_alias_page["items"])
        == overloaded_modules_items
    )
    report_record = service._runs.get(run_id)
    assert report_record is not None
    report_document = report_record.report_document
    metrics_map = cast("dict[str, object]", report_document["metrics"])
    families_map = cast("dict[str, object]", metrics_map["families"])
    overloaded_modules_family = cast(
        "dict[str, object]", families_map["overloaded_modules"]
    )
    overloaded_modules_report_items = cast(
        "list[dict[str, object]]",
        overloaded_modules_family["items"],
    )
    assert (
        overloaded_modules_items[0]["path"]
        == overloaded_modules_report_items[0]["relative_path"]
    )


def test_mcp_service_evaluate_gates_on_existing_run(tmp_path: Path) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    gate_result = service.evaluate_gates(
        MCPGateRequest(run_id=str(summary["run_id"]), fail_threshold=0)
    )

    assert gate_result["run_id"] == summary["run_id"]
    assert gate_result["would_fail"] is True
    assert gate_result["exit_code"] == 3
    assert gate_result["reasons"] == ["clone:threshold:1:0"]


def test_mcp_service_resources_expose_latest_summary_and_report(tmp_path: Path) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    latest_summary = json.loads(service.read_resource("codeclone://latest/summary"))
    latest_report = json.loads(service.read_resource("codeclone://latest/report.json"))

    assert latest_summary["run_id"] == summary["run_id"]
    assert latest_summary["cache"]["freshness"] == "fresh"
    assert set(cast("dict[str, object]", latest_summary["inventory"])) == {
        "files",
        "lines",
        "functions",
        "classes",
    }
    assert latest_report["report_schema_version"] == REPORT_SCHEMA_VERSION


def test_mcp_service_hotspot_summary_preserves_fixtures_source_kind(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path, relative_dir="tests/fixtures")
    service = CodeCloneMCPService(history_limit=4)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    findings = service.list_findings(
        family="clone",
        detail_level="summary",
        limit=1,
    )
    hotspots = service.list_hotspots(
        kind="highest_spread",
        detail_level="summary",
        limit=1,
    )

    finding = cast("list[dict[str, object]]", findings["items"])[0]
    hotspot = cast("list[dict[str, object]]", hotspots["items"])[0]
    assert finding["id"] == hotspot["id"]
    assert finding["scope"] == "fixtures"
    assert hotspot["scope"] == finding["scope"]
    assert cast("list[str]", hotspot["locations"])


def test_mcp_service_list_findings_detail_levels_slim_and_full_payloads(
    tmp_path: Path,
) -> None:
    service, summary = _analyze_quality_repository(tmp_path)
    run_id = str(summary["run_id"])

    summary_payload = service.list_findings(
        run_id=run_id,
        family="clone",
        detail_level="summary",
        limit=1,
    )
    normal_payload = service.list_findings(
        run_id=run_id,
        family="clone",
        detail_level="normal",
        limit=1,
    )
    full_payload = service.list_findings(
        run_id=run_id,
        family="clone",
        detail_level="full",
        limit=1,
    )

    summary_item = cast("list[dict[str, object]]", summary_payload["items"])[0]
    normal_item = cast("list[dict[str, object]]", normal_payload["items"])[0]
    full_item = cast("list[dict[str, object]]", full_payload["items"])[0]

    assert "priority" in summary_item
    assert "priority" in normal_item
    assert cast("dict[str, object]", full_item["priority_factors"])
    assert all(
        isinstance(location, str)
        for location in cast("list[object]", summary_item["locations"])
    )
    assert all(
        "symbol" in cast("dict[str, object]", location)
        and "path" in cast("dict[str, object]", location)
        and "uri" not in cast("dict[str, object]", location)
        for location in cast("list[object]", normal_item["locations"])
    )
    assert all(
        "symbol" in cast("dict[str, object]", location)
        and "uri" in cast("dict[str, object]", location)
        for location in cast("list[object]", full_item["locations"])
    )

    finding = service.get_finding(
        run_id=run_id,
        finding_id=str(summary_item["id"]),
        detail_level="full",
    )
    assert cast("dict[str, object]", finding["priority_factors"])
    assert all(
        "symbol" in cast("dict[str, object]", location)
        and "uri" in cast("dict[str, object]", location)
        for location in cast("list[object]", finding["locations"])
    )


def test_mcp_service_run_store_evicts_old_runs(tmp_path: Path) -> None:
    first_root, second_root = _two_clone_fixture_roots(tmp_path)
    service = CodeCloneMCPService(history_limit=1)

    first = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(first_root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    second = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(second_root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    assert service.get_run_summary()["run_id"] == second["run_id"]
    with pytest.raises(MCPRunNotFoundError):
        service.get_run_summary(str(first["run_id"]))


def test_mcp_service_reports_contract_errors_for_resources_and_findings(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    run_id = str(summary["run_id"])

    overview = json.loads(service.read_resource("codeclone://latest/overview"))
    assert overview["run_id"] == run_id

    with pytest.raises(MCPServiceContractError):
        service.get_report_section(section=cast("object", "unknown"))  # type: ignore[arg-type]
    with pytest.raises(MCPFindingNotFoundError):
        service.get_finding(run_id=run_id, finding_id="missing")
    with pytest.raises(MCPServiceContractError):
        service.read_resource("bad://resource")
    with pytest.raises(MCPServiceContractError):
        service.read_resource(f"codeclone://runs/{run_id}")
    with pytest.raises(MCPServiceContractError):
        service.read_resource(f"codeclone://runs/{run_id}/unsupported")


def test_mcp_service_build_args_handles_pyproject_and_invalid_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4)

    monkeypatch.setattr(
        mcp_service_mod,
        "load_pyproject_config",
        lambda _root: {
            "min_loc": 12,
            "baseline": "conf-baseline.json",
            "cache_path": "conf-cache.json",
        },
    )
    args = service._build_args(
        root_path=tmp_path,
        request=MCPAnalysisRequest(
            respect_pyproject=True,
            analysis_mode="clones_only",
            metrics_baseline_path="metrics.json",
        ),
    )
    assert args.min_loc == 12
    assert args.processes is None
    assert args.skip_metrics is True
    assert args.skip_dead_code is True
    assert args.skip_dependencies is True
    assert str(args.baseline).endswith("conf-baseline.json")
    assert str(args.cache_path).endswith("conf-cache.json")
    assert str(args.metrics_baseline).endswith("metrics.json")

    monkeypatch.setattr(
        mcp_service_mod,
        "load_pyproject_config",
        lambda _root: (_ for _ in ()).throw(ConfigValidationError("bad config")),
    )
    with pytest.raises(MCPServiceContractError):
        service._build_args(
            root_path=tmp_path,
            request=MCPAnalysisRequest(respect_pyproject=True),
        )

    with pytest.raises(MCPServiceContractError):
        service._build_args(
            root_path=tmp_path,
            request=MCPAnalysisRequest(
                respect_pyproject=False,
                max_cache_size_mb=-1,
            ),
        )


def test_mcp_service_root_and_helper_contract_errors(
    tmp_path: Path,
) -> None:
    service = CodeCloneMCPService(history_limit=4)
    missing_root = tmp_path / "missing"
    file_root = tmp_path / "root.py"
    file_root.write_text("print('x')\n", "utf-8")

    with pytest.raises(MCPServiceContractError):
        service.analyze_repository(
            MCPAnalysisRequest(
                root=str(missing_root),
                respect_pyproject=False,
            )
        )
    with pytest.raises(MCPServiceContractError):
        service.analyze_repository(
            MCPAnalysisRequest(
                root=str(file_root),
                respect_pyproject=False,
            )
        )
    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        service.analyze_repository(
            MCPAnalysisRequest(
                root=".",
                respect_pyproject=False,
            )
        )
    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        service.analyze_changed_paths(
            MCPAnalysisRequest(
                root=".",
                respect_pyproject=False,
                changed_paths=("pkg/dup.py",),
            )
        )

    with pytest.raises(MCPServiceError):
        service._load_report_document("{")
    with pytest.raises(MCPServiceError):
        service._load_report_document("[]")
    with pytest.raises(MCPServiceError):
        service._report_digest({})


def test_mcp_service_helper_filters_and_metrics_payload() -> None:
    service = CodeCloneMCPService(history_limit=4)

    payload = service._metrics_diff_payload(
        MetricsDiff(
            new_high_risk_functions=("pkg.a:f",),
            new_high_coupling_classes=("pkg.a:C",),
            new_cycles=(("pkg.a", "pkg.b"),),
            new_dead_code=("pkg.a:unused",),
            health_delta=-3,
        )
    )
    assert payload == {
        "new_high_risk_functions": 1,
        "new_high_coupling_classes": 1,
        "new_cycles": 1,
        "new_dead_code": 1,
        "health_delta": -3,
    }
    assert service._metrics_diff_payload(None) is None

    finding = {
        "family": "clone",
        "severity": "high",
        "novelty": "new",
        "source_scope": {"dominant_kind": "production"},
    }
    assert (
        service._matches_finding_filters(
            finding=finding,
            family="all",
            severity="medium",
            source_kind=None,
            novelty="all",
        )
        is False
    )
    assert (
        service._matches_finding_filters(
            finding=finding,
            family="all",
            severity=None,
            source_kind="tests",
            novelty="all",
        )
        is False
    )
    assert (
        service._matches_finding_filters(
            finding=finding,
            family="all",
            severity=None,
            source_kind=None,
            novelty="known",
        )
        is False
    )
    assert service._as_sequence("not-a-sequence") == ()


def test_mcp_service_git_diff_and_helper_branch_edges(
    tmp_path: Path,
) -> None:
    service = CodeCloneMCPService(history_limit=4)

    with pytest.raises(MCPGitDiffError, match="must not start with '-'"):
        mcp_service_mod._git_diff_lines_payload(
            root_path=tmp_path,
            git_diff_ref="--cached",
        )

    assert service._normalize_relative_path("./.github/workflows/docs.yml") == (
        ".github/workflows/docs.yml"
    )

    full_record = _dummy_run_record(tmp_path, "full")
    object.__setattr__(
        full_record,
        "request",
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            analysis_mode="full",
        ),
    )
    clones_only_record = _dummy_run_record(tmp_path, "clones")
    object.__setattr__(
        clones_only_record,
        "request",
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            analysis_mode="clones_only",
        ),
    )
    other_root_record = _dummy_run_record(tmp_path / "other", "other")
    object.__setattr__(
        other_root_record,
        "request",
        MCPAnalysisRequest(
            root=str(tmp_path / "other"),
            respect_pyproject=False,
            analysis_mode="full",
        ),
    )
    service._runs.register(clones_only_record)
    service._runs.register(other_root_record)
    service._runs.register(full_record)

    assert (
        service._latest_compatible_record(
            analysis_mode="clones_only",
            root_path=tmp_path,
        )
        is full_record
    )
    assert (
        service._latest_compatible_record(
            analysis_mode="full",
            root_path=tmp_path,
        )
        is full_record
    )
    assert (
        service._latest_compatible_record(
            analysis_mode="full",
            root_path=tmp_path / "other",
        )
        is other_root_record
    )

    service_full_fallback = CodeCloneMCPService(history_limit=4)
    service_full_fallback._runs.register(clones_only_record)
    service_full_fallback._runs.register(full_record)
    service_full_fallback._runs.register(
        _dummy_run_record(tmp_path, "latest-clones-only")
    )
    object.__setattr__(
        service_full_fallback._runs.get("latest-clones-only"),
        "request",
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            analysis_mode="clones_only",
        ),
    )
    assert (
        service_full_fallback._latest_compatible_record(
            analysis_mode="full",
            root_path=tmp_path,
        )
        is full_record
    )


def test_mcp_service_rejects_refresh_cache_policy_in_read_only_mode(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)

    with pytest.raises(MCPServiceContractError, match="read-only"):
        service.analyze_repository(
            MCPAnalysisRequest(
                root=str(tmp_path),
                respect_pyproject=False,
                cache_policy="refresh",
            )
        )


def test_mcp_service_all_section_and_optional_path_overrides(tmp_path: Path) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    report_document = service.get_report_section(section="all")
    assert report_document["report_schema_version"] == REPORT_SCHEMA_VERSION

    args = service._build_args(
        root_path=tmp_path,
        request=MCPAnalysisRequest(
            respect_pyproject=False,
            baseline_path="custom-baseline.json",
            metrics_baseline_path="metrics-only.json",
            cache_path="custom-cache.json",
        ),
    )
    assert str(args.baseline).endswith("custom-baseline.json")
    assert str(args.metrics_baseline).endswith("metrics-only.json")
    assert str(args.cache_path).endswith("custom-cache.json")

    _, _, metrics_baseline_path, metrics_baseline_exists, shared_payload = (
        service._resolve_baseline_inputs(root_path=tmp_path, args=args)
    )
    assert str(metrics_baseline_path).endswith("metrics-only.json")
    assert metrics_baseline_exists is False
    assert shared_payload is None


def test_mcp_service_root_cache_and_projection_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4)
    args = service._build_args(
        root_path=tmp_path,
        request=MCPAnalysisRequest(respect_pyproject=False),
    )
    load_calls: list[str] = []

    def _fake_load(self: Cache) -> None:
        load_calls.append("loaded")

    monkeypatch.setattr(Cache, "load", _fake_load)
    service._build_cache(
        root_path=tmp_path,
        args=args,
        cache_path=tmp_path / "cache.json",
        policy="reuse",
    )
    assert load_calls == ["loaded"]


def test_mcp_service_build_args_defers_process_count_to_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4)

    monkeypatch.setattr(
        mcp_service_mod,
        "load_pyproject_config",
        lambda _root: {"processes": 3},
    )
    args = service._build_args(
        root_path=tmp_path,
        request=MCPAnalysisRequest(respect_pyproject=False),
    )
    assert args.processes is None

    args_from_config = service._build_args(
        root_path=tmp_path,
        request=MCPAnalysisRequest(respect_pyproject=True),
    )
    assert args_from_config.processes == 3

    args_from_request = service._build_args(
        root_path=tmp_path,
        request=MCPAnalysisRequest(respect_pyproject=False, processes=2),
    )
    assert args_from_request.processes == 2


def test_mcp_service_invalid_path_resolution_contract_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4)

    def _boom(self: Path, *args: object, **kwargs: object) -> Path:
        raise OSError("bad path")

    monkeypatch.setattr(Path, "resolve", _boom)

    with pytest.raises(MCPServiceContractError):
        service._resolve_root(str(tmp_path))
    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        service._resolve_root(".")
    with pytest.raises(MCPServiceContractError):
        service._resolve_optional_path("cache.json", tmp_path)


def test_mcp_service_granular_checks_reject_relative_root_and_allow_omission(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    _write_quality_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    latest_clones = service.check_clones()
    assert latest_clones["check"] == "clones"

    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        service.check_clones(root=".")


def test_mcp_service_short_finding_ids_remain_unique_for_overlapping_clones(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )

    findings = service.list_findings(
        run_id=str(summary["run_id"]),
        family="clone",
        detail_level="summary",
        limit=20,
    )
    items = cast("list[dict[str, object]]", findings["items"])
    ids = [str(item["id"]) for item in items]
    assert len(ids) == len(set(ids))
    for finding_id in ids:
        resolved = service.get_finding(
            run_id=str(summary["run_id"]),
            finding_id=finding_id,
            detail_level="normal",
        )
        assert resolved["id"] == finding_id


def test_mcp_service_reports_missing_json_artifact(tmp_path: Path) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    service_module = cast(Any, importlib.import_module("codeclone.mcp_service"))
    original_report = service_module.report

    def _fake_report(**kwargs: Any) -> object:
        artifacts = cast(Any, original_report)(**kwargs)
        return SimpleNamespace(
            json=None,
            html=artifacts.html,
            md=artifacts.md,
            sarif=artifacts.sarif,
            text=artifacts.text,
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("codeclone.mcp_service.report", _fake_report)
    try:
        with pytest.raises(MCPServiceError):
            service.analyze_repository(
                MCPAnalysisRequest(
                    root=str(tmp_path),
                    respect_pyproject=False,
                    cache_policy="off",
                )
            )
    finally:
        monkeypatch.undo()


def test_mcp_service_low_level_runtime_helpers_and_run_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    console = mcp_service_mod._BufferConsole()
    console.print("alpha", 2)
    console.print("   ")
    assert console.messages == ["alpha 2"]

    monkeypatch.setattr(
        cast(Any, mcp_service_mod).subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="pkg/a.py\npkg/b.py\npkg/a.py\n"
        ),
    )
    assert mcp_service_mod._git_diff_lines_payload(
        root_path=tmp_path,
        git_diff_ref="HEAD",
    ) == ("pkg/a.py", "pkg/b.py")

    def _raise_subprocess(*args: object, **kwargs: object) -> object:
        raise subprocess.CalledProcessError(1, ["git", "diff"])

    monkeypatch.setattr(cast(Any, mcp_service_mod).subprocess, "run", _raise_subprocess)
    with pytest.raises(MCPGitDiffError):
        mcp_service_mod._git_diff_lines_payload(root_path=tmp_path, git_diff_ref="HEAD")

    assert mcp_service_mod._load_report_document_payload('{"ok": true}') == {"ok": True}
    with pytest.raises(MCPServiceError):
        mcp_service_mod._load_report_document_payload("{")
    with pytest.raises(MCPServiceError):
        mcp_service_mod._load_report_document_payload("[]")

    store = mcp_service_mod.CodeCloneMCPRunStore(history_limit=1)
    first = _dummy_run_record(tmp_path, "first")
    second = _dummy_run_record(tmp_path, "second")
    assert store.register(first) is first
    assert store.get().run_id == "first"
    store.register(second)
    assert tuple(record.run_id for record in store.records()) == ("second",)
    with pytest.raises(MCPRunNotFoundError):
        store.get("first")
    with pytest.raises(ValueError):
        mcp_service_mod.CodeCloneMCPRunStore(history_limit=11)


def test_mcp_service_branch_helpers_on_real_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_quality_service(tmp_path)
    changed = service.analyze_changed_paths(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            changed_paths=("pkg/dup.py", "pkg/quality.py"),
            complexity_threshold=1,
            coupling_threshold=1,
            cohesion_threshold=1,
        )
    )
    run_id = str(changed["run_id"])
    record = service._runs.get(run_id)

    assert service.get_report_section(run_id=run_id, section="inventory")
    assert service.get_report_section(run_id=run_id, section="derived")

    severity_rows = service.list_findings(
        run_id=run_id,
        sort_by="severity",
        detail_level="full",
        limit=5,
    )
    spread_rows = service.list_findings(
        run_id=run_id,
        sort_by="spread",
        detail_level="normal",
        limit=5,
    )
    assert cast("list[dict[str, object]]", severity_rows["items"])
    assert cast("list[dict[str, object]]", spread_rows["items"])

    highest_priority_summary = service.list_hotspots(
        kind="highest_priority",
        run_id=run_id,
        detail_level="summary",
        limit=2,
    )
    highest_priority_normal = service.list_hotspots(
        kind="highest_priority",
        run_id=run_id,
        detail_level="normal",
        limit=1,
    )
    highest_priority_full = service.list_hotspots(
        kind="highest_priority",
        run_id=run_id,
        detail_level="full",
        limit=1,
    )
    assert cast("list[dict[str, object]]", highest_priority_summary["items"])
    assert cast("list[dict[str, object]]", highest_priority_normal["items"])
    assert cast("list[dict[str, object]]", highest_priority_full["items"])

    reviewed_id = str(
        cast("list[dict[str, object]]", highest_priority_summary["items"])[0]["id"]
    )
    service.mark_finding_reviewed(run_id=run_id, finding_id=reviewed_id)
    filtered_hotspots = service.list_hotspots(
        kind="highest_priority",
        run_id=run_id,
        detail_level="summary",
        exclude_reviewed=True,
    )
    assert all(
        str(item.get("id", "")) != reviewed_id
        for item in cast("list[dict[str, object]]", filtered_hotspots["items"])
    )

    assert (
        service.check_clones(
            run_id=run_id,
            clone_type="Type-999",
            detail_level="summary",
        )["total"]
        == 0
    )
    assert (
        service.check_complexity(
            run_id=run_id,
            min_complexity=999,
            detail_level="summary",
        )["total"]
        == 0
    )

    clone_check = service.check_clones(
        root=str(tmp_path),
        path="pkg/dup.py",
        detail_level="summary",
    )
    assert cast(int, clone_check["total"]) >= 1

    no_changed_service = CodeCloneMCPService(history_limit=2)
    no_changed_service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    with pytest.raises(MCPServiceContractError):
        no_changed_service.read_resource("codeclone://latest/gates")
    with pytest.raises(MCPServiceContractError):
        no_changed_service.read_resource("codeclone://latest/changed")
    with pytest.raises(MCPServiceContractError):
        no_changed_service.get_report_section(section="changed")

    abs_dup = tmp_path / "pkg" / "dup.py"
    normalized = service._normalize_changed_paths(
        root_path=tmp_path,
        paths=(str(abs_dup), "./pkg/dup.py", "pkg", "./.github/workflows/docs.yml"),
    )
    assert normalized == (".github/workflows/docs.yml", "pkg", "pkg/dup.py")
    with pytest.raises(MCPServiceContractError):
        service._normalize_changed_paths(
            root_path=tmp_path,
            paths=(str(tmp_path.parent / "outside.py"),),
        )

    monkeypatch.setattr(
        mcp_service_mod,
        "_git_diff_lines_payload",
        lambda **kwargs: ("pkg/dup.py", "pkg/dup.py"),
    )
    assert service._resolve_request_changed_paths(
        root_path=tmp_path,
        changed_paths=(),
        git_diff_ref="HEAD",
    ) == ("pkg/dup.py",)
    with pytest.raises(MCPServiceContractError):
        service._resolve_request_changed_paths(
            root_path=tmp_path,
            changed_paths=("pkg/dup.py",),
            git_diff_ref="HEAD",
        )
    assert (
        service._resolve_query_changed_paths(
            record=record,
            changed_paths=(),
            git_diff_ref=None,
            prefer_record_paths=True,
        )
        == record.changed_paths
    )

    duplicate_locations = service._locations_for_finding(
        record,
        {
            "items": [
                {
                    "relative_path": "pkg/dup.py",
                    "start_line": 1,
                    "qualname": "pkg.dup:alpha",
                },
                {
                    "relative_path": "pkg/dup.py",
                    "start_line": 1,
                    "qualname": "pkg.dup:alpha",
                },
                {"relative_path": "", "start_line": 0, "qualname": ""},
            ]
        },
    )
    assert len(duplicate_locations) == 1
    assert service._path_matches("pkg/dup.py", ("pkg",))
    assert service._finding_touches_paths(
        finding={"items": [{"relative_path": "pkg/dup.py"}]},
        changed_paths=("pkg",),
    )
    service._review_state["stale"] = OrderedDict([("missing", None)])
    service._prune_session_state()
    assert "stale" not in service._review_state


def test_mcp_service_remediation_and_comparison_helper_branches(
    tmp_path: Path,
) -> None:
    service, before = _analyze_quality_repository(tmp_path)
    tmp_path.joinpath("pkg", "dup.py").write_text(
        "def alpha(value: int) -> int:\n    return value + 1\n",
        "utf-8",
    )
    after = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    before_record = service._runs.get(str(before["run_id"]))

    comparison = service.compare_runs(
        run_id_before=str(before["run_id"]),
        run_id_after=str(after["run_id"]),
        focus="clones",
    )
    _assert_comparable_comparison(comparison, verdict="improved")
    assert (
        service._comparison_verdict(
            regressions=1,
            improvements=0,
            health_delta=0,
        )
        == "regressed"
    )
    assert (
        service._comparison_verdict(
            regressions=0,
            improvements=1,
            health_delta=0,
        )
        == "improved"
    )
    assert (
        service._comparison_verdict(
            regressions=1,
            improvements=0,
            health_delta=1,
        )
        == "mixed"
    )
    assert (
        service._comparison_verdict(
            regressions=0,
            improvements=1,
            health_delta=-1,
        )
        == "mixed"
    )
    assert (
        service._comparison_verdict(
            regressions=1,
            improvements=1,
            health_delta=0,
        )
        == "mixed"
    )
    assert (
        service._comparison_verdict(
            regressions=0,
            improvements=0,
            health_delta=0,
        )
        == "stable"
    )
    assert (
        service._comparison_verdict(
            regressions=0,
            improvements=1,
            health_delta=None,
        )
        == "improved"
    )
    assert (
        service._changed_verdict(
            changed_projection={"new": 1, "total": 1},
            health_delta=0,
        )
        == "regressed"
    )
    assert (
        service._changed_verdict(
            changed_projection={"new": 0, "total": 0},
            health_delta=1,
        )
        == "improved"
    )
    assert (
        service._changed_verdict(
            changed_projection={"new": 0, "total": 1},
            health_delta=0,
        )
        == "stable"
    )

    assert service._comparison_index(before_record, focus="clones")
    structural_index = service._comparison_index(
        before_record,
        focus="structural",
    )
    assert isinstance(structural_index, dict)
    assert service._comparison_index(before_record, focus="metrics")

    remediation = {
        "effort": "moderate",
        "priority": 1.2,
        "confidence": "high",
        "safe_refactor_shape": "Extract helper",
        "risk_level": "medium",
        "why_now": "Because",
        "blast_radius": {"files": 1},
        "steps": ["one", "two"],
    }
    assert service._project_remediation(remediation, detail_level="full") == remediation
    summary_remediation = service._project_remediation(
        remediation,
        detail_level="summary",
    )
    assert "steps" not in summary_remediation
    assert summary_remediation["shape"] == "Extract helper"
    assert summary_remediation["risk"] == "medium"
    normal_remediation = service._project_remediation(
        remediation,
        detail_level="normal",
    )
    assert normal_remediation["steps"] == ["one", "two"]
    assert service._risk_level_for_effort("easy") == "low"
    assert service._risk_level_for_effort("hard") == "high"
    assert "new regression" in service._why_now_text(
        title="Clone group",
        severity="warning",
        novelty="new",
        count=2,
        source_kind="production",
        spread_files=1,
        spread_functions=2,
        effort="moderate",
    )


def test_mcp_service_compare_runs_marks_different_roots_incomparable(
    tmp_path: Path,
) -> None:
    first_root, second_root = _two_clone_fixture_roots(tmp_path)
    second_root.joinpath("pkg", "extra.py").write_text(
        "def gamma(value: int) -> int:\n    return value * 2\n",
        "utf-8",
    )
    service = CodeCloneMCPService(history_limit=4)
    before = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(first_root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    after = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(second_root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    after_record = service._runs.get(str(after["run_id"]))

    comparison = service.compare_runs(
        run_id_before=str(before["run_id"]),
        run_id_after=str(after["run_id"]),
        focus="all",
    )

    before_payload = cast("dict[str, object]", comparison["before"])
    after_payload = cast("dict[str, object]", comparison["after"])
    assert len(str(before_payload["run_id"])) == 8
    assert len(str(after_payload["run_id"])) == 8
    _assert_incomparable_comparison(comparison, reason="different_root")
    assert "Finding and run health deltas omitted" in str(comparison["summary"])
    assert "known debt" in service._why_now_text(
        title="Clone group",
        severity="warning",
        novelty="known",
        count=0,
        source_kind="tests",
        spread_files=1,
        spread_functions=1,
        effort="easy",
    )

    assert service._safe_refactor_shape(
        SimpleNamespace(category="clone", clone_type="Type-1", title="Function clone"),
    ).startswith("Keep one canonical")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="clone", clone_type="Type-2", title="Function clone"),
    ).startswith("Extract shared")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="clone", clone_type="Type-4", title="Block clone"),
    ).startswith("Extract the repeated statement")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="structural", clone_type="", title="Branches"),
    ).startswith("Extract the repeated branch")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="complexity", clone_type="", title="Complex"),
    ).startswith("Split the function")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="coupling", clone_type="", title="Coupling"),
    ).startswith("Isolate responsibilities")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="cohesion", clone_type="", title="Cohesion"),
    ).startswith("Split the class")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="dead_code", clone_type="", title="Dead code"),
    ).startswith("Delete the unused symbol")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="dependency", clone_type="", title="Cycle"),
    ).startswith("Break the cycle")
    assert service._safe_refactor_shape(
        SimpleNamespace(category="other", clone_type="", title="Other"),
    ).startswith("Extract the repeated logic")

    empty_markdown = service._render_pr_summary_markdown(
        {
            "health": {"score": 81, "grade": "B"},
            "health_delta": 0,
            "verdict": "stable",
            "new_findings_in_changed_files": [],
            "resolved": [],
            "blocking_gates": [],
        }
    )
    assert "- None" in empty_markdown
    assert "- none" in empty_markdown
    assert service._build_changed_projection(after_record) is None
    augmented = service._augment_summary_with_changed(
        summary={"run_id": after["run_id"]},
        changed_paths=("pkg/dup.py",),
        changed_projection={
            "total": 1,
            "new": 0,
            "known": 1,
            "items": [{"id": "x"}],
            "health_delta": -1,
            "verdict": "regressed",
        },
    )
    assert augmented["changed_paths"] == ["pkg/dup.py"]
    assert cast("dict[str, object]", augmented["changed_findings"])["total"] == 1


def test_mcp_service_compare_runs_marks_different_settings_incomparable(
    tmp_path: Path,
) -> None:
    _write_clone_fixture(tmp_path)
    _write_quality_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    before = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    after = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            complexity_threshold=1,
        )
    )

    comparison = service.compare_runs(
        run_id_before=str(before["run_id"]),
        run_id_after=str(after["run_id"]),
        focus="all",
    )

    _assert_incomparable_comparison(
        comparison,
        reason="different_analysis_settings",
    )
    assert "different analysis settings" in str(comparison["summary"])


def test_mcp_service_additional_projection_and_error_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_quality_service(tmp_path)

    with pytest.raises(MCPServiceContractError):
        service.analyze_changed_paths(
            MCPAnalysisRequest(
                root=str(tmp_path),
                respect_pyproject=False,
                cache_policy="off",
            )
        )

    summary = service.analyze_changed_paths(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
            changed_paths=("pkg/dup.py",),
            complexity_threshold=1,
            coupling_threshold=1,
            cohesion_threshold=1,
        )
    )
    run_id = str(summary["run_id"])
    record = service._runs.get(run_id)

    assert mcp_service_mod._suggestion_finding_id_payload(object()) == ""
    assert mcp_service_mod._suggestion_finding_id_payload(
        SimpleNamespace(
            finding_family="structural",
            finding_kind="duplicated_branches",
            subject_key="key",
            category="structural",
            title="Structural",
        )
    ).startswith("structural:")
    assert mcp_service_mod._suggestion_finding_id_payload(
        SimpleNamespace(
            finding_family="design",
            finding_kind="",
            subject_key="dead-key",
            category="dead_code",
            title="Dead code",
        )
    ).startswith("dead_code:")
    assert mcp_service_mod._suggestion_finding_id_payload(
        SimpleNamespace(
            finding_family="design",
            finding_kind="",
            subject_key="",
            category="coupling",
            title="Coupling title",
        )
    ).startswith("design:coupling:")

    original_service_get = service.get_finding
    original_runs_get = service._runs.get
    monkeypatch.setattr(
        service,
        "get_finding",
        lambda **kwargs: {"id": "no-remediation"},
    )
    monkeypatch.setattr(service._runs, "get", lambda run_id=None: record)
    with pytest.raises(MCPFindingNotFoundError):
        service.get_remediation(finding_id="no-remediation", run_id=run_id)
    monkeypatch.setattr(service, "get_finding", original_service_get)
    monkeypatch.setattr(service._runs, "get", original_runs_get)

    original_get_finding = service.get_finding

    def _patched_get_finding(
        *,
        finding_id: str,
        run_id: str | None = None,
        detail_level: DetailLevel = "normal",
    ) -> dict[str, object]:
        if finding_id == "missing":
            raise MCPFindingNotFoundError("missing")
        return original_get_finding(
            finding_id=finding_id,
            run_id=run_id,
            detail_level=detail_level,
        )

    monkeypatch.setattr(service, "get_finding", _patched_get_finding)
    service._review_state[record.run_id] = OrderedDict([("missing", None)])
    reviewed_items = service.list_reviewed_findings(run_id=run_id)
    assert reviewed_items["reviewed_count"] == 0

    assert (
        service.check_dead_code(
            run_id=run_id,
            min_severity="warning",
            detail_level="summary",
        )["check"]
        == "dead_code"
    )
    assert (
        json.loads(service.read_resource(f"codeclone://runs/{run_id}/schema"))["title"]
        == "CodeCloneCanonicalReport"
    )
    findings_payload = service.list_findings(run_id=run_id)
    first_finding_id = str(
        cast("list[dict[str, object]]", findings_payload["items"])[0]["id"]
    )
    assert (
        json.loads(
            service.read_resource(
                f"codeclone://runs/{run_id}/findings/{first_finding_id}"
            )
        )["id"]
        == first_finding_id
    )

    pr_summary = service.generate_pr_summary(
        run_id=run_id,
        changed_paths=("pkg/dup.py",),
        format="json",
    )
    assert pr_summary["resolved"] == []
    assert service.generate_pr_summary(run_id=run_id, format="json")["resolved"] == []

    other_root = tmp_path / "other"
    other_root.mkdir()
    service_other = CodeCloneMCPService(history_limit=4)
    _write_clone_fixture(other_root)
    first = service_other.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    second = service_other.analyze_repository(
        MCPAnalysisRequest(
            root=str(other_root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    assert (
        service_other._previous_run_for_root(
            service_other._runs.get(str(second["run_id"]))
        )
        is None
    )
    assert (
        service_other._previous_run_for_root(
            service_other._runs.get(str(first["run_id"]))
        )
        is None
    )

    same_root_service = CodeCloneMCPService(history_limit=4)
    _write_clone_fixture(other_root)
    first_same_root = same_root_service.analyze_repository(
        MCPAnalysisRequest(
            root=str(other_root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    other_root.joinpath("pkg", "dup.py").write_text(
        "def alpha(value: int) -> int:\n    return value + 1\n",
        "utf-8",
    )
    second_same_root = same_root_service.analyze_repository(
        MCPAnalysisRequest(
            root=str(other_root),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    previous_same_root = same_root_service._previous_run_for_root(
        same_root_service._runs.get(str(second_same_root["run_id"]))
    )
    assert previous_same_root is not None
    assert previous_same_root.run_id.startswith(str(first_same_root["run_id"]))
    assert same_root_service.generate_pr_summary(
        run_id=str(second_same_root["run_id"]),
        format="json",
    )["resolved"]

    fake_design_record = MCPRunRecord(
        run_id="design",
        root=tmp_path,
        request=MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            complexity_threshold=1,
            coupling_threshold=1,
            cohesion_threshold=1,
        ),
        comparison_settings=(),
        report_document={
            "metrics": {
                "families": {
                    "complexity": {
                        "items": [
                            {
                                "qualname": "pkg.quality:hot",
                                "relative_path": "pkg/quality.py",
                                "start_line": 1,
                                "end_line": 5,
                                "cyclomatic_complexity": 3,
                                "nesting_depth": 1,
                                "risk": "medium",
                            }
                        ]
                    },
                    "coupling": {
                        "items": [
                            {
                                "qualname": "pkg.quality:coupled",
                                "relative_path": "pkg/quality.py",
                                "start_line": 1,
                                "end_line": 5,
                                "cbo": 2,
                                "risk": "medium",
                                "coupled_classes": ["A"],
                            }
                        ]
                    },
                    "cohesion": {
                        "items": [
                            {
                                "qualname": "pkg.quality:cohesive",
                                "relative_path": "pkg/quality.py",
                                "start_line": 1,
                                "end_line": 5,
                                "lcom4": 2,
                                "risk": "medium",
                                "method_count": 2,
                                "instance_var_count": 2,
                            }
                        ]
                    },
                }
            },
            "findings": {
                "groups": {
                    "design": {"groups": []},
                    "clones": {"functions": [], "blocks": [], "segments": []},
                    "structural": {"groups": []},
                    "dead_code": {"groups": []},
                }
            },
        },
        summary={"run_id": "design", "health": {"score": 80, "grade": "B"}},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    design_findings = [
        finding
        for finding in service._base_findings(fake_design_record)
        if str(finding.get("family", "")) == "design"
    ]
    assert design_findings == []
    detail_payload = service._project_finding_detail(
        fake_design_record,
        {
            "id": "finding",
            "title": "Finding",
            "remediation": {"steps": ["a"], "blast_radius": {"files": 1}},
        },
        detail_level="normal",
    )
    assert "remediation" in detail_payload
    assert (
        service._project_finding_detail(
            fake_design_record,
            {"id": "finding", "title": "Finding"},
            detail_level="normal",
        )["id"]
        == "finding"
    )
    assert (
        service._matches_finding_filters(
            finding={"family": "clone", "category": "clone"},
            family="all",
            category="structural",
            severity=None,
            source_kind=None,
            novelty="all",
        )
        is False
    )
    assert (
        service._spread_weight(_dummy_run_record(tmp_path, "empty"), {"spread": {}})
        == 0.3
    )
    location_uri = service._locations_for_finding(
        record,
        {
            "items": [
                {
                    "relative_path": "pkg/dup.py",
                    "start_line": 1,
                    "qualname": "pkg.dup:alpha",
                }
            ]
        },
    )[0]["uri"]
    assert str(location_uri).endswith("#L1")
    location_without_line = service._locations_for_finding(
        record,
        {
            "items": [
                {
                    "relative_path": "pkg/dup.py",
                    "start_line": 0,
                    "qualname": "pkg.dup:alpha",
                }
            ]
        },
    )[0]["uri"]
    assert "#L" not in str(location_without_line)
    location_without_uri = service._locations_for_finding(
        record,
        {
            "items": [
                {
                    "relative_path": "pkg/dup.py",
                    "start_line": 1,
                    "qualname": "pkg.dup:alpha",
                }
            ]
        },
        include_uri=False,
    )[0]
    assert "uri" not in location_without_uri
    assert location_without_uri["symbol"] == "pkg.dup:alpha"
    assert (
        service.list_hotspots(
            kind="highest_spread",
            run_id=run_id,
            changed_paths=("does/not/match.py",),
            detail_level="summary",
        )["total"]
        == 0
    )
    fake_hotspot_record = MCPRunRecord(
        run_id="hotspot",
        root=record.root,
        request=record.request,
        comparison_settings=record.comparison_settings,
        report_document={
            **record.report_document,
            "derived": {"hotlists": {"highest_spread_ids": ["missing-id"]}},
        },
        summary=record.summary,
        changed_paths=record.changed_paths,
        changed_projection=record.changed_projection,
        warnings=record.warnings,
        failures=record.failures,
        func_clones_count=record.func_clones_count,
        block_clones_count=record.block_clones_count,
        project_metrics=record.project_metrics,
        suggestions=record.suggestions,
        new_func=record.new_func,
        new_block=record.new_block,
        metrics_diff=record.metrics_diff,
    )
    assert (
        service._hotspot_rows(
            record=fake_hotspot_record,
            kind="highest_spread",
            detail_level="summary",
            changed_paths=(),
            exclude_reviewed=False,
        )
        == []
    )
    metrics_focus = service._comparison_index(record, focus="metrics")
    assert isinstance(metrics_focus, dict)
    resolved_markdown = service._render_pr_summary_markdown(
        {
            "health": {"score": 81, "grade": "B"},
            "health_delta": 1,
            "verdict": "improved",
            "new_findings_in_changed_files": [],
            "resolved": [{"title": "Fixed", "location": "pkg/dup.py"}],
            "blocking_gates": [],
        }
    )
    assert "### Resolved (1)" in resolved_markdown
    assert (
        service._normalize_changed_paths(
            root_path=tmp_path,
            paths=(".", "./"),
        )
        == ()
    )
    complexity_check = service.check_complexity(
        run_id=run_id,
        min_complexity=1,
        detail_level="summary",
    )
    assert complexity_check["check"] == "complexity"
    unfiltered_complexity = service.check_complexity(
        run_id=run_id,
        detail_level="summary",
    )
    assert unfiltered_complexity["check"] == "complexity"


def test_mcp_service_clear_session_runs_clears_in_memory_state(tmp_path: Path) -> None:
    service = _build_quality_service(tmp_path)
    run_id = str(service.get_run_summary()["run_id"])
    first_finding = cast(
        "list[dict[str, object]]",
        service.list_findings(family="clone", detail_level="summary")["items"],
    )[0]
    service.mark_finding_reviewed(
        run_id=run_id,
        finding_id=str(first_finding["id"]),
        note="triaged",
    )
    service.evaluate_gates(MCPGateRequest(run_id=run_id, fail_threshold=0))

    cleared = service.clear_session_runs()

    assert cleared["cleared_runs"] == 1
    assert cleared["cleared_review_entries"] == 1
    assert cleared["cleared_gate_results"] == 1
    with pytest.raises(MCPRunNotFoundError):
        service.get_run_summary()


def test_mcp_service_metrics_diff_warning_and_projection_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=2)

    fake_status = SimpleNamespace(value="ok")
    fake_metrics_baseline = SimpleNamespace(
        schema_version="2.0",
        payload_sha256="digest",
        diff=lambda metrics: MetricsDiff(
            new_high_risk_functions=("pkg.dup:alpha",),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=-1,
        ),
    )
    monkeypatch.setattr(
        mcp_service_mod,
        "resolve_metrics_baseline_state",
        lambda **kwargs: SimpleNamespace(
            baseline=fake_metrics_baseline,
            loaded=True,
            status=fake_status,
            trusted_for_diff=True,
            updated_path=None,
        ),
    )
    cache_with_warning = Cache(
        tmp_path / "cache.json",
        root=tmp_path,
        max_size_bytes=1024 * 1024,
    )
    cache_with_warning.load_warning = "cache warning"
    monkeypatch.setattr(service, "_build_cache", lambda **kwargs: cache_with_warning)

    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="off",
        )
    )
    diff = cast("dict[str, object]", summary["diff"])
    assert diff["health_delta"] == -1
    assert "cache warning" in cast("list[str]", summary["warnings"])


def test_mcp_service_helper_branches_for_empty_gate_and_missing_remediation(
    tmp_path: Path,
) -> None:
    service = CodeCloneMCPService(history_limit=2)
    request = MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False)
    record = MCPRunRecord(
        run_id="helpers",
        root=tmp_path,
        request=request,
        comparison_settings=(),
        report_document={"metrics": 1},
        summary={},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    service._runs.register(record)

    success_gate = service._evaluate_gate_snapshot(
        record=record,
        request=MCPGateRequest(fail_on_new=True, fail_threshold=10),
    )
    assert success_gate.exit_code == 0
    assert success_gate.reasons == ()

    clone_gate_record = MCPRunRecord(
        run_id="helpers-new",
        root=tmp_path,
        request=request,
        comparison_settings=(),
        report_document={"meta": {}},
        summary={},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset({"clone:new"}),
        new_block=frozenset(),
        metrics_diff=None,
    )
    clone_gate = service._evaluate_gate_snapshot(
        record=clone_gate_record,
        request=MCPGateRequest(fail_on_new=True, fail_threshold=10),
    )
    assert clone_gate.exit_code == 3
    assert clone_gate.reasons == ("clone:new",)

    assert service.get_report_section(run_id="helpers", section="metrics") == {
        "summary": {}
    }
    with pytest.raises(MCPServiceContractError):
        service.get_report_section(run_id="helpers", section="metrics_detail")
    with pytest.raises(MCPServiceContractError):
        service.get_report_section(run_id="helpers", section="findings")

    assert service._summary_payload({"inventory": {}}) == {
        "inventory": {},
        "health": {"available": False, "reason": "unavailable"},
    }

    assert service._suggestion_for_finding(record, "missing") is None
    assert (
        service._remediation_for_finding(
            record,
            {"id": "missing", "severity": "info"},
        )
        is None
    )
    detail = service._decorate_finding(
        record,
        {"id": "missing", "title": "Missing remediation", "severity": "info"},
        detail_level="summary",
        remediation=None,
        priority_payload={"score": 0.1, "factors": {}},
    )
    assert detail["id"] == "missing"
    assert "remediation" not in detail


def test_mcp_service_record_lookup_helper_branches(tmp_path: Path) -> None:
    service = CodeCloneMCPService(history_limit=2)
    request = MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False)
    record = MCPRunRecord(
        run_id="lookup",
        root=tmp_path,
        request=request,
        comparison_settings=(),
        report_document={"meta": {}},
        summary={},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    service._runs.register(record)

    foreign_record = MCPRunRecord(
        run_id="foreign",
        root=tmp_path,
        request=request,
        comparison_settings=(),
        report_document={"meta": {}},
        summary={},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    assert service._previous_run_for_root(foreign_record) is None
    assert (
        service._latest_compatible_record(
            analysis_mode="full",
            root_path=tmp_path / "other",
        )
        is None
    )


def test_mcp_service_short_id_and_comparison_helper_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4)

    entry = mcp_service_mod._CloneShortIdEntry(
        canonical_id="clone:block:abcdefghij|rest",
        alias="blk",
        token="abcdefghijrest",
        suffix="|x2",
    )
    assert entry.render(0) == "blk:abcdefghijrest|x2"
    assert mcp_service_mod._partitioned_short_id("design", "cohesion") == (
        "design:cohesion"
    )

    function_entry = mcp_service_mod._clone_short_id_entry_payload(
        "clone:function:abcdef123456|bucket2"
    )
    assert function_entry.alias == "fn"
    assert function_entry.token == "abcdef123456"
    assert function_entry.suffix == "|bucket2"
    plain_function_entry = mcp_service_mod._clone_short_id_entry_payload(
        "clone:function:abcdef123456"
    )
    assert plain_function_entry.alias == "fn"
    assert plain_function_entry.suffix == ""

    fallback_entry = mcp_service_mod._clone_short_id_entry_payload("clone:weird:opaque")
    assert fallback_entry.alias == "clone"
    assert len(fallback_entry.token) == 64  # sha256 hex digest
    assert fallback_entry.suffix == "|x1"

    canonical_one = "clone:block:abcdefghzz|rest"
    canonical_two = "clone:block:abcdefghyy|rest"
    clone_short_ids = mcp_service_mod._disambiguated_clone_short_ids_payload(
        [canonical_one, canonical_two]
    )
    assert len(set(clone_short_ids.values())) == 2
    assert all(value.startswith("blk:") for value in clone_short_ids.values())
    assert all("|x2" in value for value in clone_short_ids.values())
    single_result = mcp_service_mod._disambiguated_clone_short_ids_payload(
        ["clone:block:ab"]
    )
    assert "clone:block:ab" in single_result
    assert single_result["clone:block:ab"].startswith("blk:")
    assert single_result["clone:block:ab"].endswith("|x1")

    record = MCPRunRecord(
        run_id="helper-ids",
        root=tmp_path,
        request=MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False),
        comparison_settings=(),
        report_document={
            "findings": {
                "groups": {
                    "clones": {
                        "functions": [],
                        "blocks": [
                            {"id": canonical_one},
                            {"id": canonical_two},
                        ],
                        "segments": [],
                    },
                    "structural": {"groups": []},
                    "dead_code": {"groups": []},
                    "design": {"groups": []},
                }
            }
        },
        summary={},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=2,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    canonical_to_short, short_to_canonical = service._finding_id_maps(record)
    assert len(set(canonical_to_short.values())) == 2
    assert set(short_to_canonical) == set(canonical_to_short.values())
    assert (
        service._disambiguated_short_finding_ids([canonical_one, canonical_two])
        == clone_short_ids
    )

    assert service._base_short_finding_id(canonical_one) == "blk:a1c488|x2"
    assert (
        mcp_service_mod._base_short_finding_id_payload("clone:function:abcdef123456")
        == "fn:abcdef"
    )
    assert service._base_short_finding_id("clone:function:abcdef123456") == "fn:abcdef"
    assert (
        service._base_short_finding_id("structural:duplicated_branches:abcdef123456")
        == "struct:duplicated_branches:abcdef"
    )
    assert (
        mcp_service_mod._base_short_finding_id_payload(
            "design:cohesion:pkg.mod:Runner.run"
        )
        == "design:cohesion:run"
    )
    assert service._base_short_finding_id("custom:finding") == "custom:finding"
    assert (
        service._disambiguated_short_finding_id("clone:function:abcdef123456")
        == "fn:abcdef123456"
    )
    assert (
        service._disambiguated_short_finding_id("clone:function:abcdef123456|bucket2")
        == "fn:abcdef123456|bucket2"
    )
    assert (
        service._disambiguated_short_finding_id("clone:block:abcdef123456|rest")
        == "blk:e38144d04782fe95c05f0588c53ea7d553f0efdc555788f629e73be6501597d1|x2"
    )
    assert (
        service._disambiguated_short_finding_id("structural:dup:abc:def")
        == "struct:dup:abc:def"
    )
    assert (
        service._disambiguated_short_finding_id("dead_code:pkg.mod:Runner.run")
        == "dead:pkg.mod:Runner.run"
    )
    assert service._disambiguated_short_finding_id("custom:finding") == "custom:finding"
    assert (
        service._disambiguated_short_finding_id("design:cohesion:pkg.mod:Runner")
        == "design:cohesion:pkg.mod:Runner"
    )
    assert (
        mcp_service_mod._disambiguated_short_finding_id_payload(
            "dead_code:pkg.mod:Runner.run"
        )
        == "dead:pkg.mod:Runner.run"
    )
    mixed_short_ids = service._disambiguated_short_finding_ids(
        [canonical_one, "design:cohesion:pkg.mod:Runner"]
    )
    assert mixed_short_ids[canonical_one].startswith("blk:")
    assert mixed_short_ids["design:cohesion:pkg.mod:Runner"] == (
        "design:cohesion:pkg.mod:Runner"
    )
    assert service._leaf_symbol_name("") == ""
    assert service._leaf_symbol_name("pkg.mod:Runner.run") == "run"
    assert service._leaf_symbol_name("pkg.mod") == "mod"
    assert mcp_service_mod._leaf_symbol_name_payload("pkg.mod:Runner.run") == "run"
    assert json.loads(mcp_service_mod._json_text_payload({"b": 1, "a": 2})) == {
        "a": 2,
        "b": 1,
    }

    collision_service = CodeCloneMCPService(history_limit=4)
    monkeypatch.setattr(
        collision_service,
        "_base_findings",
        lambda _record: [{"id": "clone:block:one"}, {"id": "clone:block:two"}],
    )
    monkeypatch.setattr(
        collision_service,
        "_base_short_finding_id",
        lambda _cid: "blk:dup|x1",
    )
    monkeypatch.setattr(
        collision_service,
        "_disambiguated_short_finding_ids",
        lambda _ids: {
            "clone:block:one": "blk:resolved1|x1",
            "clone:block:two": "blk:resolved2|x1",
        },
    )
    collision_to_short, collision_to_canonical = collision_service._finding_id_maps(
        record
    )
    assert collision_to_short == {
        "clone:block:one": "blk:resolved1|x1",
        "clone:block:two": "blk:resolved2|x1",
    }
    assert collision_to_canonical == {
        "blk:resolved1|x1": "clone:block:one",
        "blk:resolved2|x1": "clone:block:two",
    }

    same_root = _dummy_run_record(tmp_path, "same-root")
    different_scope = MCPRunRecord(
        run_id="different-scope",
        root=tmp_path / "other",
        request=MCPAnalysisRequest(
            root=str(tmp_path / "other"),
            respect_pyproject=False,
        ),
        comparison_settings=("full", 20),
        report_document={},
        summary={"run_id": "different-scope", "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=(),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    scope = service._comparison_scope(before=same_root, after=different_scope)
    assert scope["comparable"] is False
    assert scope["reason"] == "different_root_and_analysis_settings"


def test_mcp_service_clone_short_id_helper_iteration_and_fallback_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterative_entries = {
        "clone:block:one": mcp_service_mod._CloneShortIdEntry(
            canonical_id="clone:block:one",
            alias="blk",
            token="abcdefghij",
            suffix="|x1",
        ),
        "clone:block:two": mcp_service_mod._CloneShortIdEntry(
            canonical_id="clone:block:two",
            alias="blk",
            token="abcdefghkl",
            suffix="|x1",
        ),
    }
    monkeypatch.setattr(
        mcp_service_mod,
        "_clone_short_id_entry_payload",
        lambda canonical_id: iterative_entries[canonical_id],
    )
    assert mcp_service_mod._disambiguated_clone_short_ids_payload(
        ["clone:block:one", "clone:block:two"]
    ) == {
        "clone:block:one": "blk:abcdefghij|x1",
        "clone:block:two": "blk:abcdefghkl|x1",
    }

    fallback_entries = {
        "clone:block:one": mcp_service_mod._CloneShortIdEntry(
            canonical_id="clone:block:one",
            alias="blk",
            token="abcdefghij",
            suffix="|x1",
        ),
        "clone:block:two": mcp_service_mod._CloneShortIdEntry(
            canonical_id="clone:block:two",
            alias="blk",
            token="abcdefghij",
            suffix="|x1",
        ),
    }
    monkeypatch.setattr(
        mcp_service_mod,
        "_clone_short_id_entry_payload",
        lambda canonical_id: fallback_entries[canonical_id],
    )
    assert mcp_service_mod._disambiguated_clone_short_ids_payload(
        ["clone:block:one", "clone:block:two"]
    ) == {
        "clone:block:one": "blk:abcdefghij|x1",
        "clone:block:two": "blk:abcdefghij|x1",
    }


def test_mcp_service_payload_and_resolution_helper_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4)
    first_record = _dummy_run_record(tmp_path, "shared-one")
    second_record = _dummy_run_record(tmp_path, "shared-two")
    service._runs.register(first_record)
    service._runs.register(second_record)

    with pytest.raises(MCPServiceContractError, match="ambiguous"):
        service._runs.get("shared")

    missing_record = _dummy_run_record(tmp_path, "missing-finding")
    service._runs.register(missing_record)
    monkeypatch.setattr(
        service,
        "_resolve_canonical_finding_id",
        lambda _record, _finding_id: "design:cohesion:pkg.mod:Runner",
    )
    monkeypatch.setattr(
        service,
        "_base_findings",
        lambda _record: [{"id": "design:cohesion:pkg.mod:Other"}],
    )
    with pytest.raises(MCPFindingNotFoundError, match="missing-finding"[:8]):
        service.get_finding(
            run_id="missing-finding", finding_id="design:cohesion:Runner"
        )

    monkeypatch.setattr(
        service,
        "get_finding",
        lambda **_kwargs: {"id": "design:cohesion:pkg.mod:Runner"},
    )
    with pytest.raises(MCPFindingNotFoundError, match="remediation guidance"):
        service.get_remediation(
            run_id="missing-finding",
            finding_id="design:cohesion:Runner",
        )

    with pytest.raises(MCPServiceContractError, match="absolute repository root"):
        service._resolve_root(None)

    assert service._normal_location_payload({"file": "", "line": 4}) == {}
    assert service._normal_location_payload(
        {"file": "pkg/mod.py", "line": 4, "end_line": 9, "symbol": "pkg.mod:Runner.run"}
    ) == {
        "path": "pkg/mod.py",
        "line": 4,
        "end_line": 9,
        "symbol": "run",
    }
    assert service._normal_location_payload(
        {"file": "pkg/mod.py", "line": 0, "symbol": ""}
    ) == {"path": "pkg/mod.py", "line": 0, "end_line": 0}
    assert service._finding_display_location({"locations": []}) == "(unknown)"
    assert (
        service._finding_display_location({"locations": [{"file": "", "line": 3}]})
        == "(unknown)"
    )
    assert (
        service._finding_display_location(
            {"locations": [{"file": "pkg/mod.py", "line": 0}]}
        )
        == "pkg/mod.py"
    )

    assert service._comparison_summary_text(
        comparable=True,
        comparability_reason="comparable",
        regressions=2,
        improvements=1,
        health_delta=None,
    ) == (
        "1 findings resolved, 2 new regressions; "
        "run health delta omitted (metrics unavailable)"
    )
    assert (
        service._hotspot_rows(
            record=missing_record,
            kind=cast(Any, "unknown"),
            detail_level="summary",
            changed_paths=(),
            exclude_reviewed=False,
        )
        == []
    )

    suggestion = SimpleNamespace(
        finding_family="metrics",
        finding_kind="function_hotspot",
        subject_key="pkg.mod:Runner",
        category="complexity",
        source_kind="tests",
        title="Reduce complexity",
    )
    canonical_finding_id = mcp_service_mod._suggestion_finding_id_payload(suggestion)
    triage_record = MCPRunRecord(
        run_id="triage",
        root=tmp_path,
        request=MCPAnalysisRequest(root=str(tmp_path), respect_pyproject=False),
        comparison_settings=(),
        report_document={
            "findings": {
                "groups": {
                    "clones": {"functions": [], "blocks": [], "segments": []},
                    "structural": {"groups": []},
                    "dead_code": {"groups": []},
                    "design": {"groups": []},
                }
            },
            "derived": {
                "suggestions": [
                    {
                        "finding_id": canonical_finding_id,
                        "title": "Reduce complexity",
                        "summary": "Extract a helper.",
                        "action": {"effort": "easy", "steps": ["Extract a helper."]},
                    }
                ]
            },
        },
        summary={},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        func_clones_count=0,
        block_clones_count=0,
        project_metrics=None,
        suggestions=cast(Any, (suggestion,)),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    monkeypatch.setattr(
        service,
        "_resolve_canonical_finding_id",
        lambda _record, _finding_id: (_ for _ in ()).throw(
            MCPFindingNotFoundError("missing")
        ),
    )
    triage_rows = service._triage_suggestion_rows(triage_record)
    assert triage_rows == [
        {
            "id": "suggestion:design:complexity:Runner",
            "finding_id": "design:complexity:Runner",
            "title": "Reduce complexity",
            "summary": "Extract a helper.",
            "effort": "easy",
            "steps": ["Extract a helper."],
            "source_kind": "tests",
        }
    ]


def test_mcp_service_summary_and_metrics_detail_helper_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=4)

    with pytest.raises(MCPServiceContractError, match="section 'derived'"):
        service._derived_section_payload(_dummy_run_record(tmp_path, "no-derived"))

    assert service._summary_health_payload({"analysis_mode": "clones_only"}) == {
        "available": False,
        "reason": "metrics_skipped",
    }
    assert service._summary_health_score({"analysis_mode": "clones_only"}) is None
    assert (
        service._summary_health_delta(
            {
                "analysis_mode": "clones_only",
                "metrics_diff": {"health_delta": 7},
            }
        )
        is None
    )
    assert service._summary_health_payload({}) == {
        "available": False,
        "reason": "unavailable",
    }
    assert service._summary_cache_payload({}) == {}
    assert service._summary_findings_payload(
        {"findings_summary": {"total": 7}},
        record=None,
    ) == {
        "total": 7,
        "new": 0,
        "known": 0,
        "by_family": {},
        "production": 0,
    }

    record = _dummy_run_record(tmp_path, "summary-helper")
    monkeypatch.setattr(
        service,
        "_base_findings",
        lambda _record: [
            {
                "id": "custom:finding",
                "family": "custom",
                "novelty": "known",
                "source_scope": {"dominant_kind": "other"},
            }
        ],
    )
    assert service._summary_findings_payload({}, record=record) == {
        "total": 1,
        "new": 0,
        "known": 1,
        "by_family": {},
        "production": 0,
    }

    metrics_payload = service._metrics_detail_payload(
        metrics={
            "summary": {"families": 1},
            "families": {
                "complexity": {
                    "items": [
                        {
                            "relative_path": "pkg/mod.py",
                            "qualname": "pkg.mod:run",
                            "score": 10,
                            "empty_text": "",
                            "empty_dict": {},
                        },
                        {
                            "filepath": "pkg/other.py",
                            "qualname": "pkg.other:run",
                            "score": 11,
                        },
                        {},
                    ]
                }
            },
        },
        family=None,
        path="pkg/mod.py",
        offset=-5,
        limit=500,
    )
    assert metrics_payload == {
        "family": None,
        "path": "pkg/mod.py",
        "offset": 0,
        "limit": 200,
        "returned": 1,
        "total": 1,
        "has_more": False,
        "items": [
            {
                "family": "complexity",
                "path": "pkg/mod.py",
                "qualname": "pkg.mod:run",
                "score": 10,
            }
        ],
    }
    overloaded_modules_payload = service._metrics_detail_payload(
        metrics={
            "summary": {},
            "families": {
                "overloaded_modules": {
                    "items": [
                        {
                            "relative_path": "zeta.py",
                            "module": "pkg.zeta",
                            "score": 0.99,
                            "candidate_status": "candidate",
                        },
                        {
                            "relative_path": "alpha.py",
                            "module": "pkg.alpha",
                            "score": 0.12,
                            "candidate_status": "non_candidate",
                        },
                    ]
                }
            },
        },
        family="overloaded_modules",
        path=None,
        offset=0,
        limit=5,
    )
    assert overloaded_modules_payload == {
        "family": "overloaded_modules",
        "path": None,
        "offset": 0,
        "limit": 5,
        "returned": 2,
        "total": 2,
        "has_more": False,
        "items": [
            {
                "path": "zeta.py",
                "module": "pkg.zeta",
                "score": 0.99,
                "candidate_status": "candidate",
            },
            {
                "path": "alpha.py",
                "module": "pkg.alpha",
                "score": 0.12,
                "candidate_status": "non_candidate",
            },
        ],
    }
    assert service._compact_metrics_item(
        {"qualname": "pkg.mod:run", "score": 10, "skip": None}
    ) == {"qualname": "pkg.mod:run", "score": 10}


def test_mcp_service_clone_only_short_id_fallback_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CodeCloneMCPService(history_limit=2)
    monkeypatch.setattr(
        mcp_service_mod,
        "_disambiguated_clone_short_ids_payload",
        lambda _canonical_ids: {
            "clone:block:one": "blk:dup|x1",
            "clone:block:two": "blk:dup|x1",
        },
    )

    result = service._disambiguated_short_finding_ids(
        ["clone:block:one", "clone:block:two"]
    )
    import hashlib

    one_digest = hashlib.sha256(b"one").hexdigest()
    two_digest = hashlib.sha256(b"two").hexdigest()
    assert result == {
        "clone:block:one": f"blk:{one_digest}|x1",
        "clone:block:two": f"blk:{two_digest}|x1",
    }
