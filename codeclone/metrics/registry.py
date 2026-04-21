# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable
from typing import TypeGuard

from ..domain.findings import CATEGORY_COHESION, CATEGORY_COMPLEXITY, CATEGORY_COUPLING
from ..domain.quality import RISK_HIGH
from ..models import (
    ApiSurfaceSnapshot,
    DeadItem,
    DepGraph,
    HealthScore,
    ModuleDep,
    ModuleDocstringCoverage,
    ModuleTypingCoverage,
    ProjectMetrics,
)
from ..utils.coerce import as_int as _as_int
from ..utils.coerce import as_str as _as_str
from ._base import MetricAggregate, MetricFamily, MetricProjectContext, MetricResult
from .dead_code import find_unused
from .dependencies import build_dep_graph
from .health import HealthInputs, compute_health


def _group_item_sort_key(item: object) -> tuple[str, int, int, str]:
    if not isinstance(item, dict):
        return "", 0, 0, ""
    return (
        _as_str(item.get("filepath")),
        _as_int(item.get("start_line")),
        _as_int(item.get("end_line")),
        _as_str(item.get("qualname")),
    )


def _class_metric_sort_key(metric: object) -> tuple[str, int, int, str]:
    filepath = getattr(metric, "filepath", "")
    start_line = getattr(metric, "start_line", 0)
    end_line = getattr(metric, "end_line", 0)
    qualname = getattr(metric, "qualname", "")
    return str(filepath), int(start_line), int(end_line), str(qualname)


def _module_names_from_units(units: tuple[object, ...]) -> frozenset[str]:
    modules: set[str] = set()
    for item in units:
        if not isinstance(item, dict):
            continue
        qualname = _as_str(item.get("qualname"))
        module_name = qualname.split(":", 1)[0] if ":" in qualname else qualname
        if module_name:
            modules.add(module_name)
    return frozenset(sorted(modules))


def _empty_dep_graph() -> DepGraph:
    return DepGraph(
        modules=frozenset(),
        edges=(),
        cycles=(),
        max_depth=0,
        longest_chains=(),
    )


_EMPTY_HEALTH_SCORE = compute_health(
    HealthInputs(
        files_found=0,
        files_analyzed_or_cached=0,
        function_clone_groups=0,
        block_clone_groups=0,
        complexity_avg=0.0,
        complexity_max=0,
        high_risk_functions=0,
        coupling_avg=0.0,
        coupling_max=0,
        high_risk_classes=0,
        cohesion_avg=0.0,
        low_cohesion_classes=0,
        dependency_cycles=0,
        dependency_max_depth=0,
        dead_code_items=0,
    )
)


def _is_tuple_of_str(value: object) -> TypeGuard[tuple[str, ...]]:
    return isinstance(value, tuple) and all(isinstance(item, str) for item in value)


def _is_tuple_of_tuple_str(value: object) -> TypeGuard[tuple[tuple[str, ...], ...]]:
    return isinstance(value, tuple) and all(_is_tuple_of_str(item) for item in value)


def _is_tuple_of_dead_items(value: object) -> TypeGuard[tuple[DeadItem, ...]]:
    return isinstance(value, tuple) and all(
        isinstance(item, DeadItem) for item in value
    )


def _is_tuple_of_module_deps(value: object) -> TypeGuard[tuple[ModuleDep, ...]]:
    return isinstance(value, tuple) and all(
        isinstance(item, ModuleDep) for item in value
    )


def _is_tuple_of_typing_modules(
    value: object,
) -> TypeGuard[tuple[ModuleTypingCoverage, ...]]:
    return isinstance(value, tuple) and all(
        isinstance(item, ModuleTypingCoverage) for item in value
    )


def _is_tuple_of_docstring_modules(
    value: object,
) -> TypeGuard[tuple[ModuleDocstringCoverage, ...]]:
    return isinstance(value, tuple) and all(
        isinstance(item, ModuleDocstringCoverage) for item in value
    )


