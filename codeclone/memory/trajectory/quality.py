# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal, overload

from ...contracts import TRAJECTORY_QUALITY_SCORE_VERSION
from .anomalies import detect_trajectory_anomalies
from .models import Trajectory, TrajectoryOutcome, TrajectoryQualityTier
from .patch_trail import PatchTrail, patch_trail_from_mapping
from .projector import trajectory_digest_for

_ANOMALY_ERROR_PENALTY = 12
_ANOMALY_WARN_PENALTY = 5
_INCIDENT_PENALTY_PER = 10

_OUTCOME_SCORES: dict[TrajectoryOutcome, int] = {
    "accepted": 100,
    "accepted_with_external_changes": 85,
    "partial": 55,
    "abandoned": 40,
    "blocked": 30,
    "violated": 20,
}

_SCOPE_SCORES: dict[str, int] = {
    "clean": 100,
    "expanded": 85,
    "partial": 70,
    "violated": 0,
}

_VERIFICATION_FROM_TRAIL: dict[str, int] = {
    "accepted": 100,
    "accepted_with_external_changes": 85,
    "unverified": 50,
    "violated": 0,
    "blocked": 0,
    "not_reached": 40,
}

_VERIFICATION_FROM_TIER: dict[TrajectoryQualityTier, int] = {
    "verified": 100,
    "corrected": 90,
    "routine": 85,
    "partial": 60,
    "incident": 45,
}


@dataclass(frozen=True, slots=True)
class TrajectoryQualityComponent:
    component_id: str
    score: int
    pass_gate: bool
    label: str


@dataclass(frozen=True, slots=True)
class TrajectoryQualityContract:
    quality_score: int
    complexity_score: int
    scope_accuracy: int
    duration_seconds: int
    anomaly_count: int
    score_version: str
    components: tuple[TrajectoryQualityComponent, ...]


def compute_trajectory_duration_seconds(trajectory: Trajectory) -> int:
    """Return non-negative whole seconds between trajectory start and finish."""
    started = _parse_utc_timestamp(trajectory.started_at_utc)
    finished = _parse_utc_timestamp(trajectory.finished_at_utc)
    if started is None or finished is None:
        return 0
    delta = finished - started
    return max(0, int(delta.total_seconds()))


_COMPLEXITY_DECLARED_CAP = 40
_COMPLEXITY_EVENT_CAP = 30
_COMPLEXITY_STEP_CAP = 20
_QUALITY_FORMULA = (
    "quality_score = min(outcome, verification, scope, incidents, anomalies, receipt)"
)
_COMPLEXITY_FORMULA = "complexity_score = min(100, declared*2 + events*3 + steps*2)"


def compute_trajectory_complexity_score(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None = None,
) -> int:
    """Return a deterministic 0-100 complexity score (separate from quality)."""
    score, *_rest = _complexity_factors(
        trajectory,
        patch_trail_payload=patch_trail_payload,
    )
    return score


def _complexity_band_label(score: int) -> tuple[str, str]:
    if score >= 70:
        return "high", "High"
    if score >= 35:
        return "moderate", "Moderate"
    return "low", "Low"


@overload
def _complexity_factors(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None = None,
    include_band: Literal[False] = False,
) -> tuple[int, int, int, int, int, int, int]: ...


@overload
def _complexity_factors(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None,
    include_band: Literal[True],
) -> tuple[int, int, int, int, int, int, int, str, str]: ...


def _complexity_factors(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None = None,
    include_band: bool = False,
) -> (
    tuple[int, int, int, int, int, int, int]
    | tuple[
        int,
        int,
        int,
        int,
        int,
        int,
        int,
        str,
        str,
    ]
):
    trail = _trail_from_payload(patch_trail_payload)
    declared = trail.counts().get("declared", 0) if trail is not None else 0
    declared_raw = int(declared)
    events_raw = trajectory.event_count
    steps_raw = trajectory.step_count
    declared_part = min(_COMPLEXITY_DECLARED_CAP, declared_raw * 2)
    events_part = min(_COMPLEXITY_EVENT_CAP, events_raw * 3)
    steps_part = min(_COMPLEXITY_STEP_CAP, steps_raw * 2)
    score = min(100, declared_part + events_part + steps_part)
    base = (
        score,
        declared_raw,
        events_raw,
        steps_raw,
        declared_part,
        events_part,
        steps_part,
    )
    if include_band:
        band, band_label = _complexity_band_label(score)
        return (*base, band, band_label)
    return base


