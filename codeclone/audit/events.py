# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final, Literal, cast

AuditSeverity = Literal["info", "warn", "error"]
AuditPayloadMode = Literal["off", "compact", "full"]
AnalysisSource = Literal["mcp", "cli"]
AuditSurface = Literal["mcp", "cli", "hook", "ide", "ci", "unknown"]

AUDIT_EVENT_CORE_VERSION: Final = "2"

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
EVENT_PATCH_TRAIL_COMPUTED = "patch_trail.computed"
EVENT_BASELINE_ABUSE = "baseline_abuse.detected"
EVENT_ANALYSIS_COMPLETED = "analysis.completed"

ANALYSIS_SOURCE_MCP: AnalysisSource = "mcp"
ANALYSIS_SOURCE_CLI: AnalysisSource = "cli"

KNOWN_AUDIT_SURFACES = frozenset({"mcp", "cli", "hook", "ide", "ci", "unknown"})

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
        EVENT_PATCH_TRAIL_COMPUTED,
        EVENT_BASELINE_ABUSE,
        EVENT_ANALYSIS_COMPLETED,
    }
)

PAYLOAD_MODES = frozenset({"off", "compact", "full"})

# Compact mode keeps the intent description as a bounded forensic field.
_COMPACT_TEXT_LIMIT = 500

# Forensic-retention policy (Phase 34): payload compaction never strips these
# event types. They are durable evidence that must survive auto_clear and stay
# exactly retrievable after the run/intent is cleared (review receipt drill-down
# via get_review_receipt). Their complete payload is preserved under every
# payload mode; only the separately bounded event-core/replay projection applies.
_FULL_PAYLOAD_EVENT_TYPES: frozenset[str] = frozenset({EVENT_RECEIPT_CREATED})
_EVENT_CORE_SCOPE_PATH_LIMIT = 50
_EVENT_CORE_CITATION_LIMIT = 32
_PROJECTION_SUPPLEMENT_FACT_KEYS = frozenset(
    {
        "scope_paths",
        "declared_scope_paths",
        "changed_files",
        "untouched_in_declared",
        "citations",
    }
)

# The summary column stores the human-authored essence of an event,
# independent of audit_payloads mode. Bounded to keep the column lean.
SUMMARY_TEXT_LIMIT = 2000

# Intent lifecycle events whose payload may carry the human intent
# description. Shared by compact payloads and the summary projection so the
# two stay in lockstep.
_INTENT_PAYLOAD_EVENTS = frozenset(
    {
        EVENT_INTENT_DECLARED,
        EVENT_INTENT_QUEUED,
        EVENT_INTENT_PROMOTED,
        EVENT_INTENT_RENEWED,
        EVENT_INTENT_EXPIRED,
    }
)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    severity: AuditSeverity
    repo_root_digest: str
    agent_pid: int
    agent_label: str
    agent_start_epoch: int | None = None
    run_id: str | None = None
    intent_id: str | None = None
    report_digest: str | None = None
    status: str | None = None
    payload: Mapping[str, object] | None = None
    workflow_id: str | None = None
    surface: AuditSurface | None = None
    tool_name: str | None = None


def generate_event_id() -> str:
    timestamp = format(int(time.time() * 1000), "x")
    return f"evt_{timestamp}_{secrets.token_hex(2)}"


def repo_root_digest(root_path: Path) -> str:
    return hashlib.sha256(str(root_path).encode("utf-8")).hexdigest()[:16]


def derive_workflow_id(event: AuditEvent, event_id: str) -> str:
    """Return the deterministic workflow grouping id for an audit row.

    Intent and run handles are grouping aids, not proof fields.  Report content
    identity stays in ``report_digest`` and in event-core facts when present.
    """
    if event.intent_id:
        return f"intent:{event.intent_id}"
    if event.run_id:
        return f"run:{event.run_id}"
    explicit = _explicit_workflow_id(event)
    if explicit:
        return explicit
    return f"event:{event_id}"


def normalize_audit_surface(
    surface: AuditSurface | str | None,
    *,
    payload: Mapping[str, object] | None = None,
) -> AuditSurface:
    if isinstance(surface, str):
        normalized = surface.strip().lower()
        if normalized in KNOWN_AUDIT_SURFACES:
            return cast(AuditSurface, normalized)
    payload_source = _payload_source(payload)
    if payload_source in {ANALYSIS_SOURCE_MCP, ANALYSIS_SOURCE_CLI}:
        return payload_source
    return "unknown"


