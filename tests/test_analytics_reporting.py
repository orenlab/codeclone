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
    ActiveSelectionResult,
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusteringRunStatus,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
    ProfileAssessmentRecord,
    ProfileBatchRecord,
    ProfileBatchRunRecord,
    ProfileManifestSnapshotRecord,
    RunSelectionRecord,
)
from codeclone.analytics.corpus.keys import membership_digest
from codeclone.analytics.exceptions import AnalyticsWorkflowError
from codeclone.analytics.export import json_export
from codeclone.analytics.integrity import PartitionValidityAssessment
from codeclone.analytics.report import html as html_report
from codeclone.analytics.report import interpret as interpret_report
from codeclone.analytics.report.messages.profiles import profile_banner_message
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
        self.active_selection = ActiveSelectionResult(None, False)

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

    def get_active_run_selection(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        profile_batch_id: str | None,
    ) -> ActiveSelectionResult:
        assert snapshot_id == "snapshot"
        assert embedding_generation_id == "embedding"
        assert profile_batch_id is None
        return self.active_selection


class _ProfileReportStore(_ReportStore):
    def __init__(self) -> None:
        super().__init__()
        self.runs = (_run(),)
        self.profile_batch = ProfileBatchRecord(
            profile_batch_id="pbatch-profile",
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            profile_id="intent-small-discovery-v1",
            profile_manifest_digest="a" * 64,
            candidate_space_digest="b" * 64,
            started_at_utc="2026-01-01T00:00:00Z",
            finished_at_utc="2026-01-01T00:00:02Z",
            status="completed",
            candidate_count_planned=1,
            candidate_count_succeeded=1,
            candidate_count_failed=0,
            recommended_clustering_run_id=None,
            recommendation_rationale_json=None,
            batch_max_cluster_count=1,
            created_at_utc="2026-01-01T00:00:00Z",
        )
        self.profile_assessment = ProfileAssessmentRecord(
            profile_batch_id="pbatch-profile",
            clustering_run_id="run",
            profile_id="intent-small-discovery-v1",
            profile_version="1.0.0",
            profile_manifest_digest="a" * 64,
            suitable_for_profile=False,
            rejection_reasons_json='["dominant_ratio_above_max"]',
            observed_metrics_json=(
                '{"dominant_assigned_ratio":1.0,'
                '"dominant_cluster_ratio":0.5,'
                '"noise_ratio":0.5,'
                '"non_noise_cluster_count":1,'
                '"non_noise_count":1}'
            ),
            assessed_digest="assessment-digest",
        )
        self.profile_selection: RunSelectionRecord | None = None

    def get_profile_batch(
        self,
        profile_batch_id: str,
    ) -> ProfileBatchRecord | None:
        return (
            self.profile_batch
            if profile_batch_id == self.profile_batch.profile_batch_id
            else None
        )

    def get_latest_profile_batch(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        profile_id: str,
    ) -> ProfileBatchRecord | None:
        assert snapshot_id == "snapshot"
        assert embedding_generation_id == "embedding"
        return (
            self.profile_batch if profile_id == self.profile_batch.profile_id else None
        )

    def list_profile_batch_ids_for_run(
        self,
        *,
        clustering_run_id: str,
    ) -> tuple[str, ...]:
        return (
            (self.profile_batch.profile_batch_id,) if clustering_run_id == "run" else ()
        )

    def list_profile_batch_run_records(
        self,
        *,
        profile_batch_id: str,
    ) -> tuple[ProfileBatchRunRecord, ...]:
        assert profile_batch_id == self.profile_batch.profile_batch_id
        return (
            ProfileBatchRunRecord(
                profile_batch_id=profile_batch_id,
                clustering_run_id="run",
                candidate_ordinal=0,
                candidate_dedupe_key="2|1|1|eom",
            ),
        )

    def list_clustering_runs_for_batch(
        self,
        *,
        profile_batch_id: str,
    ) -> tuple[ClusteringRunRecord, ...]:
        assert profile_batch_id == self.profile_batch.profile_batch_id
        return self.runs

    def get_profile_assessment(
        self,
        *,
        profile_batch_id: str,
        clustering_run_id: str,
    ) -> ProfileAssessmentRecord | None:
        if (
            profile_batch_id == self.profile_batch.profile_batch_id
            and clustering_run_id == "run"
        ):
            return self.profile_assessment
        return None

    def list_profile_assessments(
        self,
        *,
        profile_batch_id: str,
    ) -> tuple[ProfileAssessmentRecord, ...]:
        assert profile_batch_id == self.profile_batch.profile_batch_id
        return (self.profile_assessment,)

    def get_profile_manifest_snapshot(
        self,
        profile_manifest_digest: str,
    ) -> ProfileManifestSnapshotRecord | None:
        if profile_manifest_digest != self.profile_batch.profile_manifest_digest:
            return None
        return ProfileManifestSnapshotRecord(
            profile_manifest_digest=profile_manifest_digest,
            profile_id=self.profile_batch.profile_id,
            profile_version="1.0.0",
            manifest_schema_version="1",
            canonical_manifest_json="{}",
            label="Discovery lens",
            description="Narrow candidate families.",
            created_at_utc="2026-01-01T00:00:00Z",
        )

    def get_active_run_selection(
        self,
        *,
        snapshot_id: str,
        embedding_generation_id: str,
        profile_batch_id: str | None,
    ) -> ActiveSelectionResult:
        assert snapshot_id == "snapshot"
        assert embedding_generation_id == "embedding"
        assert profile_batch_id == self.profile_batch.profile_batch_id
        return ActiveSelectionResult(self.profile_selection, False)


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


