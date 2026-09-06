# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from ..config.memory_defaults import (
    DEFAULT_MEMORY_BATCH_MEAN_STATEMENT_CHARS,
    DEFAULT_MEMORY_MAX_STATEMENT_CHARS,
    DEFAULT_MEMORY_SOFT_STATEMENT_CHARS,
    DEFAULT_MEMORY_TARGET_STATEMENT_CHARS,
)
from ..report.meta import current_report_timestamp_utc
from .enums import MemoryRecordType, validate_memory_record_type
from .exceptions import MemoryCapacityError, MemoryContractError
from .identity import make_identity_key
from .models import (
    MemoryEvidence,
    MemoryLink,
    MemoryProject,
    MemoryQuery,
    MemoryRecord,
    MemoryRevision,
    MemorySubject,
    generate_memory_id,
)
from .paths import normalize_memory_scope_path
from .project import (
    code_fingerprint_for_memory_subject,
    read_git_provenance,
)
from .sqlite_store import SqliteEngineeringMemoryStore
from .statement_markdown import (
    HELP_MENTION,
    STATEMENT_AUDIENCE_HUMAN,
    STATEMENT_FORMAT_MD,
    STATEMENT_FORMAT_PAYLOAD_KEY,
    markdown_reject_error,
    statement_structure_issue,
    validate_statement_markdown,
)

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

_ForbiddenClaimRule: TypeAlias = tuple[str, re.Pattern[str]]

_FORBIDDEN_APPROVE_DRAFT_RULES: tuple[_ForbiddenClaimRule, ...] = (
    (
        "agent or MCP self-approving memory drafts as active policy",
        re.compile(
            r"\b(?:mcp|memory)\b[^.]{0,80}\bapprove\b[^.]{0,80}\bdraft",
            re.I,
        ),
    ),
    (
        "approving memory drafts as active or verified policy",
        re.compile(
            r"\bapprove\b[^.]{0,80}\b(?:memory|draft)\b[^.]{0,80}"
            r"\b(?:active|policy|verified)\b",
            re.I,
        ),
    ),
)
_FORBIDDEN_OTHER_RULES: tuple[_ForbiddenClaimRule, ...] = (
    (
        "memory authorizing edits, changes, or touching paths",
        re.compile(
            r"\b(?:engineering )?memory\b[^.]{0,60}\b(?:allows?|permits?|authoriz\w+)\b"
            r"[^.]{0,40}\b(?:edit\w*|chang\w*|touch\w*)\b",
            re.I,
        ),
    ),
    (
        "scope or intent expansion via memory",
        re.compile(
            r"\b(?:scope|intent)\b[^.]{0,50}\b(?:expand|widened|broadened)\b",
            re.I,
        ),
    ),
    (
        "findings or structural checks cleared by memory",
        re.compile(
            r"\b(?:findings?|codeclone|structural)\b[^.]{0,50}"
            r"\b(?:clear\w*|resolved|gone|passed|clean\w*)\b",
            re.I,
        ),
    ),
)

MEMORY_STATEMENT_TOO_LONG_ERROR = (
    "Memory candidate is too long for a durable card. "
    "Compress it into one evidence-linked conclusion; store details in "
    "receipt/spec/docs."
)


# Two provenance facts, deliberately not one. ``created_by`` is a historical
# fact about who produced the record and never moves; ``statement_origin``
# answers a different question -- whose words the CURRENT wording is. A human
# who reads an agent's draft and rewrites it before publishing is not the
# author of the observation, and "human_amended" is not an author label. The
# individual is already named on the revision (``changed_by``).
STATEMENT_ORIGIN_PAYLOAD_KEY: Final = "statement_origin"
STATEMENT_ORIGIN_AGENT: Final = "agent"
STATEMENT_ORIGIN_HUMAN_AMENDED: Final = "human_amended"

GOVERNANCE_STALE_AMENDMENT_CODE: Final = "governance_stale_amendment"
GOVERNANCE_RECORD_IMMUTABLE_CODE: Final = "governance_record_immutable"
GOVERNANCE_TICKET_MISMATCH_CODE: Final = "governance_ticket_mismatch"
GOVERNANCE_EMPTY_STATEMENT_CODE: Final = "governance_empty_statement"

_AMENDABLE_STATUS: Final = "draft"


