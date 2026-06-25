# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic MCP response context-governance helpers.

Response context governance uses estimated context units for response-policy
decisions without binding CodeClone to a model-specific token counter. The
estimator is intentionally simple, versioned, and deterministic: canonical
UTF-8 JSON bytes divided by 4.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Final

import orjson

CONTEXT_GOVERNANCE_CONTRACT_VERSION: Final = "1.0"
CONTEXT_GOVERNANCE_DIGEST_VERSION: Final = "1"
CONTEXT_GOVERNANCE_ESTIMATOR: Final = "utf8_bytes_div_4_v1"
DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT: Final = 2200
IMPLEMENTATION_CONTEXT_RESPONSE_CONTEXT_UNIT_LIMIT: Final = 2600
FINISH_RESPONSE_PROJECTION_KIND: Final = "finish_projection_v1"
BLAST_ARTIFACT_PROJECTION_KIND: Final = "blast_artifact_projection_v1"
BLAST_ARTIFACT_RETRIEVAL_RESPONSE_PROJECTION_KIND: Final = (
    "blast_artifact_retrieval_projection_v1"
)
IMPLEMENTATION_CONTEXT_RESPONSE_PROJECTION_KIND: Final = (
    "implementation_context_projection_v1"
)
IMPLEMENTATION_CONTEXT_PAGE_RESPONSE_PROJECTION_KIND: Final = (
    "implementation_context_page_projection_v1"
)
MEMORY_RETRIEVAL_RESPONSE_PROJECTION_KIND: Final = "memory_retrieval_projection_v1"
MEMORY_CONTINUATION_RESPONSE_PROJECTION_KIND: Final = (
    "memory_continuation_projection_v1"
)
PATCH_TRAIL_RETRIEVAL_RESPONSE_PROJECTION_KIND: Final = (
    "patch_trail_retrieval_projection_v1"
)
REVIEW_RECEIPT_RESPONSE_PROJECTION_KIND: Final = "review_receipt_projection_v1"
START_RESPONSE_PROJECTION_KIND: Final = "start_projection_v1"

_OBSERVE_ENFORCEMENT: Final[dict[str, bool]] = {
    "response_budget": False,
    "nested_budget": False,
    "omission": False,
}

_PASSIVE_CAPABILITIES: Final[dict[str, object]] = {
    "typed_receipt_alias": True,
    # Phase 34.4: a durable post-clear receipt lookup now exists
    # (get_review_receipt over the audit trail), so this prerequisite is met.
    "durable_receipt_lookup": True,
    # Phase 34: a durable post-clear patch-trail lookup now exists
    # (get_patch_trail over the audit trail), so this prerequisite is met.
    "durable_patch_trail_lookup": True,
    "immutable_blast_artifact": True,
    "memory_tail_continuation": True,
    "implementation_context_artifact_pages": True,
    "omitted_evidence_continuation": False,
}

