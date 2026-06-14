# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from ..clustering.diagnostics import (
    EMPTY_MEANS_CONFIRMED_NONE_FIELDS,
    MAX_PREVIEW_CHARACTERS,
    ItemPreview,
    MetadataDisplayValue,
    build_item_preview,
    metadata_display_value,
    numeric_field_summary,
    preview_digest,
)
from ..clustering.models import NOISE_LABEL
from ..clustering.sweep import score_clustering_result
from ..contracts import (
    ClusterAssignmentRecord,
    ClusteringRunRecord,
    ClusterSummaryRecord,
    CorpusItemRecord,
    CorpusSnapshotRecord,
)
from ..exceptions import AnalyticsWorkflowError
from ..integrity import PartitionValidityAssessment, assess_partition_validity
from ..store.protocols import CorpusStore

INTERPRETATION_CONTRACT_VERSION = "1.0"
SMALL_CLUSTER_PROVENANCE_THRESHOLD = 15
INSPECTABILITY_TRACKED_METADATA_FIELDS = (
    "agent_family",
    "outcome",
    "quality_tier",
    "scope_check_status",
    "verification_status",
    "anomaly_kinds",
)
PREVIEW_SCOPES = (
    "cluster_representatives",
    "cluster_boundaries",
    "noise_items",
)
_NUMERIC_FIELDS = (
    "declared_file_count",
    "changed_file_count",
    "description_length",
)


@dataclass(frozen=True, slots=True)
class DiagnosticRunFacts:
    snapshot_item_count: int | None
    assignment_count: int | None
    summary_count: int | None
    completed_status: bool
    run_status: str | None
    clustering_run_id: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class RunPresentationStatus:
    technically_valid: bool
    failed_invariants: tuple[str, ...]
    recommended_by_heuristic: bool
    selected_by_maintainer: bool
    is_candidate_only: bool
    projection_mode: Literal["full_interpretation", "limited_diagnostic"]
    banner_kind: Literal[
        "maintainer_selected",
        "heuristic_recommended",
        "candidate_only",
        "technically_invalid",
    ]
    banner_message: str


@dataclass(frozen=True, slots=True)
class RunPartitionMetrics:
    total_items: int
    cluster_count: int
    noise_count: int
    non_noise_count: int
    noise_ratio: float
    dominant_cluster_ratio: float
    dominant_assigned_ratio: float | None
    dominant_cluster_label: int | None
    cluster_size_distribution: tuple[int, ...]
    cluster_size_histogram: dict[str, int]


@dataclass(frozen=True, slots=True)
class ProvenanceCompletenessSummary:
    item_count: int
    trajectory_selected_count: int
    patch_trail_present_count: int
    registry_overlay_present_count: int
    agent_family_known_count: int
    outcome_known_count: int
    anomaly_metadata_known_count: int
    fields_unknown_rate: dict[str, float]


