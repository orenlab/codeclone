# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from functools import partial
from uuid import UUID

from ..baseline.container_trust import evaluate_container_trust
from ..baseline.trust import current_python_tag
from ..contracts import DEFAULT_COVERAGE_MIN
from ..models import BaselineContainerV3, MetricsDiff, TrustVector
from ..observability import span
from ..report.gates.evaluator import GateResult, GateState
from ..report.gates.evaluator import MetricGateConfig as _MetricGateConfig
from ..report.gates.evaluator import (
    active_gate_lane_requirements as _active_gate_lane_requirements,
)
from ..report.gates.evaluator import evaluate_gate_state as _evaluate_gate_state
from ..report.gates.evaluator import (
    gate_state_from_project_metrics as _gate_state_from_metrics,
)
from ..report.renderers.json import render_json_report_document
from ..report.renderers.text import render_text_report_document
from ..utils.coerce import as_int as _as_int
from ..utils.coerce import as_mapping as _as_mapping
from ..utils.coerce import as_sequence as _as_sequence
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

_REPORT_FORMAT_COUNTERS = {
    "html": "report_render_format_html",
    "json": "report_render_format_json",
    "markdown": "report_render_format_markdown",
    "sarif": "report_render_format_sarif",
    "text": "report_render_format_text",
}


def _coerce_metrics_diff(value: object | None) -> MetricsDiff | None:
    return value if isinstance(value, MetricsDiff) else None


def _load_markdown_report_renderer() -> Callable[..., str]:
    from ..report.renderers.markdown import render_markdown_report_document

    return render_markdown_report_document


def _load_sarif_report_renderer() -> Callable[..., str]:
    from ..report.renderers.sarif import render_sarif_report_document

    return render_sarif_report_document


def _load_report_body_builder() -> Callable[..., dict[str, object]]:
    from ..report.document.builder import build_report_body

    return build_report_body


def _load_report_document_finalizer() -> Callable[..., dict[str, object]]:
    from ..report.document.builder import finalize_report_document

    return finalize_report_document


def _render_report_projection(
    *,
    format_name: str,
    report_document: Mapping[str, object],
    renderer: Callable[[], str | bytes],
) -> bytes:
    """Render one requested format once and attach bounded canonical counters.

    Every artifact leaves here as the bytes that will be written. Text-shaped
    renderers are encoded exactly once, here, instead of once to measure a
    length and again at write time.
    """

    counter_key = _REPORT_FORMAT_COUNTERS[format_name]
    with span(name="report.render") as render_span:
        produced = renderer()
        rendered = produced if isinstance(produced, bytes) else produced.encode("utf-8")
        del produced
        findings_summary = _as_mapping(
            _as_mapping(report_document.get("findings")).get("summary")
        )
        clone_summary = _as_mapping(findings_summary.get("clones"))
        lane_rows = tuple(
            _as_mapping(item)
            for item in _as_sequence(
                _as_mapping(report_document.get("baseline")).get("sorted_lane_trust")
            )
        )
        trusted_lanes = sum(
            1 for row in lane_rows if str(row.get("status", "")) == "trusted"
        )
        render_span.set_counter(counter_key, 1)
        render_span.set_counter("report_render_bytes", len(rendered))
        render_span.set_counter(
            "report_items",
            _as_int(findings_summary.get("total")),
        )
        render_span.set_counter(
            "report_novelty_known",
            _as_int(clone_summary.get("known")),
        )
        render_span.set_counter(
            "report_novelty_new",
            _as_int(clone_summary.get("new")),
        )
        render_span.set_counter(
            "report_novelty_unavailable",
            _as_int(clone_summary.get("unavailable")),
        )
        render_span.set_counter("report_trust_trusted", trusted_lanes)
        render_span.set_counter(
            "report_trust_untrusted",
            len(lane_rows) - trusted_lanes,
        )
        return rendered


def resolve_report_baseline_trust(
    container: BaselineContainerV3 | None,
    *,
    baseline_scope_id: str | None,
) -> TrustVector | None:
    """Consume the sole baseline trust owner for report-v3 provenance."""

    if container is None or baseline_scope_id is None:
        return None
    try:
        scope_id = UUID(baseline_scope_id)
    except ValueError:
        return None
    return evaluate_container_trust(
        container,
        python_tag=current_python_tag(),
        baseline_scope_id=scope_id,
    )


