# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from ..contracts import CORPUS_EMBEDDING_CONTRACT_VERSION
from .clustering.models import NOISE_LABEL
from .contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
    EmbeddingGenerationRecord,
    EmbeddingItemRecord,
)
from .corpus.keys import membership_digest
from .exceptions import AnalyticsWorkflowError
from .store.protocols import CorpusStore, VectorGenerationStore
from .store.vectors_lancedb import vector_digest, vector_row_key

REQUIRED_ALGORITHM_MANIFEST_PATHS = (
    "python_version",
    "numpy_version",
    "scipy_version",
    "scikit_learn_version",
    "hdbscan_version",
    "vector_preprocessing",
    "pca_solver",
    "pca_whiten",
    "clustering_input",
    "hdbscan_implementation",
    "clustering_metric",
    "hdbscan_core_dist_n_jobs",
)
_MANIFEST_VERSION_FIELDS = frozenset(REQUIRED_ALGORITHM_MANIFEST_PATHS[:5])
_MANIFEST_FIXED_FIELDS: dict[str, object] = {
    "vector_preprocessing": "l2_normalize",
    "pca_solver": "full",
    "pca_whiten": False,
    "clustering_input": "pca_reduced_coordinates",
    "hdbscan_implementation": "hdbscan",
    "clustering_metric": "euclidean",
    "hdbscan_core_dist_n_jobs": 1,
}


@dataclass(frozen=True, slots=True)
class PartitionValidityAssessment:
    technically_valid: bool
    failed_invariants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ValidityJsonContext:
    effective_parameters: dict[str, object]
    effective_parameters_readable: bool
    algorithm_manifest: dict[str, object] | None
    diagnostics_by_summary: dict[int, dict[str, object]]
    all_shapes_valid: bool


# Validity is formal store/partition integrity, never semantic meaningfulness.
# Inspectability remains a set of observable proxies, not one machine verdict.
# Stability-neighbour comparisons are a future versioned contract.
# Maintainer selection remains persisted run provenance, not validity evidence.
def validate_generation_metadata(
    *,
    store: CorpusStore,
    snapshot_id: str,
    embedding_generation_id: str,
    items: Sequence[CorpusItemRecord],
) -> tuple[EmbeddingGenerationRecord, tuple[EmbeddingItemRecord, ...]]:
    generation = store.get_embedding_generation(embedding_generation_id)
    if generation is None:
        raise AnalyticsWorkflowError(
            f"unknown embedding generation: {embedding_generation_id}"
        )
    if generation.embedding_contract_version != CORPUS_EMBEDDING_CONTRACT_VERSION:
        raise AnalyticsWorkflowError(
            "unsupported analytics embedding contract: "
            f"{generation.embedding_contract_version}; "
            f"expected {CORPUS_EMBEDDING_CONTRACT_VERSION}. "
            "Generate a new analytics embedding batch."
        )
    if (
        generation.embedding_similarity_metric != "cosine"
        or generation.vector_preprocessing != "l2_normalize"
    ):
        raise AnalyticsWorkflowError(
            "embedding generation does not match the fixed analytics "
            "cosine/L2 preprocessing contract"
        )
    expected_ids = {item.snapshot_item_id for item in items}
    embedding_items = store.list_embedding_items(
        embedding_generation_id=embedding_generation_id
    )
    actual_ids = {item.snapshot_item_id for item in embedding_items}
    if actual_ids != expected_ids:
        raise AnalyticsWorkflowError(
            "embedding generation does not match snapshot "
            f"{snapshot_id}: missing={len(expected_ids - actual_ids)}, "
            f"foreign={len(actual_ids - expected_ids)}"
        )
    for item in embedding_items:
        if item.dimensions != generation.dimensions:
            raise AnalyticsWorkflowError(
                "embedding dimension mismatch in metadata for "
                f"{item.snapshot_item_id}: item={item.dimensions}, "
                f"generation={generation.dimensions}"
            )
        expected_key = vector_row_key(
            embedding_generation_id=embedding_generation_id,
            snapshot_item_id=item.snapshot_item_id,
        )
        if item.vector_row_key != expected_key:
            raise AnalyticsWorkflowError(
                f"invalid vector row key for {item.snapshot_item_id}"
            )
    return generation, embedding_items


