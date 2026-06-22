# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic MCP response context-governance helpers.

Phase 34A uses estimated context units for response-policy decisions without
binding CodeClone to a model-specific token counter. The estimator is
intentionally simple, versioned, and deterministic: canonical UTF-8 JSON bytes
divided by 4.
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

_OBSERVE_ENFORCEMENT: Final[dict[str, bool]] = {
    "response_budget": False,
    "nested_budget": False,
    "omission": False,
}

_PASSIVE_CAPABILITIES: Final[dict[str, object]] = {
    "typed_receipt_alias": True,
    "durable_receipt_lookup": False,
    "durable_patch_trail_lookup": False,
    "immutable_blast_artifact": False,
    "omitted_evidence_continuation": False,
}


def estimate_response_context_units(payload: object) -> int:
    """Return deterministic estimated context units for an MCP response."""

    byte_count = len(_canonical_context_bytes(payload))
    return (byte_count + 3) // 4


def context_governance_digest(kind: str, payload: object) -> dict[str, str]:
    """Return the canonical Phase 34A digest representation for *payload*."""

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


def attach_passive_context_governance(
    payload: Mapping[str, object],
    *,
    limit: int = DEFAULT_RESPONSE_CONTEXT_UNIT_LIMIT,
) -> dict[str, object]:
    """Attach a passive ``context_governance`` envelope without omitting data."""

    result = dict(payload)
    result["context_governance"] = {
        "contract_version": CONTEXT_GOVERNANCE_CONTRACT_VERSION,
        "estimator": CONTEXT_GOVERNANCE_ESTIMATOR,
        "limit": limit,
        "estimated": 0,
        "truncated": False,
        "mandatory_overflow": False,
        "mode": "observe",
        "enforcement": dict(_OBSERVE_ENFORCEMENT),
        "capabilities": passive_context_capabilities(),
    }
    governance = result["context_governance"]
    assert isinstance(governance, dict)
    governance["estimated"] = estimate_response_context_units(result)
    return result


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
    "attach_passive_context_governance",
    "context_governance_digest",
    "estimate_response_context_units",
    "passive_context_capabilities",
]