def governance_refusal(code: str, *, reason: str, next_step: str) -> str:
    """One typed refusal line: what happened, and what to do about it.

    A typed outcome without an executable next_step is not shippable here, so
    the remedy is a call or a UI action the reader can actually perform.
    """
    return f"{code}: {reason} next_step: {next_step} See {HELP_MENTION}."


def compute_statement_digest(statement: str) -> str:
    """The one spelling of "which wording is this".

    Owned here rather than in the IDE channel because the compare-and-swap
    that guards an approval runs at the record layer, and a second spelling of
    a digest domain is how two callers silently stop agreeing.
    """
    return hashlib.sha256(statement.strip().encode("utf-8")).hexdigest()[:32]


def resolve_statement_origin(payload: Mapping[str, object] | None) -> str:
    """Derive whose words the current statement is; absent means the agent's.

    Derived, not backfilled: a record written before the amendment bridge
    carries no marker and reads as ``agent`` -- which is true, because nothing
    has amended it. No migration, no schema change.
    """
    if payload is None:
        return STATEMENT_ORIGIN_AGENT
    if payload.get(STATEMENT_ORIGIN_PAYLOAD_KEY) == STATEMENT_ORIGIN_HUMAN_AMENDED:
        return STATEMENT_ORIGIN_HUMAN_AMENDED
    return STATEMENT_ORIGIN_AGENT


def current_revision_number(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
) -> int:
    """Revisions already written for a record (the CAS revision axis)."""
    return store.next_revision_number(record_id) - 1


def assert_record_amendable(record: MemoryRecord) -> None:
    """Only a draft is editable. An approved statement is immutable.

    Once approved, the note is a published engineering claim other agents may
    already have read; editing it in place makes it impossible to audit what
    they read. The correction is a successor record, not a rewrite.
    """
    if record.status == _AMENDABLE_STATUS:
        return
    if record.status == "active":
        next_step = (
            "an approved statement is never edited in place -- record the "
            "correction as a new candidate linked with 'supersedes' "
            "(Memory view: Supersede), leaving the published record intact"
        )
    else:
        next_step = (
            f"only a draft can be amended; this record is '{record.status}'. "
            "Open a draft in the Memory view, or record a new candidate"
        )
    raise MemoryContractError(
        governance_refusal(
            GOVERNANCE_RECORD_IMMUTABLE_CODE,
            reason=(
                f"record {record.id} is in status '{record.status}', which is "
                "not editable."
            ),
            next_step=next_step,
        )
    )


def assert_record_unmoved(
    record: MemoryRecord,
    *,
    current_revision: int,
    shown_statement_digest: str,
    expected_revision: int,
    shown_status: str,
) -> None:
    """The compare-and-swap: nothing about the record moved since it was shown.

    Three axes, because no two of them cover the third. The statement digest
    misses a lifecycle move that leaves the bytes alone; the revision number
    misses it too -- ``mark_stale`` writes the record row without a revision,
    so a draft can go stale with the revision count unchanged (measured). The
    status axis is what makes the tuple total: the human was shown a wording,
    a revision and a status, and the approval binds to all three.
    """
    moved: list[str] = []
    actual_digest = compute_statement_digest(record.statement)
    if actual_digest != shown_statement_digest:
        moved.append(f"statement digest {shown_statement_digest} -> {actual_digest}")
    if current_revision != expected_revision:
        moved.append(f"revision {expected_revision} -> {current_revision}")
    if record.status != shown_status:
        moved.append(f"status '{shown_status}' -> '{record.status}'")
    if not moved:
        return
    raise MemoryContractError(
        governance_refusal(
            GOVERNANCE_STALE_AMENDMENT_CODE,
            reason=(
                f"record {record.id} changed after it was shown for approval "
                f"({'; '.join(moved)}); nothing was written."
            ),
            next_step=(
                "reopen the record in the Memory view and prepare governance "
                "again, so the approval binds to the wording now on screen"
            ),
        )
    )


def apply_record_cas(
    store: SqliteEngineeringMemoryStore,
    record_id: str,
    *,
    expected_revision: int | None,
    shown_statement_digest: str | None,
    shown_status: str | None,
) -> None:
    """Re-read INSIDE the transaction, then compare what the human was shown.

    Reading the record before opening the transaction and checking it after
    would be a check of a state that is no longer the one being written --
    which is the whole failure this guard exists to prevent.

    The three axes travel as three arguments rather than one value object on
    purpose: a record-shaped type belongs in the model store, and inventing a
    local one here (dataclass or hand-rolled) is the boundary the ratchet is
    watching. Absent axes mean "no CAS requested" and the caller gets the
    unguarded path -- which is why every axis is required together.
    """
    if (
        expected_revision is None
        or shown_statement_digest is None
        or shown_status is None
    ):
        return
    assert_record_unmoved(
        _require_record(store, record_id),
        current_revision=current_revision_number(store, record_id),
        shown_statement_digest=shown_statement_digest,
        expected_revision=expected_revision,
        shown_status=shown_status,
    )


