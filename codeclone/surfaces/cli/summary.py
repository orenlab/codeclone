# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ... import ui_messages as ui
from ...core._types import AnalysisResult, DiscoveryResult, ProcessingResult
from ...models import MetricsDiff
from ...utils import coerce as _coerce

_as_int = _coerce.as_int
_as_mapping = _coerce.as_mapping


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    complexity_avg: float
    complexity_max: int
    high_risk_count: int
    coupling_avg: float
    coupling_max: int
    cohesion_avg: float
    cohesion_max: int
    cycles_count: int
    dead_code_count: int
    health_total: int
    health_grade: str
    dependency_avg_depth: float = 0.0
    dependency_p95_depth: int = 0
    dependency_max_depth: int = 0
    suppressed_dead_code_count: int = 0
    overloaded_modules_candidates: int = 0
    overloaded_modules_total: int = 0
    overloaded_modules_population_status: str = ""
    overloaded_modules_top_score: float = 0.0
    adoption_param_permille: int | None = None
    adoption_return_permille: int | None = None
    adoption_docstring_permille: int | None = None
    adoption_any_annotation_count: int = 0
    api_surface_enabled: bool = False
    api_surface_modules: int = 0
    api_surface_public_symbols: int = 0
    api_surface_added: int = 0
    api_surface_breaking: int = 0
    coverage_join_status: str = ""
    coverage_join_overall_permille: int = 0
    coverage_join_coverage_hotspots: int = 0
    coverage_join_scope_gap_hotspots: int = 0
    coverage_join_threshold_percent: int = 0
    coverage_join_source_label: str = ""


@dataclass(frozen=True, slots=True)
class ChangedScopeSnapshot:
    paths_count: int
    findings_total: int
    findings_new: int
    findings_known: int