def project_metrics_defaults() -> dict[str, object]:
    return {
        "complexity_avg": 0.0,
        "complexity_max": 0,
        "high_risk_functions": (),
        "coupling_avg": 0.0,
        "coupling_max": 0,
        "high_risk_classes": (),
        "cohesion_avg": 0.0,
        "cohesion_max": 0,
        "low_cohesion_classes": (),
        "dependency_modules": 0,
        "dependency_edges": 0,
        "dependency_edge_list": (),
        "dependency_cycles": (),
        "dependency_max_depth": 0,
        "dependency_longest_chains": (),
        "dead_code": (),
        "health": _EMPTY_HEALTH_SCORE,
        "typing_param_total": 0,
        "typing_param_annotated": 0,
        "typing_return_total": 0,
        "typing_return_annotated": 0,
        "typing_any_count": 0,
        "docstring_public_total": 0,
        "docstring_public_documented": 0,
        "typing_modules": (),
        "docstring_modules": (),
        "api_surface": None,
    }


def build_project_metrics(project_fields: dict[str, object]) -> ProjectMetrics:
    return ProjectMetrics(
        complexity_avg=_result_float(project_fields, "complexity_avg"),
        complexity_max=_result_int(project_fields, "complexity_max"),
        high_risk_functions=_result_tuple_str(project_fields, "high_risk_functions"),
        coupling_avg=_result_float(project_fields, "coupling_avg"),
        coupling_max=_result_int(project_fields, "coupling_max"),
        high_risk_classes=_result_tuple_str(project_fields, "high_risk_classes"),
        cohesion_avg=_result_float(project_fields, "cohesion_avg"),
        cohesion_max=_result_int(project_fields, "cohesion_max"),
        low_cohesion_classes=_result_tuple_str(project_fields, "low_cohesion_classes"),
        dependency_modules=_result_int(project_fields, "dependency_modules"),
        dependency_edges=_result_int(project_fields, "dependency_edges"),
        dependency_edge_list=_result_module_deps(
            project_fields,
            "dependency_edge_list",
        ),
        dependency_cycles=_result_nested_tuple_str(
            project_fields,
            "dependency_cycles",
        ),
        dependency_max_depth=_result_int(project_fields, "dependency_max_depth"),
        dependency_longest_chains=_result_nested_tuple_str(
            project_fields,
            "dependency_longest_chains",
        ),
        dead_code=_result_dead_items(project_fields, "dead_code"),
        health=_result_health(project_fields, "health"),
        typing_param_total=_result_int(project_fields, "typing_param_total"),
        typing_param_annotated=_result_int(project_fields, "typing_param_annotated"),
        typing_return_total=_result_int(project_fields, "typing_return_total"),
        typing_return_annotated=_result_int(
            project_fields,
            "typing_return_annotated",
        ),
        typing_any_count=_result_int(project_fields, "typing_any_count"),
        docstring_public_total=_result_int(project_fields, "docstring_public_total"),
        docstring_public_documented=_result_int(
            project_fields,
            "docstring_public_documented",
        ),
        typing_modules=_result_typing_modules(project_fields, "typing_modules"),
        docstring_modules=_result_docstring_modules(
            project_fields,
            "docstring_modules",
        ),
        api_surface=_result_api_surface(project_fields, "api_surface"),
    )


def _result_float(result: dict[str, object], key: str) -> float:
    value = result.get(key)
    return float(value) if isinstance(value, int | float) else 0.0


def _result_int(result: dict[str, object], key: str) -> int:
    return _as_int(result.get(key), 0)


def _result_tuple_str(result: dict[str, object], key: str) -> tuple[str, ...]:
    value = result.get(key, ())
    return value if _is_tuple_of_str(value) else ()


def _result_nested_tuple_str(
    result: dict[str, object],
    key: str,
) -> tuple[tuple[str, ...], ...]:
    value = result.get(key, ())
    return value if _is_tuple_of_tuple_str(value) else ()