def event_core_for_event(event: AuditEvent) -> dict[str, object]:
    """Build bounded machine facts used by trajectory replay.

    This is deliberately separate from compact/full audit payloads: compact
    payloads are human-friendly forensics, while event core is deterministic
    replay input.  It never copies unbounded payload lists or prose.
    """
    facts, truncated = _event_core_facts(event.event_type, event.payload)
    if event.intent_id:
        facts.setdefault("intent_id", event.intent_id)
    if event.run_id:
        facts.setdefault("run_id", event.run_id)
    if event.report_digest:
        facts.setdefault("report_digest", event.report_digest)
    return {
        "core_schema_version": AUDIT_EVENT_CORE_VERSION,
        "event_family": _event_family(event.event_type),
        "event_type": event.event_type,
        "status": event.status or str(facts.get("status", "")),
        "facts": facts,
        "truncated": truncated,
    }


def compact_payload_for_event(
    *,
    event_type: str,
    payload: Mapping[str, object] | None,
) -> dict[str, object]:
    if payload is None:
        return {}
    if event_type in _FULL_PAYLOAD_EVENT_TYPES:
        # Forensic-retention policy: preserve the complete payload (e.g. the full
        # typed review receipt) so it stays exactly retrievable post-clear.
        return dict(payload)
    if event_type in _INTENT_PAYLOAD_EVENTS:
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
    if event_type == EVENT_ANALYSIS_COMPLETED:
        return _compact_analysis_completed_payload(payload)
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
    if event_type == EVENT_PATCH_TRAIL_COMPUTED:
        return _compact_patch_trail_payload(payload)
    return _compact_identifiers(payload)


def _event_core_facts(
    event_type: str,
    payload: Mapping[str, object] | None,
) -> tuple[dict[str, object], bool]:
    if payload is None:
        return {}, False
    if event_type in _INTENT_PAYLOAD_EVENTS:
        core = dict(_compact_intent_payload(payload))
        core.pop("intent_description", None)
        scope_paths, truncated = _bounded_scope_paths(payload)
        if scope_paths:
            core["scope_paths"] = list(scope_paths)
        if truncated:
            core["scope_paths_truncated"] = True
        return core, truncated
    if event_type == EVENT_INTENT_QUEUE_BLOCKED:
        return {
            "intent_id": str(payload.get("intent_id", "")),
            "blocking_count": _int_value(payload.get("blocking_count")),
        }, False
    if event_type in {
        EVENT_INTENT_CHECKED,
        EVENT_INTENT_EXPANDED,
        EVENT_INTENT_VIOLATED,
    }:
        return _check_event_core_facts(payload)
    if event_type == EVENT_INTENT_CLEARED:
        return {
            "cleared": _int_value(payload.get("cleared")),
            "workspace_cleared": bool(payload.get("workspace_cleared")),
        }, False
    if event_type == EVENT_WORKSPACE_CONFLICT:
        return {
            "concurrent_intents": _sequence_field_count(
                payload,
                "concurrent_intents",
            )
        }, False
    if event_type == EVENT_WORKSPACE_GC:
        return {
            "removed": _int_value(payload.get("removed")),
            "stale_count": _int_value(payload.get("stale_count")),
            "orphaned_count": _int_value(payload.get("orphaned_count")),
        }, False
    if event_type == EVENT_BLAST_RADIUS:
        return _compact_blast_radius_payload(payload), False
    if event_type == EVENT_ANALYSIS_COMPLETED:
        return _compact_analysis_completed_payload(payload), False
    if event_type == EVENT_PATCH_BUDGET:
        return _compact_budget_payload(payload), False
    if event_type in {
        EVENT_PATCH_VERIFIED,
        EVENT_PATCH_VIOLATED,
        EVENT_PATCH_EXPIRED,
        EVENT_BASELINE_ABUSE,
    }:
        return _verify_event_core_facts(payload), False
    if event_type in {EVENT_CLAIM_COMPLETED, EVENT_CLAIM_VIOLATED}:
        return _claim_event_core_facts(payload)
    if event_type == EVENT_RECEIPT_CREATED:
        receipt = _mapping(payload.get("receipt"))
        return {
            "format": str(payload.get("format", "")),
            "verdict": str(receipt.get("verdict", "")),
            "human_decisions": _sequence_field_count(
                receipt,
                "human_decision_points",
            ),
        }, False
    if event_type == EVENT_PATCH_TRAIL_COMPUTED:
        return _patch_trail_event_core_facts(payload)
    return _compact_identifiers(payload), False