def _metrics_for_report(
    *,
    analysis: AnalysisResult,
    metrics_diff: object | None,
    coverage_adoption_diff_available: bool,
    api_surface_diff_available: bool,
    baseline_trust: TrustVector | None = None,
) -> Mapping[str, object] | None:
    validated_metrics_diff = _coerce_metrics_diff(metrics_diff)
    if analysis.metrics_payload is None:
        return None
    enriched = _enrich_metrics_report_payload(
        metrics_payload=analysis.metrics_payload,
        metrics_diff=validated_metrics_diff,
        coverage_adoption_diff_available=coverage_adoption_diff_available,
        api_surface_diff_available=api_surface_diff_available,
    )
    trusted_lanes = {
        item.name
        for item in (() if baseline_trust is None else baseline_trust.lanes)
        if baseline_trust is not None
        and baseline_trust.root_verified
        and item.status == "trusted"
    }
    comparison_rows = (
        (
            (
                "complexity",
                "risk_observations",
                "new_high_risk",
                len(validated_metrics_diff.new_high_risk_functions),
            ),
            (
                "coupling",
                "coupling_cohesion_observations",
                "new_high_risk",
                len(validated_metrics_diff.new_high_coupling_classes),
            ),
            (
                "dependencies",
                "dependencies",
                "new_cycles",
                len(validated_metrics_diff.new_cycles),
            ),
            (
                "dead_code",
                "dead_code",
                "new_items",
                len(validated_metrics_diff.new_dead_code),
            ),
            (
                "health",
                "risk_observations",
                "delta",
                validated_metrics_diff.health_delta,
            ),
        )
        if validated_metrics_diff is not None
        else ()
    )
    for family_name, lane, value_key, value in comparison_rows:
        family = dict(_as_mapping(enriched.get(family_name)))
        summary = dict(_as_mapping(family.get("summary")))
        summary["baseline_diff_available"] = lane in trusted_lanes
        summary[value_key] = value if lane in trusted_lanes else 0
        family["summary"] = summary
        enriched[family_name] = family
    return enriched