def enrich_run_for_export(
    *,
    store: CorpusStore,
    snapshot: CorpusSnapshotRecord,
    run: ClusteringRunRecord,
) -> dict[str, object]:
    if run.snapshot_id != snapshot.snapshot_id:
        raise AnalyticsWorkflowError(
            f"run {run.clustering_run_id} does not belong to {snapshot.snapshot_id}"
        )
    items = store.list_items(snapshot.snapshot_id)
    assignments = store.list_assignments(run.clustering_run_id)
    summaries = store.list_summaries(run.clustering_run_id)
    assessment = assess_partition_validity(
        store=store,
        snapshot_id=snapshot.snapshot_id,
        clustering_run_id=run.clustering_run_id,
    )
    presentation = derive_presentation_status(run=run, assessment=assessment)
    run_payload = _run_payload(run)
    run_payload["validity"] = asdict(assessment)
    run_payload["presentation"] = asdict(presentation)
    projection: dict[str, object] = {"run": run_payload}
    if not assessment.technically_valid:
        run_payload["score"] = None
        run_payload["diagnostic_facts"] = asdict(
            _diagnostic_run_facts(
                run=run,
                assessment=assessment,
                item_count=len(items),
                assignment_count=len(assignments),
                summary_count=len(summaries),
            )
        )
        return projection

    metrics = compute_run_partition_metrics(assignments, summaries)
    run_payload["partition_metrics"] = asdict(metrics)
    run_payload["score"] = score_clustering_result(
        cluster_count=metrics.cluster_count,
        noise_fraction=metrics.noise_ratio,
        n_samples=metrics.total_items,
    )
    run_payload["cluster_count"] = metrics.cluster_count
    run_payload["noise_count"] = metrics.noise_count
    run_payload["noise_fraction"] = metrics.noise_ratio
    assignment_by_id = {
        assignment.snapshot_item_id: assignment for assignment in assignments
    }
    items_by_id = {item.snapshot_item_id: item for item in items}
    members_by_label: defaultdict[int, list[CorpusItemRecord]] = defaultdict(list)
    for assignment in assignments:
        item = items_by_id[assignment.snapshot_item_id]
        members_by_label[assignment.cluster_label].append(item)
    projection["clusters"] = [
        _cluster_projection(
            summary=summary,
            member_items=members_by_label[summary.cluster_label],
            items_by_id=items_by_id,
            assignment_by_id=assignment_by_id,
        )
        for summary in summaries
    ]
    projection["assignments"] = [
        _assignment_payload(assignment) for assignment in assignments
    ]
    projection["noise_items"] = [
        assignment.snapshot_item_id
        for assignment in assignments
        if assignment.cluster_label == NOISE_LABEL
    ]
    return projection


def derive_presentation_status(
    *,
    run: ClusteringRunRecord,
    assessment: PartitionValidityAssessment,
) -> RunPresentationStatus:
    banner_kind: Literal[
        "maintainer_selected",
        "heuristic_recommended",
        "candidate_only",
        "technically_invalid",
    ]
    if not assessment.technically_valid:
        banner_kind = "technically_invalid"
        banner_message = (
            "Technically invalid clustering run. Failed invariants: "
            + ", ".join(assessment.failed_invariants)
        )
    elif run.selected_by_maintainer:
        banner_kind = "maintainer_selected"
        banner_message = (
            "Maintainer-selected run. Selection is review evidence, not taxonomy truth."
        )
    elif run.recommended_by_heuristic:
        banner_kind = "heuristic_recommended"
        banner_message = (
            "Heuristically recommended run. Recommendation is not a semantic verdict."
        )
    else:
        banner_kind = "candidate_only"
        banner_message = (
            "Candidate run \u2014 not heuristically recommended or "
            "maintainer-selected. "
            "This partition is a valid clustering output for inspection only. "
            "Do not treat it as the corpus taxonomy."
        )
    return RunPresentationStatus(
        technically_valid=assessment.technically_valid,
        failed_invariants=assessment.failed_invariants,
        recommended_by_heuristic=run.recommended_by_heuristic,
        selected_by_maintainer=run.selected_by_maintainer,
        is_candidate_only=(
            assessment.technically_valid
            and not run.recommended_by_heuristic
            and not run.selected_by_maintainer
        ),
        projection_mode=(
            "full_interpretation"
            if assessment.technically_valid
            else "limited_diagnostic"
        ),
        banner_kind=banner_kind,
        banner_message=banner_message,
    )


