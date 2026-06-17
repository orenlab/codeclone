# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from codeclone.analytics.clustering.models import (
    ClusteringParameters,
    EffectiveClusteringParameters,
)
from codeclone.analytics.clustering.sweep import (
    SweepCandidate,
    candidate_space_digest,
    iter_profile_candidates,
)
from codeclone.analytics.contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    ProfileBatchRecord,
    ProfileBatchRunRecord,
    ProfileManifestSnapshotRecord,
)
from codeclone.analytics.exceptions import AnalyticsStoreError, AnalyticsWorkflowError
from codeclone.analytics.integrity import PartitionValidityAssessment
from codeclone.analytics.metrics.partition_metrics import RunPartitionMetrics
from codeclone.analytics.profiles.loader import (
    canonical_manifest_json,
    load_bundled_profiles,
    load_manifest_value,
    manifest_value,
    profile_manifest_digest,
)
from codeclone.analytics.profiles.ranking import (
    ProfileRankedRun,
    rank_profile_recommendations,
)
from codeclone.analytics.profiles.registry import resolve_profile_registry
from codeclone.analytics.profiles.suitability import (
    assess_profile_suitability,
    profile_assessment_digest,
)
from codeclone.analytics.store.sqlite import SqliteCorpusAnalyticsStore
from codeclone.analytics.workflow import (
    _effective_parameters_from_run,
    _resolve_profile,
    _score_completed_run,
    _validate_profile_applicability,
    assess_and_persist_profile_batch,
    new_profile_batch_id,
    record_run_selection,
)
from codeclone.config.analytics import resolve_analytics_config
from codeclone.contracts import (
    CORPUS_ANALYTICS_STORE_SCHEMA_VERSION,
    CORPUS_CONTROL_PLANE_CONTRACT_VERSION,
    CORPUS_EXPORT_SCHEMA_VERSION,
    CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION,
)
from tests.fixtures.analytics.helpers import write_bundled_profile_pyproject


def test_bundled_profile_contract_and_digest_are_stable() -> None:
    profiles = load_bundled_profiles()
    assert tuple(sorted(profiles)) == (
        "intent-small-balanced-v1",
        "intent-small-discovery-v1",
        "intent-small-outlier-v1",
        "intent-small-stable-v1",
    )
    balanced = profiles["intent-small-balanced-v1"]
    reloaded = load_manifest_value(json.loads(canonical_manifest_json(balanced)))
    assert profile_manifest_digest(reloaded) == profile_manifest_digest(balanced)
    assert CORPUS_PROFILE_MANIFEST_SCHEMA_VERSION == "1"
    assert CORPUS_ANALYTICS_STORE_SCHEMA_VERSION == "1.2"
    assert CORPUS_EXPORT_SCHEMA_VERSION == "1.3"
    assert CORPUS_CONTROL_PLANE_CONTRACT_VERSION == "1.0"


def test_profile_loader_rejects_alias_and_registry_conflict(
    tmp_path: Path,
) -> None:
    bundled = load_bundled_profiles()["intent-small-balanced-v1"]
    payload = manifest_value(bundled)
    payload["representation_kinds"] = ["intent_description"]
    with pytest.raises(
        AnalyticsWorkflowError,
        match="non-canonical representation_kind",
    ):
        load_manifest_value(payload)

    conflicting = manifest_value(bundled)
    conflicting["description"] = "Different contract value."
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(conflicting), encoding="utf-8")
    with pytest.raises(AnalyticsWorkflowError, match="conflicting profile manifest"):
        resolve_profile_registry(profile_paths=(path,))


def test_profile_grid_is_deduplicated_and_digest_is_stable() -> None:
    discovery = load_bundled_profiles()["intent-small-discovery-v1"]
    candidates = iter_profile_candidates(
        profile=discovery,
        n_samples=357,
        n_features=384,
    )
    assert len(candidates) == 24
    assert len({candidate.dedupe_key for candidate in candidates}) == 24
    assert candidate_space_digest(candidates) == candidate_space_digest(
        tuple(reversed(candidates))
    )


def test_profile_ranking_is_lens_specific() -> None:
    profiles = load_bundled_profiles()
    low_clusters = _ranked_run("low", cluster_count=2, noise_ratio=0.2)
    high_clusters = _ranked_run("high", cluster_count=8, noise_ratio=0.2)
    discovery, _ = rank_profile_recommendations(
        profile=profiles["intent-small-discovery-v1"],
        candidates=(low_clusters, high_clusters),
    )
    stable, _ = rank_profile_recommendations(
        profile=profiles["intent-small-stable-v1"],
        candidates=(low_clusters, high_clusters),
    )
    assert discovery is not None and discovery.clustering_run_id == "high"
    assert stable is not None and stable.clustering_run_id == "low"