def build_report_body_for_analysis(
    *,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
    new_func: Collection[str],
    new_block: Collection[str],
    metrics_diff: object | None = None,
    coverage_adoption_diff_available: bool = False,
    api_surface_diff_available: bool = False,
    baseline_trust: TrustVector | None = None,
) -> dict[str, object]:
    """Construct the report body once before the single gate evaluation."""

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
    with span(name="report.build"):
        return _load_report_body_builder()(
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
            metrics=_metrics_for_report(
                analysis=analysis,
                metrics_diff=metrics_diff,
                coverage_adoption_diff_available=coverage_adoption_diff_available,
                api_surface_diff_available=api_surface_diff_available,
                baseline_trust=baseline_trust,
            ),
            suggestions=analysis.suggestions,
            structural_findings=(
                analysis.structural_findings if analysis.structural_findings else None
            ),
            baseline_trust=baseline_trust,
            near_miss_pairs=analysis.near_miss_pairs,
        )


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
    report_body: Mapping[str, object] | None = None,
    baseline_container: BaselineContainerV3 | None = None,
    baseline_trust: TrustVector | None = None,
    baseline_scope_id: str | None = None,
    gate_config: MetricGateConfig | None = None,
    gate_result: GateResult | None = None,
) -> ReportArtifacts:
    contents: dict[str, bytes | None] = {
        "html": None,
        "json": None,
        "md": None,
        "sarif": None,
        "text": None,
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
        resolved_baseline_trust = (
            baseline_trust
            if baseline_trust is not None
            else resolve_report_baseline_trust(
                baseline_container,
                baseline_scope_id=baseline_scope_id,
            )
        )
        resolved_body = (
            dict(report_body)
            if report_body is not None
            else build_report_body_for_analysis(
                discovery=discovery,
                processing=processing,
                analysis=analysis,
                report_meta=report_meta,
                new_func=new_func,
                new_block=new_block,
                metrics_diff=metrics_diff,
                coverage_adoption_diff_available=coverage_adoption_diff_available,
                api_surface_diff_available=api_surface_diff_available,
                baseline_trust=resolved_baseline_trust,
            )
        )
        if (gate_config is None) != (gate_result is None):
            raise ValueError("gate config and result must be supplied together")
        if gate_config is None or gate_result is None:
            gate_config, gate_result = gate_with_config(
                boot=boot,
                analysis=analysis,
                new_func=new_func,
                new_block=new_block,
                metrics_diff=_coerce_metrics_diff(metrics_diff),
                baseline_trust=resolved_baseline_trust,
            )
        report_document = _load_report_document_finalizer()(
            body=resolved_body,
            observation_bundle=analysis.observation_bundle,
            baseline_container=baseline_container,
            baseline_trust=resolved_baseline_trust,
            gate_config=gate_config,
            gate_result=gate_result,
            new_function_group_keys=new_func,
            new_block_group_keys=new_block,
        )

    if boot.output_paths.html and html_builder is not None:
        assert report_document is not None
        contents["html"] = _render_report_projection(
            format_name="html",
            report_document=report_document,
            renderer=lambda: html_builder(
                report_document=report_document,
                title="CodeClone Report",
                context_lines=3,
                max_snippet_lines=220,
            ),
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
        contents["json"] = _render_report_projection(
            format_name="json",
            report_document=report_document,
            renderer=lambda: render_json_report_document(report_document),
        )

    for key, output_path, loader in (
        ("md", boot.output_paths.md, _load_markdown_report_renderer),
        ("sarif", boot.output_paths.sarif, _load_sarif_report_renderer),
    ):
        if output_path and report_document is not None:
            render_projection = loader()
            contents[key] = _render_report_projection(
                format_name="markdown" if key == "md" else key,
                report_document=report_document,
                renderer=partial(render_projection, report_document),
            )

    if boot.output_paths.text and report_document is not None:
        contents["text"] = _render_report_projection(
            format_name="text",
            report_document=report_document,
            renderer=lambda: render_text_report_document(report_document),
        )

    return ReportArtifacts(
        html=contents["html"],
        json=contents["json"],
        md=contents["md"],
        sarif=contents["sarif"],
        text=contents["text"],
        report_document=report_document,
    )


def build_gate_config(args: object) -> MetricGateConfig:
    """Project the sole gate policy object from parsed CLI arguments.

    Gate policy is a function of the arguments alone, so baseline trust
    resolution can build it before bootstrap results are threaded anywhere,
    and weigh untrusted lanes against the gates that are actually active.
    """

    return MetricGateConfig(
        fail_complexity=getattr(args, "fail_complexity", -1),
        fail_coupling=getattr(args, "fail_coupling", -1),
        fail_cohesion=getattr(args, "fail_cohesion", -1),
        fail_cycles=getattr(args, "fail_cycles", False),
        fail_dead_code=getattr(args, "fail_dead_code", False),
        fail_on_unresolved_dead_code=bool(
            getattr(args, "fail_on_unresolved_dead_code", False)
        ),
        fail_health=getattr(args, "fail_health", -1),
        fail_on_new_metrics=getattr(args, "fail_on_new_metrics", False),
        fail_on_typing_regression=bool(
            getattr(args, "fail_on_typing_regression", False)
        ),
        fail_on_docstring_regression=bool(
            getattr(args, "fail_on_docstring_regression", False)
        ),
        fail_on_api_break=bool(getattr(args, "fail_on_api_break", False)),
        fail_on_authority_violation=bool(
            getattr(args, "fail_on_authority_violation", False)
        ),
        fail_on_untested_hotspots=bool(
            getattr(args, "fail_on_untested_hotspots", False)
        ),
        min_typing_coverage=int(getattr(args, "min_typing_coverage", -1)),
        min_docstring_coverage=int(getattr(args, "min_docstring_coverage", -1)),
        coverage_min=int(getattr(args, "coverage_min", DEFAULT_COVERAGE_MIN)),
        fail_on_new=bool(getattr(args, "fail_on_new", False)),
        fail_threshold=int(getattr(args, "fail_threshold", -1)),
    )


def gate_required_lanes(
    *,
    args: object,
    enabled_lanes: Collection[str],
) -> frozenset[str]:
    """Return every lane the currently active gates read.

    Gate policy lives here, behind the versioned gate-to-lane matrix, so no
    surface has to re-derive which gate reads which lane. Callers receive plain
    lane names and only ever intersect them.
    """

    return frozenset(
        lane
        for _gate, lanes in _active_gate_lane_requirements(
            config=build_gate_config(args),
            enabled_lanes=enabled_lanes,
        )
        for lane in lanes
    )


def _gate_config(boot: BootstrapResult) -> MetricGateConfig:
    return build_gate_config(boot.args)


def gate_with_config(
    *,
    boot: BootstrapResult,
    analysis: AnalysisResult,
    new_func: Collection[str],
    new_block: Collection[str],
    metrics_diff: MetricsDiff | None,
    clone_threshold_total: int | None = None,
    baseline_trust: TrustVector | None = None,
    gate_config: MetricGateConfig | None = None,
) -> tuple[MetricGateConfig, GatingResult]:
    config = gate_config if gate_config is not None else _gate_config(boot)
    clone_new_count = len(tuple(new_func)) + len(tuple(new_block))
    clone_total = (
        analysis.func_clones_count + analysis.block_clones_count
        if clone_threshold_total is None
        else max(clone_threshold_total, 0)
    )
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
    lane_trust: Mapping[str, str] | None = (
        None
        if baseline_trust is None
        else {
            item.name: item.status
            for item in baseline_trust.lanes
            if baseline_trust.root_verified
        }
    )
    result = _evaluate_gate_state(
        state=state,
        config=config,
        lane_trust=lane_trust,
        enabled_lanes=analysis.observation_bundle.contract.enabled_lanes,
    )
    return config, result


def gate(
    *,
    boot: BootstrapResult,
    analysis: AnalysisResult,
    new_func: Collection[str],
    new_block: Collection[str],
    metrics_diff: MetricsDiff | None,
    baseline_trust: TrustVector | None = None,
) -> GatingResult:
    _config, result = gate_with_config(
        boot=boot,
        analysis=analysis,
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
        baseline_trust=baseline_trust,
    )
    return result
