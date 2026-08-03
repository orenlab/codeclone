# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical report-v3 digest hierarchy and verification owner."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256

from ...cache.integrity import canonical_json_bytes
from ...contracts import (
    GATE_LANE_MATRIX_VERSION,
    HEALTH_INPUT_MANIFEST_VERSION,
    REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN,
    REPORT_COMPARISON_DIGEST_DOMAIN,
    REPORT_ENVELOPE_DIGEST_DOMAIN,
    REPORT_EVALUATION_DIGEST_DOMAIN,
)
from ...models import (
    EvaluationContract,
    ObservationLaneName,
    ReportDigest,
    ReportDigestKind,
)
from ...utils.coerce import as_mapping as _as_mapping
from ..gates.evaluator import (
    HEALTH_INPUT_LANES,
    GateResult,
    MetricGateConfig,
    active_gate_lane_requirements,
)

_DIGEST_VERSION = "1"


def _digest_wire(value: ReportDigest) -> dict[str, object]:
    return {
        "kind": value.kind,
        "algorithm": value.algorithm,
        "digest_version": value.digest_version,
        "value": value.value,
    }


def _digest(
    *,
    domain: str,
    kind: ReportDigestKind,
    payload: object,
) -> ReportDigest:
    digest = sha256()
    digest.update(domain.encode("utf-8"))
    digest.update(canonical_json_bytes(payload))
    return ReportDigest(
        kind=kind,
        algorithm="sha256",
        digest_version="1",
        value=digest.hexdigest(),
    )


def _observation_wire(value: str) -> dict[str, object]:
    return {
        "kind": "source_observations",
        "algorithm": "sha256",
        "digest_version": _DIGEST_VERSION,
        "value": value,
    }


def build_evaluation_contract(
    config: MetricGateConfig,
    *,
    enabled_lanes: tuple[ObservationLaneName, ...] = (),
) -> EvaluationContract:
    """Build the report-owned evaluation identity from normalized gate policy."""

    thresholds_digest = sha256(canonical_json_bytes(asdict(config))).hexdigest()
    return EvaluationContract(
        health_algorithm_revision="1",
        gate_algorithm_revision="1",
        gate_thresholds_digest=thresholds_digest,
        gate_lane_matrix_version=GATE_LANE_MATRIX_VERSION,
        health_input_manifest_version=HEALTH_INPUT_MANIFEST_VERSION,
        health_input_lanes=tuple(
            lane for lane in HEALTH_INPUT_LANES if lane in frozenset(enabled_lanes)
        ),
        active_gate_lane_requirements=active_gate_lane_requirements(
            config=config,
            enabled_lanes=enabled_lanes,
        ),
    )


def build_evaluation_payload(
    *,
    contract: EvaluationContract,
    config: MetricGateConfig,
    result: GateResult,
) -> dict[str, object]:
    """Project one typed evaluation object without re-evaluating it."""

    return {
        "contract": asdict(contract),
        "request": asdict(config),
        "outcome": {
            "exit_code": result.exit_code,
            "reasons": list(result.reasons),
            "required_lanes": list(result.required_lanes),
            "unavailable_lanes": list(result.unavailable_lanes),
        },
    }


def _comparison_digest_input(baseline: Mapping[str, object]) -> dict[str, object]:
    return {
        "state": baseline.get("state"),
        "baseline_scope_id": baseline.get("baseline_scope_id"),
        "root_digest_or_null": baseline.get("root_digest_or_null"),
        "sorted_lane_trust": baseline.get("sorted_lane_trust"),
        "sorted_novelty_facts": baseline.get("sorted_novelty_facts"),
    }