def load_validated_snapshot_vectors(
    *,
    store: CorpusStore,
    vector_store: VectorGenerationStore,
    snapshot_id: str,
    embedding_generation_id: str,
    items: Sequence[CorpusItemRecord],
) -> list[list[float]]:
    generation, embedding_items = validate_generation_metadata(
        store=store,
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
        items=items,
    )
    metadata_by_id = {item.snapshot_item_id: item for item in embedding_items}
    sidecar_ids = set(
        vector_store.list_generation_item_ids(
            embedding_generation_id=embedding_generation_id,
            limit=len(metadata_by_id) + 1,
        )
    )
    if sidecar_ids != set(metadata_by_id):
        raise AnalyticsWorkflowError(
            "analytics vector generation does not match embedding metadata: "
            f"missing={len(set(metadata_by_id) - sidecar_ids)}, "
            f"foreign={len(sidecar_ids - set(metadata_by_id))}"
        )
    rows = vector_store.read_vector_rows(
        embedding_generation_id=embedding_generation_id,
        snapshot_item_ids=[item.snapshot_item_id for item in items],
    )
    if set(rows) != set(metadata_by_id):
        raise AnalyticsWorkflowError(
            "analytics vector sidecar does not match embedding metadata: "
            f"missing={len(set(metadata_by_id) - set(rows))}, "
            f"foreign={len(set(rows) - set(metadata_by_id))}"
        )
    vectors: list[list[float]] = []
    for corpus_item in items:
        item_id = corpus_item.snapshot_item_id
        row = rows[item_id]
        metadata = metadata_by_id[item_id]
        vector = row["vector"]
        if not isinstance(vector, list):
            raise AnalyticsWorkflowError(f"invalid vector payload for {item_id}")
        typed_vector = [float(value) for value in vector]
        if len(typed_vector) != generation.dimensions:
            raise AnalyticsWorkflowError(
                f"vector dimension mismatch for {item_id}: "
                f"actual={len(typed_vector)}, expected={generation.dimensions}"
            )
        actual_digest = vector_digest(typed_vector)
        if (
            row["vector_digest"] != actual_digest
            or metadata.vector_digest != actual_digest
        ):
            raise AnalyticsWorkflowError(f"vector digest mismatch for {item_id}")
        if row["vector_row_key"] != metadata.vector_row_key:
            raise AnalyticsWorkflowError(f"vector row key mismatch for {item_id}")
        vectors.append(typed_vector)
    return vectors


def validate_cluster_diagnostic_refs(
    *,
    cluster_label: int,
    diagnostics: Mapping[str, object],
    items_by_id: Mapping[str, CorpusItemRecord],
    assigned_item_ids: Collection[str],
) -> None:
    if cluster_label == NOISE_LABEL:
        return
    assigned = set(assigned_item_ids)
    for field in ("representatives", "boundary_items"):
        value = diagnostics.get(field)
        if not isinstance(value, list):
            raise AnalyticsWorkflowError(
                f"cluster diagnostic {field} is not a list for label {cluster_label}"
            )
        if len(value) != len(set(value)):
            raise AnalyticsWorkflowError(
                f"cluster diagnostic {field} contains duplicates for label "
                f"{cluster_label}"
            )
        if any(
            not isinstance(item_id, str)
            or item_id not in items_by_id
            or item_id not in assigned
            for item_id in value
        ):
            raise AnalyticsWorkflowError(
                f"cluster diagnostic {field} contains an invalid reference for "
                f"label {cluster_label}"
            )


