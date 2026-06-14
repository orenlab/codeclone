# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import importlib
import json
import math
import types
from dataclasses import replace
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from codeclone.analytics.agent_labels import (
    agent_family_rules,
    agent_label_contract_version,
    map_agent_family,
)
from codeclone.analytics.capabilities import check_capability, install_hint
from codeclone.analytics.clustering.canonicalize import (
    canonicalize_partitions,
    display_cluster_id_map,
    medoid_item_id,
    partition_membership_map,
)
from codeclone.analytics.clustering.diagnostics import (
    build_cluster_diagnostics,
    build_item_preview,
    cluster_size_percent,
    compute_centroids,
    correlation_rate,
    linear_percentile,
    metadata_display_value,
    metadata_distribution,
    nearest_cluster_ids,
    noise_explorer_flags,
    numeric_field_summary,
    truncate_preview,
)
from codeclone.analytics.clustering.models import (
    ClusteringParameters,
    ClusterPartition,
)
from codeclone.analytics.clustering.pipeline import (
    is_noise_label,
    resolve_effective_parameters,
    run_clustering_pipeline,
)
from codeclone.analytics.clustering.sweep import (
    SweepCandidate,
    SweepCandidateResult,
    clustering_algorithm_manifest,
    iter_sweep_candidates,
    rank_sweep_results,
    run_digest,
    score_clustering_result,
)
from codeclone.analytics.contracts import (
    INTENT_REPRESENTATION_DESCRIPTION,
    INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
    CorpusItemRecord,
)
from codeclone.analytics.corpus.adapters import intent_historical
from codeclone.analytics.corpus.adapters.intent_historical import (
    HistoricalIntentSourceItem,
    compute_source_digest,
    extract_historical_intent_items,
    materialize_corpus_item,
)
from codeclone.analytics.corpus.keys import (
    representation_key,
    snapshot_item_id,
    source_record_key,
)
from codeclone.analytics.corpus.normalizer import source_content_digest
from codeclone.analytics.corpus.representations.intent import (
    IntentRepresentationInput,
    build_intent_description_v1,
    build_intent_description_with_frame_v1,
    build_representation_text,
    declared_constraints_from_audit_payload,
    declared_path_families_from_patch_trail,
    representation_digest,
)
from codeclone.analytics.exceptions import AnalyticsCapabilityError
from codeclone.audit.reader import AuditRecord
from codeclone.surfaces.mcp._workspace_intent_schema import open_intent_registry_db
from tests.fixtures.analytics.helpers import write_intent_declared_event


def _audit_db(root: Path) -> Path:
    path = root / ".codeclone" / "db" / "audit.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _seed_intent_repo(
    tmp_path: Path, *, description: str, audit_sequence: int = 1
) -> Path:
    """Create a repo root and write one intent.declared audit event."""
    root = tmp_path / "repo"
    root.mkdir()
    write_intent_declared_event(
        db_path=_audit_db(root),
        repo_root=root,
        intent_id="intent-a",
        description=description,
        audit_sequence=audit_sequence,
    )
    return root


def _corpus_item(
    item_id: str = "item",
    *,
    text: str = "short",
    metadata_json: str = "{}",
) -> CorpusItemRecord:
    return CorpusItemRecord(
        snapshot_id="snap",
        representation_key=f"rep-{item_id}",
        snapshot_item_id=item_id,
        source_record_key=f"source-{item_id}",
        project_id="project",
        intent_id=f"intent-{item_id}",
        normalized_text=text,
        normalized_digest=f"normalized-{item_id}",
        normalizer_version="1",
        representation_digest=f"representation-{item_id}",
        metadata_json=metadata_json,
        registry_overlay_json=None,
    )


def test_identity_keys() -> None:
    project_id = "proj-abc"
    intent_id = "intent-1"
    source_key = source_record_key(project_id=project_id, intent_id=intent_id)
    rep_key = representation_key(
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="1",
        source_record_key_value=source_key,
    )
    snap_item = snapshot_item_id(snapshot_id="snap-1", representation_key_value=rep_key)
    assert len(source_key) == 64
    assert len(rep_key) == 64
    assert len(snap_item) == 64
    assert source_key != rep_key != snap_item


