# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from codeclone.cache import CacheEntry
from codeclone.metrics import build_overloaded_modules_payload
from codeclone.models import (
    ClassMetrics,
    DeadCandidate,
    DeadItem,
    HealthScore,
    MetricsDiff,
    ModuleDep,
    ProjectMetrics,
)
from codeclone.pipeline import (
    MetricGateConfig,
    _as_int,
    _as_sorted_str_tuple,
    _as_str,
    _class_metric_sort_key,
    _load_cached_metrics,
    _module_dep_sort_key,
    _module_names_from_units,
    _should_use_parallel,
    build_metrics_report_payload,
    compute_project_metrics,
    metric_gate_reasons,
)


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
    _, _, _, test_names, test_qualnames = _load_cached_metrics(
        entry,
        filepath="pkg/tests/test_mod.py",
    )
    _, _, _, regular_names, regular_qualnames = _load_cached_metrics(
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
    class_metrics, _, _, _, _ = _load_cached_metrics(entry, filepath="pkg/mod.py")
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
    _, _, dead_candidates, _, _ = _load_cached_metrics(entry, filepath="pkg/mod.py")
    assert len(dead_candidates) == 1
    assert dead_candidates[0].suppressed_rules == ("dead-code",)


def test_metric_gate_reasons_collects_all_enabled_reasons() -> None:
    reasons = metric_gate_reasons(
        project_metrics=_project_metrics(dead_confidence="high"),
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


def test_metric_gate_reasons_skip_disabled_and_non_critical_paths() -> None:
    reasons = metric_gate_reasons(
        project_metrics=_project_metrics(dead_confidence="medium"),
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
    reasons = metric_gate_reasons(
        project_metrics=_project_metrics(dead_confidence="medium"),
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
    reasons = metric_gate_reasons(
        project_metrics=_project_metrics(dead_confidence="medium"),
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