def compute_trajectory_quality_contract(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None = None,
) -> TrajectoryQualityContract:
    """Return contract-derived quality metrics and an explainable breakdown."""
    trail = _trail_from_payload(patch_trail_payload)
    label_set = {str(label) for label in trajectory.labels}
    anomalies = detect_trajectory_anomalies(
        trajectory,
        patch_trail_payload=patch_trail_payload,
    )
    anomaly_count = len(anomalies)

    outcome_score = _OUTCOME_SCORES.get(trajectory.outcome, 50)
    outcome_pass = trajectory.outcome == "accepted" and outcome_score == 100

    if trail is not None and trail.verification_status:
        verification_score = _VERIFICATION_FROM_TRAIL.get(
            trail.verification_status,
            70,
        )
    else:
        verification_score = _VERIFICATION_FROM_TIER.get(trajectory.quality_tier, 70)
    verification_pass = (
        trajectory.quality_tier == "verified" and verification_score == 100
    )

    scope_accuracy = _scope_accuracy(trajectory, trail=trail, label_set=label_set)
    scope_pass = scope_accuracy == 100

    if trajectory.incident_count == 0:
        incident_score = 100
        incident_pass = True
    else:
        incident_score = max(
            0,
            100 - trajectory.incident_count * _INCIDENT_PENALTY_PER,
        )
        incident_pass = False

    anomaly_score = 100
    for anomaly in anomalies:
        anomaly_score -= (
            _ANOMALY_ERROR_PENALTY
            if anomaly.severity == "error"
            else _ANOMALY_WARN_PENALTY
        )
    anomaly_score = max(0, anomaly_score)
    anomaly_pass = anomaly_count == 0

    if "change_control_workflow" in label_set:
        if "receipt_issued" in label_set:
            receipt_score = 100
            receipt_pass = True
        else:
            receipt_score = 85
            receipt_pass = False
    else:
        receipt_score = 100
        receipt_pass = True

    quality_score = min(
        outcome_score,
        verification_score,
        scope_accuracy,
        incident_score,
        anomaly_score,
        receipt_score,
    )
    components = (
        TrajectoryQualityComponent(
            "outcome",
            outcome_score,
            outcome_pass,
            f"Outcome {trajectory.outcome}",
        ),
        TrajectoryQualityComponent(
            "verification",
            verification_score,
            verification_pass,
            f"Verification tier {trajectory.quality_tier}",
        ),
        TrajectoryQualityComponent(
            "scope",
            scope_accuracy,
            scope_pass,
            _scope_label(trail, label_set),
        ),
        TrajectoryQualityComponent(
            "incidents",
            incident_score,
            incident_pass,
            (
                "No audit incidents"
                if incident_pass
                else f"{trajectory.incident_count} audit incident(s)"
            ),
        ),
        TrajectoryQualityComponent(
            "anomalies",
            anomaly_score,
            anomaly_pass,
            "No structural anomalies"
            if anomaly_pass
            else f"{anomaly_count} anomaly(ies)",
        ),
        TrajectoryQualityComponent(
            "receipt",
            receipt_score,
            receipt_pass,
            "Receipt issued"
            if receipt_pass
            else "Receipt missing for change-control cycle",
        ),
    )
    return TrajectoryQualityContract(
        quality_score=max(0, min(100, quality_score)),
        complexity_score=compute_trajectory_complexity_score(
            trajectory,
            patch_trail_payload=patch_trail_payload,
        ),
        scope_accuracy=scope_accuracy,
        duration_seconds=compute_trajectory_duration_seconds(trajectory),
        anomaly_count=anomaly_count,
        score_version=TRAJECTORY_QUALITY_SCORE_VERSION,
        components=components,
    )


def compute_trajectory_quality_score(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None = None,
) -> int:
    """Return a deterministic 0-100 trajectory quality score."""
    return compute_trajectory_quality_contract(
        trajectory,
        patch_trail_payload=patch_trail_payload,
    ).quality_score