def compute_run_partition_metrics(
    assignments: Sequence[ClusterAssignmentRecord],
    summaries: Sequence[ClusterSummaryRecord],
) -> RunPartitionMetrics:
    total_items = len(assignments)
    noise_count = sum(
        assignment.cluster_label == NOISE_LABEL for assignment in assignments
    )
    non_noise_summaries = [
        summary for summary in summaries if summary.cluster_label != NOISE_LABEL
    ]
    ordered = sorted(
        non_noise_summaries,
        key=lambda summary: (
            -summary.size,
            summary.membership_digest,
            summary.cluster_label,
        ),
    )
    largest = ordered[0] if ordered else None
    non_noise_count = total_items - noise_count
    sizes = tuple(
        sorted((summary.size for summary in non_noise_summaries), reverse=True)
    )
    return RunPartitionMetrics(
        total_items=total_items,
        cluster_count=len(non_noise_summaries),
        noise_count=noise_count,
        non_noise_count=non_noise_count,
        noise_ratio=(noise_count / total_items) if total_items else 0.0,
        dominant_cluster_ratio=(
            largest.size / total_items if largest is not None and total_items else 0.0
        ),
        dominant_assigned_ratio=(
            largest.size / non_noise_count
            if largest is not None and non_noise_count
            else None
        ),
        dominant_cluster_label=largest.cluster_label if largest is not None else None,
        cluster_size_distribution=sizes,
        cluster_size_histogram=_cluster_size_histogram(sizes),
    )