def _result_dead_items(
    result: dict[str, object],
    key: str,
) -> tuple[DeadItem, ...]:
    value = result.get(key, ())
    return value if _is_tuple_of_dead_items(value) else ()


def _result_module_deps(
    result: dict[str, object],
    key: str,
) -> tuple[ModuleDep, ...]:
    value = result.get(key, ())
    return value if _is_tuple_of_module_deps(value) else ()


def _result_health(result: dict[str, object], key: str) -> HealthScore:
    value = result.get(key)
    return value if isinstance(value, HealthScore) else _EMPTY_HEALTH_SCORE


def _result_typing_modules(
    result: dict[str, object],
    key: str,
) -> tuple[ModuleTypingCoverage, ...]:
    value = result.get(key, ())
    return value if _is_tuple_of_typing_modules(value) else ()


def _result_docstring_modules(
    result: dict[str, object],
    key: str,
) -> tuple[ModuleDocstringCoverage, ...]:
    value = result.get(key, ())
    return value if _is_tuple_of_docstring_modules(value) else ()


def _result_api_surface(
    result: dict[str, object],
    key: str,
) -> ApiSurfaceSnapshot | None:
    value = result.get(key)
    return value if isinstance(value, ApiSurfaceSnapshot) else None


def _memoized_result(
    context: MetricProjectContext,
    *,
    family_name: str,
    builder: Callable[[MetricProjectContext], MetricResult],
) -> MetricResult:
    cached = context.memo.get(family_name)
    if cached is not None:
        return cached
    result = builder(context)
    context.memo[family_name] = result
    return result


def _first_result(results: list[MetricResult]) -> MetricResult:
    return results[0] if results else {}


def _build_complexity_result(context: MetricProjectContext) -> MetricResult:
    unit_rows = tuple(sorted(context.units, key=_group_item_sort_key))
    complexities = tuple(
        max(1, _as_int(row.get("cyclomatic_complexity"), 1)) for row in unit_rows
    )
    complexity_max = max(complexities) if complexities else 0
    complexity_avg = (
        float(sum(complexities)) / float(len(complexities)) if complexities else 0.0
    )
    high_risk_functions = tuple(
        sorted(
            {
                _as_str(row.get("qualname"))
                for row in unit_rows
                if _as_str(row.get("risk")) == RISK_HIGH
            }
        )
    )
    return {
        "complexity_avg": complexity_avg,
        "complexity_max": complexity_max,
        "high_risk_functions": high_risk_functions,
    }


def _summarize_class_metric_family(
    context: MetricProjectContext,
    *,
    value_attr: str,
    risk_attr: str,
) -> tuple[float, int, tuple[str, ...]]:
    classes_sorted = tuple(sorted(context.class_metrics, key=_class_metric_sort_key))
    values = tuple(
        _as_int(getattr(metric, value_attr, 0), 0) for metric in classes_sorted
    )
    value_max = max(values) if values else 0
    value_avg = float(sum(values)) / float(len(values)) if values else 0.0
    high_risk_symbols = tuple(
        sorted(
            {
                metric.qualname
                for metric in classes_sorted
                if str(getattr(metric, risk_attr, "")) == RISK_HIGH
            }
        )
    )
    return value_avg, value_max, high_risk_symbols


def _compute_complexity_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name=CATEGORY_COMPLEXITY,
        builder=_build_complexity_result,
    )


def _aggregate_complexity_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    return MetricAggregate(
        project_fields={
            "complexity_avg": _result_float(result, "complexity_avg"),
            "complexity_max": _result_int(result, "complexity_max"),
            "high_risk_functions": _result_tuple_str(result, "high_risk_functions"),
        }
    )


def _build_coupling_result(context: MetricProjectContext) -> MetricResult:
    coupling_avg, coupling_max, high_risk_classes = _summarize_class_metric_family(
        context,
        value_attr="cbo",
        risk_attr="risk_coupling",
    )
    return {
        "coupling_avg": coupling_avg,
        "coupling_max": coupling_max,
        "high_risk_classes": high_risk_classes,
    }


