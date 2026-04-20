# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from codeclone.cache import (
    ApiParamSpecDict,
    CacheEntry,
    ModuleApiSurfaceDict,
    PublicSymbolDict,
)
from codeclone.core._types import (
    _as_sorted_str_tuple,
    _class_metric_sort_key,
    _module_dep_sort_key,
    _module_names_from_units,
)
from codeclone.core.bootstrap import _resolve_optional_runtime_path
from codeclone.core.coverage_payload import _coverage_join_rows, _coverage_join_summary
from codeclone.core.discovery_cache import (
    _api_param_spec_from_cache_dict,
    _api_surface_from_cache_dict,
    _cache_dict_int_fields,
    _cache_dict_module_fields,
    _docstring_coverage_from_cache_dict,
    _public_symbol_from_cache_dict,
    _typing_coverage_from_cache_dict,
)
from codeclone.core.discovery_cache import (
    load_cached_metrics_extended as _load_cached_metrics_extended,
)
from codeclone.core.metrics_payload import (
    _enrich_metrics_report_payload,
    build_metrics_report_payload,
)
from codeclone.core.parallelism import _should_use_parallel
from codeclone.core.pipeline import compute_project_metrics
from codeclone.metrics import build_overloaded_modules_payload
from codeclone.models import (
    ApiBreakingChange,
    ApiParamSpec,
    ApiSurfaceSnapshot,
    ClassMetrics,
    CoverageJoinResult,
    DeadCandidate,
    DeadItem,
    HealthScore,
    MetricsDiff,
    ModuleApiSurface,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    ProjectMetrics,
    PublicSymbol,
    UnitCoverageFact,
)
from codeclone.report.gates import (
    MetricGateConfig,
    gate_state_from_project_metrics,
    metric_gate_reasons_for_state,
)
from codeclone.utils.coerce import as_int as _as_int
from codeclone.utils.coerce import as_str as _as_str


def _project_metrics(*, dead_confidence: str = "high") -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=10.0,
        complexity_max=30,
        high_risk_functions=("pkg.mod:hot",),
        coupling_avg=5.0,
        coupling_max=12,
        high_risk_classes=("pkg.mod:Service",),
        cohesion_avg=2.5,
        cohesion_max=4,
        low_cohesion_classes=("pkg.mod:Service",),
        dependency_modules=2,
        dependency_edges=1,
        dependency_edge_list=(
            ModuleDep(source="pkg.mod", target="pkg.dep", import_type="import", line=1),
        ),
        dependency_cycles=(("pkg.mod", "pkg.dep"),),
        dependency_max_depth=9,
        dependency_longest_chains=(("pkg.mod", "pkg.dep"),),
        dead_code=(
            DeadItem(
                qualname="pkg.mod:dead",
                filepath="pkg/mod.py",
                start_line=1,
                end_line=2,
                kind="function",
                confidence="high" if dead_confidence == "high" else "medium",
            ),
        ),
        health=HealthScore(total=50, grade="D", dimensions={"health": 50}),
    )


def _project_metrics_with_adoption_and_api() -> ProjectMetrics:
    return replace(
        _project_metrics(),
        typing_param_total=4,
        typing_param_annotated=3,
        typing_return_total=2,
        typing_return_annotated=1,
        typing_any_count=1,
        docstring_public_total=3,
        docstring_public_documented=2,
        typing_modules=(
            ModuleTypingCoverage(
                module="pkg.mod",
                filepath="pkg/mod.py",
                callable_count=2,
                params_total=4,
                params_annotated=3,
                returns_total=2,
                returns_annotated=1,
                any_annotation_count=1,
            ),
        ),
        docstring_modules=(
            ModuleDocstringCoverage(
                module="pkg.mod",
                filepath="pkg/mod.py",
                public_symbol_total=3,
                public_symbol_documented=2,
            ),
        ),
        api_surface=ApiSurfaceSnapshot(
            modules=(
                ModuleApiSurface(
                    module="pkg.mod",
                    filepath="pkg/mod.py",
                    symbols=(
                        PublicSymbol(
                            qualname="pkg.mod:run",
                            kind="function",
                            start_line=10,
                            end_line=12,
                            params=(
                                ApiParamSpec(
                                    name="value",
                                    kind="pos_or_kw",
                                    has_default=False,
                                    annotation_hash="int",
                                ),
                            ),
                            returns_hash="int",
                        ),
                    ),
                ),
            )
        ),
    )


