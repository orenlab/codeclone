# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest

from codeclone.analytics.contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusteringRunStatus,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)
from codeclone.analytics.exceptions import AnalyticsWorkflowError
from codeclone.analytics.export import json_export
from codeclone.analytics.report import html as html_report
from codeclone.analytics.store.sqlite import SqliteCorpusAnalyticsStore
from codeclone.contracts import CORPUS_EMBEDDING_CONTRACT_VERSION


def _snapshot() -> CorpusSnapshotRecord:
    return CorpusSnapshotRecord(
        snapshot_id="snapshot",
        lane="intent",
        representation_kind="intent.description.v1",
        representation_version="2",
        source_stores_json='{"audit":"<external>"}',
        source_schema_versions_json='{"audit":"4"}',
        record_count=2,
        source_digest="source-digest",
        created_at_utc="2026-01-01T00:00:00Z",
    )


def _generation(*, exact: bool = True) -> EmbeddingGenerationRecord:
    return EmbeddingGenerationRecord(
        embedding_generation_id="embedding",
        provider_id="fastembed",
        provider_package_version="1",
        model_id="model",
        model_revision="revision",
        model_artifact_fingerprint="fingerprint",
        exact_model_artifact_reproducibility=exact,
        dimensions=2,
        embedding_contract_version=CORPUS_EMBEDDING_CONTRACT_VERSION,
        embedding_similarity_metric="cosine",
        vector_preprocessing="l2_normalize",
        created_at_utc="2026-01-01T00:00:00Z",
    )


def _run(
    run_id: str = "run",
    *,
    status: str = "completed",
) -> ClusteringRunRecord:
    return ClusteringRunRecord(
        clustering_run_id=run_id,
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json='{"min_cluster_size":2}',
        effective_parameters_json=(
            '{"algorithm_manifest":{"pca_solver":"full"},"pca_dimensions":2}'
        ),
        random_seed=42,
        run_digest=f"digest-{run_id}",
        recommended_by_heuristic=run_id == "run",
        selected_by_maintainer=False,
        status=cast(ClusteringRunStatus, status),
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )


def _item(item_id: str, text: str) -> CorpusItemRecord:
    return CorpusItemRecord(
        snapshot_id="snapshot",
        representation_key=f"rep-{item_id}",
        snapshot_item_id=item_id,
        source_record_key=f"source-{item_id}",
        project_id="project",
        intent_id=f"intent-{item_id}",
        normalized_text=text,
        normalized_digest=f"normalized-{item_id}",
        normalizer_version="1",
        representation_digest=f"representation-{item_id}",
        metadata_json='{"agent_family":"codex"}',
        registry_overlay_json='{"present":true}',
    )


class _ReportStore:
    def __init__(self) -> None:
        self.snapshot: CorpusSnapshotRecord | None = _snapshot()
        self.generation: EmbeddingGenerationRecord | None = _generation()
        self.runs: tuple[ClusteringRunRecord, ...] = (
            _run(),
            _run("failed", status="failed"),
        )
        self.items: tuple[CorpusItemRecord, ...] = (
            _item("clustered", "Clustered item"),
            _item("noise", "Noise item"),
        )
        self.embedding_items = (
            EmbeddingItemRecord("embedding", "clustered", "row-a", "digest-a", 2),
            EmbeddingItemRecord("embedding", "noise", "row-b", "digest-b", 2),
        )
        self.assignments = (
            ClusterAssignmentRecord("run", "clustered", 0, 0.9, "cluster"),
            ClusterAssignmentRecord("run", "noise", -1, 0.1, "noise"),
        )
        diagnostics = json.dumps(
            {
                "size_percent": 50.0,
                "average_membership_strength": 0.9,
                "medoid_snapshot_item_id": "clustered",
                "representatives": ["clustered"],
                "boundary_items": [],
                "nearest_clusters": [],
                "metadata_distributions": {
                    "agent_family": {
                        "codex": {
                            "numerator": 1,
                            "denominator": 1,
                            "rate": 1.0,
                            "insufficient_sample": False,
                        }
                    }
                },
            }
        )
        noise_diagnostics = json.dumps(
            {
                "size_percent": 50.0,
                "average_membership_strength": None,
                "medoid_snapshot_item_id": "noise",
                "representatives": ["noise"],
                "boundary_items": ["noise"],
                "metadata_distributions": {},
                "noise_items": [
                    {
                        "snapshot_item_id": "noise",
                        "flags": {"short_text": True, "template_match": False},
                    }
                ],
            }
        )
        self.summaries = (
            ClusterSummaryRecord("run", 0, 1, "cluster", 1, diagnostics),
            ClusterSummaryRecord("run", -1, None, "noise", 1, noise_diagnostics),
        )

    def get_snapshot(self, _snapshot_id: str) -> CorpusSnapshotRecord | None:
        return self.snapshot

    def get_embedding_generation(
        self,
        _embedding_generation_id: str,
    ) -> EmbeddingGenerationRecord | None:
        return self.generation

    def get_clustering_run(self, run_id: str) -> ClusteringRunRecord | None:
        return next(
            (run for run in self.runs if run.clustering_run_id == run_id),
            None,
        )

    def list_items(self, _snapshot_id: str) -> tuple[CorpusItemRecord, ...]:
        return self.items

    def list_embedding_items(
        self,
        *,
        embedding_generation_id: str,
    ) -> tuple[EmbeddingItemRecord, ...]:
        assert embedding_generation_id == "embedding"
        return self.embedding_items

    def list_clustering_runs(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str | None = None,
    ) -> tuple[ClusteringRunRecord, ...]:
        assert snapshot_id == "snapshot"
        assert embedding_generation_id == "embedding"
        return self.runs

    def list_assignments(
        self,
        run_id: str,
    ) -> tuple[ClusterAssignmentRecord, ...]:
        return self.assignments if run_id == "run" else ()

    def list_summaries(self, run_id: str) -> tuple[ClusterSummaryRecord, ...]:
        return self.summaries if run_id == "run" else ()


