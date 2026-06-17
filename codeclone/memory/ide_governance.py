# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NoReturn

from ..contracts import IDE_GOVERNANCE_PROTOCOL_VERSION
from .exceptions import MemoryContractError
from .governance import approve_record, archive_record, reject_record
from .models import MemoryRecord
from .project import compute_project_id
from .sqlite_store import SqliteEngineeringMemoryStore

IDE_GOVERNANCE_TICKET_TTL_SECONDS = 120
IDE_GOVERNANCE_MIN_KEY_BYTES = 32
IDE_GOVERNANCE_MAX_COMMIT_ATTEMPTS = 100
IDE_GOVERNANCE_ALLOWED_CLIENTS = frozenset({"CodeClone VS Code"})

GovernanceDecision = Literal["approve", "reject", "archive"]
GovernanceAction = Literal[
    "register_ide_governance",
    "prepare_governance",
    "commit_governance",
]

GOVERNANCE_MODE_UNAVAILABLE_MESSAGE = (
    "This action is only available through the CodeClone VS Code IDE governance "
    "channel."
)
GOVERNANCE_MODE_UNAVAILABLE_NEXT_STEP = (
    "Use the Memory view in the CodeClone extension to approve or reject draft records."
)


@dataclass(slots=True)
class IdeGovernanceTicket:
    ticket_id: str
    record_id: str
    decision: GovernanceDecision
    confirmation_nonce: str
    project_id: str
    statement_digest: str
    expires_at_unix: float
    consumed: bool = False


@dataclass(slots=True)
class IdeGovernanceSessionState:
    channel_enabled: bool = False
    governance_key: bytes | None = None
    client_name: str | None = None
    client_version: str | None = None
    tickets: dict[str, IdeGovernanceTicket] = field(default_factory=dict)
    commit_attempts: int = 0


def compute_statement_digest(statement: str) -> str:
    normalized = statement.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _canonical_proof_message(
    *,
    ticket_id: str,
    record_id: str,
    decision: str,
    confirmation_nonce: str,
    project_id: str,
    statement_digest: str,
    protocol: int,
) -> bytes:
    return (
        f"v{protocol}|{ticket_id}|{record_id}|{decision}|{confirmation_nonce}|"
        f"{project_id}|{statement_digest}"
    ).encode()