def test_profile_suitability_is_lens_specific_and_digest_is_stable() -> None:
    profiles = load_bundled_profiles()
    metrics = RunPartitionMetrics(
        total_items=100,
        cluster_count=4,
        noise_count=30,
        non_noise_count=70,
        noise_ratio=0.3,
        dominant_cluster_ratio=0.7,
        dominant_assigned_ratio=1.0,
        dominant_cluster_label=0,
        cluster_size_distribution=(70,),
        cluster_size_histogram={},
    )
    valid = PartitionValidityAssessment(True, ())
    stable = assess_profile_suitability(
        profile=profiles["intent-small-stable-v1"],
        validity=valid,
        metrics=metrics,
    )
    discovery = assess_profile_suitability(
        profile=profiles["intent-small-discovery-v1"],
        validity=valid,
        metrics=metrics,
    )
    assert stable.suitable_for_profile is True
    assert discovery.suitable_for_profile is False
    assert discovery.rejection_reasons == ("dominant_ratio_above_max",)

    digest = profile_assessment_digest(
        profile_batch_id="batch",
        clustering_run_id="run",
        run_digest="run-digest",
        profile_manifest_digest=discovery.profile_manifest_digest,
        assessment=discovery,
    )
    assert digest == profile_assessment_digest(
        profile_batch_id="batch",
        clustering_run_id="run",
        run_digest="run-digest",
        profile_manifest_digest=discovery.profile_manifest_digest,
        assessment=discovery,
    )

    invalid = assess_profile_suitability(
        profile=profiles["intent-small-discovery-v1"],
        validity=PartitionValidityAssessment(False, ("V7",)),
        metrics=None,
    )
    assert invalid.suitable_for_profile is False
    assert invalid.rejection_reasons == ("technically_invalid",)
    assert invalid.observed is None


def test_profile_batch_identity_is_execution_scoped() -> None:
    common = {
        "snapshot_id": "snapshot",
        "embedding_generation_id": "embedding",
        "profile_manifest_digest": "manifest",
        "candidate_space_digest": "space",
    }
    first = new_profile_batch_id(
        **common,
        started_at_utc="2026-01-01T00:00:00.000001Z",
    )
    repeated = new_profile_batch_id(
        **common,
        started_at_utc="2026-01-01T00:00:00.000001Z",
    )
    second = new_profile_batch_id(
        **common,
        started_at_utc="2026-01-01T00:00:00.000002Z",
    )
    assert first == repeated
    assert first != second


def test_profile_applicability_rejects_incompatible_corpus() -> None:
    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    with pytest.raises(AnalyticsWorkflowError, match="record count below minimum"):
        _validate_profile_applicability(
            profile=profile,
            representation_kind="intent.description.v1",
            record_count=49,
            embedding_contract_version="2",
        )
    with pytest.raises(AnalyticsWorkflowError, match="representation kind"):
        _validate_profile_applicability(
            profile=profile,
            representation_kind="other",
            record_count=100,
            embedding_contract_version="2",
        )
    with pytest.raises(AnalyticsWorkflowError, match="embedding contract"):
        _validate_profile_applicability(
            profile=profile,
            representation_kind="intent.description.v1",
            record_count=100,
            embedding_contract_version="999",
        )


