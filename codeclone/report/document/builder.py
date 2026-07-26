# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict
from typing import TYPE_CHECKING

from ...contracts import REPORT_SCHEMA_VERSION
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence

if TYPE_CHECKING:
    from ...models import (
        BaselineContainerV3,
        GroupMapLike,
        ObservationBundle,
        StructuralFindingGroup,
        Suggestion,
        SuppressedCloneGroup,
        TrustVector,
    )
    from ..gates.evaluator import GateResult, MetricGateConfig

from ._common import _collect_report_file_list
from .derived import (
    _build_derived_module_map,
    _build_derived_overview,
    _build_derived_review_queue,
    _build_derived_suggestions,
)
from .findings import _build_findings_payload
from .integrity import (
    _build_integrity_payload,
    build_evaluation_contract,
    build_evaluation_payload,
    finalize_envelope_digest,
)
from .inventory import (
    _build_inventory_payload,
    _build_meta_payload,
)
from .metrics import _build_metrics_payload

_ALL_OBSERVATION_LANES = (
    "adoption_counts",
    "api_surface",
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "module_identity",
    "risk_observations",
    "semantic_authority",
)


def build_report_body(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    meta: Mapping[str, object] | None = None,
    inventory: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    baseline_trust: TrustVector | None = None,
) -> dict[str, object]:
    """Build canonical report facts before evaluation and integrity sealing."""

    scan_root = str(_as_mapping(meta).get("scan_root", ""))
    meta_payload = _build_meta_payload(meta, scan_root=scan_root)
    design_thresholds = _as_mapping(
        _as_mapping(meta_payload.get("analysis_thresholds")).get("design_findings")
    )
    metrics_payload = _build_metrics_payload(metrics, scan_root=scan_root)
    file_list = _collect_report_file_list(
        inventory=inventory,
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        suppressed_clone_groups=suppressed_clone_groups,
        metrics=metrics,
        structural_findings=structural_findings,
    )
    inventory_payload = _build_inventory_payload(
        inventory=inventory,
        file_list=file_list,
        metrics_payload=metrics_payload,
        scan_root=scan_root,
    )
    findings_payload = _build_findings_payload(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_facts=block_facts or {},
        structural_findings=structural_findings,
        metrics_payload=metrics_payload,
        function_lane_trusted=_lane_is_trusted(
            baseline_trust,
            "clones.functions",
        ),
        block_lane_trusted=_lane_is_trusted(
            baseline_trust,
            "clones.blocks",
        ),
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        suppressed_clone_groups=suppressed_clone_groups,
        design_thresholds=design_thresholds,
        scan_root=scan_root,
    )
    overview_payload, hotlists_payload = _build_derived_overview(
        findings=findings_payload,
        metrics_payload=metrics_payload,
    )
    suggestions_payload = _build_derived_suggestions(suggestions)
    structural_groups = _as_sequence(
        _as_mapping(_as_mapping(findings_payload.get("groups")).get("structural")).get(
            "groups"
        )
    )
    overview_payload["presentation_counts"] = {
        "structural": len(structural_groups),
        "structural_kinds": len(
            {str(_as_mapping(group).get("category", "")) for group in structural_groups}
        ),
        "suggestions": len(suggestions_payload),
        "suggestions_by_family": {
            family: sum(
                1
                for suggestion in suggestions_payload
                if str(suggestion.get("finding_family", "")) == family
            )
            for family in ("clones", "structural", "metrics")
        },
    }
    return {
        "meta": meta_payload,
        "inventory": inventory_payload,
        "findings": findings_payload,
        "metrics": metrics_payload,
        "derived": {
            "suggestions": suggestions_payload,
            "overview": overview_payload,
            "hotlists": hotlists_payload,
            "module_map": _build_derived_module_map(metrics_payload),
            "review_queue": _build_derived_review_queue(
                findings_payload,
                suggestions,
            ),
        },
    }


def _lane_is_trusted(trust: TrustVector | None, lane: str) -> bool:
    return bool(
        trust is not None
        and trust.root_verified
        and any(item.name == lane and item.status == "trusted" for item in trust.lanes)
    )


def _source_facts(
    bundle: ObservationBundle,
    *,
    analysis_contract: Mapping[str, object],
) -> dict[str, object]:
    return {
        "analysis_contract": dict(analysis_contract),
        "analysis_scope": [asdict(item) for item in bundle.analysis_scope],
        "module_identity_manifest": asdict(bundle.manifest),
        "module_registry": asdict(bundle.registry),
        "observation_contract": asdict(bundle.contract),
        "semantic": None if bundle.semantic is None else asdict(bundle.semantic),
        "source_fact_families": asdict(bundle.structural),
    }