def _metric_gate_reasons_from_metrics(
    *,
    project_metrics: ProjectMetrics,
    coverage_join: CoverageJoinResult | None,
    metrics_diff: MetricsDiff | None,
    config: MetricGateConfig,
) -> tuple[str, ...]:
    state = gate_state_from_project_metrics(
        project_metrics=project_metrics,
        coverage_join=coverage_join,
        metrics_diff=metrics_diff,
    )
    return metric_gate_reasons_for_state(state=state, config=config)


def test_pipeline_basic_helpers_and_sort_keys() -> None:
    assert _as_int(True) == 1
    assert _as_int("15") == 15
    assert _as_int("bad", default=7) == 7
    assert _as_int(1.5, default=3) == 3
    assert _as_str("value", default="x") == "value"
    assert _as_str(1, default="x") == "x"
    assert _as_sorted_str_tuple(("a", "b")) == ()
    assert _as_sorted_str_tuple(["b", "a", "b", ""]) == ("a", "b")
    assert _should_use_parallel(files_count=100, processes=1) is False

    dep = ModuleDep(source="a", target="b", import_type="import", line=2)
    cls = ClassMetrics(
        qualname="pkg.mod:Service",
        filepath="pkg/mod.py",
        start_line=10,
        end_line=30,
        cbo=3,
        lcom4=2,
        method_count=4,
        instance_var_count=2,
        risk_coupling="low",
        risk_cohesion="low",
    )
    assert _module_dep_sort_key(dep) == ("a", "b", "import", 2)
    assert _class_metric_sort_key(cls) == ("pkg/mod.py", 10, 30, "pkg.mod:Service")


def test_module_names_from_units_extracts_module_prefixes() -> None:
    units = (
        {"qualname": "pkg.core:build"},
        {"qualname": "pkg.utils.helper"},
        {"qualname": ""},
    )
    assert _module_names_from_units(units) == frozenset(
        {"pkg.core", "pkg.utils.helper"}
    )


def test_optional_runtime_path_resolves_and_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _resolve_optional_runtime_path(None, root=tmp_path) is None
    assert _resolve_optional_runtime_path(" ", root=tmp_path) is None
    assert (
        _resolve_optional_runtime_path("coverage.xml", root=tmp_path)
        == (tmp_path / "coverage.xml").resolve()
    )

    def _raise_os_error(
        _self: Path,
        *_args: object,
        **_kwargs: object,
    ) -> Path:
        raise OSError("path resolution failed")

    monkeypatch.setattr(Path, "resolve", _raise_os_error)
    assert (
        _resolve_optional_runtime_path("coverage.xml", root=tmp_path)
        == (tmp_path / "coverage.xml").absolute()
    )


def test_compute_project_metrics_respects_skip_flags() -> None:
    project_metrics, dep_graph, dead_items = compute_project_metrics(
        units=(
            {
                "qualname": "pkg.mod:run",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 5,
                "cyclomatic_complexity": 3,
                "nesting_depth": 1,
                "risk": "high",
            },
        ),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(
            DeadCandidate(
                qualname="pkg.mod:unused",
                local_name="unused",
                filepath="pkg/mod.py",
                start_line=7,
                end_line=9,
                kind="function",
            ),
        ),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset(),
        files_found=1,
        files_analyzed_or_cached=1,
        function_clone_groups=0,
        block_clone_groups=0,
        skip_dependencies=True,
        skip_dead_code=True,
    )
    assert dep_graph.modules == frozenset()
    assert dead_items == ()
    assert project_metrics.dependency_modules == 0
    assert project_metrics.dead_code == ()