def test_registry_not_in_normalized_text(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    audit_db = _audit_db(root)
    write_intent_declared_event(
        db_path=audit_db,
        repo_root=root,
        intent_id="intent-a",
        description="Add analytics module",
    )
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    assert len(items) == 1
    before = materialize_corpus_item(
        snapshot_id="snap-1",
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        item=items[0],
    )
    overlay_item = replace(
        items[0],
        registry_overlay={"present": True, "status": "active"},
    )
    after = materialize_corpus_item(
        snapshot_id="snap-1",
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        item=overlay_item,
    )
    assert before[3] == after[3]
    assert before[6] == after[6]


def test_new_snapshot_materializes_explicit_provenance_v3() -> None:
    source = HistoricalIntentSourceItem(
        project_id="project",
        intent_id="intent",
        source_record_key_value="source",
        source_content_digest="digest",
        provenance={
            "trajectory": {"selected_trajectory_id": None},
            "patch_trail": {"digest": None},
        },
        metadata={"agent_family": "codex"},
        registry_overlay=None,
        representation_input=IntentRepresentationInput(
            description="Add interpretability",
            intent_kind=None,
            declared_path_families=(),
            declared_constraints=(),
        ),
    )
    materialized = materialize_corpus_item(
        snapshot_id="snapshot",
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        item=source,
    )
    metadata = json.loads(materialized[7])
    assert materialized[9] == "3"
    assert metadata["provenance"]["trajectory"]["selected"] is False
    assert metadata["provenance"]["patch_trail"]["present"] is False
    assert metadata["provenance"]["registry_overlay"]["present"] is False

    with_overlay = materialize_corpus_item(
        snapshot_id="snapshot",
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        item=replace(
            source,
            provenance={
                "trajectory": {"selected_trajectory_id": "trajectory"},
                "patch_trail": {"digest": "trail-digest"},
            },
            registry_overlay={},
        ),
    )
    enriched = json.loads(with_overlay[7])["provenance"]
    assert enriched["trajectory"]["selected"] is True
    assert enriched["patch_trail"]["present"] is True
    assert enriched["registry_overlay"]["present"] is True


def test_registry_overlay_does_not_change_source_digest(tmp_path: Path) -> None:
    root = _seed_intent_repo(tmp_path, description="Stable historical intent")
    registry_db = root / ".codeclone" / "db" / "intents.sqlite3"
    before_items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        registry_db_path=registry_db,
    )
    before_digest = compute_source_digest(
        items=before_items,
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="2",
        source_schema_versions={"audit": "4"},
    )
    conn = open_intent_registry_db(registry_db)
    try:
        conn.execute(
            """
            INSERT INTO workspace_intents (
                agent_pid, agent_start_epoch, intent_id, declared_at_utc,
                payload_json, closed_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                "intent-a",
                "2026-01-01T00:00:00Z",
                '{"status":"active"}',
                None,
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    after_items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        registry_db_path=registry_db,
    )
    after_digest = compute_source_digest(
        items=after_items,
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="2",
        source_schema_versions={"audit": "4"},
    )
    assert before_digest == after_digest
    assert after_items[0].registry_overlay is not None


def test_item_preview_and_numeric_summary_contracts() -> None:
    short = _corpus_item(
        "short",
        text="x" * 240,
        metadata_json=(
            '{"agent_family":"codex","anomaly_kinds":[],'
            '"declared_file_count":0,"changed_file_count":3}'
        ),
    )
    long = _corpus_item(
        "long",
        text="y" * 241,
        metadata_json=(
            '{"agent_family":null,"anomaly_kinds":["scope"],"declared_file_count":11}'
        ),
    )
    assert truncate_preview(short.normalized_text) == short.normalized_text
    truncated = truncate_preview(long.normalized_text)
    assert len(truncated) == 240
    assert truncated.endswith("\u2026")
    assert metadata_display_value({}, "agent_family").kind == "unknown"
    assert (
        metadata_display_value(
            {"anomaly_kinds": []},
            "anomaly_kinds",
        ).kind
        == "confirmed_none"
    )
    preview = build_item_preview(
        long,
        None,
        source_kind="intent_historical",
        source_record_id=long.intent_id,
    )
    assert preview.intent_id == long.intent_id
    assert preview.normalized_text_preview == truncated

    declared = numeric_field_summary((short, long), field="declared_file_count")
    assert declared.known_count == 2
    assert declared.unknown_count == 0
    assert declared.median == 5.5
    assert declared.buckets == {"0": 1, "1-3": 0, "4-10": 0, "11+": 1}
    changed = numeric_field_summary((short, long), field="changed_file_count")
    assert changed.known_count == 1
    assert changed.unknown_count == 1
    assert changed.median == 3.0
    assert linear_percentile([], 50) is None
    assert linear_percentile([2], 50) == 2.0
    assert linear_percentile([1, 2, 3, 4], 25) == 1.75
    assert linear_percentile([1, 2, 3], 50) == 2.0
    assert linear_percentile([1, 1, 3, 3], 50) == 2.0


def test_interpretation_value_and_bucket_edge_contracts() -> None:
    assert (
        metadata_display_value(
            {"declared_constraints": []},
            "declared_constraints",
        ).kind
        == "empty_collection"
    )
    assert (
        metadata_display_value(
            {"agent_family": ["codex", "claude", "codex"]},
            "agent_family",
        ).display
        == "claude, codex"
    )
    assert metadata_display_value(
        {"scope_expanded": True}, "scope_expanded"
    ).display == ("true")
    assert metadata_display_value(
        {"scope_expanded": False}, "scope_expanded"
    ).display == ("false")
    with pytest.raises(ValueError, match="between 0 and 100"):
        linear_percentile([1], -1)

    descriptions = (
        _corpus_item("short", text="x" * 39),
        _corpus_item("medium", text="x" * 40),
        _corpus_item("long", text="x" * 120),
        _corpus_item("very-long", text="x" * 400),
    )
    assert numeric_field_summary(
        descriptions,
        field="description_length",
    ).buckets == {
        "0-39": 1,
        "40-119": 1,
        "120-399": 1,
        "400+": 1,
    }
    file_counts = (
        _corpus_item("one", metadata_json='{"declared_file_count":1}'),
        _corpus_item("four", metadata_json='{"declared_file_count":4}'),
    )
    assert numeric_field_summary(
        file_counts,
        field="declared_file_count",
    ).buckets == {"0": 0, "1-3": 1, "4-10": 1, "11+": 0}
    assert (
        numeric_field_summary(
            (_corpus_item("unknown"),),
            field="changed_file_count",
        ).mean
        is None
    )

    non_intent_preview = build_item_preview(
        descriptions[0],
        None,
        source_kind="trajectory",
        source_record_id="trajectory-id",
    )
    assert non_intent_preview.intent_id is None
    assert intent_historical._materialized_metadata(
        HistoricalIntentSourceItem(
            project_id="project",
            intent_id="intent",
            source_record_key_value="source",
            source_content_digest="digest",
            provenance={},
            metadata={},
            registry_overlay=None,
            representation_input=IntentRepresentationInput(
                description="description",
                intent_kind=None,
                declared_path_families=(),
                declared_constraints=(),
            ),
        )
    )["provenance"] == {
        "trajectory": {"selected": False},
        "patch_trail": {"present": False},
        "registry_overlay": {"present": False},
    }


def test_source_content_digest_hashes_raw_inputs_before_normalization() -> None:
    assert source_content_digest({"description": "Add validation"}) != (
        source_content_digest({"description": "validation"})
    )
    plain = IntentRepresentationInput(
        description="Validate request",
        intent_kind="feature",
        declared_path_families=(),
        declared_constraints=(),
    )
    changed = replace(plain, intent_kind="fix")
    assert source_content_digest(
        {
            "description": plain.description,
            "intent_kind": plain.intent_kind,
        }
    ) != source_content_digest(
        {
            "description": changed.description,
            "intent_kind": changed.intent_kind,
        }
    )


def test_intent_adapter_audit_first(tmp_path: Path) -> None:
    root = _seed_intent_repo(tmp_path, description="First description")
    write_intent_declared_event(
        db_path=_audit_db(root),
        repo_root=root,
        intent_id="intent-a",
        description="Later description",
        audit_sequence=2,
    )
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    assert len(items) == 1
    assert items[0].representation_input.description == "First description"


def test_duplicate_declaration_conflict(tmp_path: Path) -> None:
    root = _seed_intent_repo(tmp_path, description="Alpha")
    write_intent_declared_event(
        db_path=_audit_db(root),
        repo_root=root,
        intent_id="intent-a",
        description="Beta",
        audit_sequence=2,
    )
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    description = items[0].provenance["description"]
    assert isinstance(description, dict)
    assert description["description_conflict"] is True


def test_source_digest_stable(tmp_path: Path) -> None:
    root = _seed_intent_repo(tmp_path, description="Stable intent")
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    digest_a = compute_source_digest(
        items=items,
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="1",
        source_schema_versions={"audit": "4"},
    )
    digest_b = compute_source_digest(
        items=items,
        lane="intent",
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        representation_version="1",
        source_schema_versions={"audit": "4"},
    )
    assert digest_a == digest_b


def test_session_intent_never_in_corpus(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _audit_db(root)
    items = extract_historical_intent_items(
        root_path=root,
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
    )
    assert items == ()


def test_correlation_sample_guard() -> None:
    cell = correlation_rate(numerator=2, denominator=4, min_sample_size=5)
    assert cell.insufficient_sample is True
    assert cell.rate is None


def test_cluster_diagnostics_use_configured_guard_and_emit_noise_flags() -> None:
    item = replace(
        _corpus_item(),
        metadata_json='{"agent_family":"cursor","anomaly_kinds":["scope_expanded"]}',
    )
    diagnostics = build_cluster_diagnostics(
        partition=ClusterPartition(
            cluster_label=-1,
            snapshot_item_ids=("item",),
            membership_digest="membership",
        ),
        items_by_id={"item": item},
        coordinates={"item": (0.0, 0.0)},
        membership_strengths={"item": 0.1},
        total_items=1,
        min_correlation_sample_size=2,
    )
    distributions = diagnostics["metadata_distributions"]
    assert isinstance(distributions, dict)
    agent = distributions["agent_family"]
    assert isinstance(agent, dict)
    assert agent["cursor"]["insufficient_sample"] is True
    noise_items = diagnostics["noise_items"]
    assert isinstance(noise_items, list)
    assert noise_items[0]["flags"]["short_text"] is True


def test_sweep_effective_dedup() -> None:
    candidates = iter_sweep_candidates(n_samples=10, n_features=384)
    keys = [candidate.dedupe_key for candidate in candidates]
    assert len(keys) == len(set(keys))


def test_cluster_display_order_uses_medoid_not_first_member() -> None:
    first_by_member = ClusterPartition(
        cluster_label=10,
        snapshot_item_ids=("a", "z", "zz"),
        membership_digest="digest-10",
    )
    first_by_medoid = ClusterPartition(
        cluster_label=20,
        snapshot_item_ids=("b", "c", "d"),
        membership_digest="digest-20",
    )
    coordinates: dict[str, tuple[float, ...]] = {
        "a": (0.0,),
        "z": (10.0,),
        "zz": (11.0,),
        "b": (0.0,),
        "c": (1.0,),
        "d": (2.0,),
    }

    canonical = canonicalize_partitions(
        (first_by_member, first_by_medoid),
        coordinates=coordinates,
    )

    assert [partition.cluster_label for partition in canonical] == [20, 10]
    assert display_cluster_id_map(canonical) == {20: 1, 10: 2}


def test_agent_family_mapping() -> None:
    assert map_agent_family("cursor-vscode") == "cursor"
    assert map_agent_family(None) == "unknown"


def test_agent_family_contract_handles_all_labels() -> None:
    assert map_agent_family("  ") == "unknown"
    assert map_agent_family("prefix CLAUDE-code") == "claude"
    assert map_agent_family("codex-cli") == "codex"
    assert map_agent_family("vscode-extension") == "vscode"
    assert map_agent_family("mcp-client") == "mcp"
    assert map_agent_family("human") == "unknown"
    assert agent_label_contract_version()
    assert tuple(agent_family_rules())


def test_capability_matrix_and_import_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "codeclone.analytics.capabilities._package_available",
        lambda package: package in {"lancedb", "sklearn"},
    )
    assert check_capability("base").available is True
    assert check_capability("embed").missing_packages == ("fastembed",)
    assert check_capability("cluster").missing_packages == ("hdbscan",)
    assert check_capability("full").missing_packages == ("fastembed", "hdbscan")
    assert install_hint(()) == "uv sync --extra analytics"
    assert install_hint(("fastembed",)) == "uv sync --extra analytics"

    def missing_import(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr(importlib, "import_module", missing_import)
    from codeclone.analytics.capabilities import _package_available

    assert _package_available("missing") is False


def test_intent_representation_contracts() -> None:
    payload = IntentRepresentationInput(
        description="  Add\r\nanalytics  ",
        intent_kind=" feature ",
        declared_path_families=("tests", "codeclone", "tests"),
        declared_constraints=("z=2", "a=1", "z=2"),
    )
    assert build_intent_description_v1(payload.description) == "Add\nanalytics"
    framed = build_intent_description_with_frame_v1(payload)
    assert "INTENT_KIND:\nfeature" in framed
    assert "DECLARED_PATH_FAMILIES:\ncodeclone, tests" in framed
    assert "DECLARED_CONSTRAINTS:\na=1; z=2" in framed
    assert (
        build_representation_text(
            representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
            payload=payload,
        )
        == "Add\nanalytics"
    )
    assert (
        build_representation_text(
            representation_kind=INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
            payload=payload,
        )
        == framed
    )
    assert representation_digest(
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        normalized_text="Add analytics",
    )
    with pytest.raises(ValueError, match="unsupported representation"):
        build_representation_text(representation_kind="unknown", payload=payload)


def test_declared_context_extractors_are_bounded_and_typed() -> None:
    assert declared_path_families_from_patch_trail(None) == ()
    assert declared_path_families_from_patch_trail({"declared_files": "bad"}) == ()
    assert declared_path_families_from_patch_trail(
        {
            "declared_files": [
                "./codeclone/a.py",
                r"tests\test_a.py",
                42,
                "",
                "./",
            ]
        }
    ) == ("codeclone", "tests")
    assert declared_path_families_from_patch_trail(
        {"declared_files": [f"dir-{index}/file.py" for index in range(20)]},
        limit=3,
    ) == ("dir-0", "dir-1", "dir-10")

    assert declared_constraints_from_audit_payload(None) == ()
    assert declared_constraints_from_audit_payload(
        {
            "verification_profile": " strict ",
            "dirty_scope_policy": "",
            "on_conflict": 3,
            "scope": {
                "allowed_files": ["a.py"],
                "allowed_related": [],
                "forbidden": ["b.py", "c.py"],
            },
        }
    ) == (
        "scope.allowed_files_count=1",
        "scope.forbidden_count=2",
        "verification_profile=strict",
    )
    assert declared_constraints_from_audit_payload({"scope": "bad"}) == ()


def test_canonical_helpers_cover_empty_missing_and_noise() -> None:
    assert medoid_item_id(member_ids=(), coordinates={}) == ""
    assert medoid_item_id(member_ids=("only",), coordinates={}) == "only"
    assert (
        medoid_item_id(
            member_ids=("missing", "present"),
            coordinates={"present": (0.0,)},
        )
        == "missing"
    )
    partitions = (
        ClusterPartition(1, ("a", "b"), "stored"),
        ClusterPartition(-1, ("noise",), "noise-stored"),
    )
    canonical = canonicalize_partitions(partitions, coordinates={"a": (0.0,)})
    assert display_cluster_id_map(canonical) == {1: 1, -1: None}
    membership = partition_membership_map(canonical)
    assert membership["a"] == membership["b"]
    assert membership["noise"] != membership["a"]


def test_diagnostics_helpers_cover_metadata_and_distance_edges() -> None:
    invalid = _corpus_item("invalid", metadata_json="{")
    scalar = _corpus_item("scalar", metadata_json="[]")
    rich = _corpus_item(
        "rich",
        text="<template and or but while>\n\none\n\ntwo" + ("x" * 820),
        metadata_json=(
            '{"field":null,"list":[],"bool":true,"number":3,"values":["b","a","a"]}'
        ),
    )
    assert cluster_size_percent(2, 0) == 0.0
    assert (
        metadata_distribution(
            (invalid, scalar, rich),
            field="field",
            min_sample_size=1,
        )["null"].rate
        == 1.0
    )
    assert (
        metadata_distribution(
            (rich,),
            field="list",
            min_sample_size=1,
        )["none"].rate
        == 1.0
    )
    assert (
        metadata_distribution(
            (rich,),
            field="bool",
            min_sample_size=1,
        )["true"].rate
        == 1.0
    )
    assert (
        metadata_distribution(
            (rich,),
            field="number",
            min_sample_size=1,
        )["3"].rate
        == 1.0
    )
    assert set(
        metadata_distribution(
            (rich,),
            field="values",
            min_sample_size=1,
        )
    ) == {"a", "b"}
    flags = noise_explorer_flags(item=rich, membership_strength=0.1)
    assert flags.long_text is True
    assert flags.multiple_paragraphs is True
    assert flags.high_conjunction_count is True
    assert flags.template_match is True
    assert flags.low_membership_strength is True
    assert nearest_cluster_ids(cluster_label=9, centroids={}) == ()
    centroids = compute_centroids(
        partitions=(
            ClusterPartition(-1, ("noise",), "n"),
            ClusterPartition(1, ("missing",), "m"),
            ClusterPartition(2, ("a", "b"), "ab"),
            ClusterPartition(3, ("c",), "c"),
        ),
        coordinates={"a": (0.0, 2.0), "b": (2.0, 4.0), "c": (8.0, 8.0)},
    )
    assert centroids == {2: (1.0, 3.0), 3: (8.0, 8.0)}
    assert nearest_cluster_ids(cluster_label=2, centroids=centroids) == (3,)

    diagnostics = build_cluster_diagnostics(
        partition=ClusterPartition(5, (), "empty"),
        items_by_id={},
        coordinates={},
        membership_strengths={},
        total_items=0,
        min_correlation_sample_size=1,
    )
    assert diagnostics["average_membership_strength"] is None
    assert diagnostics["representatives"] == []
    assert diagnostics["boundary_items"] == []


def test_pipeline_validates_inputs_and_optional_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = ClusteringParameters(3, 2, 1, "eom")
    assert resolve_effective_parameters(requested, n_samples=1, n_features=3) is None
    assert is_noise_label(-1) is True
    assert is_noise_label(0) is False
    with pytest.raises(ValueError, match="length mismatch"):
        run_clustering_pipeline(
            snapshot_item_ids=("a",),
            embeddings=(),
            requested=requested,
        )
    assert (
        run_clustering_pipeline(
            snapshot_item_ids=(),
            embeddings=(),
            requested=requested,
        )
        is None
    )
    with pytest.raises(ValueError, match="must not be empty"):
        run_clustering_pipeline(
            snapshot_item_ids=("a", "b"),
            embeddings=((), ()),
            requested=requested,
        )
    with pytest.raises(ValueError, match="dimension mismatch"):
        run_clustering_pipeline(
            snapshot_item_ids=("a", "b"),
            embeddings=((1.0, 2.0), (1.0,)),
            requested=requested,
        )
    with pytest.raises(ValueError, match="non-finite"):
        run_clustering_pipeline(
            snapshot_item_ids=("a", "b"),
            embeddings=((1.0, math.nan), (1.0, 2.0)),
            requested=requested,
        )

    def missing_import(_name: str) -> object:
        raise ImportError

    monkeypatch.setattr(importlib, "import_module", missing_import)
    from codeclone.analytics.clustering import pipeline

    with pytest.raises(AnalyticsCapabilityError, match="scikit-learn"):
        pipeline._load_sklearn_pca()
    with pytest.raises(AnalyticsCapabilityError, match="hdbscan"):
        pipeline._load_hdbscan()


def test_pipeline_without_membership_probabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Array:
        def __init__(self, values: list[list[float]] | list[int]) -> None:
            self._values = values

        def tolist(self) -> list[list[float]] | list[int]:
            return self._values

    class _Pca:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def fit_transform(self, _matrix: object) -> _Array:
            return _Array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])

    class _Hdbscan:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def fit_predict(self, _matrix: object) -> _Array:
            return _Array([0, 0, -1])

    monkeypatch.setattr(
        "codeclone.analytics.clustering.pipeline._load_sklearn_pca",
        lambda: _Pca,
    )
    monkeypatch.setattr(
        "codeclone.analytics.clustering.pipeline._load_hdbscan",
        lambda: types.SimpleNamespace(HDBSCAN=_Hdbscan),
    )
    result = run_clustering_pipeline(
        snapshot_item_ids=("b", "a", "noise"),
        embeddings=((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        requested=ClusteringParameters(2, 2, 1, "eom"),
    )
    assert result is not None
    assert result.membership_strengths == (None, None, None)
    assert result.partitions[0].snapshot_item_ids == ("noise",)
    assert result.partitions[1].snapshot_item_ids == ("a", "b")


def test_sweep_ranking_scoring_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert rank_sweep_results(()) is None
    assert (
        score_clustering_result(cluster_count=2, noise_fraction=0.5, n_samples=0) == 0
    )
    effective = resolve_effective_parameters(
        ClusteringParameters(4, 2, 1, "eom"),
        n_samples=5,
        n_features=8,
    )
    assert effective is not None
    first = SweepCandidate(
        requested=ClusteringParameters(4, 2, 1, "eom"),
        effective=effective,
        dedupe_key="first",
    )
    second_effective = replace(effective, pca_dimensions=3)
    second = SweepCandidate(
        requested=ClusteringParameters(3, 2, 1, "eom"),
        effective=second_effective,
        dedupe_key="second",
    )
    selected = rank_sweep_results(
        (
            SweepCandidateResult(first, 0.5, 2, 0.0),
            SweepCandidateResult(second, 0.5, 2, 0.0),
        )
    )
    assert selected is not None
    assert selected.candidate.dedupe_key == "second"
    manifest = clustering_algorithm_manifest()
    assert manifest["vector_preprocessing"] == "l2_normalize"
    digest = run_digest(
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        effective=effective,
        random_seed=42,
        algorithm_manifest=manifest,
    )
    assert digest != run_digest(
        snapshot_id="snapshot",
        embedding_generation_id="embedding",
        effective=replace(effective, n_samples=6),
        random_seed=42,
        algorithm_manifest=manifest,
    )

    from codeclone.analytics.clustering import sweep

    monkeypatch.setattr(
        sweep,
        "version",
        lambda _distribution: (_ for _ in ()).throw(PackageNotFoundError("missing")),
    )
    assert sweep._package_version("missing") == "unknown"


def test_historical_adapter_payload_fallback_and_raw_inputs() -> None:
    def record(
        *,
        payload_json: str | None,
        event_core_json: str | None,
    ) -> AuditRecord:
        return AuditRecord(
            audit_sequence=1,
            event_id="event",
            event_type="intent.declared",
            severity="info",
            created_at_utc="2026-01-01T00:00:00Z",
            run_id=None,
            intent_id="intent",
            report_digest=None,
            workflow_id=None,
            surface=None,
            tool_name=None,
            event_core_json=event_core_json,
            event_core_sha256=None,
            payload_sha256=None,
            status=None,
            agent_label="",
            payload_json=payload_json,
        )

    assert intent_historical._payload_mapping(
        record(payload_json='{"intent_description":"payload"}', event_core_json=None)
    ) == {"intent_description": "payload"}
    assert intent_historical._payload_mapping(
        record(
            payload_json="[]",
            event_core_json='{"intent_description":"event-core"}',
        )
    ) == {"intent_description": "event-core"}
    assert (
        intent_historical._payload_mapping(
            record(payload_json="{", event_core_json=None)
        )
        == {}
    )
    assert (
        intent_historical._payload_mapping(
            record(payload_json=None, event_core_json="{")
        )
        == {}
    )
    assert intent_historical._intent_description({"intent_description": 3}) == ""
    assert intent_historical._intent_kind({"intent_kind": "  "}) is None
    assert intent_historical._intent_kind({"intent_kind": " feature "}) == "feature"

    payload = IntentRepresentationInput(
        description="description",
        intent_kind="feature",
        declared_path_families=("tests", "codeclone", "tests"),
        declared_constraints=("strict", "strict"),
    )
    assert intent_historical._raw_representation_inputs(
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
        payload=payload,
    ) == {"description": "description"}
    framed = intent_historical._raw_representation_inputs(
        representation_kind=INTENT_REPRESENTATION_DESCRIPTION_WITH_FRAME,
        payload=payload,
    )
    assert framed["declared_path_families"] == ["codeclone", "tests"]

    empty_item = HistoricalIntentSourceItem(
        project_id="project",
        intent_id="intent",
        source_record_key_value="source",
        source_content_digest="digest",
        provenance={},
        metadata={},
        registry_overlay=None,
        representation_input=replace(payload, description=""),
    )
    with pytest.raises(ValueError, match="normalized representation text is empty"):
        materialize_corpus_item(
            snapshot_id="snapshot",
            lane="intent",
            representation_kind=INTENT_REPRESENTATION_DESCRIPTION,
            item=empty_item,
        )
