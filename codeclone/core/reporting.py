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
from ..contracts import (
    DEFAULT_COVERAGE_MIN,
    ObservedPopulation,
    observed_population,
    population_universe_observed,
)
from ..models import (
    BaselineContainerV3,
    MetricsDiff,
    RunSnapshotPublication,
    RunStoreConfig,
    TrustVector,
)
from ..observability import span
from ..report.document._common import health_verdict_withheld
from ..report.gates.evaluator import HEALTH_INPUT_LANES, GateResult, GateState
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
from .canonical_snapshot import (
    bridge_run_snapshot,
    persist_run_snapshot_link,
    publish_run_snapshot,
    resolve_run_store_config,
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


def report_document_required(
    boot: BootstrapResult,
    *,
    include_report_document: bool,
) -> bool:
    """Answer whether anything downstream will consume the report document.

    Sole owner of that question. The caller that *builds* the document and the
    caller that *uses* it have to agree, or the build is paid for and thrown
    away -- which is exactly what a gate-only run used to do.
    """

    return (
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
    # The current half of the availability question, for health and for the
    # adoption family alike. Lane trust can only vouch for the baseline term
    # of the subtraction; a run whose own population carries no verdict made
    # no comparison however trusted the stored lanes are, and publishing a
    # delta beside ``baseline_diff_available: true`` would state "compared"
    # about a comparison that never ran (`B8`, `G4`). Read through the one
    # reader the document tree already uses, not a second ``score is None``
    # derivation (`G2`). Computed from the same health family the enrichment
    # copies unchanged, so both consumers below read one fact.
    health_withheld = health_verdict_withheld(
        _as_mapping(analysis.metrics_payload.get("health"))
    )
    # The universe term of the four set-diff families below, read from the
    # same owner the API family already consults (`api.comparison`): a
    # set-membership diff needs the whole current universe observed, not
    # merely a score to exist. ``partial`` and ``unmeasured`` therefore mute
    # the four — an unread module's carriers are indistinguishable from
    # removed ones — while ``complete_empty`` keeps publishing, because a
    # genuinely emptied scope really removed what the baseline remembers.
    # This is deliberately not ``health_withheld``: the two binary collapses
    # of the population disagree on ``partial`` and on ``complete_empty``,
    # and each has its own named owner in the contract ring (`G2`).
    universe_observed = (
        analysis.project_metrics is not None
        and population_universe_observed(analysis.project_metrics.health.population)
    )
    enriched = _enrich_metrics_report_payload(
        metrics_payload=analysis.metrics_payload,
        metrics_diff=validated_metrics_diff,
        # The adoption permilles are ratios over the same unobserved
        # population, so the withheld current half silences their satellite
        # too: the enrichment then writes ``baseline_diff_available: false``
        # and zeroes the deltas, mirroring the health family below.
        coverage_adoption_diff_available=(
            coverage_adoption_diff_available and not health_withheld
        ),
        api_surface_diff_available=api_surface_diff_available,
    )
    trusted_lanes = {
        item.name
        for item in (() if baseline_trust is None else baseline_trust.lanes)
        if baseline_trust is not None
        and baseline_trust.root_verified
        and item.status == "trusted"
    }
    # Each row names *every* lane its comparison consumes, not a representative
    # one. Health is why: it is derived from seven lanes, and keying it on
    # ``risk_observations`` alone published a delta as available while one of
    # the other six was opaque -- the baseline half of that subtraction had
    # never been recovered. The report already states the seven in
    # ``contracts.evaluation.health_input_lanes`` and the gate matrix already
    # requires all of them, so this reads that same manifest instead of a
    # third opinion about what health consumes (`G2`, `G3`, `B8`).
    comparison_rows: tuple[tuple[str, tuple[str, ...], str, int], ...] = (
        (
            (
                "complexity",
                ("risk_observations",),
                "new_high_risk",
                len(validated_metrics_diff.new_high_risk_functions),
            ),
            (
                "coupling",
                ("coupling_cohesion_observations",),
                "new_high_risk",
                len(validated_metrics_diff.new_high_coupling_classes),
            ),
            (
                "dependencies",
                ("dependencies",),
                "new_cycles",
                len(validated_metrics_diff.new_cycles),
            ),
            # Carried beside the total because only this one gates. Without it
            # the report document cannot tell the gate evaluator which of the
            # new cycles can actually break an import.
            (
                "dependencies",
                ("dependencies",),
                "new_import_cycles",
                len(validated_metrics_diff.new_import_cycles),
            ),
            (
                "dependencies",
                ("dependencies",),
                "new_deferred_cycles",
                len(validated_metrics_diff.new_deferred_cycles),
            ),
            (
                "dead_code",
                ("dead_code",),
                "new_items",
                len(validated_metrics_diff.new_dead_code),
            ),
            (
                "health",
                HEALTH_INPUT_LANES,
                "delta",
                validated_metrics_diff.health_delta,
            ),
        )
        if validated_metrics_diff is not None
        else ()
    )
    for family_name, lanes, value_key, value in comparison_rows:
        family = dict(_as_mapping(enriched.get(family_name)))
        summary = dict(_as_mapping(family.get("summary")))
        available = trusted_lanes.issuperset(lanes)
        if family_name == "health":
            if health_withheld:
                available = False
        elif not universe_observed:
            # The set-diff families: lane trust vouches for the baseline term
            # only, and on an unobserved universe the current term is empty by
            # construction — publishing "0 new" beside ``available: true``
            # would state "compared" about a comparison whose current half
            # never existed (`B8`, `G4`). Health stays on its own reader
            # above: a truncated run still carries an honest score delta.
            available = False
        summary["baseline_diff_available"] = available
        summary[value_key] = value if available else 0
        family["summary"] = summary
        enriched[family_name] = family
    return enriched


def build_report_body_for_analysis(
    *,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
    # ``None`` means that lane was not compared -- it is not "compared, nothing
    # new". Callers that ran a comparison pass a (possibly empty) collection.
    new_func: Collection[str] | None,
    new_block: Collection[str] | None,
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
            "unsupported_construct_skipped": len(
                processing.unsupported_construct_skips
            ),
            "unsupported_constructs": [
                {"path": skip.filepath, "construct": skip.construct}
                for skip in processing.unsupported_construct_skips
            ],
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
            renamed_structure_groups=analysis.renamed_structure_groups,
            # The per-entity baseline differences are computed once and routed
            # to the gates; they reach the findings that were compared here.
            project_metrics=analysis.project_metrics,
            metrics_diff=_coerce_metrics_diff(metrics_diff),
        )


def _publish_canonical_snapshot(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
) -> tuple[RunStoreConfig, RunSnapshotPublication]:
    """Resolve the rollout flag and publish, at the point that publishes.

    The resolution site is the publication site on purpose: a flag read
    anywhere else would let one surface answer "enabled" while another
    answered "disabled" for the same run, which is the configuration
    drift the delivery ratchet exists to catch.  Every path returns a
    typed witness, including the default disabled path.

    The resolved config travels back out with the witness for exactly that
    reason: the bridge is written into the same store this call published
    into, and a second resolution later in ``report`` would be a second
    reading of one flag inside one run.
    """

    config = resolve_run_store_config(root=boot.root)
    return config, publish_run_snapshot(
        config=config,
        discovery=discovery,
        processing=processing,
        analysis=analysis,
        report_meta=report_meta,
    )


def report(
    *,
    boot: BootstrapResult,
    discovery: DiscoveryResult,
    processing: ProcessingResult,
    analysis: AnalysisResult,
    report_meta: Mapping[str, object],
    #: ``None`` means the lane was not compared (`RP2`); an empty collection
    #: means a comparison ran and produced nothing.
    new_func: Collection[str] | None,
    new_block: Collection[str] | None,
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
    # The ONE producer-edge publication point (backend step 7).  It lives
    # here and not in the CLI stage runner because MCP deliberately
    # bypasses ``run_analysis_stages``: a publish hung off the stage runner
    # would give the three waterfalls two dialects of one fact, and this
    # function is the single scope in which all four producer results and
    # the run root are live at once.  It runs before the document work and
    # is independent of it — a gate-only run publishes the same snapshot as
    # a rendering run, because the snapshot is the ANALYSIS, not the
    # report.
    run_store_config, publication = _publish_canonical_snapshot(
        boot=boot,
        discovery=discovery,
        processing=processing,
        analysis=analysis,
        report_meta=report_meta,
    )
    needs_report_document = report_document_required(
        boot,
        include_report_document=include_report_document,
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
                files_skipped=processing.files_skipped,
                # Computed here, from the one owner, because this fallback is
                # the only gate constructor in this path that cannot read it
                # off ``project_metrics`` when metrics were skipped.
                analysis_population=observed_population(
                    files_found=discovery.files_found,
                    files_analyzed_or_cached=analysis.files_analyzed_or_cached,
                ),
            )
        # Sealing hashes the whole document, so it is a heavyweight stage in
        # its own right and needs to be visible next to build and render.
        with span(name="report.finalize"):
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

    # The bridge is stated AFTER the document is sealed, because the report
    # half of the relation does not exist until then, and it is stated on
    # every path: a gate-only run reaches here with ``report_document`` None
    # and gets the ``unevaluated`` state rather than no link at all.  The
    # publication witness itself is not enough -- it names the store record
    # and knows nothing of the document that evaluated it.
    run_snapshot_link = bridge_run_snapshot(
        publication=publication,
        report_document=report_document,
    )
    # Persisted here and not inside the bridge: stating the relation is a
    # pure reading of two artifacts, and writing it is a store mutation.
    # A run with the rollout off has no store to write into, which is the
    # false branch of this condition on every default run.
    if run_store_config.path is not None:
        persist_run_snapshot_link(
            store_path=run_store_config.path, link=run_snapshot_link
        )
    return ReportArtifacts(
        html=contents["html"],
        json=contents["json"],
        md=contents["md"],
        sarif=contents["sarif"],
        text=contents["text"],
        report_document=report_document,
        run_snapshot_link=run_snapshot_link,
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
        fail_on_truncated_run=bool(getattr(args, "fail_on_truncated_run", False)),
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
    new_func: Collection[str] | None,
    new_block: Collection[str] | None,
    metrics_diff: MetricsDiff | None,
    clone_threshold_total: int | None = None,
    baseline_trust: TrustVector | None = None,
    gate_config: MetricGateConfig | None = None,
    files_skipped: int = 0,
    #: The run's population fact from its sole owner (``observed_population``),
    #: consulted only when metrics did not run: with ``project_metrics``
    #: present the health family carries the same fact and stays the sole
    #: authority for that branch (`G2`). Without this parameter the
    #: metrics-off gate state defaulted to ``complete_nonempty``, so
    #: ``--skip-metrics`` runs answered every gate over a population nobody
    #: measured — the identical run with metrics enabled was refused.
    analysis_population: ObservedPopulation = "complete_nonempty",
) -> tuple[MetricGateConfig, GatingResult]:
    config = gate_config if gate_config is not None else _gate_config(boot)
    # An uncompared lane contributes no new clones to count. It must not
    # therefore read as "clean": the lane-trust vector below is what makes the
    # clone gate fail closed when the lane it reads is not comparable.
    clone_new_count = len(tuple(new_func or ())) + len(tuple(new_block or ()))
    clone_total = (
        analysis.func_clones_count + analysis.block_clones_count
        if clone_threshold_total is None
        else max(clone_threshold_total, 0)
    )
    if analysis.project_metrics is None:
        state = GateState(
            clone_new_count=clone_new_count,
            clone_total=clone_total,
            files_skipped=max(files_skipped, 0),
            health_population=analysis_population,
        )
    else:
        state = _gate_state_from_metrics(
            project_metrics=analysis.project_metrics,
            coverage_join=analysis.coverage_join,
            metrics_diff=metrics_diff,
            clone_new_count=clone_new_count,
            clone_total=clone_total,
            files_skipped=files_skipped,
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
    new_func: Collection[str] | None,
    new_block: Collection[str] | None,
    metrics_diff: MetricsDiff | None,
    baseline_trust: TrustVector | None = None,
    analysis_population: ObservedPopulation = "complete_nonempty",
) -> GatingResult:
    _config, result = gate_with_config(
        boot=boot,
        analysis=analysis,
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
        baseline_trust=baseline_trust,
        analysis_population=analysis_population,
    )
    return result
