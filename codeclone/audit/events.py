# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AuditSeverity = Literal["info", "warn", "error"]
AuditPayloadMode = Literal["off", "compact", "full"]

EVENT_INTENT_DECLARED = "intent.declared"
EVENT_INTENT_QUEUED = "intent.queued"
EVENT_INTENT_PROMOTED = "intent.promoted"
EVENT_INTENT_QUEUE_BLOCKED = "intent.queue_blocked"
EVENT_INTENT_CHECKED = "intent.checked"
EVENT_INTENT_EXPANDED = "intent.expanded"
EVENT_INTENT_VIOLATED = "intent.violated"
EVENT_INTENT_CLEARED = "intent.cleared"
EVENT_INTENT_RENEWED = "intent.renewed"
EVENT_INTENT_EXPIRED = "intent.expired"
EVENT_WORKSPACE_CONFLICT = "workspace.conflict_detected"
EVENT_WORKSPACE_GC = "workspace.gc_completed"
EVENT_BLAST_RADIUS = "blast_radius.computed"
EVENT_PATCH_BUDGET = "patch_budget.computed"
EVENT_PATCH_VERIFIED = "patch_contract.verified"
EVENT_PATCH_VIOLATED = "patch_contract.violated"
EVENT_PATCH_EXPIRED = "patch_contract.expired"
EVENT_CLAIM_COMPLETED = "claim_validation.completed"
EVENT_CLAIM_VIOLATED = "claim_validation.violated"
EVENT_RECEIPT_CREATED = "review_receipt.created"
EVENT_BASELINE_ABUSE = "baseline_abuse.detected"

KNOWN_EVENT_TYPES = frozenset(
    {
        EVENT_INTENT_DECLARED,
        EVENT_INTENT_QUEUED,
        EVENT_INTENT_PROMOTED,
        EVENT_INTENT_QUEUE_BLOCKED,
        EVENT_INTENT_CHECKED,
        EVENT_INTENT_EXPANDED,
        EVENT_INTENT_VIOLATED,
        EVENT_INTENT_CLEARED,
        EVENT_INTENT_RENEWED,
        EVENT_INTENT_EXPIRED,
        EVENT_WORKSPACE_CONFLICT,
        EVENT_WORKSPACE_GC,
        EVENT_BLAST_RADIUS,
        EVENT_PATCH_BUDGET,
        EVENT_PATCH_VERIFIED,
        EVENT_PATCH_VIOLATED,
        EVENT_PATCH_EXPIRED,
        EVENT_CLAIM_COMPLETED,
        EVENT_CLAIM_VIOLATED,
        EVENT_RECEIPT_CREATED,
        EVENT_BASELINE_ABUSE,
    }
)

PAYLOAD_MODES = frozenset({"off", "compact", "full"})


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    severity: AuditSeverity
    repo_root_digest: str
    agent_pid: int
    agent_label: str
    run_id: str | None = None
    intent_id: str | None = None
    report_digest: str | None = None
    status: str | None = None
    payload: Mapping[str, object] | None = None


def generate_event_id() -> str:
    timestamp = format(int(time.time() * 1000), "x")
    return f"evt_{timestamp}_{secrets.token_hex(2)}"


def repo_root_digest(root_path: Path) -> str:
    return hashlib.sha256(str(root_path).encode("utf-8")).hexdigest()[:16]


def compact_payload_for_event(
    *,
    event_type: str,
    payload: Mapping[str, object] | None,
) -> dict[str, object]:
    if payload is None:
        return {}
    if event_type in {
        EVENT_INTENT_DECLARED,
        EVENT_INTENT_QUEUED,
        EVENT_INTENT_PROMOTED,
        EVENT_INTENT_RENEWED,
        EVENT_INTENT_EXPIRED,
    }:
        return _compact_intent_payload(payload)
    if event_type == EVENT_INTENT_QUEUE_BLOCKED:
        return {
            "intent_id": str(payload.get("intent_id", "")),
            "blocking_count": _int_value(payload.get("blocking_count")),
        }
    if event_type in {
        EVENT_INTENT_CHECKED,
        EVENT_INTENT_EXPANDED,
        EVENT_INTENT_VIOLATED,
    }:
        return _compact_check_payload(payload)
    if event_type == EVENT_INTENT_CLEARED:
        return {
            "cleared": _int_value(payload.get("cleared")),
            "workspace_cleared": bool(payload.get("workspace_cleared")),
        }
    if event_type == EVENT_WORKSPACE_CONFLICT:
        return {
            "concurrent_intents": _sequence_field_count(
                payload,
                "concurrent_intents",
            )
        }
    if event_type == EVENT_WORKSPACE_GC:
        return {
            "removed": _int_value(payload.get("removed")),
            "stale_count": _int_value(payload.get("stale_count")),
            "orphaned_count": _int_value(payload.get("orphaned_count")),
        }
    if event_type == EVENT_BLAST_RADIUS:
        return _compact_blast_radius_payload(payload)
    if event_type == EVENT_PATCH_BUDGET:
        return _compact_budget_payload(payload)
    if event_type in {
        EVENT_PATCH_VERIFIED,
        EVENT_PATCH_VIOLATED,
        EVENT_PATCH_EXPIRED,
        EVENT_BASELINE_ABUSE,
    }:
        return _compact_verify_payload(payload)
    if event_type in {EVENT_CLAIM_COMPLETED, EVENT_CLAIM_VIOLATED}:
        return {
            "valid": bool(payload.get("valid")),
            "violations": len(_sequence(payload.get("violations"))),
            "warnings": len(_sequence(payload.get("warnings"))),
        }
    if event_type == EVENT_RECEIPT_CREATED:
        receipt = _mapping(payload.get("receipt"))
        return {
            "format": str(payload.get("format", "")),
            "verdict": str(receipt.get("verdict", "")),
            "human_decisions": _sequence_field_count(
                receipt,
                "human_decision_points",
            ),
        }
    return _compact_identifiers(payload)