def _build_integrity_payload(
    *,
    report_schema_version: str,
    observation_digest: str,
    source_facts: Mapping[str, object],
    baseline: Mapping[str, object],
    evaluation: Mapping[str, object],
) -> dict[str, object]:
    observation = _observation_wire(observation_digest)
    analysis_facts = _digest(
        domain=REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN,
        kind="analysis_facts",
        payload={
            "observation_digest": observation,
            "report_schema_version": report_schema_version,
            "source_facts": source_facts,
        },
    )
    comparison = _digest(
        domain=REPORT_COMPARISON_DIGEST_DOMAIN,
        kind="comparison",
        payload={
            "analysis_facts_digest": _digest_wire(analysis_facts),
            "baseline": _comparison_digest_input(baseline),
        },
    )
    evaluation_digest = _digest(
        domain=REPORT_EVALUATION_DIGEST_DOMAIN,
        kind="evaluation",
        payload={
            "comparison_digest": _digest_wire(comparison),
            "evaluation": evaluation,
        },
    )
    return {
        "canonicalization": {
            "version": "3",
            "serializer": "orjson.OPT_SORT_KEYS",
            "envelope_null_sentinel": "integrity.digests.envelope.value",
        },
        "digests": {
            "observation": observation,
            "analysis_facts": _digest_wire(analysis_facts),
            "comparison": _digest_wire(comparison),
            "evaluation": _digest_wire(evaluation_digest),
            "envelope": {
                "kind": "report_envelope",
                "algorithm": "sha256",
                "digest_version": _DIGEST_VERSION,
                "value": None,
            },
        },
    }


def _document_with_envelope_sentinel(
    document: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(document)
    integrity = dict(_as_mapping(document.get("integrity")))
    digests = dict(_as_mapping(integrity.get("digests")))
    envelope = dict(_as_mapping(digests.get("envelope")))
    envelope["value"] = None
    digests["envelope"] = envelope
    integrity["digests"] = digests
    payload["integrity"] = integrity
    return payload


def finalize_envelope_digest(document: dict[str, object]) -> dict[str, object]:
    """Seal the completed report with only its own value replaced by null."""

    envelope = _digest(
        domain=REPORT_ENVELOPE_DIGEST_DOMAIN,
        kind="report_envelope",
        payload=_document_with_envelope_sentinel(document),
    )
    integrity = dict(_as_mapping(document.get("integrity")))
    digests = dict(_as_mapping(integrity.get("digests")))
    digests["envelope"] = _digest_wire(envelope)
    integrity["digests"] = digests
    return {**document, "integrity": integrity}


def _digest_value(
    digests: Mapping[str, object],
    name: str,
) -> str | None:
    value = _as_mapping(digests.get(name)).get("value")
    return value if isinstance(value, str) else None


def verify_report_integrity(document: Mapping[str, object]) -> str | None:
    """Recompute the four report-owned tiers and authenticate the envelope."""

    integrity = _as_mapping(document.get("integrity"))
    digests = _as_mapping(integrity.get("digests"))
    required = ("observation", "analysis_facts", "comparison", "evaluation", "envelope")
    if tuple(sorted(digests)) != tuple(sorted(required)):
        return "report digest set must contain exactly five named tiers"
    observation_value = _digest_value(digests, "observation")
    if observation_value is None:
        return "report observation digest is missing"
    report_schema_version = document.get("report_schema_version")
    if not isinstance(report_schema_version, str):
        return "report schema version is missing"
    source_facts = _as_mapping(document.get("source_facts"))
    baseline = _as_mapping(document.get("baseline"))
    evaluation = _as_mapping(document.get("evaluation"))
    expected = _build_integrity_payload(
        report_schema_version=report_schema_version,
        observation_digest=observation_value,
        source_facts=source_facts,
        baseline=baseline,
        evaluation=evaluation,
    )
    expected_digests = _as_mapping(expected.get("digests"))
    for name in ("analysis_facts", "comparison", "evaluation"):
        actual_value = _digest_value(digests, name)
        expected_value = _digest_value(expected_digests, name)
        if (
            actual_value is None
            or expected_value is None
            or not hmac.compare_digest(actual_value, expected_value)
        ):
            return f"report {name} digest mismatch"
    expected_envelope = _digest(
        domain=REPORT_ENVELOPE_DIGEST_DOMAIN,
        kind="report_envelope",
        payload=_document_with_envelope_sentinel(document),
    )
    actual_envelope = _digest_value(digests, "envelope")
    if actual_envelope is None or not hmac.compare_digest(
        actual_envelope,
        expected_envelope.value,
    ):
        return "report envelope digest mismatch"
    return None


__all__ = [
    "_build_integrity_payload",
    "build_evaluation_contract",
    "build_evaluation_payload",
    "finalize_envelope_digest",
    "verify_report_integrity",
]