def build_sweep_comparison_projection(
    *,
    store: CorpusStore,
    snapshot: CorpusSnapshotRecord,
    embedding_generation_id: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[tuple[ClusteringRunRecord, dict[str, object], dict[str, object]]] = []
    for run in store.list_clustering_runs(
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embedding_generation_id,
    ):
        projection = enrich_run_for_export(store=store, snapshot=snapshot, run=run)
        run_payload = _mapping(projection["run"])
        validity = _mapping(run_payload["validity"])
        valid = bool(validity.get("technically_valid"))
        metrics = _mapping(run_payload.get("partition_metrics"))
        comparison: dict[str, object] = {
            "score": None,
            "rank": None,
            "recommended_by_heuristic": valid and run.recommended_by_heuristic,
            "dominant_cluster_ratio": metrics.get("dominant_cluster_ratio"),
            "dominant_assigned_ratio": metrics.get("dominant_assigned_ratio"),
            "largest_cluster_size": _largest_cluster_size(metrics),
        }
        if valid:
            comparison["score"] = score_clustering_result(
                cluster_count=_required_integer(metrics, "cluster_count"),
                noise_fraction=_required_number(metrics, "noise_ratio"),
                n_samples=_required_integer(metrics, "total_items"),
            )
        projection["comparison"] = comparison
        rows.append((run, projection, comparison))

    ranked = sorted(
        (row for row in rows if row[2]["score"] is not None),
        key=_comparison_sort_key,
    )
    for rank, (_run, _projection, comparison) in enumerate(ranked, start=1):
        comparison["rank"] = rank

    recommendations = [
        run.clustering_run_id
        for run, _projection, comparison in rows
        if comparison["recommended_by_heuristic"]
    ]
    selections = [
        run.clustering_run_id
        for run, _projection, _comparison in rows
        if run.selected_by_maintainer
    ]
    if len(recommendations) > 1:
        raise AnalyticsWorkflowError("multiple valid heuristic recommendations")
    if len(selections) > 1:
        raise AnalyticsWorkflowError("multiple maintainer-selected runs")
    summary: dict[str, object] = {
        "candidate_count": len(rows),
        "technically_valid_count": len(ranked),
        "technically_invalid_count": len(rows) - len(ranked),
        "recommended_run_id": recommendations[0] if recommendations else None,
        "selected_run_id": selections[0] if selections else None,
    }
    return [projection for _run, projection, _comparison in rows], summary


def content_disclosure(payload: Mapping[str, object]) -> dict[str, object]:
    counts = dict.fromkeys(PREVIEW_SCOPES, 0)
    _count_previews(payload, counts)
    return {
        "contains_normalized_text_previews": sum(counts.values()) > 0,
        "preview_scope": [scope for scope in PREVIEW_SCOPES if counts[scope] > 0],
        "max_preview_characters": MAX_PREVIEW_CHARACTERS,
    }


def _cluster_projection(
    *,
    summary: ClusterSummaryRecord,
    member_items: Sequence[CorpusItemRecord],
    items_by_id: Mapping[str, CorpusItemRecord],
    assignment_by_id: Mapping[str, ClusterAssignmentRecord],
) -> dict[str, object]:
    diagnostics = _json_mapping(summary.diagnostics_json)
    payload: dict[str, object] = {
        "cluster_label": summary.cluster_label,
        "display_cluster_id": summary.display_cluster_id,
        "membership_digest": summary.membership_digest,
        "size": summary.size,
        "diagnostics": diagnostics,
    }
    if summary.cluster_label == NOISE_LABEL:
        payload["interpretation"] = {
            "noise_item_previews": _noise_item_previews(
                diagnostics=diagnostics,
                items_by_id=items_by_id,
                assignment_by_id=assignment_by_id,
            )
        }
        return payload

    representative_ids = _string_list(diagnostics.get("representatives"))
    boundary_ids = _string_list(diagnostics.get("boundary_items"))
    representative_previews = [
        _preview_payload(
            build_item_preview(
                items_by_id[item_id],
                assignment_by_id.get(item_id),
                source_kind="intent_historical",
                source_record_id=items_by_id[item_id].intent_id,
            )
        )
        for item_id in representative_ids
    ]
    boundary_previews = [
        _preview_payload(
            build_item_preview(
                items_by_id[item_id],
                assignment_by_id.get(item_id),
                source_kind="intent_historical",
                source_record_id=items_by_id[item_id].intent_id,
            )
        )
        for item_id in boundary_ids
    ]
    numeric_summaries = {
        field: asdict(numeric_field_summary(member_items, field=field))
        for field in _NUMERIC_FIELDS
    }
    interpretation: dict[str, object] = {
        "representative_previews": representative_previews,
        "boundary_previews": boundary_previews,
        "categorical_correlations": _categorical_correlations(diagnostics),
        "numeric_summaries": numeric_summaries,
        "machine_inspectability_signals": _machine_inspectability_signals(
            member_items=member_items,
            representative_previews=representative_previews,
            assignment_by_id=assignment_by_id,
            description_length_summary=_mapping(
                numeric_summaries["description_length"]
            ),
        ),
    }
    if summary.size <= SMALL_CLUSTER_PROVENANCE_THRESHOLD:
        interpretation["provenance_completeness"] = asdict(
            _provenance_completeness(member_items)
        )
    payload["interpretation"] = interpretation
    return payload


def _noise_item_previews(
    *,
    diagnostics: Mapping[str, object],
    items_by_id: Mapping[str, CorpusItemRecord],
    assignment_by_id: Mapping[str, ClusterAssignmentRecord],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for entry in _mapping_list(diagnostics.get("noise_items")):
        item_id = entry.get("snapshot_item_id")
        if not isinstance(item_id, str) or item_id not in items_by_id:
            continue
        item = items_by_id[item_id]
        result.append(
            {
                "preview": _preview_payload(
                    build_item_preview(
                        item,
                        assignment_by_id.get(item_id),
                        source_kind="intent_historical",
                        source_record_id=item.intent_id,
                    )
                ),
                "flags": _mapping(entry.get("flags")),
            }
        )
    return result


def _categorical_correlations(
    diagnostics: Mapping[str, object],
) -> dict[str, list[dict[str, object]]]:
    distributions = diagnostics.get("metadata_distributions")
    if not isinstance(distributions, Mapping):
        return {}
    result: dict[str, list[dict[str, object]]] = {}
    for field, values in sorted(distributions.items()):
        if field in _NUMERIC_FIELDS:
            continue
        rows: list[dict[str, object]] = []
        for key, cell in _mapping_cells(values):
            rows.append(
                {
                    "value": asdict(_distribution_display_value(str(field), str(key))),
                    "numerator": cell.get("numerator"),
                    "denominator": cell.get("denominator"),
                    "rate": cell.get("rate"),
                    "insufficient_sample": bool(cell.get("insufficient_sample")),
                }
            )
        result[str(field)] = rows
    return result


def _distribution_display_value(field: str, key: str) -> MetadataDisplayValue:
    if key == "null":
        return MetadataDisplayValue(kind="unknown", display="unknown")
    if key == "none":
        if field in EMPTY_MEANS_CONFIRMED_NONE_FIELDS:
            return MetadataDisplayValue(
                kind="confirmed_none",
                display="none (confirmed empty)",
            )
        return MetadataDisplayValue(
            kind="empty_collection",
            display="empty collection",
        )
    return MetadataDisplayValue(kind="value", display=key)


def _provenance_completeness(
    items: Sequence[CorpusItemRecord],
) -> ProvenanceCompletenessSummary:
    trajectory_selected_count = 0
    patch_trail_present_count = 0
    registry_overlay_present_count = 0
    known_counts = dict.fromkeys(INSPECTABILITY_TRACKED_METADATA_FIELDS, 0)
    for item in items:
        metadata = _json_mapping(item.metadata_json)
        provenance = metadata.get("provenance")
        provenance_map = provenance if isinstance(provenance, Mapping) else {}
        if (
            _provenance_presence(
                provenance_map,
                section="trajectory",
                explicit_key="selected",
                positive_key="selected_trajectory_id",
            )
            is True
        ):
            trajectory_selected_count += 1
        if (
            _provenance_presence(
                provenance_map,
                section="patch_trail",
                explicit_key="present",
                positive_key="digest",
            )
            is True
        ):
            patch_trail_present_count += 1
        if _registry_overlay_presence(item, provenance_map) is True:
            registry_overlay_present_count += 1
        for field in INSPECTABILITY_TRACKED_METADATA_FIELDS:
            if metadata_display_value(metadata, field).kind != "unknown":
                known_counts[field] += 1
    item_count = len(items)
    return ProvenanceCompletenessSummary(
        item_count=item_count,
        trajectory_selected_count=trajectory_selected_count,
        patch_trail_present_count=patch_trail_present_count,
        registry_overlay_present_count=registry_overlay_present_count,
        agent_family_known_count=known_counts["agent_family"],
        outcome_known_count=known_counts["outcome"],
        anomaly_metadata_known_count=known_counts["anomaly_kinds"],
        fields_unknown_rate={
            field: (
                (item_count - known_counts[field]) / item_count if item_count else 0.0
            )
            for field in INSPECTABILITY_TRACKED_METADATA_FIELDS
        },
    )


def _provenance_presence(
    provenance: Mapping[str, object],
    *,
    section: str,
    explicit_key: str,
    positive_key: str,
) -> bool | None:
    # Slice 1 compatibility: positive evidence is present, explicit absence is
    # absent, and a null/missing legacy field remains unknown.
    value = provenance.get(section)
    if not isinstance(value, Mapping):
        return None
    explicit = value.get(explicit_key)
    if isinstance(explicit, bool):
        return explicit
    if value.get(positive_key) is not None:
        return True
    if value.get("available") is False:
        return False
    return None


def _registry_overlay_presence(
    item: CorpusItemRecord,
    provenance: Mapping[str, object],
) -> bool | None:
    # Slice 1 only established non-null overlay content as positive evidence.
    value = provenance.get("registry_overlay")
    if isinstance(value, Mapping) and isinstance(value.get("present"), bool):
        return bool(value["present"])
    if item.registry_overlay_json is None:
        return None
    overlay = _json_mapping_or_none(item.registry_overlay_json)
    return True if overlay is not None else None


def _machine_inspectability_signals(
    *,
    member_items: Sequence[CorpusItemRecord],
    representative_previews: Sequence[Mapping[str, object]],
    assignment_by_id: Mapping[str, ClusterAssignmentRecord],
    description_length_summary: Mapping[str, object],
) -> dict[str, object]:
    preview_texts = [
        str(preview.get("normalized_text_preview", ""))
        for preview in representative_previews
    ]
    strengths = sorted(
        assignment.membership_strength
        for item in member_items
        if (assignment := assignment_by_id.get(item.snapshot_item_id)) is not None
        and assignment.membership_strength is not None
        and math.isfinite(assignment.membership_strength)
    )
    known = 0
    for item in member_items:
        metadata = _json_mapping(item.metadata_json)
        known += sum(
            metadata_display_value(metadata, field).kind != "unknown"
            for field in INSPECTABILITY_TRACKED_METADATA_FIELDS
        )
    denominator = len(INSPECTABILITY_TRACKED_METADATA_FIELDS) * len(member_items)
    return {
        "representative_text_present": bool(preview_texts) and all(preview_texts),
        "representative_text_unique": bool(preview_texts)
        and len({preview_digest(text) for text in preview_texts}) == len(preview_texts),
        "membership_strength_spread": (
            strengths[-1] - strengths[0] if len(strengths) >= 2 else None
        ),
        "metadata_known_fraction": known / denominator if denominator else 0.0,
        "cluster_size": len(member_items),
        "description_length_median": description_length_summary.get("median"),
    }


def _diagnostic_run_facts(
    *,
    run: ClusteringRunRecord,
    assessment: PartitionValidityAssessment,
    item_count: int,
    assignment_count: int,
    summary_count: int,
) -> DiagnosticRunFacts:
    allowed_by_invariant = {
        "V1": {"snapshot", "assignment"},
        "V2": {"snapshot", "assignment"},
        "V3": {"assignment", "summary"},
        "V4": {"assignment", "summary"},
        "V5": {"assignment", "summary"},
        "V6a": set(),
        "V7": set(),
        "V8": set(),
        "V9": {"snapshot", "assignment", "summary"},
        "V10": {"snapshot", "assignment", "summary"},
    }
    allowed = {"snapshot", "assignment", "summary"}
    for invariant in assessment.failed_invariants:
        allowed &= allowed_by_invariant[invariant]
    return DiagnosticRunFacts(
        snapshot_item_count=item_count if "snapshot" in allowed else None,
        assignment_count=assignment_count if "assignment" in allowed else None,
        summary_count=summary_count if "summary" in allowed else None,
        completed_status=run.status == "completed",
        run_status=run.status,
        clustering_run_id=run.clustering_run_id,
        snapshot_id=run.snapshot_id,
    )


def _run_payload(run: ClusteringRunRecord) -> dict[str, object]:
    requested = _json_mapping_or_none(run.requested_parameters_json)
    effective = _json_mapping_or_none(run.effective_parameters_json)
    manifest = (
        effective.get("algorithm_manifest")
        if isinstance(effective, Mapping)
        and isinstance(effective.get("algorithm_manifest"), Mapping)
        else None
    )
    return {
        "clustering_run_id": run.clustering_run_id,
        "snapshot_id": run.snapshot_id,
        "embedding_generation_id": run.embedding_generation_id,
        "requested_parameters": requested,
        "effective_parameters": effective,
        "algorithm_manifest": dict(manifest) if isinstance(manifest, Mapping) else None,
        "random_seed": run.random_seed,
        "run_digest": run.run_digest,
        "recommended_by_heuristic": run.recommended_by_heuristic,
        "selected_by_maintainer": run.selected_by_maintainer,
        "status": run.status,
        "created_at_utc": run.created_at_utc,
        "finished_at_utc": run.finished_at_utc,
        "error_message": run.error_message,
    }


def _assignment_payload(assignment: ClusterAssignmentRecord) -> dict[str, object]:
    return {
        "snapshot_item_id": assignment.snapshot_item_id,
        "cluster_label": assignment.cluster_label,
        "membership_strength": assignment.membership_strength,
        "membership_digest": assignment.membership_digest,
    }


def _preview_payload(preview: ItemPreview) -> dict[str, object]:
    return {
        "snapshot_item_id": preview.snapshot_item_id,
        "source_record_id": preview.source_record_id,
        "source_kind": preview.source_kind,
        "intent_id": preview.intent_id,
        "normalized_text_preview": preview.normalized_text_preview,
        "membership_strength": preview.membership_strength,
        "agent_family": asdict(preview.agent_family),
        "outcome": asdict(preview.outcome),
        "quality_tier": asdict(preview.quality_tier),
        "scope_check_status": asdict(preview.scope_check_status),
        "verification_status": asdict(preview.verification_status),
    }


def _cluster_size_histogram(sizes: Sequence[int]) -> dict[str, int]:
    result = {"1-3": 0, "4-7": 0, "8-15": 0, "16-31": 0, "32-63": 0, "64+": 0}
    for size in sizes:
        if size <= 3:
            result["1-3"] += 1
        elif size <= 7:
            result["4-7"] += 1
        elif size <= 15:
            result["8-15"] += 1
        elif size <= 31:
            result["16-31"] += 1
        elif size <= 63:
            result["32-63"] += 1
        else:
            result["64+"] += 1
    return result


def _largest_cluster_size(metrics: Mapping[str, object]) -> int | None:
    sizes = metrics.get("cluster_size_distribution")
    if not isinstance(sizes, list | tuple) or not sizes:
        return None
    value = sizes[0]
    return int(value) if isinstance(value, int) else None


def _comparison_sort_key(
    row: tuple[ClusteringRunRecord, dict[str, object], dict[str, object]],
) -> tuple[float, int, int, int, str]:
    _run, projection, comparison = row
    score = comparison["score"]
    run_payload = _mapping(projection["run"])
    effective = _mapping(run_payload["effective_parameters"])
    return (
        -_finite_float(score),
        _integer_parameter(effective, "pca_dimensions"),
        _integer_parameter(effective, "min_cluster_size"),
        _integer_parameter(effective, "min_samples"),
        _string_parameter(effective, "cluster_selection_method"),
    )


def _count_previews(value: object, counts: dict[str, int]) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            scope = {
                "representative_previews": "cluster_representatives",
                "boundary_previews": "cluster_boundaries",
                "noise_item_previews": "noise_items",
            }.get(str(key))
            if scope is not None and isinstance(nested, list):
                counts[scope] += len(nested)
            _count_previews(nested, counts)
    elif isinstance(value, list):
        for nested in value:
            _count_previews(nested, counts)


def _json_mapping(text: str) -> dict[str, object]:
    value = _json_mapping_or_none(text)
    return value if value is not None else {}


def _json_mapping_or_none(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping_cells(value: object) -> list[tuple[str, dict[str, object]]]:
    if not isinstance(value, Mapping):
        return []
    return [
        (str(key), dict(cell))
        for key, cell in sorted(value.items())
        if isinstance(cell, Mapping)
    ]


def _finite_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AnalyticsWorkflowError("valid comparison candidate has no finite score")
    number = float(value)
    if not math.isfinite(number):
        raise AnalyticsWorkflowError("valid comparison candidate has no finite score")
    return number


def _integer_parameter(parameters: Mapping[str, object], field: str) -> int:
    value = parameters.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnalyticsWorkflowError(
            f"valid comparison candidate is missing integer parameter {field}"
        )
    return value


def _required_integer(parameters: Mapping[str, object], field: str) -> int:
    value = parameters.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnalyticsWorkflowError(
            f"valid projection is missing integer field {field}"
        )
    return value


def _required_number(parameters: Mapping[str, object], field: str) -> float:
    value = parameters.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AnalyticsWorkflowError(
            f"valid projection is missing numeric field {field}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise AnalyticsWorkflowError(
            f"valid projection has non-finite numeric field {field}"
        )
    return number


def _string_parameter(parameters: Mapping[str, object], field: str) -> str:
    value = parameters.get(field)
    if not isinstance(value, str) or not value:
        raise AnalyticsWorkflowError(
            f"valid comparison candidate is missing string parameter {field}"
        )
    return value


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


__all__ = [
    "INSPECTABILITY_TRACKED_METADATA_FIELDS",
    "INTERPRETATION_CONTRACT_VERSION",
    "PREVIEW_SCOPES",
    "SMALL_CLUSTER_PROVENANCE_THRESHOLD",
    "DiagnosticRunFacts",
    "ProvenanceCompletenessSummary",
    "RunPartitionMetrics",
    "RunPresentationStatus",
    "build_sweep_comparison_projection",
    "compute_run_partition_metrics",
    "content_disclosure",
    "derive_presentation_status",
    "enrich_run_for_export",
]
