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

from codeclone.analytics.clustering.sweep import clustering_algorithm_manifest
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
from codeclone.analytics.corpus.keys import membership_digest
from codeclone.analytics.exceptions import AnalyticsWorkflowError
from codeclone.analytics.export import json_export
from codeclone.analytics.integrity import PartitionValidityAssessment
from codeclone.analytics.report import html as html_report
from codeclone.analytics.report import interpret as interpret_report
from codeclone.analytics.store.sqlite import SqliteCorpusAnalyticsStore
from codeclone.analytics.store.vectors_lancedb import vector_row_key
from codeclone.contracts import CORPUS_EMBEDDING_CONTRACT_VERSION


def _snapshot() -> CorpusSnapshotRecord:
    return CorpusSnapshotRecord(
        snapshot_id="snapshot",
        lane="intent",
        representation_kind="intent.description.v1",
        representation_version="3",
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
    effective_parameters = {
        "pca_dimensions": 2,
        "min_cluster_size": 1,
        "min_samples": 1,
        "cluster_selection_method": "eom",
        "algorithm_manifest": clustering_algorithm_manifest(),
    }
    return ClusteringRunRecord(
        clustering_run_id=run_id,
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json='{"min_cluster_size":1}',
        effective_parameters_json=json.dumps(effective_parameters, sort_keys=True),
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
            EmbeddingItemRecord(
                "embedding",
                "clustered",
                vector_row_key(
                    embedding_generation_id="embedding",
                    snapshot_item_id="clustered",
                ),
                "digest-a",
                2,
            ),
            EmbeddingItemRecord(
                "embedding",
                "noise",
                vector_row_key(
                    embedding_generation_id="embedding",
                    snapshot_item_id="noise",
                ),
                "digest-b",
                2,
            ),
        )
        cluster_digest = membership_digest(["clustered"])
        noise_digest = membership_digest(["noise"])
        self.assignments = (
            ClusterAssignmentRecord("run", "clustered", 0, 0.9, cluster_digest),
            ClusterAssignmentRecord("run", "noise", -1, 0.1, noise_digest),
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
            ClusterSummaryRecord("run", 0, 1, cluster_digest, 1, diagnostics),
            ClusterSummaryRecord("run", -1, None, noise_digest, 1, noise_diagnostics),
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


def test_sweep_export_includes_limited_failed_runs() -> None:
    store = _ReportStore()
    payload = json.loads(
        json_export.export_sweep_comparison_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
        )
    )
    candidate_ids = [
        candidate["run"]["clustering_run_id"] for candidate in payload["candidates"]
    ]
    assert candidate_ids == ["run", "failed"]
    assert payload["comparison_summary"] == {
        "candidate_count": 2,
        "recommended_run_id": "run",
        "selected_run_id": None,
        "technically_invalid_count": 1,
        "technically_valid_count": 1,
    }
    failed = payload["candidates"][1]
    assert failed["run"]["validity"]["technically_valid"] is False
    assert failed["run"]["presentation"]["projection_mode"] == "limited_diagnostic"
    assert failed["comparison"]["score"] is None
    assert "partition_metrics" not in failed["run"]
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
    limited = json.loads(
        json_export.export_sweep_comparison_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
        )
    )
    assert limited["embedding_generation"] is None
    assert limited["embedding_items"] == []
    assert all(
        candidate["run"]["validity"]["technically_valid"] is False
        for candidate in limited["candidates"]
    )


def test_clustering_export_serializes_optional_fields() -> None:
    store = _ReportStore()
    store.generation = _generation(exact=False)
    store.items = (
        replace(
            store.items[0],
            normalized_text="<unsafe>",
            registry_overlay_json=None,
        ),
        store.items[1],
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
    assert payload["clustering_run"]["algorithm_manifest"]["pca_solver"] == "full"
    assert payload["noise_items"] == ["noise"]
    preview = payload["clusters"][0]["interpretation"]["representative_previews"][0]
    assert preview["normalized_text_preview"] == "<unsafe>"
    assert "&lt;" not in preview["normalized_text_preview"]
    assert payload["content_disclosure"]["contains_normalized_text_previews"] is True


def test_single_export_context_errors_are_hard_failures() -> None:
    store = _ReportStore()
    store.snapshot = None
    with pytest.raises(AnalyticsWorkflowError, match="unknown snapshot"):
        json_export.export_clustering_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            clustering_run_id="run",
        )
    store.snapshot = _snapshot()
    with pytest.raises(AnalyticsWorkflowError, match="unknown clustering run"):
        json_export.export_clustering_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            clustering_run_id="missing",
        )
    store.runs = (replace(_run(), snapshot_id="other"),)
    with pytest.raises(AnalyticsWorkflowError, match="belongs to snapshot"):
        json_export.export_clustering_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            clustering_run_id="run",
        )
    assert json_export._json_object_or_none("{") is None
    assert json_export._json_object_or_none("[]") is None


