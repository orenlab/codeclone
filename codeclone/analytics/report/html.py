# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import html
import json
from collections.abc import Sequence

from ..contracts import ClusteringRunRecord, ClusterSummaryRecord, CorpusSnapshotRecord
from ..store.sqlite import SqliteCorpusAnalyticsStore


def render_analytics_html(
    *,
    store: SqliteCorpusAnalyticsStore,
    snapshot: CorpusSnapshotRecord,
    run: ClusteringRunRecord,
    comparison_only: bool = False,
) -> str:
    summaries = store.list_summaries(run.clustering_run_id)
    generation = store.get_embedding_generation(run.embedding_generation_id)
    reproducibility_note = ""
    if generation is not None and not generation.exact_model_artifact_reproducibility:
        reproducibility_note = (
            "<p><em>Full vector reproducibility is not guaranteed from model id "
            "alone.</em></p>"
        )
    if comparison_only:
        body = _render_comparison_table(store, snapshot.snapshot_id, run)
        title = "Corpus Analytics Sweep Comparison"
    else:
        body = _render_detail_view(summaries)
        title = "Corpus Analytics Cluster Report"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{html.escape(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.4; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 1rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.6rem; text-align: left; }}
th {{ background: #f5f5f5; }}
.insufficient {{ color: #666; font-style: italic; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p>Snapshot: {html.escape(snapshot.snapshot_id)}</p>
<p>Run: {html.escape(run.clustering_run_id)}</p>
<p>Recommended by heuristic: {run.recommended_by_heuristic}</p>
<p>Selected by maintainer: {run.selected_by_maintainer}</p>
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
    runs = store.list_clustering_runs(
        snapshot_id=snapshot_id,
        embedding_generation_id=current_run.embedding_generation_id,
    )
    rows = [
        "<tr>"
        f"<td>{html.escape(run.clustering_run_id)}</td>"
        f"<td>{html.escape(run.effective_parameters_json)}</td>"
        f"<td>{run.recommended_by_heuristic}</td>"
        f"<td>{run.selected_by_maintainer}</td>"
        "</tr>"
        for run in runs
    ]
    return (
        "<table><thead><tr>"
        "<th>Run</th><th>Effective Parameters</th>"
        "<th>Recommended</th><th>Selected</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _render_detail_view(summaries: Sequence[ClusterSummaryRecord]) -> str:
    sections: list[str] = ["<h2>Clusters</h2>"]
    for summary in summaries:
        diagnostics = json.loads(summary.diagnostics_json)
        if not isinstance(diagnostics, dict):
            diagnostics = {}
        display = summary.display_cluster_id
        label = "noise" if display is None else str(display)
        sections.append(f"<h3>Cluster {html.escape(label)}</h3>")
        sections.append(f"<p>Size: {summary.size}</p>")
        distributions = diagnostics.get("metadata_distributions")
        if isinstance(distributions, dict):
            sections.append(_render_distributions(distributions))
    return "\n".join(sections)


def _render_distributions(distributions: dict[str, object]) -> str:
    parts = [
        "<table><thead><tr><th>Field</th><th>Value</th><th>Rate</th></tr></thead><tbody>"
    ]
    for field, values in sorted(distributions.items()):
        if not isinstance(values, dict):
            continue
        for key, cell in sorted(values.items()):
            if not isinstance(cell, dict):
                continue
            numerator = cell.get("numerator")
            denominator = cell.get("denominator")
            rate = cell.get("rate")
            insufficient = bool(cell.get("insufficient_sample"))
            rate_text = "n/a" if insufficient else str(rate)
            css = ' class="insufficient"' if insufficient else ""
            parts.append(
                f"<tr{css}><td>{html.escape(str(field))}</td>"
                f"<td>{html.escape(str(key))}</td>"
                f"<td>{html.escape(rate_text)} "
                f"({numerator}/{denominator})</td></tr>"
            )
    parts.append("</tbody></table>")
    return "".join(parts)


__all__ = ["render_analytics_html"]