def _reject_human_statement_shape(statement: str) -> str:
    """Same rules an agent gets; a remedy a human in the approval view can run."""
    stripped = statement.strip()
    if not stripped:
        raise MemoryContractError(
            governance_refusal(
                GOVERNANCE_EMPTY_STATEMENT_CODE,
                reason="an amended statement must not be empty.",
                next_step=(
                    "restore the wording in the Memory view, or reject the "
                    "draft instead of approving it"
                ),
            )
        )
    if len(stripped) > DEFAULT_MEMORY_MAX_STATEMENT_CHARS:
        raise MemoryContractError(MEMORY_STATEMENT_TOO_LONG_ERROR)
    report = validate_statement_markdown(stripped)
    if report.rejects:
        raise MemoryContractError(
            markdown_reject_error(report, audience=STATEMENT_AUDIENCE_HUMAN)
        )
    return stripped


def _validate_candidate_record_type(record_type: MemoryRecordType) -> MemoryRecordType:
    try:
        return validate_memory_record_type(record_type)
    except ValueError as exc:
        raise MemoryContractError(str(exc)) from exc


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
    # Declarative scan (the 39Y-recorded ``while True`` literal_condition
    # dead statement was retired here, in scope): non-overlapping
    # occurrences left to right, first unnegated occurrence wins — the
    # exact semantics of the previous find-loop.
    lowered = text.lower()
    needle = phrase.lower()
    return any(
        not _phrase_is_negated(lowered, needle, start=match.start())
        for match in re.finditer(re.escape(needle), lowered)
    )


def _permission_claim_error(description: str) -> str:
    return f"Claim may grant permission memory cannot provide: {description}."


