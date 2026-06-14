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
    ProfileAssessmentRecord,
    ProfileBatchRecord,
    RunSelectionRecord,
)
from ..exceptions import AnalyticsWorkflowError
from ..integrity import PartitionValidityAssessment, assess_partition_validity
from ..metrics.partition_metrics import (
    RunPartitionMetrics,
    compute_run_partition_metrics,
)
from ..metrics.partition_metrics import (
    _cluster_size_histogram as _partition_cluster_size_histogram,
)
from ..store.protocols import CorpusStore
from .messages.profiles import profile_banner_message

INTERPRETATION_CONTRACT_VERSION = "1.1"
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
        "profile_recommended",
        "heuristic_recommended",
        "valid_but_profile_rejected",
        "no_profile_suitable_candidate",
        "candidate_only",
        "technically_invalid",
    ]
    banner_message: str


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
    profile_id: str | None = None,
    profile_batch_id: str | None = None,
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
    batch = _resolve_profile_batch(
        store=store,
        snapshot=snapshot,
        run=run,
        profile_id=profile_id,
        profile_batch_id=profile_batch_id,
    )
    profile_assessment = (
        store.get_profile_assessment(
            profile_batch_id=batch.profile_batch_id,
            clustering_run_id=run.clustering_run_id,
        )
        if batch is not None
        else None
    )
    active_selection = _active_selection(
        store=store,
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=run.embedding_generation_id,
        profile_batch_id=batch.profile_batch_id if batch is not None else None,
    )
    manifest = (
        store.get_profile_manifest_snapshot(batch.profile_manifest_digest)
        if batch is not None
        else None
    )
    presentation = derive_presentation_status(
        run=run,
        assessment=assessment,
        profile_assessment=profile_assessment,
        profile_batch_active=batch is not None,
        profile_recommended_run_id=(
            batch.recommended_clustering_run_id if batch is not None else None
        ),
        active_maintainer_selection=active_selection,
        profile_label=manifest.label if manifest is not None else None,
    )
    run_payload = _run_payload(run)
    run_payload["validity"] = asdict(assessment)
    run_payload["presentation"] = asdict(presentation)
    if batch is not None and profile_assessment is not None and manifest is not None:
        run_payload["profile_context"] = _profile_context_payload(
            batch=batch,
            assessment=profile_assessment,
            label=manifest.label,
            description=manifest.description,
            clustering_run_id=run.clustering_run_id,
        )
    if active_selection is not None:
        run_payload["selection"] = _selection_payload(
            selection=active_selection,
            run=run,
        )
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
    profile_assessment: ProfileAssessmentRecord | None = None,
    profile_batch_active: bool = False,
    profile_recommended_run_id: str | None = None,
    active_maintainer_selection: RunSelectionRecord | None = None,
    profile_label: str | None = None,
) -> RunPresentationStatus:
    banner_kind: Literal[
        "maintainer_selected",
        "profile_recommended",
        "heuristic_recommended",
        "valid_but_profile_rejected",
        "candidate_only",
        "technically_invalid",
    ]
    if not assessment.technically_valid:
        banner_kind = "technically_invalid"
    elif (
        active_maintainer_selection is not None
        and active_maintainer_selection.selected_run_id == run.clustering_run_id
    ):
        banner_kind = "maintainer_selected"
    elif profile_batch_active and profile_recommended_run_id == run.clustering_run_id:
        banner_kind = "profile_recommended"
    elif (
        profile_batch_active
        and profile_assessment is not None
        and not profile_assessment.suitable_for_profile
    ):
        banner_kind = "valid_but_profile_rejected"
    elif run.recommended_by_heuristic:
        banner_kind = "heuristic_recommended"
    else:
        banner_kind = "candidate_only"
    banner_message = profile_banner_message(
        banner_kind,
        failed_invariants=assessment.failed_invariants,
        profile_label=profile_label,
    )
    selected = (
        active_maintainer_selection is not None
        and active_maintainer_selection.selected_run_id == run.clustering_run_id
    )
    return RunPresentationStatus(
        technically_valid=assessment.technically_valid,
        failed_invariants=assessment.failed_invariants,
        recommended_by_heuristic=run.recommended_by_heuristic,
        selected_by_maintainer=selected,
        is_candidate_only=(
            assessment.technically_valid
            and not run.recommended_by_heuristic
            and not selected
            and not (
                profile_batch_active
                and profile_recommended_run_id == run.clustering_run_id
            )
            and not (
                profile_batch_active
                and profile_assessment is not None
                and not profile_assessment.suitable_for_profile
            )
        ),
        projection_mode=(
            "full_interpretation"
            if assessment.technically_valid
            else "limited_diagnostic"
        ),
        banner_kind=banner_kind,
        banner_message=banner_message,
    )


