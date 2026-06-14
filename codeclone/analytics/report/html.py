# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import html
import json
from collections.abc import Mapping, Sequence

from ..clustering.models import NOISE_LABEL
from ..contracts import ClusteringRunRecord, CorpusSnapshotRecord
from ..exceptions import AnalyticsWorkflowError
from ..store.sqlite import SqliteCorpusAnalyticsStore
from .interpret import build_sweep_comparison_projection, enrich_run_for_export


def render_analytics_html(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot: CorpusSnapshotRecord,
    run: ClusteringRunRecord,
    comparison_only: bool = False,
) -> str:
    if run.snapshot_id != snapshot.snapshot_id:
        raise AnalyticsWorkflowError(
            f"run {run.clustering_run_id} does not belong to {snapshot.snapshot_id}"
        )
    generation = store.get_embedding_generation(run.embedding_generation_id)
    if comparison_only:
        body = _render_comparison_table(store, snapshot, run)
        title = "Corpus Analytics Sweep Comparison"
        run_line = ""
        banner = ""
    else:
        projection = enrich_run_for_export(store=store, snapshot=snapshot, run=run)
        run_payload = _mapping(projection["run"])
        presentation = _mapping(run_payload.get("presentation"))
        body = _render_detail_view(projection)
        title = "Corpus Analytics Cluster Report"
        run_line = f"<p>Run: <code>{html.escape(run.clustering_run_id)}</code></p>"
        banner = _render_run_banner(presentation)
    reproducibility_note = ""
    if generation is None:
        reproducibility_note = (
            '<p class="warning"><strong>Reproducibility:</strong> Embedding '
            "generation metadata is unavailable. This report is limited to "
            "persisted diagnostic facts.</p>"
        )
    elif not generation.exact_model_artifact_reproducibility:
        reproducibility_note = (
            '<p class="warning"><strong>Reproducibility:</strong> Full vector '
            "reproducibility is not guaranteed from model id alone.</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.45;
color: #202124; }}
code {{ background: #f4f5f7; padding: .1rem .25rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
th, td {{ border: 1px solid #d7d9dd; padding: .45rem .6rem;
text-align: left; vertical-align: top; }}
th {{ background: #f4f5f7; }}
.cluster {{ border-top: 3px solid #5865f2; margin-top: 2rem; padding-top: .5rem; }}
.noise {{ border-top-color: #b26a00; }}
.insufficient {{ color: #666; font-style: italic; }}
.warning {{ background: #fff3cd; border: 1px solid #e3c66c; padding: .75rem; }}
.success {{ background: #e8f5e9; border: 1px solid #8abf8d; padding: .75rem; }}
.error {{ background: #fdecea; border: 1px solid #d88b84; padding: .75rem; }}
.pill {{ display: inline-block; background: #eef0ff; margin: .1rem;
padding: .15rem .35rem; border-radius: .3rem; }}
.muted {{ color: #666; }}
.preview {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p>Snapshot: <code>{html.escape(snapshot.snapshot_id)}</code></p>
{run_line}
{banner}
{reproducibility_note}
{body}
</body>
</html>
"""


def _render_run_banner(status: Mapping[str, object]) -> str:
    kind = str(status.get("banner_kind", "technically_invalid"))
    css = {
        "maintainer_selected": "success",
        "heuristic_recommended": "success",
        "candidate_only": "warning",
        "technically_invalid": "error",
    }.get(kind, "warning")
    message = str(status.get("banner_message", "Run presentation is unavailable."))
    return (
        f'<p class="{css}" data-banner-kind="{html.escape(kind)}">'
        f"<strong>{html.escape(kind.replace('_', ' ').title())}:</strong> "
        f"{html.escape(message)}</p>"
    )


def _render_comparison_table(
    store: SqliteCorpusAnalyticsStore,
    snapshot: CorpusSnapshotRecord,
    current_run: ClusteringRunRecord,
) -> str:
    candidates, summary = build_sweep_comparison_projection(
        store=store,
        snapshot=snapshot,
        embedding_generation_id=current_run.embedding_generation_id,
    )
    rows: list[str] = []
    for projection in candidates:
        run_payload = _mapping(projection.get("run"))
        comparison = _mapping(projection.get("comparison"))
        presentation = _mapping(run_payload.get("presentation"))
        validity = _mapping(run_payload.get("validity"))
        rows.append(
            "<tr>"
            f"<td><code>{_escaped(run_payload.get('clustering_run_id'))}</code></td>"
            f"<td>{_escaped_json(run_payload.get('requested_parameters'))}</td>"
            f"<td>{_escaped_json(run_payload.get('effective_parameters'))}</td>"
            f"<td>{_available(comparison.get('largest_cluster_size'))}</td>"
            f"<td>{_ratio(comparison.get('dominant_cluster_ratio'))}</td>"
            f"<td>{_ratio(comparison.get('dominant_assigned_ratio'))}</td>"
            f"<td>{_number(comparison.get('score'))}</td>"
            f"<td>{_available(comparison.get('rank'))}</td>"
            f"<td>{_escaped(validity.get('technically_valid'))}</td>"
            f"<td>{_escaped(presentation.get('banner_kind'))}</td>"
            f"<td>{_escaped(presentation.get('projection_mode'))}</td>"
            f"<td>{_escaped(comparison.get('recommended_by_heuristic'))}</td>"
            f"<td>{_escaped(run_payload.get('selected_by_maintainer'))}</td>"
            "</tr>"
        )
    return (
        "<h2>Candidate runs</h2>"
        '<p class="muted">Recommendation is heuristic evidence; maintainer '
        "selection remains an explicit separate decision.</p>"
        f"<p>Candidates: {summary['candidate_count']}; technically valid: "
        f"{summary['technically_valid_count']}; technically invalid: "
        f"{summary['technically_invalid_count']}.</p>"
        "<table><thead><tr><th>Run</th><th>Requested</th><th>Effective</th>"
        "<th>Largest cluster</th><th>Dominant / corpus</th>"
        "<th>Dominant / assigned</th><th>Score</th><th>Rank</th>"
        "<th>Technically valid</th><th>Banner</th><th>Projection mode</th>"
        "<th>Recommended</th><th>Maintainer selected</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_detail_view(projection: Mapping[str, object]) -> str:
    run_payload = _mapping(projection.get("run"))
    presentation = _mapping(run_payload.get("presentation"))
    if presentation.get("projection_mode") != "full_interpretation":
        return _render_limited_overview(run_payload)
    clusters = _mapping_list(projection.get("clusters"))
    sections = [
        _render_full_overview(run_payload),
        _render_cluster_index_projection(clusters),
    ]
    sections.extend(_render_cluster_panel_projection(cluster) for cluster in clusters)
    return "\n".join(sections)


def _render_full_overview(run_payload: Mapping[str, object]) -> str:
    metrics = _mapping(run_payload.get("partition_metrics"))
    validity = _mapping(run_payload.get("validity"))
    return (
        "<h2>Overview</h2><table><tbody>"
        f"<tr><th>Corpus items</th><td>{_escaped(metrics.get('total_items'))}</td></tr>"
        f"<tr><th>Clusters</th><td>{_escaped(metrics.get('cluster_count'))}</td></tr>"
        f"<tr><th>Noise items</th><td>{_escaped(metrics.get('noise_count'))}</td></tr>"
        f"<tr><th>Noise ratio</th><td>{_ratio(metrics.get('noise_ratio'))}</td></tr>"
        "<tr><th>Dominant cluster / corpus</th>"
        f"<td>{_ratio(metrics.get('dominant_cluster_ratio'))}</td></tr>"
        "<tr><th>Dominant cluster / assigned</th>"
        f"<td>{_ratio(metrics.get('dominant_assigned_ratio'))}</td></tr>"
        "<tr><th>Cluster-size histogram</th>"
        f"<td>{_escaped_json(metrics.get('cluster_size_histogram'))}</td></tr>"
        "<tr><th>Technically valid</th>"
        f"<td>{_escaped(validity.get('technically_valid'))}</td></tr>"
        "<tr><th>Requested parameters</th>"
        f"<td>{_escaped_json(run_payload.get('requested_parameters'))}</td></tr>"
        "<tr><th>Effective parameters</th>"
        f"<td>{_escaped_json(run_payload.get('effective_parameters'))}</td></tr>"
        "</tbody></table>"
    )


def _render_limited_overview(run_payload: Mapping[str, object]) -> str:
    validity = _mapping(run_payload.get("validity"))
    facts = _mapping(run_payload.get("diagnostic_facts"))
    failed = validity.get("failed_invariants")
    return (
        "<h2>Limited diagnostic overview</h2>"
        '<p class="muted">Partition-derived metrics and item interpretation are '
        "withheld because formal validity checks failed.</p>"
        "<table><tbody>"
        f"<tr><th>Failed invariants</th><td>{_escaped_json(failed)}</td></tr>"
        f"<tr><th>Run status</th><td>{_escaped(facts.get('run_status'))}</td></tr>"
        "<tr><th>Completed status</th>"
        f"<td>{_escaped(facts.get('completed_status'))}</td></tr>"
        "<tr><th>Snapshot item count</th>"
        f"<td>{_available(facts.get('snapshot_item_count'))}</td></tr>"
        "<tr><th>Assignment count</th>"
        f"<td>{_available(facts.get('assignment_count'))}</td></tr>"
        "<tr><th>Summary count</th>"
        f"<td>{_available(facts.get('summary_count'))}</td></tr>"
        "</tbody></table>"
    )


def _render_cluster_index_projection(
    clusters: Sequence[Mapping[str, object]],
) -> str:
    rows = []
    for cluster in clusters:
        diagnostics = _mapping(cluster.get("diagnostics"))
        rows.append(
            "<tr>"
            f"<td>{_escaped(_cluster_label(cluster))}</td>"
            f"<td>{_escaped(cluster.get('size'))}</td>"
            f"<td>{_number(diagnostics.get('size_percent'), suffix='%')}</td>"
            f"<td>{_number(diagnostics.get('average_membership_strength'))}</td>"
            "<td><code>"
            f"{_escaped(diagnostics.get('medoid_snapshot_item_id', ''))}"
            "</code></td></tr>"
        )
    return (
        "<h2>Cluster index</h2><table><thead><tr>"
        "<th>Cluster</th><th>Size</th><th>Corpus %</th>"
        "<th>Average membership</th><th>Medoid</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_cluster_panel_projection(cluster: Mapping[str, object]) -> str:
    label = _cluster_label(cluster)
    is_noise = cluster.get("cluster_label") == NOISE_LABEL
    css = "cluster noise" if is_noise else "cluster"
    diagnostics = _mapping(cluster.get("diagnostics"))
    interpretation = _mapping(cluster.get("interpretation"))
    parts = [
        f'<section class="{css}"><h2>Cluster {_escaped(label)}</h2>',
        f"<p>Size: {_escaped(cluster.get('size'))}; membership digest: "
        f"<code>{_escaped(cluster.get('membership_digest'))}</code></p>",
        _render_id_group("Nearest clusters", diagnostics.get("nearest_clusters")),
    ]
    if is_noise:
        parts.append(
            _render_projected_noise(
                _mapping_list(interpretation.get("noise_item_previews"))
            )
        )
    else:
        parts.append(
            _render_item_preview_table(
                "Representative items",
                _mapping_list(interpretation.get("representative_previews")),
            )
        )
        parts.append(
            _render_item_preview_table(
                "Boundary items",
                _mapping_list(interpretation.get("boundary_previews")),
            )
        )
        parts.append(
            _render_projected_correlations(
                _mapping(interpretation.get("categorical_correlations"))
            )
        )
        parts.append(
            _render_numeric_summaries(_mapping(interpretation.get("numeric_summaries")))
        )
        provenance = _mapping(interpretation.get("provenance_completeness"))
        if provenance:
            parts.append(_render_provenance(provenance))
        parts.append(
            "<h3>Machine-inspectability signals</h3><pre>"
            f"{_escaped_json(interpretation.get('machine_inspectability_signals'))}"
            "</pre>"
        )
    parts.append("</section>")
    return "\n".join(parts)


def _render_item_preview_table(
    title: str,
    previews: Sequence[Mapping[str, object]],
) -> str:
    if not previews:
        return f'<h3>{_escaped(title)}</h3><p class="muted">None</p>'
    rows = []
    for preview in previews:
        metadata = ", ".join(
            f"{field}={_display_metadata_value(preview.get(field))}"
            for field in (
                "agent_family",
                "outcome",
                "quality_tier",
                "scope_check_status",
                "verification_status",
            )
        )
        rows.append(
            "<tr>"
            f"<td><code>{_escaped(preview.get('snapshot_item_id'))}</code></td>"
            f"<td><code>{_escaped(preview.get('source_record_id'))}</code></td>"
            f'<td class="preview">'
            f"{_escaped(preview.get('normalized_text_preview'))}</td>"
            f"<td>{_number(preview.get('membership_strength'))}</td>"
            f"<td>{_escaped(metadata)}</td>"
            "</tr>"
        )
    return (
        f"<h3>{_escaped(title)}</h3><table><thead><tr>"
        "<th>Item</th><th>Source record</th><th>Normalized text preview</th>"
        "<th>Membership</th><th>Metadata</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_projected_correlations(
    correlations: Mapping[str, object],
) -> str:
    rows: list[str] = []
    for field, raw_cells in sorted(correlations.items()):
        for raw_cell in _mapping_list(raw_cells):
            display = _display_metadata_value(raw_cell.get("value"))
            insufficient = bool(raw_cell.get("insufficient_sample"))
            css = ' class="insufficient"' if insufficient else ""
            rate = "n/a" if insufficient else str(raw_cell.get("rate"))
            rows.append(
                f"<tr{css}><td>{_escaped(field)}</td>"
                f"<td>{_escaped(display)}</td>"
                f"<td>{_escaped(raw_cell.get('numerator'))}</td>"
                f"<td>{_escaped(raw_cell.get('denominator'))}</td>"
                f"<td>{_escaped(rate)}</td></tr>"
            )
    if not rows:
        return '<h3>Categorical correlations</h3><p class="muted">None</p>'
    return (
        "<h3>Categorical correlations</h3><table><thead><tr>"
        "<th>Field</th><th>Value</th><th>Numerator</th>"
        "<th>Denominator</th><th>Rate</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_numeric_summaries(summaries: Mapping[str, object]) -> str:
    rows: list[str] = []
    for field, raw_summary in sorted(summaries.items()):
        summary = _mapping(raw_summary)
        rows.append(
            "<tr>"
            f"<td>{_escaped(field)}</td>"
            f"<td>{_escaped(summary.get('known_count'))}</td>"
            f"<td>{_escaped(summary.get('unknown_count'))}</td>"
            f"<td>{_available(summary.get('min'))}</td>"
            f"<td>{_available(summary.get('p25'))}</td>"
            f"<td>{_available(summary.get('median'))}</td>"
            f"<td>{_available(summary.get('p75'))}</td>"
            f"<td>{_available(summary.get('max'))}</td>"
            f"<td>{_available(summary.get('mean'))}</td>"
            f"<td>{_escaped_json(summary.get('buckets'))}</td>"
            "</tr>"
        )
    return (
        "<h3>Numeric summaries</h3><table><thead><tr>"
        "<th>Field</th><th>Known</th><th>Unknown</th><th>Min</th>"
        "<th>P25</th><th>Median</th><th>P75</th><th>Max</th>"
        "<th>Mean</th><th>Buckets</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _render_provenance(provenance: Mapping[str, object]) -> str:
    return (
        "<h3>Provenance completeness</h3><table><tbody>"
        f"<tr><th>Items</th><td>{_escaped(provenance.get('item_count'))}</td></tr>"
        "<tr><th>Trajectory selected</th>"
        f"<td>{_escaped(provenance.get('trajectory_selected_count'))}</td></tr>"
        "<tr><th>Patch Trail present</th>"
        f"<td>{_escaped(provenance.get('patch_trail_present_count'))}</td></tr>"
        "<tr><th>Registry overlay present</th>"
        f"<td>{_escaped(provenance.get('registry_overlay_present_count'))}</td></tr>"
        "<tr><th>Unknown rates</th>"
        f"<td>{_escaped_json(provenance.get('fields_unknown_rate'))}</td></tr>"
        "</tbody></table>"
    )


def _render_projected_noise(
    entries: Sequence[Mapping[str, object]],
) -> str:
    if not entries:
        return '<h3>Noise explorer</h3><p class="muted">No noise items.</p>'
    rows: list[str] = []
    for entry in entries:
        preview = _mapping(entry.get("preview"))
        flags = _mapping(entry.get("flags"))
        active_flags = sorted(key for key, enabled in flags.items() if enabled)
        rows.append(
            "<tr>"
            f"<td><code>{_escaped(preview.get('snapshot_item_id'))}</code></td>"
            f"<td>{_escaped(', '.join(active_flags) or 'none')}</td>"
            f'<td class="preview">'
            f"{_escaped(preview.get('normalized_text_preview'))}</td>"
            f"<td>{_number(preview.get('membership_strength'))}</td>"
            "</tr>"
        )
    return (
        "<h3>Noise explorer</h3><table><thead><tr>"
        "<th>Item</th><th>Observable flags (not semantic classification)</th>"
        "<th>Normalized text preview</th><th>Membership</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_id_group(title: str, value: object) -> str:
    if not isinstance(value, list) or not value:
        return f'<h3>{html.escape(title)}</h3><p class="muted">None</p>'
    pills = "".join(
        f'<span class="pill">{html.escape(str(item))}</span>' for item in value
    )
    return f"<h3>{html.escape(title)}</h3><p>{pills}</p>"


def _cluster_label(cluster: Mapping[str, object]) -> str:
    display = cluster.get("display_cluster_id")
    return "noise" if display is None else str(display)


def _display_metadata_value(value: object) -> str:
    if not isinstance(value, Mapping):
        return "unknown"
    return str(value.get("display", "unknown"))


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _escaped(value: object) -> str:
    return html.escape(str(value))


def _escaped_json(value: object) -> str:
    return html.escape(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _available(value: object) -> str:
    return "unavailable" if value is None else _escaped(value)


def _number(value: object, *, suffix: str = "") -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "unavailable"
    return f"{float(value):.3f}{suffix}"


def _ratio(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "unavailable"
    return f"{float(value):.1%}"


__all__ = ["render_analytics_html"]