class _Printer(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def build_summary_counts(
    *,
    discovery_result: DiscoveryResult,
    processing_result: ProcessingResult,
) -> dict[str, int]:
    return {
        "analyzed_lines": processing_result.analyzed_lines
        + int(getattr(discovery_result, "cached_lines", 0)),
        "analyzed_functions": processing_result.analyzed_functions
        + int(getattr(discovery_result, "cached_functions", 0)),
        "analyzed_methods": processing_result.analyzed_methods
        + int(getattr(discovery_result, "cached_methods", 0)),
        "analyzed_classes": processing_result.analyzed_classes
        + int(getattr(discovery_result, "cached_classes", 0)),
    }


def build_metrics_snapshot(
    *,
    analysis_result: AnalysisResult,
    metrics_diff: MetricsDiff | None,
    api_surface_diff_available: bool,
) -> MetricsSnapshot:
    project_metrics = analysis_result.project_metrics
    if project_metrics is None:
        raise ValueError("Metrics snapshot requires computed project metrics.")
    metrics_payload_map = _as_mapping(analysis_result.metrics_payload)
    overloaded_modules_summary = _as_mapping(
        _as_mapping(metrics_payload_map.get("overloaded_modules")).get("summary")
    )
    adoption_summary = _as_mapping(
        _as_mapping(metrics_payload_map.get("coverage_adoption")).get("summary")
    )
    api_surface_summary = _as_mapping(
        _as_mapping(metrics_payload_map.get("api_surface")).get("summary")
    )
    coverage_join_summary = _as_mapping(
        _as_mapping(metrics_payload_map.get("coverage_join")).get("summary")
    )
    coverage_join_source = str(coverage_join_summary.get("source", "")).strip()
    return MetricsSnapshot(
        complexity_avg=project_metrics.complexity_avg,
        complexity_max=project_metrics.complexity_max,
        high_risk_count=len(project_metrics.high_risk_functions),
        coupling_avg=project_metrics.coupling_avg,
        coupling_max=project_metrics.coupling_max,
        cohesion_avg=project_metrics.cohesion_avg,
        cohesion_max=project_metrics.cohesion_max,
        cycles_count=len(project_metrics.dependency_cycles),
        dependency_avg_depth=_coerce.as_float(
            _as_mapping(metrics_payload_map.get("dependencies")).get("avg_depth")
        ),
        dependency_p95_depth=_as_int(
            _as_mapping(metrics_payload_map.get("dependencies")).get("p95_depth")
        ),
        dependency_max_depth=project_metrics.dependency_max_depth,
        dead_code_count=len(project_metrics.dead_code),
        health_total=project_metrics.health.total,
        health_grade=project_metrics.health.grade,
        suppressed_dead_code_count=analysis_result.suppressed_dead_code_items,
        overloaded_modules_candidates=_as_int(
            overloaded_modules_summary.get("candidates")
        ),
        overloaded_modules_total=_as_int(overloaded_modules_summary.get("total")),
        overloaded_modules_population_status=str(
            overloaded_modules_summary.get("population_status", "")
        ),
        overloaded_modules_top_score=_coerce.as_float(
            overloaded_modules_summary.get("top_score")
        ),
        adoption_param_permille=(
            _as_int(adoption_summary.get("param_permille"))
            if adoption_summary
            else None
        ),
        adoption_return_permille=(
            _as_int(adoption_summary.get("return_permille"))
            if adoption_summary
            else None
        ),
        adoption_docstring_permille=(
            _as_int(adoption_summary.get("docstring_permille"))
            if adoption_summary
            else None
        ),
        adoption_any_annotation_count=_as_int(adoption_summary.get("typing_any_count")),
        api_surface_enabled=bool(api_surface_summary.get("enabled")),
        api_surface_modules=_as_int(api_surface_summary.get("modules")),
        api_surface_public_symbols=_as_int(api_surface_summary.get("public_symbols")),
        api_surface_added=(
            len(metrics_diff.new_api_symbols)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        ),
        api_surface_breaking=(
            len(metrics_diff.new_api_breaking_changes)
            if metrics_diff is not None and api_surface_diff_available
            else 0
        ),
        coverage_join_status=str(coverage_join_summary.get("status", "")).strip(),
        coverage_join_overall_permille=_as_int(
            coverage_join_summary.get("overall_permille")
        ),
        coverage_join_coverage_hotspots=_as_int(
            coverage_join_summary.get("coverage_hotspots")
        ),
        coverage_join_scope_gap_hotspots=_as_int(
            coverage_join_summary.get("scope_gap_hotspots")
        ),
        coverage_join_threshold_percent=_as_int(
            coverage_join_summary.get("hotspot_threshold_percent")
        ),
        coverage_join_source_label=(
            coverage_join_source.rsplit("/", maxsplit=1)[-1]
            if coverage_join_source
            else ""
        ),
    )


def _print_summary(
    *,
    console: _Printer,
    quiet: bool,
    files_found: int,
    files_analyzed: int,
    cache_hits: int,
    files_skipped: int,
    analyzed_lines: int = 0,
    analyzed_functions: int = 0,
    analyzed_methods: int = 0,
    analyzed_classes: int = 0,
    func_clones_count: int,
    block_clones_count: int,
    segment_clones_count: int,
    suppressed_golden_fixture_groups: int,
    suppressed_segment_groups: int,
    new_clones_count: int,
) -> None:
    invariant_ok = files_found == (files_analyzed + cache_hits + files_skipped)

    if quiet:
        console.print(
            ui.fmt_summary_compact(
                found=files_found,
                analyzed=files_analyzed,
                cache_hits=cache_hits,
                skipped=files_skipped,
            )
        )
        console.print(
            ui.fmt_summary_compact_clones(
                function=func_clones_count,
                block=block_clones_count,
                segment=segment_clones_count,
                suppressed=suppressed_segment_groups,
                fixture_excluded=suppressed_golden_fixture_groups,
                new=new_clones_count,
            )
        )
    else:
        from rich.rule import Rule

        console.print()
        console.print(Rule(title=ui.SUMMARY_TITLE, style="dim", characters="\u2500"))
        console.print(
            ui.fmt_summary_files(
                found=files_found,
                analyzed=files_analyzed,
                cached=cache_hits,
                skipped=files_skipped,
            )
        )
        parsed_line = ui.fmt_summary_parsed(
            lines=analyzed_lines,
            functions=analyzed_functions,
            methods=analyzed_methods,
            classes=analyzed_classes,
        )
        if parsed_line is not None:
            console.print(parsed_line)
        console.print(
            ui.fmt_summary_clones(
                func=func_clones_count,
                block=block_clones_count,
                segment=segment_clones_count,
                suppressed=suppressed_segment_groups,
                fixture_excluded=suppressed_golden_fixture_groups,
                new=new_clones_count,
            )
        )

    if not invariant_ok:
        console.print(f"[warning]{ui.WARN_SUMMARY_ACCOUNTING_MISMATCH}[/warning]")


def _print_metrics(
    *,
    console: _Printer,
    quiet: bool,
    metrics: MetricsSnapshot,
) -> None:
    if quiet:
        console.print(
            ui.fmt_summary_compact_metrics(
                cc_avg=metrics.complexity_avg,
                cc_max=metrics.complexity_max,
                cbo_avg=metrics.coupling_avg,
                cbo_max=metrics.coupling_max,
                lcom_avg=metrics.cohesion_avg,
                lcom_max=metrics.cohesion_max,
                cycles=metrics.cycles_count,
                dead=metrics.dead_code_count,
                health=metrics.health_total,
                grade=metrics.health_grade,
                overloaded_modules=metrics.overloaded_modules_candidates,
            )
        )
        console.print(
            ui.fmt_summary_compact_dependencies(
                avg_depth=metrics.dependency_avg_depth,
                p95_depth=metrics.dependency_p95_depth,
                max_depth=metrics.dependency_max_depth,
            )
        )
        if (
            metrics.adoption_param_permille is not None
            and metrics.adoption_return_permille is not None
            and metrics.adoption_docstring_permille is not None
        ):
            console.print(
                ui.fmt_summary_compact_adoption(
                    param_permille=metrics.adoption_param_permille,
                    return_permille=metrics.adoption_return_permille,
                    docstring_permille=metrics.adoption_docstring_permille,
                    any_annotation_count=metrics.adoption_any_annotation_count,
                )
            )
        if metrics.api_surface_enabled:
            console.print(
                ui.fmt_summary_compact_api_surface(
                    public_symbols=metrics.api_surface_public_symbols,
                    modules=metrics.api_surface_modules,
                    added=metrics.api_surface_added,
                    breaking=metrics.api_surface_breaking,
                )
            )
        if metrics.coverage_join_status:
            console.print(
                ui.fmt_summary_compact_coverage_join(
                    status=metrics.coverage_join_status,
                    overall_permille=metrics.coverage_join_overall_permille,
                    coverage_hotspots=metrics.coverage_join_coverage_hotspots,
                    scope_gap_hotspots=metrics.coverage_join_scope_gap_hotspots,
                    threshold_percent=metrics.coverage_join_threshold_percent,
                    source_label=metrics.coverage_join_source_label,
                )
            )
    else:
        from rich.rule import Rule

        console.print()
        console.print(Rule(title=ui.METRICS_TITLE, style="dim", characters="\u2500"))
        console.print(ui.fmt_metrics_health(metrics.health_total, metrics.health_grade))
        console.print(
            ui.fmt_metrics_cc(
                metrics.complexity_avg,
                metrics.complexity_max,
                metrics.high_risk_count,
            )
        )
        console.print(
            ui.fmt_metrics_coupling(metrics.coupling_avg, metrics.coupling_max)
        )
        console.print(
            ui.fmt_metrics_cohesion(metrics.cohesion_avg, metrics.cohesion_max)
        )
        console.print(ui.fmt_metrics_cycles(metrics.cycles_count))
        console.print(
            ui.fmt_metrics_dependencies(
                avg_depth=metrics.dependency_avg_depth,
                p95_depth=metrics.dependency_p95_depth,
                max_depth=metrics.dependency_max_depth,
            )
        )
        console.print(
            ui.fmt_metrics_dead_code(
                metrics.dead_code_count,
                suppressed=metrics.suppressed_dead_code_count,
            )
        )
        if (
            metrics.adoption_param_permille is not None
            and metrics.adoption_return_permille is not None
            and metrics.adoption_docstring_permille is not None
        ):
            console.print(
                ui.fmt_metrics_adoption(
                    param_permille=metrics.adoption_param_permille,
                    return_permille=metrics.adoption_return_permille,
                    docstring_permille=metrics.adoption_docstring_permille,
                    any_annotation_count=metrics.adoption_any_annotation_count,
                )
            )
        if metrics.api_surface_enabled:
            console.print(
                ui.fmt_metrics_api_surface(
                    public_symbols=metrics.api_surface_public_symbols,
                    modules=metrics.api_surface_modules,
                    added=metrics.api_surface_added,
                    breaking=metrics.api_surface_breaking,
                )
            )
        if metrics.coverage_join_status:
            console.print(
                ui.fmt_metrics_coverage_join(
                    status=metrics.coverage_join_status,
                    overall_permille=metrics.coverage_join_overall_permille,
                    coverage_hotspots=metrics.coverage_join_coverage_hotspots,
                    scope_gap_hotspots=metrics.coverage_join_scope_gap_hotspots,
                    threshold_percent=metrics.coverage_join_threshold_percent,
                    source_label=metrics.coverage_join_source_label,
                )
            )
        console.print(
            ui.fmt_metrics_overloaded_modules(
                candidates=metrics.overloaded_modules_candidates,
                total=metrics.overloaded_modules_total,
                population_status=metrics.overloaded_modules_population_status,
                top_score=metrics.overloaded_modules_top_score,
            )
        )


def _print_changed_scope(
    *,
    console: _Printer,
    quiet: bool,
    changed_scope: ChangedScopeSnapshot,
) -> None:
    if quiet:
        console.print(
            ui.fmt_changed_scope_compact(
                paths=changed_scope.paths_count,
                findings=changed_scope.findings_total,
                new=changed_scope.findings_new,
                known=changed_scope.findings_known,
            )
        )
        return

    from rich.rule import Rule

    console.print()
    console.print(Rule(title=ui.CHANGED_SCOPE_TITLE, style="dim", characters="\u2500"))
    console.print(ui.fmt_changed_scope_paths(count=changed_scope.paths_count))
    console.print(
        ui.fmt_changed_scope_findings(
            total=changed_scope.findings_total,
            new=changed_scope.findings_new,
            known=changed_scope.findings_known,
        )
    )