def build_sweep_comparison_projection(
    *,
    store: CorpusStore,
    snapshot: CorpusSnapshotRecord,
    embedding_generation_id: str,
    profile_id: str | None = None,
    profile_batch_id: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    batch = _resolve_comparison_batch(
        store=store,
        snapshot=snapshot,
        embedding_generation_id=embedding_generation_id,
        profile_id=profile_id,
        profile_batch_id=profile_batch_id,
    )
    rows: list[tuple[ClusteringRunRecord, dict[str, object], dict[str, object]]] = []
    runs = (
        store.list_clustering_runs_for_batch(profile_batch_id=batch.profile_batch_id)
        if batch is not None
        else store.list_clustering_runs(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embedding_generation_id,
        )
    )
    for run in runs:
        projection = enrich_run_for_export(
            store=store,
            snapshot=snapshot,
            run=run,
            profile_batch_id=batch.profile_batch_id if batch is not None else None,
        )
        run_payload = _mapping(projection["run"])
        validity = _mapping(run_payload["validity"])
        valid = bool(validity.get("technically_valid"))
        metrics = _mapping(run_payload.get("partition_metrics"))
        comparison: dict[str, object] = {
            "score": None,
            "rank": None,
            "recommended_by_heuristic": valid and run.recommended_by_heuristic,
            "is_profile_recommended": (
                batch is not None
                and batch.recommended_clustering_run_id == run.clustering_run_id
            ),
            "profile_suitable": _profile_suitable(run_payload),
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
    if len(recommendations) > 1:
        raise AnalyticsWorkflowError("multiple valid heuristic recommendations")
    active_selection = _active_selection(
        store=store,
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embedding_generation_id,
        profile_batch_id=batch.profile_batch_id if batch is not None else None,
    )
    summary: dict[str, object] = {
        "candidate_count": len(rows),
        "technically_valid_count": len(ranked),
        "technically_invalid_count": len(rows) - len(ranked),
        "recommended_run_id": recommendations[0] if recommendations else None,
        "selected_run_id": (
            active_selection.selected_run_id if active_selection is not None else None
        ),
    }
    return [projection for _run, projection, _comparison in rows], summary


def build_profile_summary(
    *,
    store: CorpusStore,
    snapshot: CorpusSnapshotRecord,
    embedding_generation_id: str,
    profile_id: str | None = None,
    profile_batch_id: str | None = None,
) -> dict[str, object] | None:
    batch = _resolve_comparison_batch(
        store=store,
        snapshot=snapshot,
        embedding_generation_id=embedding_generation_id,
        profile_id=profile_id,
        profile_batch_id=profile_batch_id,
    )
    if batch is None:
        return None
    manifest = store.get_profile_manifest_snapshot(batch.profile_manifest_digest)
    if manifest is None:
        raise AnalyticsWorkflowError(
            f"profile manifest snapshot missing: {batch.profile_manifest_digest}"
        )
    runs = store.list_clustering_runs_for_batch(profile_batch_id=batch.profile_batch_id)
    assessments = store.list_profile_assessments(
        profile_batch_id=batch.profile_batch_id
    )
    active_selection = _active_selection(
        store=store,
        snapshot_id=snapshot.snapshot_id,
        embedding_generation_id=embedding_generation_id,
        profile_batch_id=batch.profile_batch_id,
    )
    technically_valid_count = sum(
        assess_partition_validity(
            store=store,
            snapshot_id=snapshot.snapshot_id,
            clustering_run_id=run.clustering_run_id,
        ).technically_valid
        for run in runs
    )
    heuristic = [run.clustering_run_id for run in runs if run.recommended_by_heuristic]
    if len(heuristic) > 1:
        raise AnalyticsWorkflowError("multiple valid heuristic recommendations")
    summary: dict[str, object] = {
        "profile_batch_id": batch.profile_batch_id,
        "profile_id": batch.profile_id,
        "profile_version": manifest.profile_version,
        "profile_manifest_digest": batch.profile_manifest_digest,
        "label": manifest.label,
        "description": manifest.description,
        "candidate_count": batch.candidate_count_planned,
        "candidate_count_failed": batch.candidate_count_failed,
        "technically_valid_count": technically_valid_count,
        "profile_suitable_count": sum(
            assessment.suitable_for_profile for assessment in assessments
        ),
        "batch_status": batch.status,
        "recommended_for_profile_run_id": (batch.recommended_clustering_run_id),
        "recommended_by_heuristic_run_id": (heuristic[0] if heuristic else None),
        "active_selected_run_id": (
            active_selection.selected_run_id if active_selection is not None else None
        ),
        "recommendation_rationale": (
            _json_mapping_or_none(batch.recommendation_rationale_json)
            if batch.recommendation_rationale_json is not None
            else None
        ),
    }
    if not summary["profile_suitable_count"]:
        summary["presentation"] = asdict(
            derive_sweep_comparison_presentation(profile_summary=summary)
        )
    return summary


def derive_sweep_comparison_presentation(
    *,
    profile_summary: Mapping[str, object],
) -> RunPresentationStatus:
    profile_label = (
        str(profile_summary["label"])
        if isinstance(profile_summary.get("label"), str)
        else None
    )
    return RunPresentationStatus(
        technically_valid=bool(profile_summary.get("technically_valid_count")),
        failed_invariants=(),
        recommended_by_heuristic=False,
        selected_by_maintainer=False,
        is_candidate_only=False,
        projection_mode="full_interpretation",
        banner_kind="no_profile_suitable_candidate",
        banner_message=profile_banner_message(
            "no_profile_suitable_candidate",
            profile_label=profile_label,
        ),
    )


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


def _resolve_profile_batch(
    *,
    store: CorpusStore,
    snapshot: CorpusSnapshotRecord,
    run: ClusteringRunRecord,
    profile_id: str | None,
    profile_batch_id: str | None,
) -> ProfileBatchRecord | None:
    batch = _resolve_comparison_batch(
        store=store,
        snapshot=snapshot,
        embedding_generation_id=run.embedding_generation_id,
        profile_id=profile_id,
        profile_batch_id=profile_batch_id,
    )
    if batch is None and profile_id is None and profile_batch_id is None:
        if not hasattr(store, "list_profile_batch_ids_for_run"):
            return None
        candidates = [
            store.get_profile_batch(batch_id)
            for batch_id in store.list_profile_batch_ids_for_run(
                clustering_run_id=run.clustering_run_id
            )
        ]
        matching = [candidate for candidate in candidates if candidate is not None]
        batch = (
            max(
                matching,
                key=lambda candidate: (
                    candidate.started_at_utc,
                    candidate.profile_batch_id,
                ),
            )
            if matching
            else None
        )
    if batch is None:
        return None
    return batch if _batch_contains_run(store, batch, run.clustering_run_id) else None


def _resolve_comparison_batch(
    *,
    store: CorpusStore,
    snapshot: CorpusSnapshotRecord,
    embedding_generation_id: str,
    profile_id: str | None,
    profile_batch_id: str | None,
) -> ProfileBatchRecord | None:
    if profile_batch_id is not None:
        if not hasattr(store, "get_profile_batch"):
            return None
        batch = store.get_profile_batch(profile_batch_id)
        if batch is None:
            raise AnalyticsWorkflowError(f"unknown profile batch: {profile_batch_id}")
    elif profile_id is not None:
        if not hasattr(store, "get_latest_profile_batch"):
            return None
        batch = store.get_latest_profile_batch(
            snapshot_id=snapshot.snapshot_id,
            embedding_generation_id=embedding_generation_id,
            profile_id=profile_id,
        )
        if batch is None:
            return None
    else:
        return None
    if (
        batch.snapshot_id != snapshot.snapshot_id
        or batch.embedding_generation_id != embedding_generation_id
    ):
        raise AnalyticsWorkflowError(
            "profile batch does not belong to requested corpus: "
            f"{batch.profile_batch_id}"
        )
    if profile_id is not None and batch.profile_id != profile_id:
        raise AnalyticsWorkflowError(
            f"profile batch does not match profile: {profile_id}"
        )
    return batch


def _batch_contains_run(
    store: CorpusStore,
    batch: ProfileBatchRecord,
    clustering_run_id: str,
) -> bool:
    return any(
        member.clustering_run_id == clustering_run_id
        for member in store.list_profile_batch_run_records(
            profile_batch_id=batch.profile_batch_id
        )
    )


def _active_selection(
    *,
    store: CorpusStore,
    snapshot_id: str,
    embedding_generation_id: str,
    profile_batch_id: str | None,
) -> RunSelectionRecord | None:
    if not hasattr(store, "get_active_run_selection"):
        return None
    result = store.get_active_run_selection(
        snapshot_id=snapshot_id,
        embedding_generation_id=embedding_generation_id,
        profile_batch_id=profile_batch_id,
    )
    if result.ambiguous:
        raise AnalyticsWorkflowError(
            "selection chain ambiguous: multiple active selections"
        )
    return result.record


def _profile_context_payload(
    *,
    batch: ProfileBatchRecord,
    assessment: ProfileAssessmentRecord,
    label: str,
    description: str,
    clustering_run_id: str,
) -> dict[str, object]:
    return {
        "profile_id": assessment.profile_id,
        "profile_version": assessment.profile_version,
        "profile_manifest_digest": assessment.profile_manifest_digest,
        "label": label,
        "description": description,
        "profile_batch_id": batch.profile_batch_id,
        "suitability": {
            "suitable_for_profile": assessment.suitable_for_profile,
            "rejection_reasons": _json_string_list(assessment.rejection_reasons_json),
            "observed": (
                _json_mapping_or_none(assessment.observed_metrics_json)
                if assessment.observed_metrics_json is not None
                else None
            ),
        },
        "is_profile_recommended": (
            batch.recommended_clustering_run_id == clustering_run_id
        ),
    }


def _selection_payload(
    *,
    selection: RunSelectionRecord,
    run: ClusteringRunRecord,
) -> dict[str, object]:
    return {
        "selection_id": selection.selection_id,
        "profile_batch_id": selection.profile_batch_id,
        "profile_id": selection.profile_id,
        "profile_manifest_digest": selection.profile_manifest_digest,
        "selected_by": selection.selected_by,
        "selected_at_utc": selection.selected_at_utc,
        "rationale": selection.rationale,
        "is_active": selection.selected_run_id == run.clustering_run_id,
        "legacy_bool_mirror": run.selected_by_maintainer,
    }


def _profile_suitable(run_payload: Mapping[str, object]) -> bool | None:
    context = run_payload.get("profile_context")
    if not isinstance(context, Mapping):
        return None
    suitability = context.get("suitability")
    if not isinstance(suitability, Mapping):
        return None
    value = suitability.get("suitable_for_profile")
    return bool(value) if isinstance(value, bool) else None


def _assignment_payload(assignment: ClusterAssignmentRecord) -> dict[str, object]:
    return {
        "snapshot_item_id": assignment.snapshot_item_id,
        "cluster_label": assignment.cluster_label,
        "membership_strength": assignment.membership_strength,
        "membership_digest": assignment.membership_digest,
    }


def _cluster_size_histogram(sizes: Sequence[int]) -> dict[str, int]:
    """Compatibility alias for the neutral partition-metrics helper."""

    return _partition_cluster_size_histogram(sizes)


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


def _json_string_list(text: str) -> list[str]:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


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
    "build_profile_summary",
    "build_sweep_comparison_projection",
    "compute_run_partition_metrics",
    "content_disclosure",
    "derive_presentation_status",
    "derive_sweep_comparison_presentation",
    "enrich_run_for_export",
]