_PASSIVE_DRILL_DOWN: Final[dict[str, dict[str, object]]] = {
    "memory_record": {
        "object_lookup": "available",
        "route": "query_engineering_memory(mode='get', record_id=...)",
        "continuation": "available",
        "continuation_route": "get_memory_projection_page(cursor=...)",
        "snapshot_identity": (
            "memory continuation cursor + lane identity digest + request digest"
        ),
    },
    "trajectory": {
        "object_lookup": "available",
        "route": "query_engineering_memory(mode='trajectory_get', record_id=...)",
        "continuation": "available",
        "continuation_route": "get_memory_projection_page(cursor=...)",
        "snapshot_identity": (
            "memory continuation cursor + lane identity digest + request digest"
        ),
    },
    "experience": {
        "object_lookup": "available",
        "route": "query_engineering_memory(mode='experience_get', record_id=...)",
        "continuation": "available",
        "continuation_route": "get_memory_projection_page(cursor=...)",
        "snapshot_identity": (
            "memory continuation cursor + lane identity digest + request digest"
        ),
    },
    "structured_receipt": {
        "object_lookup": "available",
        "route": "get_review_receipt(run_id=..., receipt_digest=...)",
        "continuation": "blocked",
        "current_complete_path": "receipt.receipt",
    },
    "patch_trail": {
        "object_lookup": "available",
        "route": "get_patch_trail(run_id=..., patch_trail_digest=...)",
        "continuation": "blocked",
        "current_complete_path": "patch_trail",
    },
    "blast_artifact": {
        "object_lookup": "available",
        "route": "get_blast_artifact(run_id=..., blast_artifact_id=...)",
        "continuation": "blocked",
        "snapshot_identity": "blast_artifact_id + run_id + projection_digest",
    },
    "implementation_context_facet": {
        "object_lookup": "available",
        "route": (
            "get_implementation_context_page(context_projection_digest=..., facet=...)"
        ),
        "continuation": "available",
        "snapshot_identity": (
            "context_artifact_digest + context_projection_digest "
            "+ facet_identity_digest"
        ),
    },
}

_PASSIVE_ENFORCEMENT_BLOCKED: Final[dict[str, list[str]]] = {
    # durable_receipt_lookup cleared in Phase 34.4 (get_review_receipt);
    # durable_patch_trail_lookup cleared by get_patch_trail; immutable
    # blast-artifact lookup cleared by get_blast_artifact. Memory tails and
    # implementation-context pages have exact page tools, but global response
    # budget and omission still wait for the adopted omission-policy slice.
    "response_budget": [
        "omitted_evidence_continuation",
    ],
    "nested_budget": [],
    "omission": [
        "exact_continuation_for_omitted_tails",
    ],
}


def estimate_response_context_units(payload: object) -> int:
    """Return deterministic estimated context units for an MCP response."""

    byte_count = len(_canonical_context_bytes(payload))
    return (byte_count + 3) // 4


def context_governance_digest(kind: str, payload: object) -> dict[str, str]:
    """Return the canonical response-governance digest for *payload*."""

    normalized_kind = kind.strip()
    if not normalized_kind:
        raise ValueError("digest kind must be non-empty")
    digest = hashlib.sha256(_canonical_context_bytes(payload)).hexdigest()
    return {
        "kind": normalized_kind,
        "algorithm": "sha256",
        "digest_version": CONTEXT_GOVERNANCE_DIGEST_VERSION,
        "value": digest,
    }


def passive_context_capabilities() -> dict[str, object]:
    """Return response-governance capabilities advertised in observe mode."""

    return dict(_PASSIVE_CAPABILITIES)


def passive_drill_down_reachability() -> dict[str, dict[str, object]]:
    """Return exact drill-down routes and blocked continuations for observe mode."""

    return {key: dict(value) for key, value in _PASSIVE_DRILL_DOWN.items()}


def passive_enforcement_blockers() -> dict[str, list[str]]:
    """Return missing exact retrieval capabilities that block enforcement."""

    return {key: list(value) for key, value in _PASSIVE_ENFORCEMENT_BLOCKED.items()}


def attach_passive_context_governance(
    payload: Mapping[str, object],
    *,
    limit: int = DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
    response: Mapping[str, object] | None = None,
    projection_kind: str | None = None,
) -> dict[str, object]:
    """Attach a passive ``context_governance`` envelope without omitting data."""

    result = dict(payload)
    response_context = _response_context_metadata(
        result, response=response, projection_kind=projection_kind
    )
    context_governance: dict[str, object] = {
        "contract_version": CONTEXT_GOVERNANCE_CONTRACT_VERSION,
        "estimator": CONTEXT_GOVERNANCE_ESTIMATOR,
        "limit": limit,
        "estimated": 0,
        "truncated": False,
        "mandatory_overflow": False,
        "mode": "observe",
        "enforcement": dict(_OBSERVE_ENFORCEMENT),
        "enforcement_blocked": passive_enforcement_blockers(),
        "capabilities": passive_context_capabilities(),
        "drill_down": passive_drill_down_reachability(),
    }
    context_governance.update(response_context)
    result["context_governance"] = context_governance
    governance = result["context_governance"]
    assert isinstance(governance, dict)
    governance["estimated"] = estimate_response_context_units(result)
    return result