def compute_governance_proof(
    key: bytes,
    *,
    ticket_id: str,
    record_id: str,
    decision: str,
    confirmation_nonce: str,
    project_id: str,
    statement_digest: str,
    protocol: int = IDE_GOVERNANCE_PROTOCOL_VERSION,
) -> str:
    message = _canonical_proof_message(
        ticket_id=ticket_id,
        record_id=record_id,
        decision=decision,
        confirmation_nonce=confirmation_nonce,
        project_id=project_id,
        statement_digest=statement_digest,
        protocol=protocol,
    )
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _raise_memory_contract(
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    if cause is None:
        raise MemoryContractError(message)
    raise MemoryContractError(message) from cause


def _parse_governance_key(raw_key: str) -> bytes:
    cleaned = raw_key.strip().lower()
    if cleaned.startswith("0x"):
        cleaned = cleaned[2:]
    if len(cleaned) % 2 != 0:
        _raise_memory_contract("ide_governance_key hex length must be even.")
    try:
        key = bytes.fromhex(cleaned)
    except ValueError as exc:
        _raise_memory_contract(
            "ide_governance_key must be valid hexadecimal.",
            cause=exc,
        )
    if len(key) < IDE_GOVERNANCE_MIN_KEY_BYTES:
        _raise_memory_contract(
            "ide_governance_key must be at least 32 bytes (64 hex characters)."
        )
    return key


def _validate_ide_governance_protocol(protocol: int) -> None:
    if protocol != IDE_GOVERNANCE_PROTOCOL_VERSION:
        _raise_memory_contract(
            f"Unsupported ide_attestation protocol {protocol!r}. "
            f"Expected {IDE_GOVERNANCE_PROTOCOL_VERSION}."
        )


def _governance_key_or_reject(
    state: IdeGovernanceSessionState,
    *,
    action: str,
) -> bytes | dict[str, object]:
    key = state.governance_key
    if key is None:
        return _governance_rejected(
            action,
            reason="governance_key_missing",
        )
    return key


def _assert_ticket_request_matches(
    ticket: IdeGovernanceTicket,
    *,
    record_id: str,
    decision: GovernanceDecision,
    project_id: str,
    statement_digest: str,
) -> None:
    if (
        ticket.record_id != record_id
        or ticket.decision != decision
        or ticket.project_id != project_id
        or ticket.statement_digest != statement_digest
    ):
        _raise_memory_contract("Governance ticket does not match the commit request.")


def _require_matching_confirmation_nonce(
    ticket: IdeGovernanceTicket,
    confirmation_nonce: str,
) -> None:
    if confirmation_nonce != ticket.confirmation_nonce:
        _raise_memory_contract(
            "confirmation_nonce does not match the prepared governance ticket."
        )


def _require_valid_governance_proof(
    *,
    key: bytes,
    ticket_id: str,
    record_id: str,
    decision: GovernanceDecision,
    confirmation_nonce: str,
    project_id: str,
    statement_digest: str,
    protocol: int,
    proof: str,
) -> None:
    expected_proof = compute_governance_proof(
        key,
        ticket_id=ticket_id,
        record_id=record_id,
        decision=decision,
        confirmation_nonce=confirmation_nonce,
        project_id=project_id,
        statement_digest=statement_digest,
        protocol=protocol,
    )
    if not hmac.compare_digest(expected_proof, proof.strip().lower()):
        _raise_memory_contract("Invalid IDE governance proof.")


def _register_commit_attempt(
    state: IdeGovernanceSessionState,
    *,
    action: str,
) -> dict[str, object] | None:
    if state.commit_attempts >= IDE_GOVERNANCE_MAX_COMMIT_ATTEMPTS:
        return _governance_rejected(
            action,
            reason="governance_rate_limited",
            message=(
                "IDE governance commit attempt limit reached for this MCP session. "
                "Restart the CodeClone MCP session before further governance commits."
            ),
        )
    state.commit_attempts += 1
    return None


def _resolve_client_label(state: IdeGovernanceSessionState) -> str:
    name = state.client_name or "unknown-client"
    version = state.client_version
    if version:
        return f"{name}/{version}"
    return name


def _governance_rejected(
    action: str,
    *,
    reason: str = "governance_mode_unavailable",
    message: str = GOVERNANCE_MODE_UNAVAILABLE_MESSAGE,
) -> dict[str, object]:
    return {
        "action": action,
        "status": "rejected",
        "reason": reason,
        "message": message,
        "next_step": GOVERNANCE_MODE_UNAVAILABLE_NEXT_STEP,
    }


def _require_governance_channel(
    state: IdeGovernanceSessionState,
    *,
    action: str,
) -> dict[str, object] | None:
    if not state.channel_enabled:
        return _governance_rejected(action)
    if state.governance_key is None and action != "register_ide_governance":
        return _governance_rejected(
            action,
            reason="governance_key_missing",
            message=(
                "IDE governance channel is active but no session key is registered. "
                "Reconnect the CodeClone VS Code extension."
            ),
        )
    if (
        action != "register_ide_governance"
        and state.client_name not in IDE_GOVERNANCE_ALLOWED_CLIENTS
    ):
        return _governance_rejected(action)
    return None


def _validate_repository_project(project_id: str, root_path: str | Path) -> None:
    expected_project_id = compute_project_id(Path(root_path))
    if project_id != expected_project_id:
        _raise_memory_contract(
            "Memory project identity does not match the requested repository root."
        )


def _find_project_record(
    store: SqliteEngineeringMemoryStore,
    *,
    record_id: str,
    project_id: str,
) -> MemoryRecord | None:
    record = store.find_record(record_id)
    if record is None or record.project_id != project_id:
        return None
    return record


def _validate_decision(decision: str) -> GovernanceDecision:
    normalized = decision.strip().lower()
    if normalized not in {"approve", "reject", "archive"}:
        _raise_memory_contract(f"Unknown governance decision: {decision!r}")
    return normalized  # type: ignore[return-value]


def _validate_record_for_decision(
    record: MemoryRecord,
    decision: GovernanceDecision,
) -> None:
    # Mirror governance.py: approve accepts {draft, stale}, reject accepts only
    # draft (stale is discarded via vacuum, never human-rejected — see the
    # trust-and-lifecycle state machine), archive accepts only active. Keeps the
    # IDE channel consistent with reject_record so a VS Code reject on a stale
    # record fails here with a clear message instead of raising downstream.
    allowed_by_decision: dict[GovernanceDecision, frozenset[str]] = {
        "approve": frozenset({"draft", "stale"}),
        "reject": frozenset({"draft"}),
        "archive": frozenset({"active"}),
    }
    if record.status not in allowed_by_decision[decision]:
        _raise_memory_contract(f"Cannot {decision} record in status '{record.status}'")


def register_ide_governance(
    state: IdeGovernanceSessionState,
    *,
    ide_governance_key: str,
    client_name: str,
    client_version: str | None,
) -> dict[str, object]:
    rejected = _require_governance_channel(state, action="register_ide_governance")
    if rejected is not None:
        return rejected
    if client_name not in IDE_GOVERNANCE_ALLOWED_CLIENTS:
        return _governance_rejected("register_ide_governance")
    key = _parse_governance_key(ide_governance_key)
    state.governance_key = key
    state.client_name = client_name
    state.client_version = client_version
    state.tickets.clear()
    state.commit_attempts = 0
    return {
        "action": "register_ide_governance",
        "status": "ok",
        "protocol": IDE_GOVERNANCE_PROTOCOL_VERSION,
        "client_name": client_name,
        "client_version": client_version,
        "max_commit_attempts": IDE_GOVERNANCE_MAX_COMMIT_ATTEMPTS,
    }


def prepare_governance(
    state: IdeGovernanceSessionState,
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    root_path: str | Path,
    record_id: str,
    decision: str,
) -> dict[str, object]:
    rejected = _require_governance_channel(state, action="prepare_governance")
    if rejected is not None:
        return rejected
    normalized_decision = _validate_decision(decision)
    record = _find_project_record(
        store,
        record_id=record_id,
        project_id=project_id,
    )
    if record is None:
        return {
            "action": "prepare_governance",
            "status": "not_found",
            "record_id": record_id,
        }
    _validate_record_for_decision(record, normalized_decision)
    _validate_repository_project(project_id, root_path)
    statement_digest = compute_statement_digest(record.statement)
    ticket_id = secrets.token_hex(16)
    nonce = secrets.token_hex(16)
    ticket = IdeGovernanceTicket(
        ticket_id=ticket_id,
        record_id=record_id,
        decision=normalized_decision,
        confirmation_nonce=nonce,
        project_id=project_id,
        statement_digest=statement_digest,
        expires_at_unix=time.time() + IDE_GOVERNANCE_TICKET_TTL_SECONDS,
    )
    state.tickets[ticket_id] = ticket
    subjects = store.list_subjects_for_memory(record.id)
    return {
        "action": "prepare_governance",
        "status": "ok",
        "protocol": IDE_GOVERNANCE_PROTOCOL_VERSION,
        "governance_ticket": ticket_id,
        "expires_at_unix": ticket.expires_at_unix,
        "confirmation_nonce": nonce,
        "project_id": project_id,
        "statement_digest": statement_digest,
        "record": {
            "id": record.id,
            "type": record.type,
            "status": record.status,
            "statement": record.statement,
            "confidence": record.confidence,
            "subjects": [
                {
                    "subject_kind": item.subject_kind,
                    "subject_key": item.subject_key,
                    "relation": item.relation,
                }
                for item in subjects
            ],
        },
    }


def _consume_ticket(
    state: IdeGovernanceSessionState,
    *,
    ticket_id: str,
    record_id: str,
    decision: GovernanceDecision,
    project_id: str,
    statement_digest: str,
) -> IdeGovernanceTicket:
    ticket = state.tickets.get(ticket_id)
    if ticket is None:
        _raise_memory_contract(f"Unknown or expired governance ticket: {ticket_id!r}")
    if ticket.consumed:
        _raise_memory_contract("Governance ticket was already used.")
    if time.time() > ticket.expires_at_unix:
        state.tickets.pop(ticket_id, None)
        _raise_memory_contract(
            "Governance ticket expired. Prepare governance again from the IDE."
        )
    _assert_ticket_request_matches(
        ticket,
        record_id=record_id,
        decision=decision,
        project_id=project_id,
        statement_digest=statement_digest,
    )
    ticket.consumed = True
    return ticket


def commit_governance(
    state: IdeGovernanceSessionState,
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    root_path: str | Path,
    record_id: str,
    decision: str,
    governance_ticket: str,
    confirmation_nonce: str,
    proof: str,
    actor: str,
    protocol: int,
) -> dict[str, object]:
    rejected = _require_governance_channel(state, action="commit_governance")
    if rejected is not None:
        return rejected
    rate_limited = _register_commit_attempt(state, action="commit_governance")
    if rate_limited is not None:
        return rate_limited
    _validate_ide_governance_protocol(protocol)
    key_or_rejected = _governance_key_or_reject(
        state,
        action="commit_governance",
    )
    if isinstance(key_or_rejected, dict):
        return key_or_rejected
    key = key_or_rejected
    normalized_decision = _validate_decision(decision)
    record = _find_project_record(
        store,
        record_id=record_id,
        project_id=project_id,
    )
    if record is None:
        return {
            "action": "commit_governance",
            "status": "not_found",
            "record_id": record_id,
        }
    _validate_repository_project(project_id, root_path)
    statement_digest = compute_statement_digest(record.statement)
    ticket = _consume_ticket(
        state,
        ticket_id=governance_ticket,
        record_id=record_id,
        decision=normalized_decision,
        project_id=project_id,
        statement_digest=statement_digest,
    )
    _require_matching_confirmation_nonce(ticket, confirmation_nonce)
    _require_valid_governance_proof(
        key=key,
        ticket_id=governance_ticket,
        record_id=record_id,
        decision=normalized_decision,
        confirmation_nonce=confirmation_nonce,
        project_id=project_id,
        statement_digest=statement_digest,
        protocol=protocol,
        proof=proof,
    )
    _validate_record_for_decision(record, normalized_decision)
    actor_label = actor.strip() or _resolve_client_label(state)
    if normalized_decision == "approve":
        updated = approve_record(
            store,
            record_id=record_id,
            approved_by=actor_label,
            revision_reason="ide_govern_approve",
        )
    elif normalized_decision == "reject":
        updated = reject_record(
            store,
            record_id=record_id,
            rejected_by=actor_label,
            reason="ide_govern_reject",
            revision_reason="ide_govern_reject",
        )
    else:
        updated = archive_record(
            store,
            record_id=record_id,
            archived_by=actor_label,
            revision_reason="ide_govern_archive",
        )
    state.tickets.pop(governance_ticket, None)
    return {
        "action": "commit_governance",
        "status": "ok",
        "record_id": updated.id,
        "record_status": updated.status,
        "approved_by": updated.approved_by,
    }


__all__ = [
    "GOVERNANCE_MODE_UNAVAILABLE_MESSAGE",
    "GOVERNANCE_MODE_UNAVAILABLE_NEXT_STEP",
    "IDE_GOVERNANCE_ALLOWED_CLIENTS",
    "IDE_GOVERNANCE_MAX_COMMIT_ATTEMPTS",
    "IDE_GOVERNANCE_PROTOCOL_VERSION",
    "IDE_GOVERNANCE_TICKET_TTL_SECONDS",
    "IdeGovernanceSessionState",
    "IdeGovernanceTicket",
    "commit_governance",
    "compute_governance_proof",
    "compute_statement_digest",
    "prepare_governance",
    "register_ide_governance",
]
