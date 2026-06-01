# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from ..report.meta import current_report_timestamp_utc
from .enums import MemoryRecordType
from .exceptions import MemoryCapacityError, MemoryContractError
from .identity import make_identity_key
from .models import (
    MemoryProject,
    MemoryQuery,
    MemoryRecord,
    MemoryRevision,
    MemorySubject,
    generate_memory_id,
)
from .paths import normalize_repo_path
from .sqlite_store import SqliteEngineeringMemoryStore

_NEGATION_WINDOW = re.compile(
    r"(?:cannot|can't|can not|does not|doesn't|do not|don't|never|not)\s+"
    r"(?:\w+\s+){0,4}$",
    re.IGNORECASE,
)

_FORBIDDEN_LITERALS = (
    "edit allowed",
    "do_not_touch cleared",
    "gate passed because memory",
    "scope expanded because memory",
    "expanded scope because memory",
)

_FORBIDDEN_NEGATABLE = (
    "override finding",
    "override findings",
    "overrides finding",
    "overrides findings",
)

_FORBIDDEN_APPROVE_DRAFT_PATTERNS = (
    re.compile(r"\b(?:mcp|memory)\b[^.]{0,80}\bapprove\b[^.]{0,80}\bdraft", re.I),
    re.compile(
        r"\bapprove\b[^.]{0,80}\b(?:memory|draft)\b[^.]{0,80}\b(?:active|policy|verified)\b",
        re.I,
    ),
)
_FORBIDDEN_OTHER_PATTERNS = (
    re.compile(
        r"\b(?:engineering )?memory\b[^.]{0,60}\b(?:allows?|permits?|authoriz\w+)\b"
        r"[^.]{0,40}\b(?:edit\w*|chang\w*|touch\w*)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:scope|intent)\b[^.]{0,50}\b(?:expand|widened|broadened)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:findings?|codeclone|structural)\b[^.]{0,50}"
        r"\b(?:clear\w*|resolved|gone|passed|clean\w*)\b",
        re.I,
    ),
)
_FORBIDDEN_PATTERNS = _FORBIDDEN_APPROVE_DRAFT_PATTERNS + _FORBIDDEN_OTHER_PATTERNS

_VS_CODE_CHANNEL_RE = re.compile(r"\bvs\s*code\b|\bvscode\b", re.IGNORECASE)
_HUMAN_GOVERNANCE_MARKERS = (
    "human",
    "operator",
    "maintainer",
    "ide channel",
    "human review",
    "not mcp",
    "not available through mcp",
)


def _is_vscode_human_approval_descriptor(text: str) -> bool:
    """Describe IDE human governance, not agent/MCP self-grant of approval power."""
    lowered = text.lower()
    if _VS_CODE_CHANNEL_RE.search(text) is None:
        return False
    if "memory view" not in lowered:
        return False
    if "approve" not in lowered or "draft" not in lowered:
        return False
    return any(marker in lowered for marker in _HUMAN_GOVERNANCE_MARKERS)


def _phrase_is_negated(text: str, phrase: str, *, start: int) -> bool:
    del phrase
    return _match_is_negated(text, start=start)


def _match_is_negated(text: str, *, start: int) -> bool:
    window = text[max(0, start - 48) : start]
    return _NEGATION_WINDOW.search(window) is not None


_PERMISSION_VERB_IN_MATCH = re.compile(
    r"\b(approve\w*|allow\w*|permits?\w*|authoriz\w+|clear\w*|"
    r"expand\w*|widened|broadened|resolved|gone|passed|clean\w*)\b",
    re.IGNORECASE,
)


def _pattern_matches_unnegated(text: str, pattern: re.Pattern[str]) -> bool:
    for match in pattern.finditer(text):
        span_start, span_end = match.span()
        segment = text[span_start:span_end]
        anchors = list(_PERMISSION_VERB_IN_MATCH.finditer(segment))
        if not anchors:
            if not _match_is_negated(text, start=span_start):
                return True
            continue
        if any(
            not _match_is_negated(text, start=span_start + anchor.start())
            for anchor in anchors
        ):
            return True
    return False


def _contains_unnegated_phrase(text: str, phrase: str) -> bool:
    lowered = text.lower()
    needle = phrase.lower()
    start = 0
    while True:
        index = lowered.find(needle, start)
        if index < 0:
            return False
        if not _phrase_is_negated(lowered, needle, start=index):
            return True
        start = index + len(needle)
    return False