def attach_finish_context_governance(
    payload: Mapping[str, object],
    *,
    limit: int = DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
) -> dict[str, object]:
    """Attach whole-response governance metadata for finish responses."""

    return attach_passive_context_governance(
        payload,
        limit=limit,
        projection_kind=FINISH_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "finish_controlled_change",
            "budget_scope": "whole_response",
            "evidence_policy": "observe_only_no_omission",
            # 34.3 dedup: finish inlines only the human-complete markdown content
            # plus identity; the duplicate typed receipt is omitted and reachable
            # via get_review_receipt (durable). Full response-budget enforcement
            # stays for the later 34.5 slice.
            "receipt_content": "markdown_inlined_typed_via_lookup",
        },
    )


def attach_start_context_governance(
    payload: Mapping[str, object],
    *,
    limit: int = DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
) -> dict[str, object]:
    """Attach whole-response governance metadata for start responses."""

    return attach_passive_context_governance(
        payload,
        limit=limit,
        projection_kind=START_RESPONSE_PROJECTION_KIND,
        response={
            "tool": "start_controlled_change",
            "budget_scope": "whole_response",
            "evidence_policy": "observe_only_no_omission",
            "blast_radius_content": "summary_with_immutable_artifact_lookup",
        },
    )


def _response_context_metadata(
    payload: Mapping[str, object],
    *,
    response: Mapping[str, object] | None,
    projection_kind: str | None,
) -> dict[str, object]:
    if response is None:
        return {}
    response_payload = dict(response)
    if projection_kind is not None:
        response_payload["projection_digest"] = context_governance_digest(
            projection_kind, payload
        )
    return {"response": response_payload}


def _canonical_context_bytes(payload: object) -> bytes:
    return orjson.dumps(
        _normalize_context_estimates(payload), option=orjson.OPT_SORT_KEYS
    )


def _normalize_context_estimates(value: object) -> object:
    if isinstance(value, Mapping):
        is_context_envelope = (
            value.get("contract_version") == CONTEXT_GOVERNANCE_CONTRACT_VERSION
            and value.get("estimator") == CONTEXT_GOVERNANCE_ESTIMATOR
        )
        return {
            key: (
                0
                if is_context_envelope and key == "estimated"
                else _normalize_context_estimates(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_context_estimates(item) for item in value]
    return value


__all__ = [
    "CONTEXT_GOVERNANCE_CONTRACT_VERSION",
    "CONTEXT_GOVERNANCE_DIGEST_VERSION",
    "CONTEXT_GOVERNANCE_ESTIMATOR",
    "DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT",
    "FINISH_RESPONSE_PROJECTION_KIND",
    "IMPLEMENTATION_CONTEXT_RESPONSE_CONTEXT_UNIT_LIMIT",
    "IMPLEMENTATION_CONTEXT_RESPONSE_PROJECTION_KIND",
    "MEMORY_RETRIEVAL_RESPONSE_PROJECTION_KIND",
    "PATCH_TRAIL_RETRIEVAL_RESPONSE_PROJECTION_KIND",
    "REVIEW_RECEIPT_RESPONSE_PROJECTION_KIND",
    "START_RESPONSE_PROJECTION_KIND",
    "attach_finish_context_governance",
    "attach_passive_context_governance",
    "attach_start_context_governance",
    "context_governance_digest",
    "estimate_response_context_units",
    "passive_context_capabilities",
    "passive_drill_down_reachability",
    "passive_enforcement_blockers",
]
