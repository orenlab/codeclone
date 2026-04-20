# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import cast

from ..models import MetricsDiff
from ..report.document import build_report_document
from ..report.gates.evaluator import GateResult, GateState
from ..report.gates.evaluator import MetricGateConfig as _MetricGateConfig
from ..report.gates.evaluator import evaluate_gate_state as _evaluate_gate_state
from ..report.gates.evaluator import (
    gate_state_from_project_metrics as _gate_state_from_metrics,
)
from ..report.renderers.json import render_json_report_document
from ..report.renderers.text import render_text_report_document
from ._types import (
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    ProcessingResult,
    ReportArtifacts,
)
from .metrics_payload import _enrich_metrics_report_payload

MetricGateConfig = _MetricGateConfig
GatingResult = GateResult


def _load_markdown_report_renderer() -> Callable[..., str]:
    from ..report.markdown import to_markdown_report

    return to_markdown_report


def _load_sarif_report_renderer() -> Callable[..., str]:
    from ..report.sarif import to_sarif_report

    return to_sarif_report


def report(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
    new_func: Collection[str],
    new_block: Collection[str],
    html_builder: Callable[..., str] | None = None,
    metrics_diff: object | None = None,
    coverage_adoption_diff_available: bool = False,
    api_surface_diff_available: bool = False,
    include_report_document: bool = False,
) -> ReportArtifacts:
    contents: dict[str, str | None] = {
        "html": None,
        "json": None,
        "md": None,
        "sarif": None,
        "text": None,
    }
    structural_findings = (
        analysis.structural_findings if analysis.structural_findings else None
    )
    report_inventory = {
        "files": {
            "total_found": discovery.files_found,
            "analyzed": processing.files_analyzed,
            "cached": discovery.cache_hits,
            "skipped": processing.files_skipped,
            "source_io_skipped": len(processing.source_read_failures),
        },
        "code": {
            "parsed_lines": processing.analyzed_lines + discovery.cached_lines,
            "functions": processing.analyzed_functions + discovery.cached_functions,
            "methods": processing.analyzed_methods + discovery.cached_methods,
            "classes": processing.analyzed_classes + discovery.cached_classes,
        },
        "file_list": list(discovery.all_file_paths),
    }
    report_document: dict[str, object] | None = None
    needs_report_document = (
        include_report_document
        or boot.output_paths.html is not None
        or any(
            path is not None
            for path in (
                boot.output_paths.json,
                boot.output_paths.md,
                boot.output_paths.sarif,
                boot.output_paths.text,
            )
        )
    )
    if needs_report_document:
        metrics_for_report = (
            _enrich_metrics_report_payload(
                metrics_payload=analysis.metrics_payload,
                metrics_diff=cast("MetricsDiff | None", metrics_diff),
                coverage_adoption_diff_available=coverage_adoption_diff_available,
                api_surface_diff_available=api_surface_diff_available,
            )
            if analysis.metrics_payload is not None
            else None
        )
        report_document = build_report_document(
            func_groups=analysis.func_groups,
            block_groups=analysis.block_groups_report,
            segment_groups=analysis.segment_groups,
            suppressed_clone_groups=analysis.suppressed_clone_groups,
            meta=report_meta,
            inventory=report_inventory,
            block_facts=analysis.block_group_facts,
            new_function_group_keys=new_func,
            new_block_group_keys=new_block,
            new_segment_group_keys=set(analysis.segment_groups.keys()),
            metrics=metrics_for_report,
            suggestions=analysis.suggestions,
            structural_findings=structural_findings,
        )

    if boot.output_paths.html and html_builder is not None:
        metrics_for_html = (
            _enrich_metrics_report_payload(
                metrics_payload=analysis.metrics_payload,
                metrics_diff=cast("MetricsDiff | None", metrics_diff),
                coverage_adoption_diff_available=coverage_adoption_diff_available,
                api_surface_diff_available=api_surface_diff_available,
            )
            if analysis.metrics_payload is not None
            else None
        )
        contents["html"] = html_builder(
            func_groups=analysis.func_groups,
            block_groups=analysis.block_groups_report,
            segment_groups=analysis.segment_groups,
            block_group_facts=analysis.block_group_facts,
            new_function_group_keys=new_func,
            new_block_group_keys=new_block,
            report_meta=report_meta,
            metrics=metrics_for_html,
            suggestions=analysis.suggestions,
            structural_findings=structural_findings,
            report_document=report_document,
            metrics_diff=metrics_diff,
            title="CodeClone Report",
            context_lines=3,
            max_snippet_lines=220,
        )

    if any(
        path is not None
        for path in (
            boot.output_paths.json,
            boot.output_paths.md,
            boot.output_paths.sarif,
            boot.output_paths.text,
        )
    ):
        assert report_document is not None

    if boot.output_paths.json and report_document is not None:
        contents["json"] = render_json_report_document(report_document)

    def _render_projection_artifact(renderer: Callable[..., str]) -> str:
        assert report_document is not None
        return renderer(
            report_document=report_document,
            meta=report_meta,
            inventory=report_inventory,
            func_groups=analysis.func_groups,
            block_groups=analysis.block_groups_report,
            segment_groups=analysis.segment_groups,
            block_facts=analysis.block_group_facts,
            new_function_group_keys=new_func,
            new_block_group_keys=new_block,
            new_segment_group_keys=set(analysis.segment_groups.keys()),
            metrics=analysis.metrics_payload,
            suggestions=analysis.suggestions,
            structural_findings=structural_findings,
        )

    for key, output_path, loader in (
        ("md", boot.output_paths.md, _load_markdown_report_renderer),
        ("sarif", boot.output_paths.sarif, _load_sarif_report_renderer),
    ):
        if output_path and report_document is not None:
            contents[key] = _render_projection_artifact(loader())

    if boot.output_paths.text and report_document is not None:
        contents["text"] = render_text_report_document(report_document)

    return ReportArtifacts(
        html=contents["html"],
        json=contents["json"],
        md=contents["md"],
        sarif=contents["sarif"],
        text=contents["text"],
        report_document=report_document,
    )