def _forbidden_claim_errors(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    errors = [
        f"Claim may grant permission memory cannot provide: {phrase!r}"
        for phrase in _FORBIDDEN_LITERALS
        if phrase in lowered
    ]
    errors.extend(
        f"Claim may grant permission memory cannot provide: {phrase!r}"
        for phrase in _FORBIDDEN_NEGATABLE
        if _contains_unnegated_phrase(lowered, phrase)
    )
    approve_patterns = (
        ()
        if _is_vscode_human_approval_descriptor(text)
        else _FORBIDDEN_APPROVE_DRAFT_PATTERNS
    )
    errors.extend(
        f"Claim may grant permission memory cannot provide: {pattern.pattern!r}"
        for pattern in approve_patterns + _FORBIDDEN_OTHER_PATTERNS
        if _pattern_matches_unnegated(text, pattern)
    )
    return tuple(errors)


@dataclass(frozen=True, slots=True)
class ClaimValidationResult:
    valid: bool
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


def _require_record(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
) -> MemoryRecord:
    record = store.find_record(record_id)
    if record is None:
        msg = f"Memory record not found: {record_id}"
        raise MemoryContractError(msg)
    return record


def _write_governance_revision(
    store: SqliteEngineeringMemoryStore,
    record: MemoryRecord,
    *,
    record_id: str,
    reason: str,
    changed_by: str,
    now: str,
) -> None:
    store.write_revision(
        MemoryRevision(
            id=generate_memory_id(prefix="rev"),
            memory_id=record_id,
            revision_number=store.next_revision_number(record_id),
            previous_statement=record.statement,
            new_statement=record.statement,
            previous_payload=record.payload,
            new_payload=record.payload,
            reason=reason,
            changed_by=changed_by,
            changed_at_utc=now,
            branch=record.verified_on_branch,
            commit=record.verified_at_commit,
        )
    )


def _finalize_governance_record(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
) -> MemoryRecord:
    store.commit()
    updated = store.find_record(record_id)
    assert updated is not None
    return updated


def approve_record(
    store: SqliteEngineeringMemoryStore,
    *,
    record_id: str,
    approved_by: str,
    revision_reason: str = "human_approve",
) -> MemoryRecord:
    record = _require_record(store, record_id)
    if record.status not in {"draft", "stale"}:
        msg = f"Cannot approve record in status '{record.status}'"
        raise MemoryContractError(msg)
    now = current_report_timestamp_utc()
    store.update_record_status(
        record_id,
        status="active",
        approved_by=approved_by,
        approved_at_utc=now,
        stale_reason=None,
    )
    _write_governance_revision(
        store,
        record,
        record_id=record_id,
        reason=revision_reason,
        changed_by=approved_by,
        now=now,
    )
    return _finalize_governance_record(store, record_id)


def reject_record(
    store: SqliteEngineeringMemoryStore,
    *,
    record_id: str,
    rejected_by: str,
    reason: str | None = None,
    revision_reason: str | None = None,
) -> MemoryRecord:
    record = _require_record(store, record_id)
    if record.status != "draft":
        msg = f"Cannot reject record in status '{record.status}'"
        raise MemoryContractError(msg)
    now = current_report_timestamp_utc()
    store.update_record_status(
        record_id,
        status="rejected",
        stale_reason=reason,
    )
    _write_governance_revision(
        store,
        record,
        record_id=record_id,
        reason=revision_reason or reason or "human_reject",
        changed_by=rejected_by,
        now=now,
    )
    return _finalize_governance_record(store, record_id)


def archive_record(
    store: SqliteEngineeringMemoryStore,
    *,
    record_id: str,
    archived_by: str,
    revision_reason: str = "human_archive",
) -> MemoryRecord:
    record = _require_record(store, record_id)
    if record.status != "active":
        msg = f"Cannot archive record in status '{record.status}'"
        raise MemoryContractError(msg)
    now = current_report_timestamp_utc()
    store.update_record_status(record_id, status="archived")
    _write_governance_revision(
        store,
        record,
        record_id=record_id,
        reason=revision_reason,
        changed_by=archived_by,
        now=now,
    )
    return _finalize_governance_record(store, record_id)


def record_candidate(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    record_type: MemoryRecordType,
    statement: str,
    subject_path: str | None = None,
    created_by: str = "agent",
    max_candidates: int,
) -> MemoryRecord:
    if len(statement.strip()) == 0:
        raise MemoryContractError("Candidate statement must not be empty.")
    draft_count = store.count_records_by_status(project.id, "draft")
    if draft_count >= max_candidates:
        raise MemoryCapacityError(
            f"max_candidates_reached: {draft_count}/{max_candidates}"
        )
    now = current_report_timestamp_utc()
    normalized_path = (
        normalize_repo_path(subject_path) if subject_path is not None else None
    )
    statement_digest = hashlib.sha256(statement.strip().encode("utf-8")).hexdigest()[
        :12
    ]
    subject_key = normalized_path or "general"
    identity = make_identity_key(
        type=record_type,
        subject_kind="path" if normalized_path else "module",
        subject_key=subject_key.replace("/", ".").removesuffix(".py"),
        discriminator=f"agent_candidate:{statement_digest}",
    )
    if store.find_by_identity_key(project.id, identity) is not None:
        msg = f"Candidate already exists for identity_key={identity}"
        raise MemoryContractError(msg)

    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project.id,
        identity_key=identity,
        type=record_type,
        status="draft",
        confidence="inferred",
        origin="agent",
        ingest_source="agent",
        statement=statement.strip(),
        summary=None,
        payload={"subject_path": normalized_path} if normalized_path else None,
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by=created_by,
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )
    store.write_record(record)
    if normalized_path:
        from .paths import repo_path_to_module_key

        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="path",
                subject_key=normalized_path,
                relation="about",
            )
        )
        store.write_subject(
            MemorySubject(
                id=generate_memory_id(prefix="subj"),
                memory_id=record.id,
                subject_kind="module",
                subject_key=repo_path_to_module_key(normalized_path),
                relation="about",
            )
        )
    store.sync_fts_record(record.id)
    store.commit()
    return record


def validate_memory_claims(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    text: str,
) -> ClaimValidationResult:
    warnings: list[str] = []
    lowered = text.lower()
    errors = list(_forbidden_claim_errors(text))
    if "inferred" in lowered and "established fact" in lowered:
        warnings.append("Treat inferred memory as hypothesis, not established fact.")
    stale_hits = store.query_records(
        MemoryQuery(
            project_id=project_id,
            statuses=("stale",),
            limit=5,
        )
    )
    if stale_hits and "no stale" in lowered:
        warnings.append("Active stale records exist; do not claim freshness.")
    return ClaimValidationResult(
        valid=not errors,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


__all__ = [
    "ClaimValidationResult",
    "approve_record",
    "archive_record",
    "record_candidate",
    "reject_record",
    "validate_memory_claims",
]
