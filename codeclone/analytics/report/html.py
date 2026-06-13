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
from ..clustering.sweep import score_clustering_result
from ..contracts import ClusteringRunRecord, ClusterSummaryRecord, CorpusSnapshotRecord
from ..exceptions import AnalyticsWorkflowError
from ..integrity import validate_persisted_run
from ..store.sqlite import SqliteCorpusAnalyticsStore


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
    if generation is None:
        raise AnalyticsWorkflowError(
            f"missing embedding generation: {run.embedding_generation_id}"
        )
    if comparison_only:
        body = _render_comparison_table(store, snapshot.snapshot_id, run)
        title = "Corpus Analytics Sweep Comparison"
        run_line = ""
    else:
        validate_persisted_run(
            store=store,
            snapshot_id=snapshot.snapshot_id,
            clustering_run_id=run.clustering_run_id,
        )
        body = _render_detail_view(store=store, snapshot=snapshot, run=run)
        title = "Corpus Analytics Cluster Report"
        run_line = f"<p>Run: <code>{html.escape(run.clustering_run_id)}</code></p>"
    reproducibility_note = ""
    if not generation.exact_model_artifact_reproducibility:
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
.pill {{ display: inline-block; background: #eef0ff; margin: .1rem;
padding: .15rem .35rem; border-radius: .3rem; }}
.muted {{ color: #666; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p>Snapshot: <code>{html.escape(snapshot.snapshot_id)}</code></p>
{run_line}
{reproducibility_note}
{body}
</body>
</html>
"""


def _render_comparison_table(
    store: SqliteCorpusAnalyticsStore,
    snapshot_id: str,
    current_run: ClusteringRunRecord,
) -> str:
    rows: list[str] = []
    for run in store.list_clustering_runs(
        snapshot_id=snapshot_id,
        embedding_generation_id=current_run.embedding_generation_id,
    ):
        if run.status != "completed":
            continue
        validate_persisted_run(
            store=store,
            snapshot_id=snapshot_id,
            clustering_run_id=run.clustering_run_id,
        )
        assignments = store.list_assignments(run.clustering_run_id)
        cluster_count = len(
            {
                item.cluster_label
                for item in assignments
                if item.cluster_label != NOISE_LABEL
            }
        )
        noise_count = sum(
            1 for item in assignments if item.cluster_label == NOISE_LABEL
        )
        noise_fraction = noise_count / len(assignments) if assignments else 1.0
        score = score_clustering_result(
            cluster_count=cluster_count,
            noise_fraction=noise_fraction,
            n_samples=len(assignments),
        )
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(run.clustering_run_id)}</code></td>"
            f"<td>{html.escape(run.requested_parameters_json)}</td>"
            f"<td>{html.escape(run.effective_parameters_json)}</td>"
            f"<td>{cluster_count}</td><td>{noise_fraction:.3f}</td>"
            f"<td>{score:.3f}</td>"
            f"<td>{run.recommended_by_heuristic}</td>"
            f"<td>{run.selected_by_maintainer}</td>"
            "</tr>"
        )
    return (
        "<h2>Candidate runs</h2>"
        '<p class="muted">Recommendation is heuristic evidence; maintainer '
        "selection remains an explicit separate decision.</p>"
        "<table><thead><tr><th>Run</th><th>Requested</th><th>Effective</th>"
        "<th>Clusters</th><th>Noise fraction</th><th>Score</th>"
        "<th>Recommended</th><th>Maintainer selected</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_detail_view(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot: CorpusSnapshotRecord,
    run: ClusteringRunRecord,
) -> str:
    summaries = store.list_summaries(run.clustering_run_id)
    assignments = store.list_assignments(run.clustering_run_id)
    items = {
        item.snapshot_item_id: item for item in store.list_items(snapshot.snapshot_id)
    }
    noise_count = sum(1 for item in assignments if item.cluster_label == NOISE_LABEL)
    cluster_count = sum(1 for item in summaries if item.cluster_label != NOISE_LABEL)
    sections = [
        "<h2>Overview</h2>",
        "<table><tbody>"
        f"<tr><th>Corpus items</th><td>{snapshot.record_count}</td></tr>"
        f"<tr><th>Clusters</th><td>{cluster_count}</td></tr>"
        f"<tr><th>Noise items</th><td>{noise_count}</td></tr>"
        "<tr><th>Recommended by heuristic</th>"
        f"<td>{run.recommended_by_heuristic}</td></tr>"
        "<tr><th>Selected by maintainer</th>"
        f"<td>{run.selected_by_maintainer}</td></tr>"
        "<tr><th>Requested parameters</th>"
        f"<td>{html.escape(run.requested_parameters_json)}</td></tr>"
        "<tr><th>Effective parameters</th>"
        f"<td>{html.escape(run.effective_parameters_json)}</td></tr>"
        "</tbody></table>",
        _render_cluster_index(summaries),
    ]
    for summary in summaries:
        diagnostics = _diagnostics(summary)
        sections.append(_render_cluster_panel(summary, diagnostics, items))
    return "\n".join(sections)


def _render_cluster_index(summaries: Sequence[ClusterSummaryRecord]) -> str:
    rows = []
    for summary in summaries:
        diagnostics = _diagnostics(summary)
        label = _display_label(summary)
        rows.append(
            "<tr>"
            f"<td>{html.escape(label)}</td><td>{summary.size}</td>"
            f"<td>{_float_value(diagnostics.get('size_percent')):.2f}%</td>"
            f"<td>{html.escape(str(diagnostics.get('average_membership_strength')))}</td>"
            "<td><code>"
            f"{html.escape(str(diagnostics.get('medoid_snapshot_item_id', '')))}"
            "</code></td>"
            "</tr>"
        )
    return (
        "<h2>Cluster index</h2><table><thead><tr>"
        "<th>Cluster</th><th>Size</th><th>Corpus %</th>"
        "<th>Average membership</th><th>Medoid</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_cluster_panel(
    summary: ClusterSummaryRecord,
    diagnostics: Mapping[str, object],
    items: Mapping[str, object],
) -> str:
    label = _display_label(summary)
    css = "cluster noise" if summary.cluster_label == NOISE_LABEL else "cluster"
    parts = [
        f'<section class="{css}"><h2>Cluster {html.escape(label)}</h2>',
        f"<p>Size: {summary.size}; membership digest: "
        f"<code>{html.escape(summary.membership_digest)}</code></p>",
        _render_id_group("Representatives", diagnostics.get("representatives")),
        _render_id_group("Boundary items", diagnostics.get("boundary_items")),
        _render_id_group("Nearest clusters", diagnostics.get("nearest_clusters")),
    ]
    distributions = diagnostics.get("metadata_distributions")
    if isinstance(distributions, dict):
        parts.append("<h3>Metadata correlations</h3>")
        parts.append(_render_distributions(distributions))
    if summary.cluster_label == NOISE_LABEL:
        parts.append(_render_noise_explorer(diagnostics, items))
    parts.append("</section>")
    return "\n".join(parts)


def _render_id_group(title: str, value: object) -> str:
    if not isinstance(value, list) or not value:
        return f'<h3>{html.escape(title)}</h3><p class="muted">None</p>'
    pills = "".join(
        f'<span class="pill">{html.escape(str(item))}</span>' for item in value
    )
    return f"<h3>{html.escape(title)}</h3><p>{pills}</p>"


def _render_distributions(distributions: dict[str, object]) -> str:
    parts = [
        "<table><thead><tr><th>Field</th><th>Value</th>"
        "<th>Numerator</th><th>Denominator</th><th>Rate</th>"
        "</tr></thead><tbody>"
    ]
    for field, values in sorted(distributions.items()):
        if not isinstance(values, dict):
            continue
        for key, cell in sorted(values.items()):
            if not isinstance(cell, dict):
                continue
            insufficient = bool(cell.get("insufficient_sample"))
            css = ' class="insufficient"' if insufficient else ""
            rate = "n/a" if insufficient else str(cell.get("rate"))
            parts.append(
                f"<tr{css}><td>{html.escape(str(field))}</td>"
                f"<td>{html.escape(str(key))}</td>"
                f"<td>{html.escape(str(cell.get('numerator')))}</td>"
                f"<td>{html.escape(str(cell.get('denominator')))}</td>"
                f"<td>{html.escape(rate)}</td></tr>"
            )
    parts.append("</tbody></table>")
    return "".join(parts)


def _render_noise_explorer(
    diagnostics: Mapping[str, object],
    items: Mapping[str, object],
) -> str:
    rows: list[str] = []
    noise_items = diagnostics.get("noise_items")
    if not isinstance(noise_items, list):
        return '<h3>Noise explorer</h3><p class="muted">No noise items.</p>'
    for entry in noise_items:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("snapshot_item_id", ""))
        item = items.get(item_id)
        text = str(getattr(item, "normalized_text", ""))
        flags = entry.get("flags")
        active_flags = []
        if isinstance(flags, dict):
            active_flags = sorted(key for key, enabled in flags.items() if enabled)
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(item_id)}</code></td>"
            f"<td>{html.escape(', '.join(active_flags) or 'none')}</td>"
            f"<td>{html.escape(text[:240])}</td>"
            "</tr>"
        )
    return (
        "<h3>Noise explorer</h3><table><thead><tr>"
        "<th>Item</th><th>Observable flags</th><th>Normalized text preview</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _diagnostics(summary: ClusterSummaryRecord) -> dict[str, object]:
    try:
        payload = json.loads(summary.diagnostics_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _display_label(summary: ClusterSummaryRecord) -> str:
    if summary.display_cluster_id is None:
        return "noise"
    return str(summary.display_cluster_id)


def _float_value(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    return 0.0


__all__ = ["render_analytics_html"]