def test_broken_representative_exports_limited_diagnostic_only() -> None:
    store = _ReportStore()
    broken = replace(
        store.summaries[0],
        diagnostics_json=(
            '{"boundary_items":[],"representatives":["missing"],'
            '"metadata_distributions":{}}'
        ),
    )
    store.summaries = (broken, store.summaries[1])
    payload = json.loads(
        json_export.export_clustering_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            clustering_run_id="run",
        )
    )
    run = payload["clustering_run"]
    assert run["validity"]["failed_invariants"] == ["V9"]
    assert run["presentation"]["banner_kind"] == "technically_invalid"
    assert run["score"] is None
    assert "partition_metrics" not in run
    assert "clusters" not in payload
    assert "items" not in payload
    assert payload["content_disclosure"] == {
        "contains_normalized_text_previews": False,
        "max_preview_characters": 240,
        "preview_scope": [],
    }


def test_html_escapes_previews_and_marks_candidate_only() -> None:
    store = _ReportStore()
    candidate = replace(_run(), recommended_by_heuristic=False)
    store.runs = (candidate, store.runs[1])
    store.items = (
        replace(store.items[0], normalized_text="<script>alert(1)</script>"),
        store.items[1],
    )
    rendered = html_report.render_analytics_html(
        store=_as_sqlite_store(store),
        snapshot=_snapshot(),
        run=candidate,
    )
    assert "Candidate run \u2014 not heuristically recommended" in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "Provenance completeness" in rendered
    assert "Observable flags (not semantic classification)" in rendered


def test_html_comparison_and_context_errors() -> None:
    store = _ReportStore()
    rendered = html_report.render_analytics_html(
        store=_as_sqlite_store(store),
        snapshot=_snapshot(),
        run=_run(),
        comparison_only=True,
    )
    assert "Corpus Analytics Sweep Comparison" in rendered
    assert "failed" in rendered
    assert "Dominant / corpus" in rendered
    assert "Projection mode" in rendered
    assert "unavailable" in rendered
    assert "Reproducibility:" not in rendered

    with pytest.raises(AnalyticsWorkflowError, match="does not belong"):
        html_report.render_analytics_html(
            store=_as_sqlite_store(store),
            snapshot=replace(_snapshot(), snapshot_id="other"),
            run=_run(),
        )
    store.generation = None
    limited = html_report.render_analytics_html(
        store=_as_sqlite_store(store),
        snapshot=_snapshot(),
        run=_run(),
    )
    assert "Embedding generation metadata is unavailable" in limited
    assert "Limited diagnostic overview" in limited
    assert "Cluster index" not in limited


def test_html_id_group_escapes_values() -> None:
    assert html_report._render_id_group("Empty", None).endswith("None</p>")
    assert "pill" in html_report._render_id_group("Values", ["<unsafe>"])
    assert "&lt;unsafe&gt;" in html_report._render_id_group("Values", ["<unsafe>"])