def _as_sqlite_store(store: _ReportStore) -> SqliteCorpusAnalyticsStore:
    return cast(SqliteCorpusAnalyticsStore, store)


def test_sweep_export_validates_context_and_skips_failed_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReportStore()
    validated: list[str] = []
    monkeypatch.setattr(
        json_export,
        "validate_generation_metadata",
        lambda **_kwargs: (_generation(), store.embedding_items),
    )
    monkeypatch.setattr(
        json_export,
        "validate_persisted_run",
        lambda **kwargs: validated.append(str(kwargs["clustering_run_id"])),
    )
    payload = json.loads(
        json_export.export_sweep_comparison_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
        )
    )
    assert validated == ["run"]
    candidate_ids = [
        candidate["run"]["clustering_run_id"] for candidate in payload["candidates"]
    ]
    assert candidate_ids == ["run"]
    assert payload["reproducibility_statement"] is None
    generation = payload["embedding_generation"]
    assert generation["model_artifact_fingerprint"] == "fingerprint"

    store.snapshot = None
    with pytest.raises(AnalyticsWorkflowError, match="unknown snapshot"):
        json_export.export_sweep_comparison_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
        )
    store.snapshot = _snapshot()
    store.generation = None
    with pytest.raises(AnalyticsWorkflowError, match="unknown embedding generation"):
        json_export.export_sweep_comparison_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
        )


def test_clustering_export_serializes_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReportStore()
    store.generation = _generation(exact=False)
    store.items = (replace(store.items[0], registry_overlay_json=None),)
    monkeypatch.setattr(
        json_export,
        "validate_persisted_run",
        lambda **_kwargs: _run(),
    )
    payload = json.loads(
        json_export.export_clustering_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            clustering_run_id="run",
        )
    )
    assert payload["items"][0]["registry_overlay"] is None
    assert "not guaranteed" in payload["reproducibility_statement"]
    assert payload["clustering_run"]["algorithm_manifest"] == {"pca_solver": "full"}
    assert payload["noise_items"] == ["noise"]


def test_html_comparison_and_context_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ReportStore()
    monkeypatch.setattr(
        html_report,
        "validate_persisted_run",
        lambda **_kwargs: _run(),
    )
    rendered = html_report.render_analytics_html(
        store=_as_sqlite_store(store),
        snapshot=_snapshot(),
        run=_run(),
        comparison_only=True,
    )
    assert "Corpus Analytics Sweep Comparison" in rendered
    assert "failed" not in rendered
    assert "<td>1</td><td>0.500</td>" in rendered
    assert "Reproducibility:" not in rendered

    with pytest.raises(AnalyticsWorkflowError, match="does not belong"):
        html_report.render_analytics_html(
            store=_as_sqlite_store(store),
            snapshot=replace(_snapshot(), snapshot_id="other"),
            run=_run(),
        )
    store.generation = None
    with pytest.raises(AnalyticsWorkflowError, match="missing embedding generation"):
        html_report.render_analytics_html(
            store=_as_sqlite_store(store),
            snapshot=_snapshot(),
            run=_run(),
        )


def test_html_helpers_tolerate_malformed_diagnostics() -> None:
    malformed = ClusterSummaryRecord("run", 0, 1, "digest", 1, "{")
    scalar = ClusterSummaryRecord("run", -1, None, "noise", 1, "[]")
    assert html_report._diagnostics(malformed) == {}
    assert html_report._diagnostics(scalar) == {}
    assert html_report._display_label(malformed) == "1"
    assert html_report._display_label(scalar) == "noise"
    assert html_report._float_value("bad") == 0.0
    assert html_report._render_id_group("Empty", None).endswith("None</p>")
    assert "pill" in html_report._render_id_group("Values", ["<unsafe>"])
    assert "&lt;unsafe&gt;" in html_report._render_id_group("Values", ["<unsafe>"])
    distributions: dict[str, object] = {
        "bad": "not-a-map",
        "field": {
            "bad": "not-a-cell",
            "small": {
                "numerator": 1,
                "denominator": 2,
                "rate": None,
                "insufficient_sample": True,
            },
        },
    }
    table = html_report._render_distributions(distributions)
    assert 'class="insufficient"' in table
    assert "n/a" in table
    assert "not-a-cell" not in table
    assert "No noise items" in html_report._render_noise_explorer({}, {})
    noise = html_report._render_noise_explorer(
        {
            "noise_items": [
                "bad",
                {"snapshot_item_id": "missing", "flags": "bad"},
                {"snapshot_item_id": "known", "flags": {"short_text": True}},
            ]
        },
        {"known": _item("known", "<unsafe>")},
    )
    assert "<unsafe>" not in noise
    assert "&lt;unsafe&gt;" in noise
    assert "short_text" in noise