def assess_partition_validity(
    *,
    store: CorpusStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> PartitionValidityAssessment:
    """Assess formal persisted-run invariants without making semantic judgments."""
    snapshot = store.get_snapshot(snapshot_id)
    if snapshot is None:
        raise AnalyticsWorkflowError(f"unknown snapshot: {snapshot_id}")
    run = store.get_clustering_run(clustering_run_id)
    if run is None:
        raise AnalyticsWorkflowError(f"unknown clustering run: {clustering_run_id}")
    if run.snapshot_id != snapshot_id:
        raise AnalyticsWorkflowError(
            f"clustering run {clustering_run_id} belongs to snapshot "
            f"{run.snapshot_id}, not {snapshot_id}"
        )

    items = store.list_items(snapshot_id)
    assignments = store.list_assignments(clustering_run_id)
    summaries = store.list_summaries(clustering_run_id)
    context = _decode_validity_json(
        snapshot=snapshot,
        run=run,
        items=items,
        summaries=summaries,
    )
    failed: set[str] = set()
    if not context.all_shapes_valid:
        failed.add("V10")
    if not _assignment_coverage_is_valid(items, assignments):
        failed.add("V1")
    if not _summary_links_are_valid(assignments, summaries):
        failed.add("V2")
    members_by_label = _members_by_label(assignments)
    failed.update(
        _membership_integrity_failures(
            assignments=assignments,
            summaries=summaries,
            members_by_label=members_by_label,
        )
    )
    if not _minimum_cluster_size_is_valid(
        effective_parameters=context.effective_parameters,
        effective_parameters_readable=context.effective_parameters_readable,
        summaries=summaries,
    ):
        failed.add("V5")
    if not _persisted_interpretation_numbers_are_finite(
        assignments=assignments,
        diagnostics_by_summary=context.diagnostics_by_summary,
    ):
        failed.add("V6a")
    if not _run_and_manifest_are_valid(
        run=run,
        algorithm_manifest=context.algorithm_manifest,
    ):
        failed.add("V7")
    if not _generation_metadata_is_valid(
        store=store,
        snapshot_id=snapshot_id,
        run=run,
        items=items,
    ):
        failed.add("V8")
    if not _diagnostic_references_are_valid(
        items=items,
        summaries=summaries,
        diagnostics_by_summary=context.diagnostics_by_summary,
        members_by_label=members_by_label,
    ):
        failed.add("V9")

    failed_invariants = tuple(sorted(failed, key=_invariant_sort_key))
    return PartitionValidityAssessment(
        technically_valid=not failed_invariants,
        failed_invariants=failed_invariants,
    )


def _decode_validity_json(
    *,
    snapshot: CorpusSnapshotRecord,
    run: ClusteringRunRecord,
    items: Sequence[CorpusItemRecord],
    summaries: Sequence[ClusterSummaryRecord],
) -> _ValidityJsonContext:
    effective, effective_ok = _json_object(run.effective_parameters_json)
    raw_manifest = effective.get("algorithm_manifest") if effective_ok else None
    manifest = raw_manifest.copy() if isinstance(raw_manifest, dict) else None
    shapes = [
        _json_object(snapshot.source_stores_json)[1],
        _json_object(snapshot.source_schema_versions_json)[1],
        _json_object(run.requested_parameters_json)[1],
        effective_ok,
        manifest is not None,
    ]
    for item in items:
        shapes.append(_json_object(item.metadata_json)[1])
        if item.registry_overlay_json is not None:
            shapes.append(_json_object(item.registry_overlay_json)[1])
    diagnostics_by_summary: dict[int, dict[str, object]] = {}
    for summary in summaries:
        diagnostics, valid = _json_object(summary.diagnostics_json)
        shapes.append(valid)
        if valid:
            diagnostics_by_summary[summary.cluster_label] = diagnostics
    return _ValidityJsonContext(
        effective_parameters=effective,
        effective_parameters_readable=effective_ok,
        algorithm_manifest=manifest,
        diagnostics_by_summary=diagnostics_by_summary,
        all_shapes_valid=all(shapes),
    )


def _assignment_coverage_is_valid(
    items: Sequence[CorpusItemRecord],
    assignments: Sequence[ClusterAssignmentRecord],
) -> bool:
    expected_ids = [item.snapshot_item_id for item in items]
    assignment_ids = [item.snapshot_item_id for item in assignments]
    return (
        len(assignments) == len(items)
        and len(assignment_ids) == len(set(assignment_ids))
        and set(assignment_ids) == set(expected_ids)
    )


def _summary_links_are_valid(
    assignments: Sequence[ClusterAssignmentRecord],
    summaries: Sequence[ClusterSummaryRecord],
) -> bool:
    assignment_labels = {item.cluster_label for item in assignments}
    summary_labels = [item.cluster_label for item in summaries]
    summary_label_counts = Counter(summary_labels)
    non_noise_assignments = assignment_labels - {NOISE_LABEL}
    non_noise_summaries = set(summary_labels) - {NOISE_LABEL}
    noise_summary_count = summary_label_counts[NOISE_LABEL]
    return (
        len(summary_labels) == len(set(summary_labels))
        and all(label >= NOISE_LABEL for label in assignment_labels)
        and all(label >= NOISE_LABEL for label in summary_label_counts)
        and non_noise_assignments == non_noise_summaries
        and all(summary_label_counts[label] == 1 for label in non_noise_summaries)
        and (
            noise_summary_count == 1
            if NOISE_LABEL in assignment_labels
            else noise_summary_count == 0
        )
    )


def _members_by_label(
    assignments: Sequence[ClusterAssignmentRecord],
) -> defaultdict[int, list[str]]:
    result: defaultdict[int, list[str]] = defaultdict(list)
    for assignment in assignments:
        result[assignment.cluster_label].append(assignment.snapshot_item_id)
    return result


def _membership_integrity_failures(
    *,
    assignments: Sequence[ClusterAssignmentRecord],
    summaries: Sequence[ClusterSummaryRecord],
    members_by_label: Mapping[int, Sequence[str]],
) -> set[str]:
    failed: set[str] = set()
    summaries_by_label = {summary.cluster_label: summary for summary in summaries}
    for summary in summaries:
        label = summary.cluster_label
        members = members_by_label.get(label, ())
        if summary.size != len(
            members
        ) or summary.membership_digest != membership_digest(list(members)):
            failed.add("V3")
    for assignment in assignments:
        assigned_summary = summaries_by_label.get(assignment.cluster_label)
        if (
            assigned_summary is not None
            and assignment.membership_digest != assigned_summary.membership_digest
        ):
            failed.add("V4")
    return failed


def _minimum_cluster_size_is_valid(
    *,
    effective_parameters: Mapping[str, object],
    effective_parameters_readable: bool,
    summaries: Sequence[ClusterSummaryRecord],
) -> bool:
    if not effective_parameters_readable:
        return True
    value = effective_parameters.get("min_cluster_size")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return False
    return all(
        summary.cluster_label == NOISE_LABEL or summary.size >= value
        for summary in summaries
    )


def _persisted_interpretation_numbers_are_finite(
    *,
    assignments: Sequence[ClusterAssignmentRecord],
    diagnostics_by_summary: Mapping[int, Mapping[str, object]],
) -> bool:
    assignment_numbers_are_finite = all(
        (value := assignment.membership_strength) is None or math.isfinite(value)
        for assignment in assignments
    )
    return assignment_numbers_are_finite and all(
        _diagnostic_numbers_are_finite(diagnostics)
        for diagnostics in diagnostics_by_summary.values()
    )


def _run_and_manifest_are_valid(
    *,
    run: ClusteringRunRecord,
    algorithm_manifest: Mapping[str, object] | None,
) -> bool:
    if run.status != "completed":
        return False
    return (
        True if algorithm_manifest is None else _manifest_is_valid(algorithm_manifest)
    )


def _generation_metadata_is_valid(
    *,
    store: CorpusStore,
    snapshot_id: str,
    run: ClusteringRunRecord,
    items: Sequence[CorpusItemRecord],
) -> bool:
    try:
        validate_generation_metadata(
            store=store,
            snapshot_id=snapshot_id,
            embedding_generation_id=run.embedding_generation_id,
            items=items,
        )
    except AnalyticsWorkflowError:
        return False
    return True


def _diagnostic_references_are_valid(
    *,
    items: Sequence[CorpusItemRecord],
    summaries: Sequence[ClusterSummaryRecord],
    diagnostics_by_summary: Mapping[int, Mapping[str, object]],
    members_by_label: Mapping[int, Sequence[str]],
) -> bool:
    items_by_id = {item.snapshot_item_id: item for item in items}
    for summary in summaries:
        label = summary.cluster_label
        if label == NOISE_LABEL or label not in diagnostics_by_summary:
            continue
        try:
            validate_cluster_diagnostic_refs(
                cluster_label=label,
                diagnostics=diagnostics_by_summary[label],
                items_by_id=items_by_id,
                assigned_item_ids=members_by_label.get(label, ()),
            )
        except AnalyticsWorkflowError:
            return False
    return True


def validate_persisted_run(
    *,
    store: CorpusStore,
    snapshot_id: str,
    clustering_run_id: str,
) -> ClusteringRunRecord:
    snapshot = store.get_snapshot(snapshot_id)
    if snapshot is None:
        raise AnalyticsWorkflowError(f"unknown snapshot: {snapshot_id}")
    run = store.get_clustering_run(clustering_run_id)
    if run is None:
        raise AnalyticsWorkflowError(f"unknown clustering run: {clustering_run_id}")
    if run.snapshot_id != snapshot_id:
        raise AnalyticsWorkflowError(
            f"clustering run {clustering_run_id} belongs to snapshot "
            f"{run.snapshot_id}, not {snapshot_id}"
        )
    assessment = assess_partition_validity(
        store=store,
        snapshot_id=snapshot_id,
        clustering_run_id=clustering_run_id,
    )
    if assessment.technically_valid:
        return run
    first = assessment.failed_invariants[0]
    v7_message = (
        f"clustering run is not completed: {clustering_run_id} ({run.status})"
        if run.status != "completed"
        else f"clustering run manifest is invalid: {clustering_run_id}"
    )
    messages = {
        "V1": "clustering assignments do not match snapshot items",
        "V2": "cluster summaries do not match assignments",
        "V3": "cluster summary integrity mismatch",
        "V4": "assignment membership digest mismatch",
        "V5": "cluster smaller than effective min_cluster_size",
        "V6a": "persisted interpretation numeric is not finite",
        "V7": v7_message,
        "V8": "embedding generation does not match snapshot items",
        "V9": "cluster diagnostic reference integrity mismatch",
        "V10": "persisted analytics JSON payload is malformed",
    }
    raise AnalyticsWorkflowError(
        f"{messages[first]} (failed invariants: "
        f"{', '.join(assessment.failed_invariants)})"
    )


def _json_object(text: str) -> tuple[dict[str, object], bool]:
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}, False
    if not isinstance(payload, dict):
        return {}, False
    return payload, True