def test_analytics_config_resolves_profiles_and_sweep_grid(
    tmp_path: Path,
) -> None:
    profile_path = write_bundled_profile_pyproject(
        tmp_path,
        profile_filename="custom-profile.json",
        analytics_toml_body="""
[tool.codeclone.analytics]
default_profile_id = "intent-small-balanced-v1"
profile_paths = ["custom-profile.json"]
sweep_pca_dimensions = [16, 32]
sweep_min_cluster_sizes = [5]
sweep_min_samples = [1, 3]
sweep_selection_methods = ["leaf"]
""",
    )
    config = resolve_analytics_config(tmp_path)
    assert config.default_profile_id == "intent-small-balanced-v1"
    assert config.profile_paths == (profile_path,)
    assert config.sweep_pca_dimensions == (16, 32)
    assert config.sweep_selection_methods == ("leaf",)

    invalid_root = tmp_path / "invalid"
    invalid_root.mkdir()
    (invalid_root / "pyproject.toml").write_text(
        """
[tool.codeclone.analytics]
default_profile_id = "missing-profile"
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(AnalyticsWorkflowError, match="unknown analytics profile"):
        resolve_analytics_config(invalid_root)


def test_store_profile_batch_and_selection_chain(tmp_path: Path) -> None:
    store = SqliteCorpusAnalyticsStore.open(tmp_path / "analytics.sqlite3")
    try:
        _seed_store(store)
        manifest = load_bundled_profiles()["intent-small-balanced-v1"]
        digest = profile_manifest_digest(manifest)
        store.insert_profile_manifest_snapshot(
            ProfileManifestSnapshotRecord(
                profile_manifest_digest=digest,
                profile_id=manifest.profile_id,
                profile_version=manifest.profile_version,
                manifest_schema_version=manifest.manifest_schema_version,
                canonical_manifest_json=canonical_manifest_json(manifest),
                label=manifest.label,
                description=manifest.description,
                created_at_utc="2026-01-01T00:00:00Z",
            )
        )
        stored_manifest = store.get_profile_manifest_snapshot(digest)
        assert stored_manifest is not None
        store.insert_profile_manifest_snapshot(
            replace(
                stored_manifest,
                created_at_utc="2026-01-02T00:00:00Z",
            )
        )
        store.insert_profile_batch(_batch(digest))
        store.insert_profile_batch_run(
            ProfileBatchRunRecord("batch", "run-a", 0, "2|5|1|eom")
        )
        store.commit()

        first = record_run_selection(
            store=store,
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            selected_run_id="run-a",
            profile_batch_id="batch",
            selected_by="maintainer",
            rationale="first",
        )
        second = record_run_selection(
            store=store,
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            selected_run_id="run-a",
            profile_batch_id="batch",
            selected_by="maintainer",
            rationale="second",
        )
        active = store.get_active_run_selection(
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            profile_batch_id="batch",
        )
        assert active.ambiguous is False
        assert active.record == second
        assert second.supersedes_selection_id == first.selection_id
        persisted_run = store.get_clustering_run("run-a")
        assert persisted_run is not None
        assert persisted_run.selected_by_maintainer is False

        global_selection = record_run_selection(
            store=store,
            snapshot_id="snapshot",
            embedding_generation_id="embedding",
            selected_run_id="run-a",
            profile_batch_id=None,
            selected_by="maintainer",
            rationale=None,
        )
        persisted_run = store.get_clustering_run("run-a")
        assert persisted_run is not None
        assert persisted_run.selected_by_maintainer is True
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            store._conn.execute(
                "UPDATE run_selections SET rationale='changed' WHERE selection_id=?",
                (global_selection.selection_id,),
            )
        store.rollback()

        second_batch = replace(
            _batch(digest),
            profile_batch_id="batch-two",
            started_at_utc="2026-01-01T00:00:02Z",
            created_at_utc="2026-01-01T00:00:02Z",
        )
        store.insert_profile_batch(second_batch)
        store.commit()
        assert store.get_profile_batch("batch") == _batch(digest)
        assert store.get_profile_batch("batch-two") == second_batch
    finally:
        store.close()


def _ranked_run(
    run_id: str,
    *,
    cluster_count: int,
    noise_ratio: float,
) -> ProfileRankedRun:
    metrics = RunPartitionMetrics(
        total_items=100,
        cluster_count=cluster_count,
        noise_count=int(noise_ratio * 100),
        non_noise_count=100 - int(noise_ratio * 100),
        noise_ratio=noise_ratio,
        dominant_cluster_ratio=0.3,
        dominant_assigned_ratio=0.4,
        dominant_cluster_label=0,
        cluster_size_distribution=(30,),
        cluster_size_histogram={},
    )
    return ProfileRankedRun(
        clustering_run_id=run_id,
        base_score=0.5,
        profile_score=0.0,
        effective=EffectiveClusteringParameters(
            pca_dimensions=32 if run_id == "low" else 64,
            min_cluster_size=5,
            min_samples=1,
            cluster_selection_method="eom",
            n_samples=100,
            n_features=384,
        ),
        metrics=metrics,
    )


def _seed_store(store: SqliteCorpusAnalyticsStore) -> None:
    store.insert_snapshot(
        CorpusSnapshotRecord(
            snapshot_id="snapshot",
            lane="intent",
            representation_kind="intent.description.v1",
            representation_version="3",
            source_stores_json="{}",
            source_schema_versions_json="{}",
            record_count=0,
            source_digest="digest",
            created_at_utc="2026-01-01T00:00:00Z",
        ),
        (),
    )
    store.insert_embedding_generation(
        EmbeddingGenerationRecord(
            embedding_generation_id="embedding",
            provider_id="fastembed",
            provider_package_version="1",
            model_id="model",
            model_revision=None,
            model_artifact_fingerprint=None,
            exact_model_artifact_reproducibility=False,
            dimensions=2,
            embedding_contract_version="2",
            embedding_similarity_metric="cosine",
            vector_preprocessing="l2_normalize",
            created_at_utc="2026-01-01T00:00:00Z",
        )
    )
    store.insert_clustering_run(_run("run-a"))
    store.commit()


def _run(run_id: str) -> ClusteringRunRecord:
    return ClusteringRunRecord(
        clustering_run_id=run_id,
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        requested_parameters_json="{}",
        effective_parameters_json="{}",
        random_seed=42,
        run_digest=f"digest-{run_id}",
        recommended_by_heuristic=False,
        selected_by_maintainer=False,
        status="completed",
        created_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        error_message=None,
    )


def _batch(digest: str) -> ProfileBatchRecord:
    return ProfileBatchRecord(
        profile_batch_id="batch",
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        profile_id="intent-small-balanced-v1",
        profile_manifest_digest=digest,
        candidate_space_digest="space",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc=None,
        status="running",
        candidate_count_planned=1,
        candidate_count_succeeded=0,
        candidate_count_failed=0,
        recommended_clustering_run_id=None,
        recommendation_rationale_json=None,
        batch_max_cluster_count=None,
        created_at_utc="2026-01-01T00:00:00Z",
    )


def test_resolve_profile_auto_uses_default(tmp_path: Path) -> None:
    write_bundled_profile_pyproject(
        tmp_path,
        profile_filename="profile.json",
        analytics_toml_body="""
[tool.codeclone.analytics]
default_profile_id = "intent-small-balanced-v1"
profile_paths = ["profile.json"]
""",
    )
    config = resolve_analytics_config(tmp_path)
    resolved = _resolve_profile(config=config, profile_id="auto")
    assert resolved.profile_id == "intent-small-balanced-v1"

    bare = tmp_path / "bare"
    bare.mkdir()
    bare_config = resolve_analytics_config(bare)
    with pytest.raises(
        AnalyticsWorkflowError, match="default_profile_id not configured"
    ):
        _resolve_profile(config=bare_config, profile_id="auto")


def test_profile_applicability_rejects_max_record_count() -> None:
    profile = load_bundled_profiles()["intent-small-balanced-v1"]
    with pytest.raises(AnalyticsWorkflowError, match="record count above maximum"):
        _validate_profile_applicability(
            profile=replace(
                profile,
                applicability=replace(
                    profile.applicability,
                    max_record_count=10,
                ),
            ),
            representation_kind="intent.description.v1",
            record_count=100,
            embedding_contract_version="2",
        )


def test_effective_parameters_from_run_validates_shape() -> None:
    valid = _run("run-valid")
    valid = replace(
        valid,
        effective_parameters_json=json.dumps(
            {
                "pca_dimensions": 8,
                "min_cluster_size": 5,
                "min_samples": 1,
                "cluster_selection_method": "eom",
                "n_samples": 100,
                "n_features": 384,
            },
            sort_keys=True,
        ),
    )
    effective = _effective_parameters_from_run(valid)
    assert effective.pca_dimensions == 8
    assert effective.n_features == 384

    incomplete = replace(valid, effective_parameters_json="{}")
    with pytest.raises(AnalyticsWorkflowError, match="incomplete"):
        _effective_parameters_from_run(incomplete)

    invalid = replace(
        valid,
        effective_parameters_json=json.dumps(
            {
                "pca_dimensions": True,
                "min_cluster_size": 5,
                "min_samples": 1,
                "cluster_selection_method": "eom",
                "n_samples": 100,
                "n_features": 384,
            },
            sort_keys=True,
        ),
    )
    with pytest.raises(AnalyticsWorkflowError, match="invalid"):
        _effective_parameters_from_run(invalid)


def test_score_completed_run_uses_assignments(tmp_path: Path) -> None:
    store = SqliteCorpusAnalyticsStore.open(tmp_path / "analytics.sqlite3")
    try:
        _seed_store(store)
        store._conn.execute(
            """
            INSERT INTO corpus_items (
                snapshot_id, representation_key, snapshot_item_id,
                source_record_key, project_id, intent_id, normalized_text,
                normalized_digest, normalizer_version, representation_digest,
                metadata_json, registry_overlay_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "snapshot",
                "representation-item",
                "item",
                "source-item",
                "project",
                "intent-item",
                "embed this text",
                "normalized",
                "1",
                "representation",
                "{}",
                None,
            ),
        )
        store.insert_cluster_assignments(
            (
                ClusterAssignmentRecord(
                    "run-a",
                    "item",
                    0,
                    0.9,
                    "digest",
                ),
            )
        )
        store.commit()
        candidate = SweepCandidate(
            requested=ClusteringParameters(
                pca_dimensions=8,
                min_cluster_size=5,
                min_samples=1,
                cluster_selection_method="eom",
            ),
            effective=EffectiveClusteringParameters(
                pca_dimensions=8,
                min_cluster_size=5,
                min_samples=1,
                cluster_selection_method="eom",
                n_samples=1,
                n_features=384,
            ),
            dedupe_key="8|5|1|eom",
        )
        scored = _score_completed_run(
            store=store,
            clustering_run_id="run-a",
            candidate=candidate,
        )
        assert scored.cluster_count == 1
        assert scored.noise_fraction == 0.0
    finally:
        store.close()


