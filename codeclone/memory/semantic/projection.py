# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from ..models import MemoryRecord
from ..trajectory.models import Trajectory
from ..trajectory.retrieval import trajectory_semantic_text_parts
from .models import SemanticProjection

# Prose/decision subset only. Structural records (module_role, test_anchor,
# document_link, public_surface, stale_marker) are served by exact subject
# match and are NOT semantically indexed (Phase 20 spec §6.1).
INDEXED_MEMORY_TYPES: frozenset[str] = frozenset(
    {
        "contract_note",
        "change_rationale",
        "risk_note",
        "architecture_decision",
        "contradiction_note",
        "protocol_rule",
        "human_note",
    }
)

# Forensically useful audit incidents (Phase 20 spec §6.2). Projected from the
# bounded controller_events.summary column only — never payload_json.
INDEXED_AUDIT_EVENTS: frozenset[str] = frozenset(
    {
        "intent.declared",
        "patch_contract.violated",
        "workspace.conflict_detected",
        "baseline_abuse.detected",
        "claim_validation.violated",
        "review_receipt.created",
    }
)


def text_hash(text: str) -> str:
    """Stable sha256 of the projected text — the idempotent upsert key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_indexed_memory_type(record_type: str) -> bool:
    return record_type in INDEXED_MEMORY_TYPES


def is_indexed_audit_event(event_type: str) -> bool:
    return event_type in INDEXED_AUDIT_EVENTS


def _join(parts: Iterable[str]) -> str:
    return " | ".join(part.strip() for part in parts if part and part.strip())


def project_memory_record(
    record: MemoryRecord,
    *,
    subject_path: str | None = None,
) -> SemanticProjection:
    """Build the deterministic projection for a memory record."""
    parts: list[str] = [record.type]
    if subject_path:
        parts.append(f"subject {subject_path}")
    if record.summary:
        parts.append(record.summary)
    parts.append(record.statement)
    text = _join(parts)
    return SemanticProjection(
        source="memory",
        source_id=record.id,
        project_id=record.project_id,
        kind=record.type,
        subject_path=subject_path,
        status=record.status,
        text=text,
        text_hash=text_hash(text),
    )


def project_audit_event(
    *,
    event_id: str,
    event_type: str,
    summary: str,
    project_id: str | None = None,
) -> SemanticProjection:
    """Build the deterministic projection for an audit incident.

    ``summary`` is the bounded controller_events.summary column; callers must
    skip events whose summary is empty (no human text to embed).
    """
    text = _join([event_type, summary])
    return SemanticProjection(
        source="audit",
        source_id=event_id,
        project_id=project_id,
        kind=event_type,
        subject_path=None,
        status=None,
        text=text,
        text_hash=text_hash(text),
    )


def project_trajectory(
    trajectory: Trajectory,
) -> SemanticProjection:
    """Build deterministic projection text for a stored trajectory.

    Only bounded trajectory projection fields are embedded: summary, outcome,
    quality tier, labels, path subjects, and compact step summaries. Raw audit
    payloads and event-core JSON stay out of the semantic sidecar.
    """
    text = _join(trajectory_semantic_text_parts(trajectory))
    return SemanticProjection(
        source="trajectory",
        source_id=trajectory.id,
        project_id=trajectory.project_id,
        kind="trajectory",
        subject_path=_primary_trajectory_path(trajectory),
        status=trajectory.outcome,
        text=text,
        text_hash=text_hash(text),
    )


def _primary_trajectory_path(trajectory: Trajectory) -> str | None:
    for subject in trajectory.subjects:
        if subject.subject_kind == "path":
            return subject.subject_key
    return None


__all__ = [
    "INDEXED_AUDIT_EVENTS",
    "INDEXED_MEMORY_TYPES",
    "is_indexed_audit_event",
    "is_indexed_memory_type",
    "project_audit_event",
    "project_memory_record",
    "project_trajectory",
    "text_hash",
]