def _forbidden_claim_errors(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    errors = [
        _permission_claim_error(phrase)
        for phrase in _FORBIDDEN_LITERALS
        if phrase in lowered
    ]
    errors.extend(
        _permission_claim_error(f"unnegated '{phrase}'")
        for phrase in _FORBIDDEN_NEGATABLE
        if _contains_unnegated_phrase(lowered, phrase)
    )
    approve_rules = (
        ()
        if _is_vscode_human_approval_descriptor(text)
        else _FORBIDDEN_APPROVE_DRAFT_RULES
    )
    errors.extend(
        _permission_claim_error(label)
        for label, pattern in approve_rules + _FORBIDDEN_OTHER_RULES
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
    """Re-read after the transaction closed. Deliberately no commit here.

    Committing at the end used to be the ONLY commit that mattered, but the
    status write committed on its own before it -- so a failure in between
    left a record durably approved with zero revisions. Durability is now the
    transaction's job, and this function only reports the settled state.
    """
    updated = store.find_record(record_id)
    assert updated is not None
    return updated


def _ensure_approval_evidence(
    store: SqliteEngineeringMemoryStore,
    record: MemoryRecord,
    *,
    record_id: str,
    approved_by: str,
    now: str,
) -> None:
    """Record the human approval as the warrant for an evidence-less record.

    Every active record must carry at least one evidence link. Agent
    candidates are approved with no ingested evidence, so the approval itself
    is the recorded warrant — keeping the store evidence-linked rather than
    leaving active records with no provenance. Records that already carry
    evidence (system-ingested facts that went stale and are re-approved) are
    left untouched.
    """
    if store.count_evidence_for_memory(record_id) > 0:
        return
    branch = record.verified_on_branch or ""
    commit = record.verified_at_commit or ""
    locator = f"{branch}@{commit}".strip("@") or None
    store.write_evidence(
        MemoryEvidence(
            id=generate_memory_id(prefix="evid"),
            memory_id=record_id,
            evidence_kind="audit_event",
            ref=f"human_approval:{approved_by}",
            locator=locator,
            quote=None,
            digest=None,
            created_at_utc=now,
        )
    )


def approve_record(
    store: SqliteEngineeringMemoryStore,
    *,
    record_id: str,
    approved_by: str,
    revision_reason: str = "human_approve",
    expected_revision: int | None = None,
    shown_statement_digest: str | None = None,
    shown_status: str | None = None,
) -> MemoryRecord:
    record = _require_record(store, record_id)
    if record.status not in {"draft", "stale"}:
        msg = f"Cannot approve record in status '{record.status}'"
        raise MemoryContractError(msg)
    now = current_report_timestamp_utc()
    with store.transaction():
        apply_record_cas(
            store,
            record_id,
            expected_revision=expected_revision,
            shown_statement_digest=shown_statement_digest,
            shown_status=shown_status,
        )
        store.update_record_status(
            record_id,
            status="active",
            approved_by=approved_by,
            approved_at_utc=now,
            stale_reason=None,
            commit=False,
        )
        _ensure_approval_evidence(
            store,
            record,
            record_id=record_id,
            approved_by=approved_by,
            now=now,
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
    expected_revision: int | None = None,
    shown_statement_digest: str | None = None,
    shown_status: str | None = None,
) -> MemoryRecord:
    record = _require_record(store, record_id)
    if record.status != "draft":
        msg = f"Cannot reject record in status '{record.status}'"
        raise MemoryContractError(msg)
    now = current_report_timestamp_utc()
    with store.transaction():
        apply_record_cas(
            store,
            record_id,
            expected_revision=expected_revision,
            shown_statement_digest=shown_statement_digest,
            shown_status=shown_status,
        )
        store.update_record_status(
            record_id,
            status="rejected",
            stale_reason=reason,
            commit=False,
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
    expected_revision: int | None = None,
    shown_statement_digest: str | None = None,
    shown_status: str | None = None,
) -> MemoryRecord:
    record = _require_record(store, record_id)
    if record.status != "active":
        msg = f"Cannot archive record in status '{record.status}'"
        raise MemoryContractError(msg)
    now = current_report_timestamp_utc()
    with store.transaction():
        apply_record_cas(
            store,
            record_id,
            expected_revision=expected_revision,
            shown_statement_digest=shown_statement_digest,
            shown_status=shown_status,
        )
        store.update_record_status(record_id, status="archived", commit=False)
        _write_governance_revision(
            store,
            record,
            record_id=record_id,
            reason=revision_reason,
            changed_by=archived_by,
            now=now,
        )
    return _finalize_governance_record(store, record_id)


def amend_and_approve_record(
    store: SqliteEngineeringMemoryStore,
    *,
    record_id: str,
    submitted_statement: str,
    expected_revision: int,
    shown_statement_digest: str,
    shown_status: str = _AMENDABLE_STATUS,
    approved_by: str,
    revision_reason: str = "ide_govern_amend_approve",
) -> tuple[MemoryRecord, dict[str, object]]:
    """Amend a draft's wording and approve it as ONE transaction.

    Not "amend, then approve later": a two-step shape leaves a window in which
    an approval signs text nobody reviewed. The compare-and-swap runs INSIDE
    the transaction, immediately before the writes, so the state it checks is
    the state that gets written -- and any refusal or failure rolls the whole
    thing back rather than leaving the record half-moved.

    Returns the settled record plus the transaction receipt (``proof``): what
    was shown, what was submitted, over which revision it succeeded. That is
    concurrency evidence, not a human signature -- the system has none, and
    the individual is already named in ``approved_by``/``changed_by``.
    """
    submitted = _reject_human_statement_shape(submitted_statement)
    now = current_report_timestamp_utc()
    with store.transaction():
        record = _require_record(store, record_id)
        assert_record_amendable(record)
        apply_record_cas(
            store,
            record_id,
            expected_revision=expected_revision,
            shown_statement_digest=shown_statement_digest,
            shown_status=shown_status,
        )
        payload = dict(record.payload or {})
        payload[STATEMENT_ORIGIN_PAYLOAD_KEY] = STATEMENT_ORIGIN_HUMAN_AMENDED
        payload[STATEMENT_FORMAT_PAYLOAD_KEY] = STATEMENT_FORMAT_MD
        revision_number = store.next_revision_number(record_id)
        store.update_record_statement(
            record_id,
            statement=submitted,
            payload=payload,
            commit=False,
        )
        store.update_record_status(
            record_id,
            status="active",
            approved_by=approved_by,
            approved_at_utc=now,
            stale_reason=None,
            commit=False,
        )
        _ensure_approval_evidence(
            store,
            record,
            record_id=record_id,
            approved_by=approved_by,
            now=now,
        )
        store.write_revision(
            MemoryRevision(
                id=generate_memory_id(prefix="rev"),
                memory_id=record_id,
                revision_number=revision_number,
                previous_statement=record.statement,
                new_statement=submitted,
                previous_payload=record.payload,
                new_payload=payload,
                reason=revision_reason,
                changed_by=approved_by,
                changed_at_utc=now,
                branch=record.verified_on_branch,
                commit=record.verified_at_commit,
            )
        )
        store.sync_fts_record(record_id)
    proof: dict[str, object] = {
        "operation": "amend_and_approve",
        "record_id": record_id,
        "actor": approved_by,
        "expected_revision": expected_revision,
        "expected_revision_matched": True,
        "shown_statement_digest": shown_statement_digest,
        "shown_status": shown_status,
        "submitted_statement_digest": compute_statement_digest(submitted),
        "revision_created": revision_number,
        "approval_bound_to": "submitted_statement_digest",
    }
    return _finalize_governance_record(store, record_id), proof


def supersede_approved_record(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    record_id: str,
    statement: str,
    actor: str,
    max_candidates: int,
    record_type: MemoryRecordType | None = None,
) -> MemoryRecord:
    """Correct an approved record by succeeding it, never by rewriting it.

    The predecessor is left exactly as published -- other agents may already
    have read it, and the audit of what they read has to survive the
    correction. The successor is an ordinary draft (it still needs human
    approval) carrying a ``supersedes`` link to the record it replaces.
    """
    predecessor = _require_record(store, record_id)
    if predecessor.status != "active":
        raise MemoryContractError(
            governance_refusal(
                GOVERNANCE_RECORD_IMMUTABLE_CODE,
                reason=(
                    f"only an approved record is superseded; record "
                    f"{record_id} is '{predecessor.status}'."
                ),
                next_step=(
                    "amend the draft in place through the Memory view, or "
                    "approve it first if the correction belongs to a "
                    "published statement"
                ),
            )
        )
    submitted = _reject_human_statement_shape(statement)
    resolved_type = _validate_candidate_record_type(record_type or predecessor.type)
    draft_count = store.count_records_by_status(project.id, "draft")
    if draft_count >= max_candidates:
        raise MemoryCapacityError(
            f"max_candidates_reached: {draft_count}/{max_candidates}"
        )
    now = current_report_timestamp_utc()
    subject_path = str((predecessor.payload or {}).get("subject_path") or "")
    identity = make_identity_key(
        type=resolved_type,
        subject_kind="path",
        subject_key=(subject_path or predecessor.id)
        .replace("/", ".")
        .removesuffix(".py"),
        discriminator=f"supersedes:{record_id}:{compute_statement_digest(submitted)[:12]}",
    )
    if store.find_by_identity_key(project.id, identity) is not None:
        raise MemoryContractError(
            governance_refusal(
                GOVERNANCE_RECORD_IMMUTABLE_CODE,
                reason=(
                    f"a successor for record {record_id} with this wording "
                    "already exists."
                ),
                next_step=(
                    "open the existing successor draft in the Memory view "
                    "instead of creating a second one"
                ),
            )
        )
    git = read_git_provenance(Path(project.root).resolve())
    successor = _new_draft_record(
        project=project,
        record_type=resolved_type,
        identity=identity,
        statement=submitted,
        payload={
            "subject_path": subject_path,
            STATEMENT_FORMAT_PAYLOAD_KEY: STATEMENT_FORMAT_MD,
            STATEMENT_ORIGIN_PAYLOAD_KEY: STATEMENT_ORIGIN_HUMAN_AMENDED,
            "supersedes_record_id": record_id,
        },
        now=now,
        created_by=actor,
        code_fingerprint=predecessor.code_fingerprint,
        created_on_branch=git.branch if git.available else None,
        created_at_commit=git.head if git.available else None,
    )
    with store.transaction():
        store.write_record(successor, commit=False)
        if subject_path:
            store.write_subject(
                MemorySubject(
                    id=generate_memory_id(prefix="subj"),
                    memory_id=successor.id,
                    subject_kind="path",
                    subject_key=subject_path,
                    relation="about",
                ),
                commit=False,
            )
        store.write_link(
            MemoryLink(
                id=generate_memory_id(prefix="link"),
                project_id=project.id,
                from_memory_id=successor.id,
                to_memory_id=record_id,
                relation="supersedes",
                created_by=actor,
                created_at_utc=now,
            )
        )
        store.sync_fts_record(successor.id)
    return successor


def _statement_length_warnings(
    length: int,
    *,
    target_limit: int = DEFAULT_MEMORY_TARGET_STATEMENT_CHARS,
    soft_limit: int = DEFAULT_MEMORY_SOFT_STATEMENT_CHARS,
) -> tuple[str, ...]:
    if length > soft_limit:
        return (
            f"Statement length {length} exceeds soft limit ({soft_limit} chars); "
            "compress to one durable fact before record_candidate.",
        )
    if length > target_limit:
        return (
            f"Statement length {length} exceeds target ({target_limit} chars); "
            "prefer <= 300 chars for durable cards.",
        )
    return ()


_UNEVIDENCED_ATTESTATION_WARN_CODE: Final = "memory_statement_unevidenced_attestation"

# The attestation idiom this project actually writes measurements in: an
# all-caps token anywhere, or a capitalised one opening a line or a sentence.
# Lower-case mid-sentence use is prose about the word ("the thing measured",
# 'prints `measured <name>`') and stays silent. Measured over the live store's
# 63 drafts: 37 attest in this position with no false positive, while a bare
# case-insensitive token would also have fired on 2 notes asserting no
# measurement of their own. The rule is deliberately conservative -- it is an
# advisory, and one that cries wolf gets trained away. Its cost is recall: 3
# of those 63 state a real measurement in lower-case mid-sentence and stay
# silent here.
_ATTESTATION_RE: Final = re.compile(
    r"\bMEASURED\b|\b\u0417\u0410\u041c\u0415\u0420\u0415\u041d\u041e\b"
    r"|(?:^|(?<=[.!?]\s))(?:Measured|\u0417\u0430\u043c\u0435\u0440\u0435\u043d\u043e)\b",
    re.MULTILINE,
)

_UNEVIDENCED_ATTESTATION_HINT: Final = (
    f"{_UNEVIDENCED_ATTESTATION_WARN_CODE}: this statement attests a "
    "measurement, but record_candidate "
    "attaches no evidence row, so the note lands confidence=inferred with "
    "evidence_count=0 and no reader can reach what was measured. "
    "next_step: record the measured change through "
    "finish_controlled_change(propose_memory=true), which attaches receipt, "
    "patch-trail and commit evidence to the draft; or, if the claim is an "
    "inference, state it without the attestation."
)


def _unevidenced_attestation_warning(statement: str) -> str | None:
    """Warn when a statement attests a measurement this path cannot evidence.

    ``record_candidate`` writes the record and its subjects and nothing else:
    no ``memory_evidence`` row exists for it, and no later transition adds
    one. Measured on the live store, 61 of 63 drafts carry
    ``evidence_count == 0``; the two that do not came from
    ``finish(propose_memory=true)``, which attaches its attested identifiers
    through ``_attach_attested_evidence``. So a body that says MEASURED and
    metadata that says inferred-with-nothing-attached disagree, and until now
    they disagreed silently. Confidence itself is not the lever: it is
    origin-derived (every agent record in the store is ``inferred``, every
    system record is not) and no code path can raise it, so the honest signal
    is the missing evidence, not a rung.
    """
    if _ATTESTATION_RE.search(statement) is None:
        return None
    return _UNEVIDENCED_ATTESTATION_HINT


def statement_markdown_warnings(
    statement: str,
    *,
    target_limit: int = DEFAULT_MEMORY_TARGET_STATEMENT_CHARS,
) -> tuple[str, ...]:
    """Advisory statement-shape warnings for a candidate statement.

    Governance owns statement hygiene; surfaces call this instead of
    reaching into the markdown validator directly. Three lanes ride it: the
    markdown-subset discipline rules, the structure hint that carries the
    md-v1 shape to a writer who never called help, and the unevidenced
    attestation notice. Each is conditional by construction, so the constant
    size of a record_candidate response is unchanged.
    """
    stripped = statement.strip()
    warnings = list(validate_statement_markdown(stripped).warnings)
    issue = statement_structure_issue(stripped, target_limit=target_limit)
    if issue is not None:
        warnings.append(issue.message)
    attestation = _unevidenced_attestation_warning(stripped)
    if attestation is not None:
        warnings.append(attestation)
    return tuple(warnings)


_BATCH_UNIT_SPLIT = re.compile(r"\n[ \t]*\n")


def _batch_unit_lengths(text: str) -> tuple[int, ...]:
    """Blank-line-separated note units — the validate_claims batch shape."""
    return tuple(
        len(unit)
        for unit in (chunk.strip() for chunk in _BATCH_UNIT_SPLIT.split(text))
        if unit
    )


def batch_statement_length_warnings(
    lengths: Sequence[int],
    *,
    mean_limit: int = DEFAULT_MEMORY_BATCH_MEAN_STATEMENT_CHARS,
) -> tuple[str, ...]:
    """Average-size gate over a statement batch. Warn-level, never a reject.

    Fires only for real batches (two or more statements): a single note is
    governed by the per-record target/soft/hard gates. The threshold sits
    above the live-store mean (147 chars) plus measured markdown overhead
    (~+11%) so compliant notes stay comfortable while essay drift warns.
    """
    if len(lengths) < 2:
        return ()
    mean = sum(lengths) / len(lengths)
    if mean <= mean_limit:
        return ()
    return (
        f"Batch mean statement length {round(mean)} exceeds {mean_limit} chars "
        f"across {len(lengths)} statements; compress each note to one durable "
        "fact (live-store mean is ~150 chars).",
    )


def _new_draft_record(
    *,
    project: MemoryProject,
    record_type: MemoryRecordType,
    identity: str,
    statement: str,
    payload: dict[str, object],
    now: str,
    created_by: str,
    code_fingerprint: str | None,
    created_on_branch: str | None,
    created_at_commit: str | None,
) -> MemoryRecord:
    """Build a draft agent record with the shared field defaults (status=draft,
    confidence=inferred, origin=agent). Single source for the draft shape used by
    record_candidate and promote_experience."""
    return MemoryRecord(
        id=generate_memory_id(),
        project_id=project.id,
        identity_key=identity,
        type=record_type,
        status="draft",
        confidence="inferred",
        origin="agent",
        ingest_source="agent",
        statement=statement,
        summary=None,
        payload=payload,
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by=created_by,
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=code_fingerprint,
        stale_reason=None,
        created_on_branch=created_on_branch,
        created_at_commit=created_at_commit,
        verified_on_branch=None,
        verified_at_commit=None,
    )


def record_candidate(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    record_type: MemoryRecordType,
    statement: str,
    subject_path: str | None = None,
    root_path: Path | None = None,
    created_by: str = "agent",
    max_candidates: int,
    max_statement_chars: int = DEFAULT_MEMORY_MAX_STATEMENT_CHARS,
) -> MemoryRecord:
    record_type = _validate_candidate_record_type(record_type)
    stripped = statement.strip()
    if not stripped:
        raise MemoryContractError("Candidate statement must not be empty.")
    if len(stripped) > max_statement_chars:
        raise MemoryContractError(MEMORY_STATEMENT_TOO_LONG_ERROR)
    markdown_report = validate_statement_markdown(stripped)
    if markdown_report.rejects:
        raise MemoryContractError(markdown_reject_error(markdown_report))
    if subject_path is None or not subject_path.strip():
        raise MemoryContractError(
            "record_candidate requires subject_path linking the observation to a "
            "repo file."
        )
    draft_count = store.count_records_by_status(project.id, "draft")
    if draft_count >= max_candidates:
        raise MemoryCapacityError(
            f"max_candidates_reached: {draft_count}/{max_candidates}"
        )
    now = current_report_timestamp_utc()
    normalized_path = normalize_memory_scope_path(subject_path)
    statement_digest = hashlib.sha256(statement.strip().encode("utf-8")).hexdigest()[
        :12
    ]
    subject_key = normalized_path
    identity = make_identity_key(
        type=record_type,
        subject_kind="path",
        subject_key=subject_key.replace("/", ".").removesuffix(".py"),
        discriminator=f"agent_candidate:{statement_digest}",
    )
    if store.find_by_identity_key(project.id, identity) is not None:
        msg = f"Candidate already exists for identity_key={identity}"
        raise MemoryContractError(msg)

    resolved_root = (root_path or Path(project.root)).resolve()
    git = read_git_provenance(resolved_root)
    code_fingerprint = code_fingerprint_for_memory_subject(
        resolved_root,
        subject_path=normalized_path,
    )
    anchor_available = git.available and code_fingerprint is not None

    record = _new_draft_record(
        project=project,
        record_type=record_type,
        identity=identity,
        statement=stripped,
        payload={
            "subject_path": normalized_path,
            STATEMENT_FORMAT_PAYLOAD_KEY: STATEMENT_FORMAT_MD,
        },
        now=now,
        created_by=created_by,
        code_fingerprint=code_fingerprint,
        created_on_branch=git.branch if anchor_available else None,
        created_at_commit=git.head if anchor_available else None,
    )
    store.write_record(record)
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


def promote_experience(
    store: SqliteEngineeringMemoryStore,
    *,
    project: MemoryProject,
    experience_id: str,
    record_type: MemoryRecordType = "risk_note",
    created_by: str = "agent",
    max_candidates: int,
) -> MemoryRecord:
    """Promote a distilled Experience into a human-approvable draft record.

    The draft carries the experience statement and one ``evidence_kind=trajectory``
    row per proof trajectory, then follows the normal draft -> human approve path.
    Idempotent: re-promoting the same experience is rejected. The experience keeps
    informing agents advisorily whether or not it is ever promoted.
    """
    record_type = _validate_candidate_record_type(record_type)
    experience = store.find_experience(experience_id)
    if experience is None or experience.project_id != project.id:
        raise MemoryContractError(f"Experience not found: {experience_id}")
    draft_count = store.count_records_by_status(project.id, "draft")
    if draft_count >= max_candidates:
        raise MemoryCapacityError(
            f"max_candidates_reached: {draft_count}/{max_candidates}"
        )
    now = current_report_timestamp_utc()
    family = experience.subject_family
    identity = make_identity_key(
        type=record_type,
        subject_kind="path",
        subject_key=family.replace("/", "."),
        discriminator=f"experience:{experience.experience_digest[:12]}",
    )
    existing = store.find_by_identity_key(project.id, identity)
    if existing is not None:
        raise MemoryContractError(f"Experience already promoted: record={existing.id}")
    git = read_git_provenance(Path(project.root).resolve())
    record = _new_draft_record(
        project=project,
        record_type=record_type,
        identity=identity,
        statement=experience.statement,
        payload={
            "subject_path": family,
            "promoted_from_experience": experience.id,
            "experience_digest": experience.experience_digest,
            "support": experience.support,
        },
        now=now,
        created_by=created_by,
        code_fingerprint=None,
        created_on_branch=git.branch if git.available else None,
        created_at_commit=git.head if git.available else None,
    )
    store.write_record(record)
    store.write_subject(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key=family,
            relation="about",
        )
    )
    for item in experience.evidence:
        store.write_evidence(
            MemoryEvidence(
                id=generate_memory_id(prefix="evid"),
                memory_id=record.id,
                evidence_kind="trajectory",
                ref=item.trajectory_id,
                locator=None,
                quote=None,
                digest=None,
                created_at_utc=now,
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
    warnings: list[str] = list(_statement_length_warnings(len(text.strip())))
    markdown_report = validate_statement_markdown(text)
    warnings.extend(markdown_report.warnings)
    warnings.extend(batch_statement_length_warnings(_batch_unit_lengths(text)))
    lowered = text.lower()
    errors = list(_forbidden_claim_errors(text))
    errors.extend(issue.message for issue in markdown_report.rejects)
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
    "GOVERNANCE_EMPTY_STATEMENT_CODE",
    "GOVERNANCE_RECORD_IMMUTABLE_CODE",
    "GOVERNANCE_STALE_AMENDMENT_CODE",
    "GOVERNANCE_TICKET_MISMATCH_CODE",
    "MEMORY_STATEMENT_TOO_LONG_ERROR",
    "STATEMENT_ORIGIN_AGENT",
    "STATEMENT_ORIGIN_HUMAN_AMENDED",
    "STATEMENT_ORIGIN_PAYLOAD_KEY",
    "ClaimValidationResult",
    "amend_and_approve_record",
    "apply_record_cas",
    "approve_record",
    "archive_record",
    "assert_record_amendable",
    "assert_record_unmoved",
    "batch_statement_length_warnings",
    "compute_statement_digest",
    "current_revision_number",
    "governance_refusal",
    "promote_experience",
    "record_candidate",
    "reject_record",
    "resolve_statement_origin",
    "statement_markdown_warnings",
    "supersede_approved_record",
    "validate_memory_claims",
]