def test_build_metrics_report_payload_includes_suppressed_dead_code_items() -> None:
    payload = build_metrics_report_payload(
        project_metrics=_project_metrics(dead_confidence="high"),
        units=(),
        class_metrics=(),
        suppressed_dead_code=(
            DeadItem(
                qualname="pkg.mod:suppressed_dead",
                filepath="pkg/mod.py",
                start_line=10,
                end_line=12,
                kind="function",
                confidence="high",
            ),
        ),
    )
    dead_code = payload["dead_code"]
    assert isinstance(dead_code, dict)
    summary = dead_code["summary"]
    assert summary == {"total": 1, "critical": 1, "high_confidence": 1, "suppressed": 1}
    suppressed_items = dead_code["suppressed_items"]
    assert suppressed_items == [
        {
            "qualname": "pkg.mod:suppressed_dead",
            "filepath": "pkg/mod.py",
            "start_line": 10,
            "end_line": 12,
            "kind": "function",
            "confidence": "high",
            "suppressed_by": [{"rule": "dead-code", "source": "inline_codeclone"}],
        }
    ]


def test_build_metrics_report_payload_includes_adoption_and_api_surface_families() -> (
    None
):
    payload = build_metrics_report_payload(
        project_metrics=_project_metrics_with_adoption_and_api(),
        units=(),
        class_metrics=(),
        suppressed_dead_code=(),
    )

    coverage_adoption = cast(dict[str, object], payload["coverage_adoption"])
    assert coverage_adoption["summary"] == {
        "modules": 1,
        "params_total": 4,
        "params_annotated": 3,
        "param_permille": 750,
        "returns_total": 2,
        "returns_annotated": 1,
        "return_permille": 500,
        "public_symbol_total": 3,
        "public_symbol_documented": 2,
        "docstring_permille": 667,
        "typing_any_count": 1,
    }
    assert coverage_adoption["items"] == [
        {
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "callable_count": 2,
            "params_total": 4,
            "params_annotated": 3,
            "param_permille": 750,
            "returns_total": 2,
            "returns_annotated": 1,
            "return_permille": 500,
            "any_annotation_count": 1,
            "public_symbol_total": 3,
            "public_symbol_documented": 2,
            "docstring_permille": 667,
        }
    ]

    api_surface = cast(dict[str, object], payload["api_surface"])
    assert api_surface["summary"] == {
        "enabled": True,
        "modules": 1,
        "public_symbols": 1,
        "added": 0,
        "breaking": 0,
        "strict_types": False,
    }
    assert api_surface["items"] == [
        {
            "record_kind": "symbol",
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "qualname": "pkg.mod:run",
            "start_line": 10,
            "end_line": 12,
            "symbol_kind": "function",
            "exported_via": "name",
            "params_total": 1,
            "params": [
                {
                    "name": "value",
                    "kind": "pos_or_kw",
                    "has_default": False,
                    "annotated": True,
                }
            ],
            "returns_annotated": True,
        }
    ]