def test_record_run_selection_rejects_empty_actor_and_unknown_batch(
    tmp_path: Path,
) -> None:
    store = SqliteCorpusAnalyticsStore.open(tmp_path / "analytics.sqlite3")
    try:
        _seed_store(store)
        with pytest.raises(
            AnalyticsWorkflowError, match="selected_by must not be empty"
        ):
            record_run_selection(
                store=store,
                snapshot_id="snapshot",
                embedding_generation_id="embedding",
                selected_run_id="run-a",
                profile_batch_id=None,
                selected_by="   ",
                rationale=None,
            )
        with pytest.raises(AnalyticsWorkflowError, match="unknown profile batch"):
            record_run_selection(
                store=store,
                snapshot_id="snapshot",
                embedding_generation_id="embedding",
                selected_run_id="run-a",
                profile_batch_id="missing-batch",
                selected_by="maintainer",
                rationale=None,
            )

        digest = profile_manifest_digest(
            load_bundled_profiles()["intent-small-balanced-v1"]
        )
        batch_record = _batch(digest)

        class _FailingStore:
            def get_profile_batch(self, _batch_id: str) -> ProfileBatchRecord:
                return batch_record

            def record_run_selection_atomic(
                self,
                _record: object,
            ) -> object:
                raise AnalyticsStoreError("atomic failure")

        with pytest.raises(AnalyticsWorkflowError, match="atomic failure"):
            record_run_selection(
                store=_FailingStore(),  # type: ignore[arg-type]
                snapshot_id="snapshot",
                embedding_generation_id="embedding",
                selected_run_id="run-a",
                profile_batch_id="batch",
                selected_by="maintainer",
                rationale="  trimmed  ",
            )
    finally:
        store.close()