def test_interpretation_helper_edge_contracts() -> None:
    valid = PartitionValidityAssessment(True, ())
    selected = interpret_report.derive_presentation_status(
        run=replace(_run(), selected_by_maintainer=True),
        assessment=valid,
    )
    recommended = interpret_report.derive_presentation_status(
        run=_run(),
        assessment=valid,
    )
    assert selected.banner_kind == "maintainer_selected"
    assert recommended.banner_kind == "heuristic_recommended"

    disclosure = interpret_report.content_disclosure(
        {
            "clusters": [
                {
                    "representative_previews": [{}],
                    "boundary_previews": [{}],
                    "nested": {"noise_item_previews": [{}]},
                }
            ]
        }
    )
    assert disclosure["preview_scope"] == [
        "cluster_representatives",
        "cluster_boundaries",
        "noise_items",
    ]

    assert (
        interpret_report._distribution_display_value("agent_family", "null").kind
        == "unknown"
    )
    assert (
        interpret_report._distribution_display_value("anomaly_kinds", "none").kind
        == "confirmed_none"
    )
    assert (
        interpret_report._distribution_display_value("agent_family", "none").kind
        == "empty_collection"
    )
    assert (
        interpret_report._distribution_display_value("agent_family", "codex").kind
        == "value"
    )

    assert (
        interpret_report._provenance_presence(
            {},
            section="trajectory",
            explicit_key="selected",
            positive_key="selected_trajectory_id",
        )
        is None
    )
    assert (
        interpret_report._provenance_presence(
            {"trajectory": {"selected": False}},
            section="trajectory",
            explicit_key="selected",
            positive_key="selected_trajectory_id",
        )
        is False
    )
    assert (
        interpret_report._provenance_presence(
            {"trajectory": {"selected_trajectory_id": "trajectory"}},
            section="trajectory",
            explicit_key="selected",
            positive_key="selected_trajectory_id",
        )
        is True
    )
    assert (
        interpret_report._provenance_presence(
            {"trajectory": {"available": False}},
            section="trajectory",
            explicit_key="selected",
            positive_key="selected_trajectory_id",
        )
        is False
    )
    assert (
        interpret_report._provenance_presence(
            {"trajectory": {"selected_trajectory_id": None}},
            section="trajectory",
            explicit_key="selected",
            positive_key="selected_trajectory_id",
        )
        is None
    )

    assert interpret_report._cluster_size_histogram([1, 4, 8, 16, 32, 64]) == {
        "1-3": 1,
        "4-7": 1,
        "8-15": 1,
        "16-31": 1,
        "32-63": 1,
        "64+": 1,
    }
    assert interpret_report._largest_cluster_size({}) is None
    assert (
        interpret_report._largest_cluster_size({"cluster_size_distribution": ["bad"]})
        is None
    )
    assert interpret_report._json_mapping_or_none("{") is None
    assert interpret_report._json_mapping_or_none("[]") is None
    assert interpret_report._mapping("bad") == {}
    assert interpret_report._string_list("bad") == []
    assert interpret_report._string_list(["a", 1]) == ["a"]

    for value in (True, float("nan")):
        with pytest.raises(AnalyticsWorkflowError, match="finite score"):
            interpret_report._finite_float(value)
    with pytest.raises(AnalyticsWorkflowError, match="integer parameter"):
        interpret_report._integer_parameter({}, "pca_dimensions")
    with pytest.raises(AnalyticsWorkflowError, match="integer field"):
        interpret_report._required_integer({}, "cluster_count")
    with pytest.raises(AnalyticsWorkflowError, match="numeric field"):
        interpret_report._required_number({}, "noise_ratio")
    with pytest.raises(AnalyticsWorkflowError, match="non-finite"):
        interpret_report._required_number({"noise_ratio": float("nan")}, "noise_ratio")
    with pytest.raises(AnalyticsWorkflowError, match="string parameter"):
        interpret_report._string_parameter({}, "cluster_selection_method")


def test_provenance_legacy_evidence_and_overlay_states() -> None:
    item = replace(
        _item("clustered", "text"),
        metadata_json=json.dumps(
            {
                "agent_family": "codex",
                "outcome": "success",
                "anomaly_kinds": [],
                "provenance": {
                    "trajectory": {"selected_trajectory_id": "trajectory"},
                    "patch_trail": {"digest": "trail"},
                },
            }
        ),
        registry_overlay_json="{}",
    )
    summary = interpret_report._provenance_completeness((item,))
    assert summary.trajectory_selected_count == 1
    assert summary.patch_trail_present_count == 1
    assert (
        summary.registry_overlay_present_count,
        summary.agent_family_known_count,
        summary.outcome_known_count,
        summary.anomaly_metadata_known_count,
    ) == (1, 1, 1, 1)

    assert (
        interpret_report._registry_overlay_presence(
            replace(item, registry_overlay_json=None),
            {"registry_overlay": {"present": False}},
        )
        is False
    )
    assert (
        interpret_report._registry_overlay_presence(
            replace(item, registry_overlay_json=None),
            {},
        )
        is None
    )
    assert (
        interpret_report._registry_overlay_presence(
            replace(item, registry_overlay_json="{"),
            {},
        )
        is None
    )


def test_sweep_projection_rejects_conflicting_decisions() -> None:
    store = _ReportStore()
    store.runs = (_run(), _run())
    with pytest.raises(AnalyticsWorkflowError, match="multiple valid heuristic"):
        interpret_report.build_sweep_comparison_projection(
            store=_as_sqlite_store(store),
            snapshot=_snapshot(),
            embedding_generation_id="embedding",
        )

    selected = replace(
        _run(),
        recommended_by_heuristic=False,
        selected_by_maintainer=True,
    )
    store.runs = (selected, selected)
    with pytest.raises(AnalyticsWorkflowError, match="multiple maintainer-selected"):
        interpret_report.build_sweep_comparison_projection(
            store=_as_sqlite_store(store),
            snapshot=_snapshot(),
            embedding_generation_id="embedding",
        )


def test_html_projection_helper_empty_and_malformed_rows() -> None:
    assert "None" in html_report._render_item_preview_table("Items", ())
    assert "None" in html_report._render_projected_correlations(
        {"bad": "value", "also_bad": ["cell"]}
    )
    assert "No noise items" in html_report._render_projected_noise(())
    assert html_report._display_metadata_value("bad") == "unknown"
    assert html_report._mapping_list("bad") == []
    assert html_report._available(None) == "unavailable"
    assert html_report._number(None) == "unavailable"
    assert html_report._ratio(None) == "unavailable"