def test_metrics_payload_includes_overloaded_modules_for_small_population() -> None:
    payload = build_metrics_report_payload(
        scan_root="/repo",
        project_metrics=_project_metrics(dead_confidence="high"),
        units=(
            {
                "qualname": "pkg.alpha:run",
                "filepath": "/repo/pkg/alpha.py",
                "cyclomatic_complexity": 12,
            },
            {
                "qualname": "tests.test_beta:run",
                "filepath": "/repo/tests/test_beta.py",
                "cyclomatic_complexity": 2,
            },
        ),
        class_metrics=(),
        module_deps=(
            ModuleDep(
                source="pkg.alpha",
                target="tests.test_beta",
                import_type="import",
                line=1,
            ),
        ),
        source_stats_by_file=(
            ("/repo/pkg/alpha.py", 240, 3, 1, 1),
            ("/repo/tests/test_beta.py", 40, 1, 0, 0),
        ),
        suppressed_dead_code=(),
    )

    overloaded_modules = payload["overloaded_modules"]
    assert isinstance(overloaded_modules, dict)
    summary = overloaded_modules["summary"]
    assert summary["total"] == 2
    assert summary["candidates"] == 0
    assert summary["population_status"] == "limited"
    assert summary["top_score"] >= summary["average_score"] >= 0.0
    assert summary["candidate_score_cutoff"] <= 1.0
    assert summary["candidate_score_cutoff"] >= summary["top_score"]
    items = overloaded_modules["items"]
    assert [item["module"] for item in items] == ["pkg.alpha", "tests.test_beta"]
    assert items[0]["candidate_status"] == "ranked_only"
    assert items[0]["candidate_reasons"] == ["size_pressure", "dependency_pressure"]
    assert items[0]["source_kind"] == "production"
    assert items[1]["candidate_status"] == "ranked_only"
    assert items[1]["candidate_reasons"] == ["dependency_pressure"]
    assert items[1]["source_kind"] == "tests"


def test_build_overloaded_modules_payload_flags_project_relative_candidates() -> None:
    scan_root = "/repo"
    source_stats = [
        (f"{scan_root}/pkg/core.py", 2000, 24, 4, 2),
        *((f"{scan_root}/pkg/mod_{idx}.py", 40 + idx, 1, 0, 0) for idx in range(20)),
    ]
    units = [
        *(
            {
                "qualname": f"pkg.core:fn_{idx}",
                "filepath": f"{scan_root}/pkg/core.py",
                "cyclomatic_complexity": 8 + (idx % 4),
            }
            for idx in range(24)
        ),
        *(
            {
                "qualname": f"pkg.mod_{idx}:fn",
                "filepath": f"{scan_root}/pkg/mod_{idx}.py",
                "cyclomatic_complexity": 1,
            }
            for idx in range(20)
        ),
    ]
    deps = [
        *(
            ModuleDep(
                source=f"pkg.mod_{idx}",
                target="pkg.core",
                import_type="import",
                line=1,
            )
            for idx in range(10)
        ),
        *(
            ModuleDep(
                source="pkg.core",
                target=f"pkg.mod_{idx}",
                import_type="import",
                line=idx + 1,
            )
            for idx in range(10, 20)
        ),
    ]

    payload = build_overloaded_modules_payload(
        scan_root=scan_root,
        source_stats_by_file=source_stats,
        units=units,
        class_metrics=(),
        module_deps=deps,
    )

    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["population_status"] == "ok"
    assert summary["candidates"] >= 1
    items = payload["items"]
    assert isinstance(items, list)
    first = items[0]
    assert isinstance(first, dict)
    assert first["module"] == "pkg.core"
    assert first["candidate_status"] == "candidate"
    assert first["candidate_reasons"] == [
        "size_pressure",
        "dependency_pressure",
        "hub_like_shape",
    ]


def test_load_cached_metrics_ignores_referenced_names_from_test_files() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 1},
        "units": [],
        "blocks": [],
        "segments": [],
        "referenced_names": ["orphan", "helper"],
    }
    _, _, _, test_names, test_qualnames, *_ = _load_cached_metrics_extended(
        entry,
        filepath="pkg/tests/test_mod.py",
    )
    _, _, _, regular_names, regular_qualnames, *_ = _load_cached_metrics_extended(
        entry,
        filepath="pkg/mod.py",
    )
    assert test_names == frozenset()
    assert test_qualnames == frozenset()
    assert regular_names == frozenset({"helper", "orphan"})
    assert regular_qualnames == frozenset()


def test_load_cached_metrics_preserves_coupled_classes() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 1},
        "units": [],
        "blocks": [],
        "segments": [],
        "class_metrics": [
            {
                "qualname": "pkg.mod:Service",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 2,
                "lcom4": 1,
                "method_count": 3,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "low",
                "coupled_classes": ["TypeB", "TypeA", "TypeA"],
            }
        ],
    }
    class_metrics, _, _, _, _, *_ = _load_cached_metrics_extended(
        entry,
        filepath="pkg/mod.py",
    )
    assert len(class_metrics) == 1
    assert class_metrics[0].coupled_classes == ("TypeA", "TypeB")