def test_assess_and_persist_profile_batch_finalizes_status(tmp_path: Path) -> None:
    store = SqliteCorpusAnalyticsStore.open(tmp_path / "analytics.sqlite3")
    try:
        _seed_store(store)
        profile = load_bundled_profiles()["intent-small-balanced-v1"]
        digest = profile_manifest_digest(profile)
        store.insert_profile_manifest_snapshot(
            ProfileManifestSnapshotRecord(
                profile_manifest_digest=digest,
                profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                manifest_schema_version=profile.manifest_schema_version,
                canonical_manifest_json=canonical_manifest_json(profile),
                label=profile.label,
                description=profile.description,
                created_at_utc="2026-01-01T00:00:00Z",
            )
        )
        batch = _batch(digest)
        store.insert_profile_batch(batch)
        store.insert_profile_batch_run(
            ProfileBatchRunRecord("batch", "run-a", 0, "8|5|1|eom")
        )
        store.commit()
        with pytest.raises(AnalyticsWorkflowError, match="unknown profile batch"):
            assess_and_persist_profile_batch(
                store=store,
                profile_batch_id="missing",
                profile=profile,
                profile_manifest_digest=digest,
                clustering_run_ids=("run-a",),
            )
        result = assess_and_persist_profile_batch(
            store=store,
            profile_batch_id=batch.profile_batch_id,
            profile=profile,
            profile_manifest_digest=digest,
            clustering_run_ids=("run-a",),
        )
        assert result.profile_batch_id == batch.profile_batch_id
        assert result.batch_status in {"completed", "completed_partial", "failed"}
        finalized = store.get_profile_batch(batch.profile_batch_id)
        assert finalized is not None
        assert finalized.finished_at_utc is not None
    finally:
        store.close()