def _compute_coupling_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name=CATEGORY_COUPLING,
        builder=_build_coupling_result,
    )


def _aggregate_coupling_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    return MetricAggregate(
        project_fields={
            "coupling_avg": _result_float(result, "coupling_avg"),
            "coupling_max": _result_int(result, "coupling_max"),
            "high_risk_classes": _result_tuple_str(result, "high_risk_classes"),
        }
    )


def _build_cohesion_result(context: MetricProjectContext) -> MetricResult:
    cohesion_avg, cohesion_max, low_cohesion_classes = _summarize_class_metric_family(
        context,
        value_attr="lcom4",
        risk_attr="risk_cohesion",
    )
    return {
        "cohesion_avg": cohesion_avg,
        "cohesion_max": cohesion_max,
        "low_cohesion_classes": low_cohesion_classes,
    }


def _compute_cohesion_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name=CATEGORY_COHESION,
        builder=_build_cohesion_result,
    )


def _aggregate_cohesion_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    return MetricAggregate(
        project_fields={
            "cohesion_avg": _result_float(result, "cohesion_avg"),
            "cohesion_max": _result_int(result, "cohesion_max"),
            "low_cohesion_classes": _result_tuple_str(result, "low_cohesion_classes"),
        }
    )


def _build_dependencies_result(context: MetricProjectContext) -> MetricResult:
    dep_graph = _empty_dep_graph()
    if not context.skip_dependencies:
        dep_graph = build_dep_graph(
            modules=_module_names_from_units(tuple(context.units)),
            deps=context.module_deps,
        )
    return {
        "dependency_modules": len(dep_graph.modules),
        "dependency_edges": len(dep_graph.edges),
        "dependency_edge_list": dep_graph.edges,
        "dependency_cycles": dep_graph.cycles,
        "dependency_max_depth": dep_graph.max_depth,
        "dependency_longest_chains": dep_graph.longest_chains,
        "dep_graph": dep_graph,
    }


def _compute_dependencies_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name="dependencies",
        builder=_build_dependencies_result,
    )


def _aggregate_dependencies_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    dep_graph = result.get("dep_graph")
    return MetricAggregate(
        project_fields={
            "dependency_modules": _result_int(result, "dependency_modules"),
            "dependency_edges": _result_int(result, "dependency_edges"),
            "dependency_edge_list": _result_module_deps(result, "dependency_edge_list"),
            "dependency_cycles": _result_nested_tuple_str(result, "dependency_cycles"),
            "dependency_max_depth": _result_int(result, "dependency_max_depth"),
            "dependency_longest_chains": _result_nested_tuple_str(
                result,
                "dependency_longest_chains",
            ),
        },
        artifacts=({"dep_graph": dep_graph} if isinstance(dep_graph, DepGraph) else {}),
    )


def _build_dead_code_result(context: MetricProjectContext) -> MetricResult:
    dead_items: tuple[DeadItem, ...] = ()
    if not context.skip_dead_code:
        dead_items = find_unused(
            definitions=tuple(context.dead_candidates),
            referenced_names=context.referenced_names,
            referenced_qualnames=context.referenced_qualnames,
        )
    return {
        "dead_code": dead_items,
        "dead_items": dead_items,
    }


def _compute_dead_code_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name="dead_code",
        builder=_build_dead_code_result,
    )


def _aggregate_dead_code_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    dead_items = result.get("dead_items")
    return MetricAggregate(
        project_fields={
            "dead_code": _result_dead_items(result, "dead_code"),
        },
        artifacts=({"dead_items": dead_items} if isinstance(dead_items, tuple) else {}),
    )