def test_load_cached_metrics_preserves_dead_candidate_suppressions() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 1},
        "units": [],
        "blocks": [],
        "segments": [],
        "dead_candidates": [
            {
                "qualname": "pkg.mod:runtime_hook",
                "local_name": "runtime_hook",
                "filepath": "pkg/mod.py",
                "start_line": 10,
                "end_line": 11,
                "kind": "function",
                "suppressed_rules": ["dead-code", "dead-code"],
            }
        ],
    }
    _, _, dead_candidates, _, _, *_ = _load_cached_metrics_extended(
        entry,
        filepath="pkg/mod.py",
    )
    assert len(dead_candidates) == 1
    assert dead_candidates[0].suppressed_rules == ("dead-code",)


def test_pipeline_cache_decode_helpers_cover_invalid_and_valid_payloads() -> None:
    assert _cache_dict_module_fields(1) is None
    assert _cache_dict_module_fields({"module": "pkg.mod"}) is None
    assert _cache_dict_int_fields({"count": "x"}, "count") is None
    assert (
        _typing_coverage_from_cache_dict(
            {
                "module": "pkg.mod",
                "filepath": "pkg/mod.py",
                "callable_count": "bad",
            }
        )
        is None
    )
    assert (
        _docstring_coverage_from_cache_dict(
            {
                "module": "pkg.mod",
                "filepath": "pkg/mod.py",
                "public_symbol_total": 1,
                "public_symbol_documented": "bad",
            }
        )
        is None
    )
    assert (
        _api_param_spec_from_cache_dict(
            cast(
                "ApiParamSpecDict",
                {
                    "name": "value",
                    "kind": "pos_or_kw",
                    "has_default": "bad",
                    "annotation_hash": "",
                },
            )
        )
        is None
    )
    assert (
        _public_symbol_from_cache_dict(
            cast(
                "PublicSymbolDict",
                {
                    "qualname": "pkg.mod:run",
                    "kind": "function",
                    "start_line": 1,
                    "end_line": 2,
                    "exported_via": "name",
                    "returns_hash": "",
                    "params": ["bad"],
                },
            )
        )
        is None
    )
    assert (
        _api_surface_from_cache_dict(
            cast(
                "ModuleApiSurfaceDict",
                {
                    "module": "pkg.mod",
                    "filepath": "pkg/mod.py",
                    "all_declared": ["run"],
                    "symbols": ["bad"],
                },
            )
        )
        is None
    )

    valid_surface = _api_surface_from_cache_dict(
        {
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "all_declared": ["run", "run"],
            "symbols": [
                {
                    "qualname": "pkg.mod:run",
                    "kind": "function",
                    "start_line": 10,
                    "end_line": 12,
                    "exported_via": "name",
                    "returns_hash": "int",
                    "params": [
                        {
                            "name": "value",
                            "kind": "pos_or_kw",
                            "has_default": False,
                            "annotation_hash": "int",
                        }
                    ],
                }
            ],
        }
    )
    assert valid_surface is not None
    assert valid_surface.all_declared == ("run",)
    assert valid_surface.symbols[0].params[0].annotation_hash == "int"