def test_resolve_profile_registry_custom_bundled_dir(tmp_path: Path) -> None:
    balanced = load_bundled_profiles()["intent-small-balanced-v1"]
    manifest_path = tmp_path / "intent-small-balanced-v1.json"
    manifest_path.write_text(canonical_manifest_json(balanced), encoding="utf-8")
    registry = resolve_profile_registry(bundled_dir=tmp_path)
    assert (
        registry.profiles["intent-small-balanced-v1"].profile_id == balanced.profile_id
    )
    assert (
        registry.sources["intent-small-balanced-v1"]
        == "bundled:intent-small-balanced-v1.json"
    )


def test_resolve_profile_registry_rejects_duplicate_bundled_manifests(
    tmp_path: Path,
) -> None:
    balanced = load_bundled_profiles()["intent-small-balanced-v1"]
    text = canonical_manifest_json(balanced)
    (tmp_path / "first.json").write_text(text, encoding="utf-8")
    (tmp_path / "second.json").write_text(text, encoding="utf-8")
    with pytest.raises(AnalyticsWorkflowError, match="conflicting profile manifest"):
        resolve_profile_registry(bundled_dir=tmp_path)


def test_resolve_profile_registry_rejects_unknown_default_profile() -> None:
    with pytest.raises(AnalyticsWorkflowError, match="unknown analytics profile"):
        resolve_profile_registry(default_profile_id="missing-profile-id")


def test_get_profile_unknown_raises() -> None:
    from codeclone.analytics.profiles.registry import get_profile

    registry = resolve_profile_registry()
    with pytest.raises(AnalyticsWorkflowError, match="unknown analytics profile"):
        get_profile(registry, "missing-profile-id")


def test_profile_manifest_validation_rejects_invalid_payloads() -> None:
    import copy
    from typing import Any

    def payload() -> dict[str, object]:
        return copy.deepcopy(
            manifest_value(load_bundled_profiles()["intent-small-balanced-v1"])
        )

    base = payload()
    applicability = cast(dict[str, Any], base["applicability"])
    primary_space = cast(dict[str, Any], base["primary_space"])
    ranking = cast(dict[str, Any], base["ranking"])
    suitability = cast(dict[str, Any], base["suitability"])

    cases: list[tuple[str, dict[str, object]]] = [
        (
            "empty embedding contract versions",
            {
                **base,
                "applicability": {
                    **applicability,
                    "embedding_contract_versions": [],
                },
            },
        ),
        (
            "min_record_count above max_record_count",
            {
                **base,
                "applicability": {
                    **applicability,
                    "min_record_count": 100,
                    "max_record_count": 1,
                },
            },
        ),
        (
            "empty pca_dimensions axis",
            {
                **base,
                "primary_space": {**primary_space, "pca_dimensions": []},
            },
        ),
        (
            "empty cluster_selection_method axis",
            {
                **base,
                "primary_space": {
                    **primary_space,
                    "cluster_selection_method": [],
                },
            },
        ),
        (
            "negative ranking weight",
            {
                **base,
                "ranking": {**ranking, "base_score_weight": -1.0},
            },
        ),
        (
            "unsupported manifest schema version",
            {**base, "manifest_schema_version": "99"},
        ),
        (
            "invalid profile_id",
            {**base, "profile_id": ""},
        ),
        (
            "invalid profile_version",
            {**base, "profile_version": "not-semver"},
        ),
        (
            "empty label",
            {**base, "label": "   "},
        ),
        (
            "empty representation_kinds",
            {**base, "representation_kinds": []},
        ),
    ]
    for _label, invalid in cases:
        with pytest.raises(AnalyticsWorkflowError, match="invalid analytics profile"):
            load_manifest_value(invalid)

    for invalid_ratio in (
        {**base, "suitability": {**suitability, "max_noise_ratio": 1.5}},
        {
            **payload(),
            "suitability": {
                **cast(dict[str, float], payload()["suitability"]),
                "max_noise_ratio": 1.5,
            },
        },
    ):
        with pytest.raises(AnalyticsWorkflowError, match="invalid analytics profile"):
            load_manifest_value(invalid_ratio)
