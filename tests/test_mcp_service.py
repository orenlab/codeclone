# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib
import json
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
    MCPRunNotFoundError,
    MCPServiceContractError,
    MCPServiceError,
)
from codeclone.models import MetricsDiff


def _write_clone_fixture(root: Path) -> None:
    root.joinpath("pkg").mkdir()
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