def gate(
    *,
    boot: BootstrapResult,
    analysis: AnalysisResult,
    new_func: Collection[str],
    new_block: Collection[str],
    metrics_diff: MetricsDiff | None,
) -> GatingResult:
    config = MetricGateConfig(
        fail_complexity=boot.args.fail_complexity,
        fail_coupling=boot.args.fail_coupling,
        fail_cohesion=boot.args.fail_cohesion,
        fail_cycles=boot.args.fail_cycles,
        fail_dead_code=boot.args.fail_dead_code,
        fail_health=boot.args.fail_health,
        fail_on_new_metrics=boot.args.fail_on_new_metrics,
        fail_on_typing_regression=bool(
            getattr(boot.args, "fail_on_typing_regression", False)
        ),
        fail_on_docstring_regression=bool(
            getattr(boot.args, "fail_on_docstring_regression", False)
        ),
        fail_on_api_break=bool(getattr(boot.args, "fail_on_api_break", False)),
        fail_on_untested_hotspots=bool(
            getattr(boot.args, "fail_on_untested_hotspots", False)
        ),
        min_typing_coverage=int(getattr(boot.args, "min_typing_coverage", -1)),
        min_docstring_coverage=int(getattr(boot.args, "min_docstring_coverage", -1)),
        coverage_min=int(getattr(boot.args, "coverage_min", 50)),
        fail_on_new=bool(getattr(boot.args, "fail_on_new", False)),
        fail_threshold=int(getattr(boot.args, "fail_threshold", -1)),
    )
    clone_new_count = len(tuple(new_func)) + len(tuple(new_block))
    clone_total = analysis.func_clones_count + analysis.block_clones_count
    if analysis.project_metrics is None:
        state = GateState(clone_new_count=clone_new_count, clone_total=clone_total)
    else:
        state = _gate_state_from_metrics(
            project_metrics=analysis.project_metrics,
            coverage_join=analysis.coverage_join,
            metrics_diff=metrics_diff,
            clone_new_count=clone_new_count,
            clone_total=clone_total,
        )
    result = _evaluate_gate_state(state=state, config=config)
    return GatingResult(exit_code=result.exit_code, reasons=result.reasons)