def _build_health_result(context: MetricProjectContext) -> MetricResult:
    complexity = _compute_complexity_family(context)
    coupling = _compute_coupling_family(context)
    cohesion = _compute_cohesion_family(context)
    dependencies = _compute_dependencies_family(context)
    dead_code = _compute_dead_code_family(context)
    health = compute_health(
        HealthInputs(
            files_found=context.files_found,
            files_analyzed_or_cached=context.files_analyzed_or_cached,
            function_clone_groups=context.function_clone_groups,
            block_clone_groups=context.block_clone_groups,
            complexity_avg=_result_float(complexity, "complexity_avg"),
            complexity_max=_result_int(complexity, "complexity_max"),
            high_risk_functions=len(
                _result_tuple_str(complexity, "high_risk_functions")
            ),
            coupling_avg=_result_float(coupling, "coupling_avg"),
            coupling_max=_result_int(coupling, "coupling_max"),
            high_risk_classes=len(_result_tuple_str(coupling, "high_risk_classes")),
            cohesion_avg=_result_float(cohesion, "cohesion_avg"),
            low_cohesion_classes=len(
                _result_tuple_str(cohesion, "low_cohesion_classes")
            ),
            dependency_cycles=len(
                _result_nested_tuple_str(dependencies, "dependency_cycles")
            ),
            dependency_max_depth=_result_int(dependencies, "dependency_max_depth"),
            dead_code_items=len(_result_dead_items(dead_code, "dead_code")),
        )
    )
    return {"health": health}


def _compute_health_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name="health",
        builder=_build_health_result,
    )


def _aggregate_health_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    return MetricAggregate(project_fields={"health": _result_health(result, "health")})


def _build_coverage_adoption_result(context: MetricProjectContext) -> MetricResult:
    typing_rows = tuple(
        sorted(context.typing_modules, key=lambda item: (item.filepath, item.module))
    )
    docstring_rows = tuple(
        sorted(context.docstring_modules, key=lambda item: (item.filepath, item.module))
    )
    return {
        "typing_param_total": sum(item.params_total for item in typing_rows),
        "typing_param_annotated": sum(item.params_annotated for item in typing_rows),
        "typing_return_total": sum(item.returns_total for item in typing_rows),
        "typing_return_annotated": sum(item.returns_annotated for item in typing_rows),
        "typing_any_count": sum(item.any_annotation_count for item in typing_rows),
        "docstring_public_total": sum(
            item.public_symbol_total for item in docstring_rows
        ),
        "docstring_public_documented": sum(
            item.public_symbol_documented for item in docstring_rows
        ),
        "typing_modules": typing_rows,
        "docstring_modules": docstring_rows,
    }


def _compute_coverage_adoption_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name="coverage_adoption",
        builder=_build_coverage_adoption_result,
    )


def _aggregate_coverage_adoption_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    return MetricAggregate(
        project_fields={
            "typing_param_total": _result_int(result, "typing_param_total"),
            "typing_param_annotated": _result_int(result, "typing_param_annotated"),
            "typing_return_total": _result_int(result, "typing_return_total"),
            "typing_return_annotated": _result_int(
                result,
                "typing_return_annotated",
            ),
            "typing_any_count": _result_int(result, "typing_any_count"),
            "docstring_public_total": _result_int(result, "docstring_public_total"),
            "docstring_public_documented": _result_int(
                result,
                "docstring_public_documented",
            ),
            "typing_modules": _result_typing_modules(result, "typing_modules"),
            "docstring_modules": _result_docstring_modules(
                result,
                "docstring_modules",
            ),
        }
    )


def _build_api_surface_result(context: MetricProjectContext) -> MetricResult:
    api_rows = tuple(
        sorted(context.api_modules, key=lambda item: (item.filepath, item.module))
    )
    return {
        "api_surface": ApiSurfaceSnapshot(modules=api_rows) if api_rows else None,
    }


def _compute_api_surface_family(context: MetricProjectContext) -> MetricResult:
    return _memoized_result(
        context,
        family_name="api_surface",
        builder=_build_api_surface_result,
    )