def test_load_cached_metrics_extended_decodes_adoption_and_api_surface() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 1},
        "units": [],
        "blocks": [],
        "segments": [],
        "typing_coverage": {
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "callable_count": 2,
            "params_total": 4,
            "params_annotated": 3,
            "returns_total": 2,
            "returns_annotated": 1,
            "any_annotation_count": 1,
        },
        "docstring_coverage": {
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "public_symbol_total": 3,
            "public_symbol_documented": 2,
        },
        "api_surface": {
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "all_declared": ["run"],
            "symbols": [
                {
                    "qualname": "pkg.mod:run",
                    "kind": "function",
                    "start_line": 10,
                    "end_line": 12,
                    "exported_via": "name",
                    "returns_hash": "int",
                    "params": [],
                }
            ],
        },
    }
    *_, typing_coverage, docstring_coverage, api_surface = (
        _load_cached_metrics_extended(
            entry,
            filepath="pkg/mod.py",
        )
    )
    assert typing_coverage is not None
    assert docstring_coverage is not None
    assert api_surface is not None
    assert typing_coverage.any_annotation_count == 1
    assert docstring_coverage.public_symbol_documented == 2
    assert api_surface.symbols[0].qualname == "pkg.mod:run"


def test_metric_gate_reasons_collects_all_enabled_reasons() -> None:
    reasons = _metric_gate_reasons_from_metrics(
        project_metrics=_project_metrics(dead_confidence="high"),
        coverage_join=None,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=("pkg.mod:new_hot",),
            new_high_coupling_classes=("pkg.mod:new_class",),
            new_cycles=(("pkg.x", "pkg.y"),),
            new_dead_code=("pkg.mod:new_dead",),
            health_delta=-1,
        ),
        config=MetricGateConfig(
            fail_complexity=20,
            fail_coupling=10,
            fail_cohesion=3,
            fail_cycles=True,
            fail_dead_code=True,
            fail_health=70,
            fail_on_new_metrics=True,
        ),
    )
    assert len(reasons) == 11
    assert any(reason.startswith("Complexity threshold exceeded") for reason in reasons)
    assert any(reason.startswith("Coupling threshold exceeded") for reason in reasons)
    assert any(reason.startswith("Cohesion threshold exceeded") for reason in reasons)
    assert any(reason.startswith("Dependency cycles detected") for reason in reasons)
    assert any(reason.startswith("Dead code detected") for reason in reasons)
    assert any(reason.startswith("Health score below threshold") for reason in reasons)
    assert any(reason.startswith("New high-risk functions") for reason in reasons)
    assert any(reason.startswith("New high-coupling classes") for reason in reasons)
    assert any(reason.startswith("New dependency cycles") for reason in reasons)
    assert any(reason.startswith("New dead code items") for reason in reasons)
    assert any(reason.startswith("Health score regressed") for reason in reasons)


def test_enrich_metrics_report_payload_adds_docstring_and_breaking_api_rows() -> None:
    metrics_diff = MetricsDiff(
        new_high_risk_functions=(),
        new_high_coupling_classes=(),
        new_cycles=(),
        new_dead_code=(),
        health_delta=0,
        typing_param_permille_delta=-25,
        typing_return_permille_delta=0,
        docstring_permille_delta=10,
        new_api_symbols=("pkg.mod:added",),
        new_api_breaking_changes=cast(
            "tuple[ApiBreakingChange, ...]",
            (
                ApiBreakingChange(
                    qualname="pkg.mod:old",
                    filepath="pkg/mod.py",
                    start_line=20,
                    end_line=21,
                    symbol_kind="function",
                    change_kind="removed",
                    detail="Removed from the public API surface.",
                ),
                "ignored",
            ),
        ),
    )
    base_payload = build_metrics_report_payload(
        project_metrics=replace(
            _project_metrics_with_adoption_and_api(),
            typing_modules=(),
            docstring_modules=(
                ModuleDocstringCoverage(
                    module="pkg.docs",
                    filepath="pkg/docs.py",
                    public_symbol_total=2,
                    public_symbol_documented=1,
                ),
            ),
        ),
        units=(),
        class_metrics=(),
        suppressed_dead_code=(),
    )
    payload = _enrich_metrics_report_payload(
        metrics_payload=base_payload,
        metrics_diff=metrics_diff,
        coverage_adoption_diff_available=True,
        api_surface_diff_available=True,
    )

    coverage_adoption = cast(dict[str, object], payload["coverage_adoption"])
    adoption_items = cast(list[dict[str, object]], coverage_adoption["items"])
    api_surface = cast(dict[str, object], payload["api_surface"])
    api_summary = cast(dict[str, object], api_surface["summary"])
    api_items = cast(list[dict[str, object]], api_surface["items"])

    assert any(item["module"] == "pkg.docs" for item in adoption_items)
    assert api_summary["baseline_diff_available"] is True
    assert api_summary["added"] == 1
    assert api_summary["breaking"] == 2
    assert any(item.get("record_kind") == "breaking_change" for item in api_items)