def _compact_intent_payload(payload: Mapping[str, object]) -> dict[str, object]:
    scope = _mapping(payload.get("scope"))
    allowed = _sequence(scope.get("allowed_files"))
    return {
        # Compaction drops volume, not substance: the intent description is
        # the key forensic field and survives (bounded) even in compact mode.
        "intent_description": _bounded_text(
            payload.get("intent_description"), _COMPACT_TEXT_LIMIT
        ),
        "scope_file_count": len(allowed),
        "concurrent_intents": len(_sequence(payload.get("concurrent_intents"))),
        "workspace_registered": bool(payload.get("workspace_registered")),
        "ttl_seconds": _int_value(payload.get("ttl_seconds")),
        "lease_seconds": _int_value(payload.get("lease_seconds")),
    }


def _bounded_scope_paths(payload: Mapping[str, object]) -> tuple[tuple[str, ...], bool]:
    scope = _mapping(payload.get("scope"))
    raw_paths = [
        *_sequence(scope.get("allowed_files")),
        *_sequence(scope.get("allowed_related")),
    ]
    normalized: list[str] = []
    for raw_path in raw_paths:
        path = _normalized_event_core_path(raw_path)
        if path is not None:
            normalized.append(path)
    unique = tuple(sorted(set(normalized)))
    return (
        unique[:_EVENT_CORE_SCOPE_PATH_LIMIT],
        len(unique) > _EVENT_CORE_SCOPE_PATH_LIMIT,
    )


def _normalized_event_core_path(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    if not text or text in {".", ".."} or text.startswith("/"):
        return None
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


def event_summary(
    event_type: str,
    payload: Mapping[str, object] | None,
) -> str | None:
    """Human-readable essence of an event for the summary column.

    Independent of audit_payloads mode: the summary is lightweight structured
    metadata (like status or intent_id), not bulk payload, so it is captured
    even when payloads are 'off' or 'compact'. Returns None when the event
    carries no human-authored text. Bounded to ``SUMMARY_TEXT_LIMIT``.
    """
    if payload is None:
        return None
    if event_type in _INTENT_PAYLOAD_EVENTS:
        text = _bounded_text(payload.get("intent_description"), SUMMARY_TEXT_LIMIT)
        return text or None
    if event_type == EVENT_ANALYSIS_COMPLETED:
        return _analysis_completed_summary(payload)
    incident = _incident_summary(event_type, payload)
    return _bounded_text(incident, SUMMARY_TEXT_LIMIT) if incident else None


# Incident events whose summary is a labelled count of a payload list.
_COUNT_INCIDENTS: dict[str, tuple[str, str, str]] = {
    EVENT_WORKSPACE_CONFLICT: (
        "concurrent_intents",
        "workspace conflict",
        "concurrent intent(s)",
    ),
    EVENT_CLAIM_VIOLATED: ("violations", "claim validation failed", "violation(s)"),
}


def _join_or(values: object, *, default: str) -> str:
    items = [str(item) for item in _sequence(values)]
    return ", ".join(items) if items else default


def _summary_patch_violated(payload: Mapping[str, object]) -> str:
    delta = _mapping(payload.get("structural_delta"))
    regressions = len(_sequence(delta.get("regressions")))
    detail = _join_or(payload.get("contract_violations"), default="none")
    return f"patch contract violated: {regressions} regression(s); {detail}"


def _summary_baseline_abuse(payload: Mapping[str, object]) -> str:
    abuse = _mapping(payload.get("baseline_abuse"))
    detail = _join_or(abuse.get("triggers"), default="unspecified")
    return f"baseline abuse detected: {detail}"


def _summary_receipt_created(payload: Mapping[str, object]) -> str:
    receipt = _mapping(payload.get("receipt"))
    verdict = str(receipt.get("verdict", "")).strip() or "unknown"
    return f"review receipt: {verdict}"


# Incident events whose summary needs bespoke per-type field extraction.
_INCIDENT_BUILDERS: dict[str, Callable[[Mapping[str, object]], str]] = {
    EVENT_PATCH_VIOLATED: _summary_patch_violated,
    EVENT_BASELINE_ABUSE: _summary_baseline_abuse,
    EVENT_RECEIPT_CREATED: _summary_receipt_created,
}


def _incident_summary(event_type: str, payload: Mapping[str, object]) -> str:
    """Bounded human-readable line for an indexed incident event.

    Field paths mirror ``compact_payload_for_event`` so the summary and the
    compact payload stay in lockstep. Non-incident event types yield "".
    """
    count_spec = _COUNT_INCIDENTS.get(event_type)
    if count_spec is not None:
        key, prefix, noun = count_spec
        return f"{prefix}: {len(_sequence(payload.get(key)))} {noun}"
    builder = _INCIDENT_BUILDERS.get(event_type)
    return builder(payload) if builder is not None else ""


def _compact_check_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": str(payload.get("status", "")),
        "unexpected_files": len(_sequence(payload.get("unexpected_files"))),
        "forbidden_touched": len(_sequence(payload.get("forbidden_touched"))),
    }