def _manifest_is_valid(manifest: Mapping[str, object]) -> bool:
    for field in _MANIFEST_VERSION_FIELDS:
        value = manifest.get(field)
        if not isinstance(value, str) or not value:
            return False
    return all(
        manifest.get(field) == value for field, value in _MANIFEST_FIXED_FIELDS.items()
    )


def _diagnostic_numbers_are_finite(diagnostics: Mapping[str, object]) -> bool:
    for field in (
        "size",
        "size_percent",
        "average_membership_strength",
        "min_correlation_sample_size",
    ):
        if not _persisted_number_is_finite(diagnostics.get(field)):
            return False
    distributions = diagnostics.get("metadata_distributions")
    if not isinstance(distributions, Mapping):
        return True
    for values in _mapping_values(distributions):
        for cell in _mapping_values(values):
            for field in ("numerator", "denominator", "rate"):
                if not _persisted_number_is_finite(cell.get(field)):
                    return False
    return True


def _mapping_values(value: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(
        cast(Mapping[str, object], item)
        for item in value.values()
        if isinstance(item, Mapping)
    )


def _persisted_number_is_finite(value: object) -> bool:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return True
    return math.isfinite(value)


def _invariant_sort_key(code: str) -> tuple[int, str]:
    digits = "".join(character for character in code if character.isdigit())
    suffix = code[len(digits) + 1 :] if digits else code
    return (int(digits) if digits else 999, suffix)


__all__ = [
    "REQUIRED_ALGORITHM_MANIFEST_PATHS",
    "PartitionValidityAssessment",
    "assess_partition_validity",
    "load_validated_snapshot_vectors",
    "validate_cluster_diagnostic_refs",
    "validate_generation_metadata",
    "validate_persisted_run",
]