def test_profile_export_and_html_use_persisted_control_plane() -> None:
    store = _ProfileReportStore()
    store.profile_selection = replace(
        _selection(),
        profile_batch_id=store.profile_batch.profile_batch_id,
        profile_id=store.profile_batch.profile_id,
        profile_manifest_digest=store.profile_batch.profile_manifest_digest,
    )
    single = json.loads(
        json_export.export_clustering_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            clustering_run_id="run",
            profile_batch_id=store.profile_batch.profile_batch_id,
        )
    )
    run = single["clustering_run"]
    assert single["schema_version"] == "1.3"
    assert single["control_plane_contract_version"] == "1.0"
    assert single["interpretation_contract_version"] == "1.1"
    assert run["profile_context"]["label"] == "Discovery lens"
    assert run["profile_context"]["suitability"]["suitable_for_profile"] is False
    assert run["selection"]["is_active"] is True
    assert run["selection"]["legacy_bool_mirror"] is False
    assert run["presentation"]["banner_kind"] == "maintainer_selected"

    store.profile_selection = None
    rejected = html_report.render_analytics_html(
        store=_as_sqlite_store(store),
        snapshot=_snapshot(),
        run=_run(),
        profile_batch_id=store.profile_batch.profile_batch_id,
    )
    assert 'data-banner-kind="valid_but_profile_rejected"' in rejected
    assert "Discovery lens" in rejected

    store.profile_assessment = replace(
        store.profile_assessment,
        suitable_for_profile=True,
        rejection_reasons_json="[]",
    )
    store.profile_batch = replace(
        store.profile_batch,
        recommended_clustering_run_id="run",
        recommendation_rationale_json='{"profile_score":0.5}',
    )
    recommended = html_report.render_analytics_html(
        store=_as_sqlite_store(store),
        snapshot=_snapshot(),
        run=_run(),
        profile_batch_id=store.profile_batch.profile_batch_id,
    )
    assert 'data-banner-kind="profile_recommended"' in recommended

    comparison = json.loads(
        json_export.export_sweep_comparison_json(
            store=_as_sqlite_store(store),
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            profile_batch_id=store.profile_batch.profile_batch_id,
        )
    )
    assert comparison["profile_summary"]["recommended_for_profile_run_id"] == "run"
    assert comparison["candidates"][0]["comparison"]["is_profile_recommended"] is True


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
    assert profile_banner_message("candidate_only") in rendered
    assert 'data-banner-kind="candidate_only"' in rendered
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
        active_maintainer_selection=_selection(),
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

    store.runs = (_run(),)
    store.active_selection = ActiveSelectionResult(None, True)
    with pytest.raises(AnalyticsWorkflowError, match="selection chain ambiguous"):
        interpret_report.build_sweep_comparison_projection(
            store=_as_sqlite_store(store),
            snapshot=_snapshot(),
            embedding_generation_id="embedding",
        )


def _selection() -> RunSelectionRecord:
    return RunSelectionRecord(
        selection_id="selection",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        profile_batch_id=None,
        profile_id=None,
        profile_manifest_digest=None,
        selected_run_id="run",
        selected_at_utc="2026-01-01T00:00:02Z",
        selected_by="maintainer",
        rationale=None,
        supersedes_selection_id=None,
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