def test_enrich_metrics_report_payload_hides_api_diff_without_api_baseline() -> None:
    payload = _enrich_metrics_report_payload(
        metrics_payload=build_metrics_report_payload(
            project_metrics=_project_metrics_with_adoption_and_api(),
            units=(),
            class_metrics=(),
            suppressed_dead_code=(),
        ),
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=0,
            typing_param_permille_delta=10,
            typing_return_permille_delta=0,
            docstring_permille_delta=0,
            new_api_symbols=("pkg.mod:added",),
            new_api_breaking_changes=(
                ApiBreakingChange(
                    qualname="pkg.mod:run",
                    filepath="pkg/mod.py",
                    start_line=1,
                    end_line=2,
                    symbol_kind="function",
                    change_kind="removed",
                    detail="Removed from the public API surface.",
                ),
            ),
        ),
        coverage_adoption_diff_available=True,
        api_surface_diff_available=False,
    )

    api_surface = cast(dict[str, object], payload["api_surface"])
    api_summary = cast(dict[str, object], api_surface["summary"])
    api_items = cast(list[dict[str, object]], api_surface["items"])

    assert api_summary["baseline_diff_available"] is False
    assert api_summary["added"] == 0
    assert api_summary["breaking"] == 0
    assert not any(item.get("record_kind") == "breaking_change" for item in api_items)


def test_metric_gate_reasons_skip_disabled_and_non_critical_paths() -> None:
    reasons = _metric_gate_reasons_from_metrics(
        project_metrics=_project_metrics(dead_confidence="medium"),
        coverage_join=None,
        metrics_diff=None,
        config=MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=True,
            fail_health=-1,
            fail_on_new_metrics=True,
        ),
    )
    assert reasons == ()


def test_metric_gate_reasons_partial_new_metrics_paths() -> None:
    reasons = _metric_gate_reasons_from_metrics(
        project_metrics=_project_metrics(dead_confidence="medium"),
        coverage_join=None,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=("pkg.mod:new_class",),
            new_cycles=(),
            new_dead_code=("pkg.mod:new_dead",),
            health_delta=0,
        ),
        config=MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=True,
        ),
    )
    assert reasons == (
        "New high-coupling classes vs metrics baseline: 1.",
        "New dead code items vs metrics baseline: 1.",
    )


def test_metric_gate_reasons_new_metrics_optional_buckets_empty() -> None:
    reasons = _metric_gate_reasons_from_metrics(
        project_metrics=_project_metrics(dead_confidence="medium"),
        coverage_join=None,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(("pkg.a", "pkg.b"),),
            new_dead_code=(),
            health_delta=-2,
        ),
        config=MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=True,
        ),
    )
    assert reasons == (
        "New dependency cycles vs metrics baseline: 1.",
        "Health score regressed vs metrics baseline: delta=-2.",
    )