def _aggregate_api_surface_family(results: list[MetricResult]) -> MetricAggregate:
    result = _first_result(results)
    return MetricAggregate(project_fields={"api_surface": result.get("api_surface")})


def _compute_report_only_family(_context: MetricProjectContext) -> MetricResult:
    return {}


def _aggregate_empty_family(_results: list[MetricResult]) -> MetricAggregate:
    return MetricAggregate(project_fields={})


METRIC_FAMILIES: dict[str, MetricFamily] = {
    CATEGORY_COMPLEXITY: MetricFamily(
        name=CATEGORY_COMPLEXITY,
        compute=_compute_complexity_family,
        aggregate=_aggregate_complexity_family,
        report_section=CATEGORY_COMPLEXITY,
        baseline_key="max_complexity",
        gate_keys=("complexity_threshold", "new_high_risk_functions"),
        skippable_flag="skip_metrics",
    ),
    CATEGORY_COUPLING: MetricFamily(
        name=CATEGORY_COUPLING,
        compute=_compute_coupling_family,
        aggregate=_aggregate_coupling_family,
        report_section=CATEGORY_COUPLING,
        baseline_key="max_coupling",
        gate_keys=("coupling_threshold", "new_high_coupling_classes"),
        skippable_flag="skip_metrics",
    ),
    CATEGORY_COHESION: MetricFamily(
        name=CATEGORY_COHESION,
        compute=_compute_cohesion_family,
        aggregate=_aggregate_cohesion_family,
        report_section=CATEGORY_COHESION,
        baseline_key="max_cohesion",
        gate_keys=("cohesion_threshold",),
        skippable_flag="skip_metrics",
    ),
    "dependencies": MetricFamily(
        name="dependencies",
        compute=_compute_dependencies_family,
        aggregate=_aggregate_dependencies_family,
        report_section="dependencies",
        baseline_key="dependency_cycles",
        gate_keys=("dependency_cycles", "new_dependency_cycles"),
        skippable_flag="skip_metrics",
    ),
    "dead_code": MetricFamily(
        name="dead_code",
        compute=_compute_dead_code_family,
        aggregate=_aggregate_dead_code_family,
        report_section="dead_code",
        baseline_key="dead_code_items",
        gate_keys=("dead_code_high_confidence", "new_dead_code"),
        skippable_flag="skip_metrics",
    ),
    "health": MetricFamily(
        name="health",
        compute=_compute_health_family,
        aggregate=_aggregate_health_family,
        report_section="health",
        baseline_key="health_score",
        gate_keys=("health_threshold", "health_regression"),
        skippable_flag="skip_metrics",
    ),
    "coverage_adoption": MetricFamily(
        name="coverage_adoption",
        compute=_compute_coverage_adoption_family,
        aggregate=_aggregate_coverage_adoption_family,
        report_section="coverage_adoption",
        baseline_key="typing_param_permille",
        gate_keys=(
            "typing_coverage_threshold",
            "docstring_coverage_threshold",
            "typing_regression",
            "docstring_regression",
        ),
        skippable_flag="skip_metrics",
    ),
    "api_surface": MetricFamily(
        name="api_surface",
        compute=_compute_api_surface_family,
        aggregate=_aggregate_api_surface_family,
        report_section="api_surface",
        baseline_key=None,
        gate_keys=("api_breaking_changes",),
        skippable_flag="skip_metrics",
    ),
    "overloaded_modules": MetricFamily(
        name="overloaded_modules",
        compute=_compute_report_only_family,
        aggregate=_aggregate_empty_family,
        report_section="overloaded_modules",
        baseline_key=None,
        gate_keys=(),
        skippable_flag="skip_metrics",
    ),
    "coverage_join": MetricFamily(
        name="coverage_join",
        compute=_compute_report_only_family,
        aggregate=_aggregate_empty_family,
        report_section="coverage_join",
        baseline_key=None,
        gate_keys=("coverage_hotspots",),
        skippable_flag="skip_metrics",
    ),
}