def _compact_intent_payload(payload: Mapping[str, object]) -> dict[str, object]:
    scope = _mapping(payload.get("scope"))
    allowed = _sequence(scope.get("allowed_files"))
    return {
        "scope_file_count": len(allowed),
        "concurrent_intents": len(_sequence(payload.get("concurrent_intents"))),
        "workspace_registered": bool(payload.get("workspace_registered")),
        "ttl_seconds": _int_value(payload.get("ttl_seconds")),
        "lease_seconds": _int_value(payload.get("lease_seconds")),
    }


def _compact_check_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": str(payload.get("status", "")),
        "unexpected_files": len(_sequence(payload.get("unexpected_files"))),
        "forbidden_touched": len(_sequence(payload.get("forbidden_touched"))),
    }


def _compact_blast_radius_payload(payload: Mapping[str, object]) -> dict[str, object]:
    structural_risk = _mapping(payload.get("structural_risk"))
    return {
        "radius_level": str(payload.get("radius_level", "")),
        "direct_dependents": len(_sequence(payload.get("direct_dependents"))),
        "clone_cohort_members": len(_sequence(payload.get("clone_cohort_members"))),
        "do_not_touch": len(_sequence(payload.get("do_not_touch"))),
        "review_context": len(_sequence(payload.get("review_context"))),
        "risk_keys": sorted(str(key) for key in structural_risk),
    }


def _compact_budget_payload(payload: Mapping[str, object]) -> dict[str, object]:
    blast = _mapping(payload.get("blast_radius_summary"))
    gate = _mapping(payload.get("gate_preview"))
    return {
        "strictness": str(payload.get("strictness", "")),
        "radius_level": str(blast.get("radius_level", "")),
        "do_not_touch_count": _int_value(blast.get("do_not_touch_count")),
        "review_context_count": _int_value(blast.get("review_context_count")),
        "gate_would_fail": bool(gate.get("would_fail")),
    }


def _compact_verify_payload(payload: Mapping[str, object]) -> dict[str, object]:
    delta = _mapping(payload.get("structural_delta"))
    baseline_abuse = _mapping(payload.get("baseline_abuse"))
    return {
        "status": str(payload.get("status", "")),
        "regressions": len(_sequence(delta.get("regressions"))),
        "improvements": len(_sequence(delta.get("improvements"))),
        "health_delta": _int_or_none(delta.get("health_delta")),
        "contract_violations": [
            str(item) for item in _sequence(payload.get("contract_violations"))
        ],
        "baseline_abuse": bool(baseline_abuse.get("detected")),
    }


def _compact_identifiers(payload: Mapping[str, object]) -> dict[str, object]:
    keys = ("mode", "status", "reason", "run_id", "intent_id")
    return {key: payload[key] for key in keys if key in payload}


def _sequence_field_count(payload: Mapping[str, object], key: str) -> int:
    return len(_sequence(payload.get(key)))


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, str):
        return ()
    return value if isinstance(value, Sequence) else ()


def _int_value(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "EVENT_BASELINE_ABUSE",
    "EVENT_BLAST_RADIUS",
    "EVENT_CLAIM_COMPLETED",
    "EVENT_CLAIM_VIOLATED",
    "EVENT_INTENT_CHECKED",
    "EVENT_INTENT_CLEARED",
    "EVENT_INTENT_DECLARED",
    "EVENT_INTENT_EXPANDED",
    "EVENT_INTENT_EXPIRED",
    "EVENT_INTENT_PROMOTED",
    "EVENT_INTENT_QUEUED",
    "EVENT_INTENT_QUEUE_BLOCKED",
    "EVENT_INTENT_RENEWED",
    "EVENT_INTENT_VIOLATED",
    "EVENT_PATCH_BUDGET",
    "EVENT_PATCH_EXPIRED",
    "EVENT_PATCH_VERIFIED",
    "EVENT_PATCH_VIOLATED",
    "EVENT_RECEIPT_CREATED",
    "EVENT_WORKSPACE_CONFLICT",
    "EVENT_WORKSPACE_GC",
    "KNOWN_EVENT_TYPES",
    "PAYLOAD_MODES",
    "AuditEvent",
    "AuditPayloadMode",
    "AuditSeverity",
    "compact_payload_for_event",
    "generate_event_id",
    "repo_root_digest",
]
