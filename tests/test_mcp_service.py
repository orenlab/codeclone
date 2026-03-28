# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib
import json
import subprocess
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from codeclone import mcp_service as mcp_service_mod
from codeclone._cli_config import ConfigValidationError
from codeclone.cache import Cache
from codeclone.errors import CacheError
from codeclone.mcp_service import (
    CodeCloneMCPService,
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


def _write_clone_fixture(root: Path) -> None:
    root.joinpath("pkg").mkdir(exist_ok=True)
    root.joinpath("pkg", "__init__.py").write_text("", "utf-8")
    root.joinpath("pkg", "dup.py").write_text(
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


def _dummy_run_record(root: Path, run_id: str) -> MCPRunRecord:
    return MCPRunRecord(
        run_id=run_id,
        root=root,
        request=MCPAnalysisRequest(root=str(root), respect_pyproject=False),
        report_document={},
        report_json="{}",
        summary={"run_id": run_id, "health": {"score": 0, "grade": "N/A"}},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        analysis=cast(Any, SimpleNamespace(suggestions=[])),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )


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
    assert summary["root"] == str(tmp_path)
    assert summary["analysis_mode"] == "full"
    assert summary["report_schema_version"] == "2.1"
    latest_baseline = cast("dict[str, object]", latest["baseline"])
    latest_cache = cast("dict[str, object]", latest["cache"])
    assert latest_baseline["status"] == "missing"
    assert latest_cache["used"] is False
    assert latest_cache["path"] == ".cache/codeclone/cache.json"
    latest_health = cast("dict[str, object]", latest["health"])
    assert isinstance(latest_health["score"], int)
    assert latest_health["grade"]


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
    assert str(first["id"]).startswith("clone:")

    finding = service.get_finding(finding_id=str(first["id"]))
    assert finding["id"] == first["id"]

    hotspots = service.list_hotspots(kind="highest_spread")
    assert hotspots["run_id"] == summary["run_id"]
    assert cast(int, hotspots["total"]) >= 1


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
    assert comparison["verdict"] == "regressed"
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
    assert remediation_payload["safe_refactor_shape"]
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

    clones = service.check_clones(
        run_id=run_id,
        path="pkg/dup.py",
        detail_level="summary",
    )
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
    assert json_summary["changed_paths"] == ["pkg/dup.py"]


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
    cache_summary = cast("dict[str, object]", summary["cache"])
    cache_meta = cast("dict[str, object]", report_meta["cache"])
    health_summary = cast("dict[str, object]", summary["health"])
    metrics_summary = cast("dict[str, object]", report_metrics["summary"])
    metrics_health = cast("dict[str, object]", metrics_summary["health"])

    assert cache_summary["path"] == cache_meta["path"]
    assert cache_summary["status"] == cache_meta["status"]
    assert cache_summary["used"] == cache_meta["used"]
    assert cache_summary["schema_version"] == cache_meta["schema_version"]
    assert health_summary == metrics_health


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
    assert latest_report["report_schema_version"] == "2.1"


def test_mcp_service_run_store_evicts_old_runs(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    _write_clone_fixture(first_root)
    _write_clone_fixture(second_root)
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


def test_mcp_service_refresh_cache_reports_save_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_clone_fixture(tmp_path)
    service = CodeCloneMCPService(history_limit=4)
    refresh_calls: list[str] = []

    def _fake_refresh(*, cache: object, analysis: object) -> None:
        refresh_calls.append("called")

    def _fake_save(self: Cache) -> None:
        raise CacheError("boom")

    monkeypatch.setattr(service, "_refresh_cache_projection", _fake_refresh)
    monkeypatch.setattr(Cache, "save", _fake_save)

    summary = service.analyze_repository(
        MCPAnalysisRequest(
            root=str(tmp_path),
            respect_pyproject=False,
            cache_policy="refresh",
        )
    )

    assert refresh_calls == ["called"]
    assert "Cache save failed: boom" in cast("list[str]", summary["warnings"])


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
    assert report_document["report_schema_version"] == "2.1"

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

    cache_without_projection = SimpleNamespace()
    service._refresh_cache_projection(
        cache=cast(Any, cache_without_projection),
        analysis=cast(
            Any,
            SimpleNamespace(
                suppressed_segment_groups=0,
                segment_groups_raw_digest=None,
                segment_groups={},
            ),
        ),
    )

    cache_with_projection = SimpleNamespace(segment_report_projection=())
    service._refresh_cache_projection(
        cache=cast(Any, cache_with_projection),
        analysis=cast(
            Any,
            SimpleNamespace(
                suppressed_segment_groups=0,
                segment_groups_raw_digest="digest",
                segment_groups={},
            ),
        ),
    )
    assert cache_with_projection.segment_report_projection is not None


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
    with pytest.raises(MCPServiceContractError):
        service._resolve_optional_path("cache.json", tmp_path)


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
        paths=(str(abs_dup), "./pkg/dup.py", "pkg"),
    )
    assert normalized == ("pkg", "pkg/dup.py")
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
    after_record = service._runs.get(str(after["run_id"]))

    comparison = service.compare_runs(
        run_id_before=str(before["run_id"]),
        run_id_after=str(after["run_id"]),
        focus="clones",
    )
    assert comparison["verdict"] == "improved"
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
            regressions=0,
            improvements=0,
            health_delta=0,
        )
        == "stable"
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
    assert "blast_radius" not in service._project_remediation(
        remediation,
        detail_level="summary",
    )
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

    complexity_group = mcp_service_mod._complexity_group_for_threshold_payload(
        {
            "qualname": "pkg.quality:hot",
            "relative_path": "pkg/quality.py",
            "start_line": 1,
            "end_line": 5,
            "cyclomatic_complexity": 99,
            "nesting_depth": 4,
            "risk": "high",
        },
        threshold=20,
        scan_root=str(tmp_path),
    )
    assert complexity_group is not None
    assert complexity_group["severity"] == "critical"
    assert mcp_service_mod._coupling_group_for_threshold_payload(
        {
            "qualname": "pkg.quality:coupled",
            "relative_path": "pkg/quality.py",
            "start_line": 1,
            "end_line": 5,
            "cbo": 3,
            "risk": "high",
            "coupled_classes": ["A", "B"],
        },
        threshold=1,
        scan_root=str(tmp_path),
    )
    assert mcp_service_mod._cohesion_group_for_threshold_payload(
        {
            "qualname": "pkg.quality:cohesive",
            "relative_path": "pkg/quality.py",
            "start_line": 1,
            "end_line": 5,
            "lcom4": 2,
            "risk": "medium",
            "method_count": 3,
            "instance_var_count": 2,
        },
        threshold=1,
        scan_root=str(tmp_path),
    )
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
    ) -> dict[str, object]:
        if finding_id == "missing":
            raise MCPFindingNotFoundError("missing")
        return original_get_finding(finding_id=finding_id, run_id=run_id)

    monkeypatch.setattr(service, "get_finding", _patched_get_finding)
    service._review_state[run_id] = OrderedDict([("missing", None)])
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
    assert previous_same_root.run_id == first_same_root["run_id"]
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
        report_json="{}",
        summary={"run_id": "design", "health": {"score": 80, "grade": "B"}},
        changed_paths=(),
        changed_projection=None,
        warnings=(),
        failures=(),
        analysis=cast(Any, SimpleNamespace(suggestions=[])),
        new_func=frozenset(),
        new_block=frozenset(),
        metrics_diff=None,
    )
    findings_section = cast(
        "dict[str, object]",
        fake_design_record.report_document["findings"],
    )
    fake_design_groups = cast("dict[str, object]", findings_section["groups"])
    assert (
        len(
            service._design_groups_for_record(
                fake_design_record,
                groups=fake_design_groups,
            )
        )
        == 3
    )
    wrapped_group = service._design_singleton_group(
        category="cohesion",
        kind="class_hotspot",
        severity="warning",
        qualname="pkg.quality:cohesive",
        filepath="pkg/quality.py",
        start_line=1,
        end_line=5,
        item_data={"lcom4": 2},
        facts={"lcom4": 2},
        scan_root=str(tmp_path),
    )
    assert wrapped_group["category"] == "cohesion"
    detail_payload = service._project_finding_detail(
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
        report_document={
            **record.report_document,
            "derived": {"hotlists": {"highest_spread_ids": ["missing-id"]}},
        },
        report_json=record.report_json,
        summary=record.summary,
        changed_paths=record.changed_paths,
        changed_projection=record.changed_projection,
        warnings=record.warnings,
        failures=record.failures,
        analysis=record.analysis,
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
    metrics_diff = cast("dict[str, object]", summary["metrics_diff"])
    assert metrics_diff["new_high_risk_functions"] == 1
    assert "cache warning" in cast("list[str]", summary["warnings"])
    analysis = cast(
        Any,
        SimpleNamespace(
            suppressed_segment_groups=0,
            segment_groups_raw_digest="digest",
            segment_groups={},
        ),
    )
    service._refresh_cache_projection(cache=cache_with_warning, analysis=analysis)
    service._refresh_cache_projection(cache=cache_with_warning, analysis=analysis)