def serialize_trajectory_quality_contract(
    contract: TrajectoryQualityContract,
    *,
    trajectory: Trajectory | None = None,
    patch_trail_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    limiting_ids = _limiting_component_ids(contract)
    calculation_lines = [
        {
            "id": component.component_id,
            "label": component.label,
            "score": component.score,
            "pass": component.pass_gate,
            "limits_quality": component.component_id in limiting_ids,
        }
        for component in contract.components
    ]
    return {
        "score_version": contract.score_version,
        "quality_score": contract.quality_score,
        "complexity_score": contract.complexity_score,
        "scope_accuracy": contract.scope_accuracy,
        "duration_seconds": contract.duration_seconds,
        "anomaly_count": contract.anomaly_count,
        "components": [
            {
                "id": component.component_id,
                "score": component.score,
                "pass": component.pass_gate,
                "label": component.label,
            }
            for component in contract.components
        ],
        "calculation": {
            "method": "contract_min",
            "formula": _QUALITY_FORMULA,
            "quality_score": contract.quality_score,
            "limiting_component_ids": list(limiting_ids),
            "lines": calculation_lines,
        },
        "complexity_calculation": _serialize_complexity_calculation(
            contract.complexity_score,
            trajectory=trajectory,
            patch_trail_payload=patch_trail_payload,
        ),
    }


def _serialize_complexity_calculation(
    complexity_score: int,
    *,
    trajectory: Trajectory | None,
    patch_trail_payload: Mapping[str, object] | None,
) -> dict[str, object]:
    if trajectory is None:
        return {
            "method": "weighted_sum",
            "formula": _COMPLEXITY_FORMULA,
            "complexity_score": complexity_score,
            "band": _complexity_band_label(complexity_score)[0],
            "band_label": _complexity_band_label(complexity_score)[1],
            "hint": "Higher = larger change surface (not a pass/fail grade).",
            "lines": [],
        }
    (
        score,
        declared_raw,
        events_raw,
        steps_raw,
        declared_part,
        events_part,
        steps_part,
        band,
        band_label,
    ) = _complexity_factors(
        trajectory,
        patch_trail_payload=patch_trail_payload,
        include_band=True,
    )
    del score
    return {
        "method": "weighted_sum",
        "formula": _COMPLEXITY_FORMULA,
        "complexity_score": complexity_score,
        "band": band,
        "band_label": band_label,
        "hint": "Higher = larger change surface (not a pass/fail grade).",
        "lines": [
            {
                "id": "declared_files",
                "label": "Declared files",
                "raw": declared_raw,
                "unit": "files",
                "contribution": declared_part,
                "cap": _COMPLEXITY_DECLARED_CAP,
            },
            {
                "id": "events",
                "label": "Audit events",
                "raw": events_raw,
                "unit": "events",
                "contribution": events_part,
                "cap": _COMPLEXITY_EVENT_CAP,
            },
            {
                "id": "steps",
                "label": "Trajectory steps",
                "raw": steps_raw,
                "unit": "steps",
                "contribution": steps_part,
                "cap": _COMPLEXITY_STEP_CAP,
            },
        ],
    }


def _limiting_component_ids(contract: TrajectoryQualityContract) -> tuple[str, ...]:
    minimum = contract.quality_score
    return tuple(
        component.component_id
        for component in contract.components
        if component.score == minimum
    )


def apply_trajectory_quality_score(
    trajectory: Trajectory,
    *,
    patch_trail_payload: Mapping[str, object] | None = None,
    patch_trail_digest: str | None = None,
) -> Trajectory:
    """Attach quality_score and refresh trajectory_digest for storage."""
    contract = compute_trajectory_quality_contract(
        trajectory,
        patch_trail_payload=patch_trail_payload,
    )
    trajectory_digest = trajectory_digest_for(
        trajectory,
        quality_score=contract.quality_score,
        patch_trail_digest=patch_trail_digest,
    )
    return replace(
        trajectory,
        quality_score=contract.quality_score,
        trajectory_digest=trajectory_digest,
    )


def _scope_accuracy(
    trajectory: Trajectory,
    *,
    trail: PatchTrail | None,
    label_set: set[str],
) -> int:
    del trajectory
    if trail is not None and trail.scope_check_status:
        return _SCOPE_SCORES.get(trail.scope_check_status, 70)
    if "scope_clean" in label_set:
        return 100
    if "scope_expanded" in label_set:
        return 85
    return 70


def _scope_label(trail: PatchTrail | None, label_set: set[str]) -> str:
    if trail is not None and trail.scope_check_status:
        return f"Scope {trail.scope_check_status}"
    if "scope_clean" in label_set:
        return "Scope clean"
    if "scope_expanded" in label_set:
        return "Scope expanded"
    return "Scope partial"


def _trail_from_payload(
    patch_trail_payload: Mapping[str, object] | None,
) -> PatchTrail | None:
    if patch_trail_payload is None:
        return None
    return patch_trail_from_mapping(patch_trail_payload)


def _parse_utc_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "TRAJECTORY_QUALITY_SCORE_VERSION",
    "TrajectoryQualityComponent",
    "TrajectoryQualityContract",
    "apply_trajectory_quality_score",
    "compute_trajectory_complexity_score",
    "compute_trajectory_duration_seconds",
    "compute_trajectory_quality_contract",
    "compute_trajectory_quality_score",
    "serialize_trajectory_quality_contract",
]