def _bounded_path_list(
    value: object,
) -> tuple[tuple[str, ...], bool]:
    normalized: list[str] = []
    for raw_path in _sequence(value):
        path = _normalized_event_core_path(raw_path)
        if path is not None:
            normalized.append(path)
    unique = tuple(sorted(set(normalized)))
    return (
        unique[:_EVENT_CORE_SCOPE_PATH_LIMIT],
        len(unique) > _EVENT_CORE_SCOPE_PATH_LIMIT,
    )


def _check_event_core_facts(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    core = _compact_check_payload(payload)
    truncated = False
    changed, changed_truncated = _bounded_path_list(payload.get("actual_changed_files"))
    declared, declared_truncated = _bounded_path_list(payload.get("declared_scope"))
    unexpected, unexpected_truncated = _bounded_path_list(
        payload.get("unexpected_files")
    )
    forbidden, forbidden_truncated = _bounded_path_list(
        payload.get("forbidden_touched")
    )
    if changed:
        core["changed_files"] = list(changed)
    if declared:
        core["declared_scope_paths"] = list(declared)
    if unexpected:
        core["unexpected_files_list"] = list(unexpected)
    if forbidden:
        core["forbidden_touched_list"] = list(forbidden)
    untouched = tuple(sorted(set(declared) - set(changed)))
    if untouched:
        bounded = untouched[:_EVENT_CORE_SCOPE_PATH_LIMIT]
        core["untouched_in_declared"] = list(bounded)
        if len(untouched) > _EVENT_CORE_SCOPE_PATH_LIMIT:
            truncated = True
    truncated = (
        truncated
        or changed_truncated
        or declared_truncated
        or unexpected_truncated
        or forbidden_truncated
    )
    if truncated:
        core["paths_truncated"] = True
    return core, truncated


def _compact_analysis_completed_payload(
    payload: Mapping[str, object],
) -> dict[str, object]:
    health = _mapping(payload.get("health"))
    findings = _mapping(payload.get("findings"))
    inventory = _mapping(payload.get("inventory"))
    return {
        "source": str(payload.get("source", "")),
        "mode": str(payload.get("mode", "")),
        "focus": str(payload.get("focus", "")),
        "health_score": _int_or_none(health.get("score")),
        "health_grade": str(health.get("grade", "")),
        "findings_total": _int_or_none(findings.get("total")),
        "findings_new": _int_or_none(findings.get("new")),
        "files": _int_or_none(inventory.get("files")),
    }


def _analysis_completed_summary(payload: Mapping[str, object]) -> str:
    health = _mapping(payload.get("health"))
    score = health.get("score")
    source = str(payload.get("source", "")).strip() or "unknown"
    if isinstance(score, int) and not isinstance(score, bool):
        return f"analysis completed ({source}): health={score}"
    return f"analysis completed ({source})"


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


def _compact_patch_trail_payload(payload: Mapping[str, object]) -> dict[str, object]:
    counts = _patch_trail_counts(payload)
    truncation = _mapping(payload.get("truncation"))
    return {
        "patch_trail_digest": str(payload.get("patch_trail_digest", "")),
        "scope_check_status": str(payload.get("scope_check_status", "")),
        "verification_status": str(payload.get("verification_status", "")),
        "declared": _int_value(counts.get("declared")),
        "changed": _int_value(counts.get("changed")),
        "untouched_in_declared": _int_value(counts.get("untouched_in_declared")),
        "unexpected": _int_value(counts.get("unexpected")),
        "forbidden_touched": _int_value(counts.get("forbidden_touched")),
        "truncation": bool(any(bool(value) for value in truncation.values())),
    }


def _patch_trail_event_core_facts(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    counts = _patch_trail_counts(payload)
    truncation = _mapping(payload.get("truncation"))
    truncated = bool(any(bool(value) for value in truncation.values()))
    return {
        "patch_trail_digest": str(payload.get("patch_trail_digest", "")),
        "scope_check_status": str(payload.get("scope_check_status", "")),
        "verification_status": str(payload.get("verification_status", "")),
        "declared": _int_value(counts.get("declared")),
        "changed": _int_value(counts.get("changed")),
        "untouched_in_declared": _int_value(counts.get("untouched_in_declared")),
        "unexpected": _int_value(counts.get("unexpected")),
        "forbidden_touched": _int_value(counts.get("forbidden_touched")),
        "truncation": truncated,
    }, truncated


def _patch_trail_counts(payload: Mapping[str, object]) -> Mapping[str, object]:
    counts = payload.get("counts")
    if isinstance(counts, Mapping):
        return counts
    return {
        "declared": len(_sequence(payload.get("declared_files"))),
        "changed": len(_sequence(payload.get("changed_files"))),
        "untouched_in_declared": len(_sequence(payload.get("untouched_in_declared"))),
        "unexpected": len(_sequence(payload.get("unexpected_files"))),
        "forbidden_touched": len(_sequence(payload.get("forbidden_touched"))),
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


def _claim_event_core_facts(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    core: dict[str, object] = {
        "valid": bool(payload.get("valid")),
        "violations": len(_sequence(payload.get("violations"))),
        "warnings": len(_sequence(payload.get("warnings"))),
        "citations_found": _int_value(payload.get("citations_found")),
    }
    truncated = False
    citations: list[dict[str, object]] = []
    for raw in _sequence(payload.get("validated_citations")):
        if isinstance(raw, Mapping):
            entry = _validated_citation_entry(raw)
            if entry is not None:
                citations.append(entry)
    if citations:
        bounded = citations[:_EVENT_CORE_CITATION_LIMIT]
        core["citations"] = bounded
        if len(citations) > _EVENT_CORE_CITATION_LIMIT:
            truncated = True
            core["citations_truncated"] = True
    return core, truncated


def _validated_citation_entry(raw: Mapping[str, object]) -> dict[str, object] | None:
    cited_id = str(raw.get("cited_id", "")).strip()
    kind = str(raw.get("kind", "")).strip()
    if not cited_id or not kind:
        return None
    return {
        "cited_id": cited_id,
        "kind": kind,
        "valid": bool(raw.get("valid")),
    }


def projection_supplement_facts_from_payload(
    event_type: str,
    payload_json: str | None,
) -> dict[str, object]:
    """Re-derive bounded replay facts from stored audit payload for projection."""
    if not payload_json or payload_json == "{}":
        return {}
    try:
        parsed = json.loads(payload_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    facts, _ = _event_core_facts(event_type, parsed)
    return {
        key: value
        for key in sorted(_PROJECTION_SUPPLEMENT_FACT_KEYS)
        if (value := facts.get(key))
    }


def _verify_event_core_facts(payload: Mapping[str, object]) -> dict[str, object]:
    delta = _mapping(payload.get("structural_delta"))
    baseline_abuse = _mapping(payload.get("baseline_abuse"))
    return {
        "status": str(payload.get("status", "")),
        "regressions": len(_sequence(delta.get("regressions"))),
        "improvements": len(_sequence(delta.get("improvements"))),
        "health_delta": _int_or_none(delta.get("health_delta")),
        "contract_violation_count": len(_sequence(payload.get("contract_violations"))),
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


def _bounded_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _event_family(event_type: str) -> str:
    head, _, _tail = event_type.partition(".")
    return head or "unknown"


def _explicit_workflow_id(event: AuditEvent) -> str:
    candidates = (event.workflow_id, _mapping(event.payload).get("workflow_id"))
    for candidate in candidates:
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped:
                return stripped
    return ""


def _payload_source(payload: Mapping[str, object] | None) -> str:
    source = _mapping(payload).get("source")
    return source.strip().lower() if isinstance(source, str) else ""


__all__ = [
    "ANALYSIS_SOURCE_CLI",
    "ANALYSIS_SOURCE_MCP",
    "AUDIT_EVENT_CORE_VERSION",
    "EVENT_ANALYSIS_COMPLETED",
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
    "KNOWN_AUDIT_SURFACES",
    "KNOWN_EVENT_TYPES",
    "PAYLOAD_MODES",
    "SUMMARY_TEXT_LIMIT",
    "AnalysisSource",
    "AuditEvent",
    "AuditPayloadMode",
    "AuditSeverity",
    "AuditSurface",
    "compact_payload_for_event",
    "derive_workflow_id",
    "event_core_for_event",
    "event_summary",
    "generate_event_id",
    "normalize_audit_surface",
    "projection_supplement_facts_from_payload",
    "repo_root_digest",
]