def test_metric_gate_reasons_include_adoption_and_api_surface_contracts() -> None:
    reasons = _metric_gate_reasons_from_metrics(
        project_metrics=_project_metrics(dead_confidence="medium"),
        coverage_join=None,
        metrics_diff=MetricsDiff(
            new_high_risk_functions=(),
            new_high_coupling_classes=(),
            new_cycles=(),
            new_dead_code=(),
            health_delta=0,
            typing_param_permille_delta=-125,
            typing_return_permille_delta=-250,
            docstring_permille_delta=-333,
            new_api_breaking_changes=(
                ApiBreakingChange(
                    qualname="pkg.mod:run",
                    filepath="pkg/mod.py",
                    start_line=10,
                    end_line=12,
                    symbol_kind="function",
                    change_kind="signature_break",
                    detail="Parameter value became required.",
                ),
            ),
        ),
        config=MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
            fail_on_typing_regression=True,
            fail_on_docstring_regression=True,
            fail_on_api_break=True,
            min_typing_coverage=80,
            min_docstring_coverage=70,
        ),
    )
    assert reasons == (
        "Typing coverage below threshold: coverage=0.0%, threshold=80%.",
        "Docstring coverage below threshold: coverage=0.0%, threshold=70%.",
        (
            "Typing coverage regressed vs metrics baseline: "
            "params_delta=-125, returns_delta=-250."
        ),
        "Docstring coverage regressed vs metrics baseline: delta=-333.",
        "Public API breaking changes vs metrics baseline: 1.",
    )


def test_coverage_join_summary_rows_and_gate_reasons() -> None:
    coverage_join = CoverageJoinResult(
        coverage_xml="/repo/coverage.xml",
        status="ok",
        hotspot_threshold_percent=50,
        files=1,
        measured_units=1,
        overall_executable_lines=4,
        overall_covered_lines=1,
        coverage_hotspots=1,
        scope_gap_hotspots=0,
        units=(
            UnitCoverageFact(
                qualname="pkg.mod:cold",
                filepath="/repo/pkg/mod.py",
                start_line=20,
                end_line=24,
                cyclomatic_complexity=2,
                risk="low",
                executable_lines=0,
                covered_lines=0,
                coverage_permille=0,
                coverage_status="missing_from_report",
            ),
            UnitCoverageFact(
                qualname="pkg.mod:hot",
                filepath="/repo/pkg/mod.py",
                start_line=1,
                end_line=4,
                cyclomatic_complexity=12,
                risk="high",
                executable_lines=4,
                covered_lines=1,
                coverage_permille=250,
                coverage_status="measured",
            ),
        ),
    )

    summary = _coverage_join_summary(coverage_join)
    rows = _coverage_join_rows(coverage_join)

    assert {
        "overall_permille": summary["overall_permille"],
        "missing_from_report_units": summary["missing_from_report_units"],
        "coverage_hotspots": summary["coverage_hotspots"],
        "scope_gap_hotspots": summary["scope_gap_hotspots"],
    } == {
        "overall_permille": 250,
        "missing_from_report_units": 1,
        "coverage_hotspots": 1,
        "scope_gap_hotspots": 0,
    }
    assert [
        (
            row["qualname"],
            row["coverage_hotspot"],
            row["scope_gap_hotspot"],
        )
        for row in rows
    ] == [
        ("pkg.mod:hot", True, False),
        ("pkg.mod:cold", False, False),
    ]
    assert _coverage_join_summary(None) == {}
    assert _coverage_join_rows(None) == []
    assert (
        _coverage_join_rows(
            CoverageJoinResult(
                coverage_xml="/repo/broken.xml",
                status="invalid",
                hotspot_threshold_percent=50,
                invalid_reason="broken xml",
            )
        )
        == []
    )

    reasons = _metric_gate_reasons_from_metrics(
        project_metrics=_project_metrics(dead_confidence="medium"),
        coverage_join=coverage_join,
        metrics_diff=None,
        config=MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
            fail_on_untested_hotspots=True,
            coverage_min=50,
        ),
    )
    assert reasons == ("Coverage hotspots detected: hotspots=1, threshold=50%.",)

    invalid_reasons = _metric_gate_reasons_from_metrics(
        project_metrics=_project_metrics(dead_confidence="medium"),
        coverage_join=CoverageJoinResult(
            coverage_xml="/repo/broken.xml",
            status="invalid",
            hotspot_threshold_percent=50,
            invalid_reason="broken xml",
        ),
        metrics_diff=None,
        config=MetricGateConfig(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
            fail_on_untested_hotspots=True,
        ),
    )
    assert invalid_reasons == ()