def _baseline_projection(
    *,
    bundle: ObservationBundle,
    container: BaselineContainerV3 | None,
    trust: TrustVector | None,
    new_function_group_keys: Collection[str] | None,
    new_block_group_keys: Collection[str] | None,
) -> dict[str, object]:
    trust_by_lane = {} if trust is None else {item.name: item for item in trust.lanes}
    enabled_lanes = tuple(sorted(bundle.contract.enabled_lanes))
    trusted_lanes = [
        {
            "name": name,
            "status": (
                trust_by_lane[name].status
                if name in trust_by_lane and trust is not None and trust.root_verified
                else "unavailable"
            ),
            "reason": (
                trust_by_lane[name].reason
                if name in trust_by_lane and trust is not None and trust.root_verified
                else "baseline_missing"
                if container is None
                else "root_unverified"
            ),
        }
        for name in enabled_lanes
    ]
    all_lanes_trusted = bool(
        trust is not None
        and trust.root_verified
        and all(item.status == "trusted" for item in trust.lanes)
    )
    state = (
        "missing"
        if container is None
        else "trusted"
        if all_lanes_trusted
        else "untrusted"
    )
    new_functions = frozenset(new_function_group_keys or ())
    new_blocks = frozenset(new_block_group_keys or ())
    novelty_facts = [
        {
            "lane": lane,
            "identity": identity,
            "novelty": (
                "unavailable"
                if not _lane_is_trusted(trust, lane)
                else "new"
                if identity in new_keys
                else "known"
            ),
        }
        for lane, identities, new_keys in (
            (
                "clones.blocks",
                bundle.structural.block_clone_keys,
                new_blocks,
            ),
            (
                "clones.functions",
                bundle.structural.function_clone_keys,
                new_functions,
            ),
        )
        for identity in identities
    ]
    enabled = frozenset(enabled_lanes)
    return {
        "state": state,
        "baseline_scope_id": (
            None if container is None else str(container.baseline_scope_id)
        ),
        "root_digest_or_null": (
            None if container is None else container.meta.root_digest.value
        ),
        "sorted_lane_trust": [dict(item) for item in trusted_lanes],
        "sorted_novelty_facts": novelty_facts,
        "disabled_capabilities": [
            name for name in _ALL_OBSERVATION_LANES if name not in enabled
        ],
    }


def finalize_report_document(
    *,
    body: Mapping[str, object],
    observation_bundle: ObservationBundle,
    baseline_container: BaselineContainerV3 | None,
    baseline_trust: TrustVector | None,
    gate_config: MetricGateConfig,
    gate_result: GateResult,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
) -> dict[str, object]:
    """Attach contracts, comparison/evaluation facts, then seal the envelope."""

    evaluation_contract = build_evaluation_contract(
        gate_config,
        enabled_lanes=observation_bundle.contract.enabled_lanes,
    )
    evaluation = build_evaluation_payload(
        contract=evaluation_contract,
        config=gate_config,
        result=gate_result,
    )
    report_meta = _as_mapping(body.get("meta"))
    source_facts = _source_facts(
        observation_bundle,
        analysis_contract=_as_mapping(report_meta.get("analysis_thresholds")),
    )
    baseline = _baseline_projection(
        bundle=observation_bundle,
        container=baseline_container,
        trust=baseline_trust,
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
    )
    document: dict[str, object] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "meta": body["meta"],
        "contracts": {
            "observation": asdict(observation_bundle.contract),
            "evaluation": asdict(evaluation_contract),
        },
        "source_facts": source_facts,
        "baseline": baseline,
        "evaluation": evaluation,
        "inventory": body["inventory"],
        "findings": body["findings"],
        "metrics": body["metrics"],
        "derived": body["derived"],
        "integrity": _build_integrity_payload(
            report_schema_version=REPORT_SCHEMA_VERSION,
            observation_digest=observation_bundle.observation_digest.value,
            source_facts=source_facts,
            baseline=baseline,
            evaluation=evaluation,
        ),
    }
    return finalize_envelope_digest(document)


def build_report_document(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    observation_bundle: ObservationBundle,
    baseline_container: BaselineContainerV3 | None,
    baseline_trust: TrustVector | None,
    gate_config: MetricGateConfig,
    gate_result: GateResult,
    meta: Mapping[str, object] | None = None,
    inventory: Mapping[str, object] | None = None,
    block_facts: Mapping[str, Mapping[str, str]] | None = None,
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    new_segment_group_keys: Collection[str] | None = None,
    suppressed_clone_groups: Sequence[SuppressedCloneGroup] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
) -> dict[str, object]:
    body = build_report_body(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        meta=meta,
        inventory=inventory,
        block_facts=block_facts,
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        new_segment_group_keys=new_segment_group_keys,
        suppressed_clone_groups=suppressed_clone_groups,
        metrics=metrics,
        suggestions=suggestions,
        structural_findings=structural_findings,
        baseline_trust=baseline_trust,
    )
    return finalize_report_document(
        body=body,
        observation_bundle=observation_bundle,
        baseline_container=baseline_container,
        baseline_trust=baseline_trust,
        gate_config=gate_config,
        gate_result=gate_result,
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
    )


__all__ = [
    "build_report_body",
    "build_report_document",
    "finalize_report_document",
]
