# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    ValidationError,
    field_validator,
    model_validator,
)
from typing_extensions import Self

from ..models import BeforeExecutionWitness
from .contract import (
    DEFAULT_LEASE_SECONDS,
    LEGACY_REGISTRY_VERSION,
    MAX_LEASE_SECONDS,
    MIN_LEASE_SECONDS,
    REGISTRY_VERSION,
    WorkspaceDocumentRead,
    WorkspaceDocumentReadKind,
    WorkspaceIntentRecord,
    compute_intent_digest,
    compute_scope_digest,
    verify_intent_integrity,
)

_HEX_DIGEST_LENGTH = 64
_SAFE_INTENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_VALID_STATUSES = frozenset(
    {
        "active",
        "queued",
        "clean",
        "expanded",
        "violated",
        "expired",
        "orphaned",
    }
)
_VALID_DIRTY_DIGEST_STATUSES = frozenset({"ok", "unavailable"})


def _scope_path_violation(path: str) -> str | None:
    if Path(path).is_absolute() or ".." in Path(path).parts:
        return "scope paths must be repo-relative without traversal"
    return None


def _normalize_pattern_list(value: list[str]) -> list[str]:
    """Validate a ``forbidden`` deny-pattern list on a persisted document.

    Never required: an empty deny list is a legitimate scope, so there is no
    emptiness guard here to reach.
    """

    paths: list[str] = []
    for item in value:
        path = item.replace("\\", "/").strip()
        if not path:
            continue
        violation = _scope_path_violation(path)
        if violation is not None:
            raise ValueError(violation)
        paths.append(path.rstrip("/"))
    return sorted(set(paths))


def _normalize_scope_entry_list(value: list[str], *, required: bool) -> list[str]:
    """Validate a declared scope list on a persisted document.

    Two deliberate differences from :func:`_normalize_pattern_list`.

    The trailing slash is kept: it is the entire difference between an exact
    file and a directory prefix, and stripping it here would make the record's
    ``scope_digest`` disagree with the scope the door wrote.

    The grammar is **not** enforced. Records written before the grammar was
    ratified may hold a glob, and a stored intent that cannot be read is a
    coordination boundary that has silently disappeared -- foreign scope would
    stop being seen at all. The refusal belongs at the input door, where a
    caller can still act on it; here the total reader gives such an entry its
    conservative, literal reading.
    """

    entries: list[str] = []
    for item in value:
        path = item.replace("\\", "/").strip()
        if not path:
            continue
        violation = _scope_path_violation(path)
        if violation is not None:
            raise ValueError(violation)
        entries.append(path)
    deduped = sorted(set(entries))
    if required and not deduped:
        raise ValueError("allowed_files must not be empty")
    return deduped


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _is_hex_digest(value: str) -> bool:
    if len(value) != _HEX_DIGEST_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


_BEFORE_EXECUTION_KEYS = frozenset(
    {
        "execution_event_id",
        "report_semantic_id",
        "source_state_digest",
        "workspace_witness",
    }
)


def _validate_before_execution_payload(
    value: dict[str, object] | None,
) -> dict[str, object] | None:
    """Validate the persisted before-execution witness.

    Typed here rather than by a nested model for the same reason
    ``dirty_snapshot`` is: this module is not a model store, and the boundary
    ratchet admits no new structure definition on it.  An unknown key is a
    reader disagreeing with the writer about what was signed, so the record is
    refused rather than partly understood.
    """

    if value is None:
        return None
    unknown = sorted(set(value) - _BEFORE_EXECUTION_KEYS)
    if unknown:
        raise ValueError(f"before_execution has unknown keys: {unknown}")
    for name in ("execution_event_id", "report_semantic_id"):
        text = value.get(name)
        if not isinstance(text, str) or not text.strip() or len(text) > 128:
            raise ValueError(f"before_execution.{name} must be a non-empty id")
    for name in ("source_state_digest", "workspace_witness"):
        digest = value.get(name)
        if digest is not None and (
            not isinstance(digest, str) or not _is_hex_digest(digest)
        ):
            raise ValueError(f"before_execution.{name} must be null or 64-char hex")
    return value


def _validate_dirty_snapshot_payload(
    value: dict[str, object] | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    git_available = value.get("git_available")
    captured_at = value.get("captured_at_utc")
    entries = value.get("entries")
    if not isinstance(git_available, bool):
        raise ValueError("dirty_snapshot.git_available must be boolean")
    if not isinstance(captured_at, str) or _parse_utc(captured_at) is None:
        raise ValueError("dirty_snapshot.captured_at_utc must be valid UTC ISO-8601")
    if not isinstance(entries, dict):
        raise ValueError("dirty_snapshot.entries must be an object")
    for raw_path, raw_entry in entries.items():
        if not isinstance(raw_path, str) or not raw_path:
            raise ValueError("dirty_snapshot entry path must be a non-empty string")
        violation = _scope_path_violation(raw_path)
        if violation is not None:
            raise ValueError(violation)
        if not isinstance(raw_entry, dict):
            raise ValueError("dirty_snapshot entry must be an object")
        status_xy = raw_entry.get("status_xy")
        digest = raw_entry.get("digest")
        digest_status = raw_entry.get("digest_status")
        if not isinstance(status_xy, str) or len(status_xy) != 2:
            raise ValueError("dirty_snapshot.status_xy must be two characters")
        if digest is not None and (
            not isinstance(digest, str) or not _is_hex_digest(digest)
        ):
            raise ValueError("dirty_snapshot.digest must be null or 64-char hex")
        if (
            not isinstance(digest_status, str)
            or digest_status not in _VALID_DIRTY_DIGEST_STATUSES
        ):
            raise ValueError("dirty_snapshot.digest_status is invalid")
        if digest_status == "ok" and digest is None:
            raise ValueError("dirty_snapshot.digest is required when status is ok")
    return value


class IntentScopeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_files: list[str]
    allowed_related: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)

    @field_validator("allowed_files")
    @classmethod
    def validate_allowed_files(cls, value: list[str]) -> list[str]:
        return _normalize_scope_entry_list(value, required=True)

    @field_validator("allowed_related")
    @classmethod
    def validate_allowed_related(cls, value: list[str]) -> list[str]:
        return _normalize_scope_entry_list(value, required=False)

    @field_validator("forbidden")
    @classmethod
    def validate_forbidden(cls, value: list[str]) -> list[str]:
        return _normalize_pattern_list(value)


class IntentIntegrityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload_sha256: str

    @field_validator("payload_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if not _is_hex_digest(value):
            msg = "payload_sha256 must be a 64-char hex digest"
            raise ValueError(msg)
        return value.lower()


class WorkspaceIntentDocument(BaseModel):
    """Integrity-protected on-disk / SQLite JSON payload (registry v1/v2)."""

    model_config = ConfigDict(extra="forbid")

    registry_version: Literal["1", "2", "3"]
    intent_id: Annotated[str, Field(min_length=1, max_length=128)]
    agent_pid: PositiveInt
    agent_start_epoch: PositiveInt
    agent_label: str = ""
    run_id: Annotated[str, Field(min_length=1)]
    declared_at_utc: Annotated[str, Field(min_length=1)]
    expires_at_utc: Annotated[str, Field(min_length=1)]
    ttl_seconds: PositiveInt
    status: str
    intent: Annotated[str, Field(min_length=1)]
    scope: IntentScopeModel
    scope_digest: str
    blast_radius_summary: dict[str, object]
    lease_renewed_at_utc: str | None = None
    lease_seconds: PositiveInt | None = None
    report_digest: str | None = None
    dirty_snapshot: dict[str, object] | None = None
    before_execution: dict[str, object] | None = None
    integrity: IntentIntegrityModel

    @field_validator("before_execution")
    @classmethod
    def validate_before_execution(
        cls,
        value: dict[str, object] | None,
    ) -> dict[str, object] | None:
        return _validate_before_execution_payload(value)

    @field_validator("dirty_snapshot")
    @classmethod
    def validate_dirty_snapshot(
        cls,
        value: dict[str, object] | None,
    ) -> dict[str, object] | None:
        return _validate_dirty_snapshot_payload(value)

    def _contract_violations(self) -> tuple[str, ...]:
        violations: list[str] = []
        if _SAFE_INTENT_ID_RE.match(self.intent_id) is None:
            violations.append("intent_id contains unsafe characters")
        if not _is_hex_digest(self.scope_digest):
            violations.append("scope_digest must be a 64-char hex digest")
        if self.status not in _VALID_STATUSES:
            violations.append(f"invalid workspace intent status: {self.status}")
        if (self.registry_version == REGISTRY_VERSION) != (
            self.before_execution is not None
        ):
            violations.append(
                "the before-execution witness and registry version "
                f"{REGISTRY_VERSION} imply each other"
            )
        if (
            self.before_execution is not None
            and self.before_execution.get("report_semantic_id") != self.run_id
        ):
            violations.append(
                "before_execution.report_semantic_id must be the record's run_id"
            )
        if self.registry_version != LEGACY_REGISTRY_VERSION and (
            self.lease_renewed_at_utc is None
            or self.lease_seconds is None
            or self.report_digest is None
        ):
            violations.append(
                "v2 registry records require lease and report_digest fields"
            )

        lease_renewed_at, lease_seconds, _report_digest = self.normalized_lease_fields()
        if self.registry_version != LEGACY_REGISTRY_VERSION and (
            lease_seconds < MIN_LEASE_SECONDS or lease_seconds > MAX_LEASE_SECONDS
        ):
            violations.append("lease_seconds out of allowed range")

        for timestamp in (
            self.declared_at_utc,
            self.expires_at_utc,
            lease_renewed_at,
        ):
            if _parse_utc(timestamp) is None:
                violations.append("timestamp fields must be valid UTC ISO-8601")
                break

        scope_payload = self.scope.model_dump(mode="json")
        if compute_scope_digest(scope_payload) != self.scope_digest.lower():
            violations.append("scope_digest does not match scope payload")

        expected = compute_intent_digest(unsigned_document_payload(self))
        if expected != self.integrity.payload_sha256:
            violations.append("integrity.payload_sha256 mismatch")
        return tuple(violations)

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        violations = self._contract_violations()
        if violations:
            raise ValueError(violations[0])
        return self

    def normalized_lease_fields(self) -> tuple[str, int, str]:
        if self.registry_version == LEGACY_REGISTRY_VERSION:
            return (
                self.lease_renewed_at_utc or self.declared_at_utc,
                int(self.lease_seconds or DEFAULT_LEASE_SECONDS),
                self.report_digest or "",
            )
        assert self.lease_renewed_at_utc is not None
        assert self.lease_seconds is not None
        assert self.report_digest is not None
        return self.lease_renewed_at_utc, self.lease_seconds, self.report_digest


class WorkspaceIntentRowModel(BaseModel):
    """Typed SQLite row for workspace_intents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_pid: PositiveInt
    agent_start_epoch: PositiveInt
    intent_id: Annotated[str, Field(min_length=1, max_length=128)]
    declared_at_utc: Annotated[str, Field(min_length=1)]
    payload_json: Annotated[str, Field(min_length=2)]
    updated_at_utc: Annotated[str, Field(min_length=1)]
    closed_at_utc: str | None = None

    @field_validator("intent_id")
    @classmethod
    def validate_intent_id(cls, value: str) -> str:
        if _SAFE_INTENT_ID_RE.match(value) is None:
            msg = "intent_id contains unsafe characters"
            raise ValueError(msg)
        return value

    @field_validator("payload_json")
    @classmethod
    def validate_payload_json(cls, value: str) -> str:
        if parse_workspace_document_json(value) is None:
            msg = "payload_json is not a valid workspace intent document"
            raise ValueError(msg)
        return value

    @classmethod
    def from_record_fields(
        cls,
        *,
        agent_pid: int,
        agent_start_epoch: int,
        intent_id: str,
        declared_at_utc: str,
        payload_json: str,
        updated_at_utc: str,
        closed_at_utc: str | None = None,
    ) -> WorkspaceIntentRowModel:
        return cls(
            agent_pid=agent_pid,
            agent_start_epoch=agent_start_epoch,
            intent_id=intent_id,
            declared_at_utc=declared_at_utc,
            payload_json=payload_json,
            updated_at_utc=updated_at_utc,
            closed_at_utc=closed_at_utc,
        )


def unsigned_document_payload(document: WorkspaceIntentDocument) -> dict[str, object]:
    """Build the integrity-signed payload shape for registry v1/v2 wire records."""
    scope_payload = document.scope.model_dump(mode="json")
    payload: dict[str, object] = {
        "registry_version": document.registry_version,
        "intent_id": document.intent_id,
        "agent_pid": document.agent_pid,
        "agent_start_epoch": document.agent_start_epoch,
        "agent_label": document.agent_label,
        "run_id": document.run_id,
        "declared_at_utc": document.declared_at_utc,
        "expires_at_utc": document.expires_at_utc,
        "ttl_seconds": document.ttl_seconds,
        "status": document.status,
        "intent": document.intent,
        "scope": scope_payload,
        "scope_digest": document.scope_digest,
        "blast_radius_summary": document.blast_radius_summary,
    }
    if document.registry_version != LEGACY_REGISTRY_VERSION:
        lease_renewed_at_utc, lease_seconds, report_digest = (
            document.normalized_lease_fields()
        )
        payload["lease_renewed_at_utc"] = lease_renewed_at_utc
        payload["lease_seconds"] = lease_seconds
        payload["report_digest"] = report_digest
    if document.dirty_snapshot is not None:
        payload["dirty_snapshot"] = document.dirty_snapshot
    if document.before_execution is not None:
        payload["before_execution"] = document.before_execution
    return payload


def parse_workspace_document(data: object) -> WorkspaceIntentDocument | None:
    if not isinstance(data, dict):
        return None
    try:
        return WorkspaceIntentDocument.model_validate(data)
    except (ValidationError, TypeError, ValueError):
        return None


def read_workspace_payload(payload: object) -> WorkspaceDocumentRead:
    """Read one stored payload, distinguishing damage from unfamiliarity.

    The discriminator is the persisted ``integrity.payload_sha256`` and
    nothing else.  It is the writer's own digest over the canonical JSON of
    the document minus that key, and :func:`verify_intent_integrity`
    recomputes it from the raw mapping WITHOUT consulting this build's model —
    which is the whole reason it can answer for a document this build cannot
    model.  So:

    * digest verifies, model refuses → some writer produced exactly these
      bytes and they arrived intact.  The record is unreadable HERE, and it is
      live coordination state everywhere else.  Refusing to understand it is
      honest; destroying it is not.
    * digest does not verify → the bytes are attributable to no writer: not
      JSON, not an object, no digest, or a value edited under a stale one.
      Removing them is hygiene.

    The check is deliberately not "does the version look newer".  A generation
    is one of several ways a writer can outrun a reader — an added field, an
    unknown status token — and a rule keyed on the version number would be
    blind to the others while looking like it covered them.

    Never answers :attr:`WorkspaceDocumentReadKind.ABSENT`: this function is
    handed bytes, and the storage layer cannot tell a vanished file from an
    unparseable one.  Absence is decided by the lookup that went looking for a
    particular id, which is the only caller that knows it found nothing.
    """

    if isinstance(payload, str):
        try:
            data: object = json.loads(payload)
        except json.JSONDecodeError:
            return WorkspaceDocumentRead(WorkspaceDocumentReadKind.CORRUPT)
    else:
        data = payload
    if not isinstance(data, dict):
        return WorkspaceDocumentRead(WorkspaceDocumentReadKind.CORRUPT)
    document = parse_workspace_document(data)
    if document is not None:
        return WorkspaceDocumentRead.of_record(record_from_document(document))
    if verify_intent_integrity(data):
        return WorkspaceDocumentRead(WorkspaceDocumentReadKind.INCOMPATIBLE)
    return WorkspaceDocumentRead(WorkspaceDocumentReadKind.CORRUPT)


def parse_workspace_document_json(payload_json: str) -> WorkspaceIntentDocument | None:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return None
    return parse_workspace_document(payload)


def document_to_record_fields(document: WorkspaceIntentDocument) -> dict[str, object]:
    lease_renewed_at_utc, lease_seconds, report_digest = (
        document.normalized_lease_fields()
    )
    scope_payload = document.scope.model_dump(mode="json")
    return {
        "intent_id": document.intent_id,
        "agent_pid": document.agent_pid,
        "agent_start_epoch": document.agent_start_epoch,
        "agent_label": document.agent_label,
        "run_id": document.run_id,
        "declared_at_utc": document.declared_at_utc,
        "expires_at_utc": document.expires_at_utc,
        "ttl_seconds": document.ttl_seconds,
        "status": document.status,
        "intent": document.intent,
        "scope": scope_payload,
        "scope_digest": document.scope_digest,
        "blast_radius_summary": document.blast_radius_summary,
        "lease_renewed_at_utc": lease_renewed_at_utc,
        "lease_seconds": lease_seconds,
        "report_digest": report_digest,
        "dirty_snapshot": document.dirty_snapshot,
        "before_execution": _witness_from_document(document),
    }


def record_from_document(document: WorkspaceIntentDocument) -> WorkspaceIntentRecord:
    lease_renewed_at_utc, lease_seconds, report_digest = (
        document.normalized_lease_fields()
    )
    scope_payload = document.scope.model_dump(mode="json")
    return WorkspaceIntentRecord(
        intent_id=document.intent_id,
        agent_pid=document.agent_pid,
        agent_start_epoch=document.agent_start_epoch,
        agent_label=document.agent_label,
        run_id=document.run_id,
        declared_at_utc=document.declared_at_utc,
        expires_at_utc=document.expires_at_utc,
        ttl_seconds=document.ttl_seconds,
        status=document.status,
        intent=document.intent,
        scope=scope_payload,
        scope_digest=document.scope_digest,
        blast_radius_summary=document.blast_radius_summary,
        lease_renewed_at_utc=lease_renewed_at_utc,
        lease_seconds=lease_seconds,
        report_digest=report_digest,
        dirty_snapshot=document.dirty_snapshot,
        before_execution=_witness_from_document(document),
    )


def _witness_from_document(
    document: WorkspaceIntentDocument,
) -> BeforeExecutionWitness | None:
    """Carry the witness out of the wire model without re-deriving it."""

    witness = document.before_execution
    if witness is None:
        return None
    source_state = witness.get("source_state_digest")
    workspace = witness.get("workspace_witness")
    return BeforeExecutionWitness(
        execution_event_id=str(witness["execution_event_id"]),
        report_semantic_id=str(witness["report_semantic_id"]),
        source_state_digest=None if source_state is None else str(source_state),
        workspace_witness=None if workspace is None else str(workspace),
    )


def signed_payload_dict_from_record(record: object) -> dict[str, object]:
    if not isinstance(record, WorkspaceIntentRecord):
        raise TypeError("record must be a WorkspaceIntentRecord")
    raw_unsigned = record.unsigned_payload()
    provisional = {
        **raw_unsigned,
        "integrity": {"payload_sha256": compute_intent_digest(raw_unsigned)},
    }
    document = parse_workspace_document(provisional)
    if document is None:
        raise ValueError("record must contain a valid WorkspaceIntentRecord payload")
    unsigned = unsigned_document_payload(document)
    return {
        **unsigned,
        "integrity": {"payload_sha256": compute_intent_digest(unsigned)},
    }


def signed_payload_json_from_record(record: object) -> str:
    payload = signed_payload_dict_from_record(record)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


__all__ = [
    "IntentIntegrityModel",
    "IntentScopeModel",
    "WorkspaceDocumentRead",
    "WorkspaceDocumentReadKind",
    "WorkspaceIntentDocument",
    "WorkspaceIntentRowModel",
    "document_to_record_fields",
    "parse_workspace_document",
    "parse_workspace_document_json",
    "read_workspace_payload",
    "record_from_document",
    "signed_payload_dict_from_record",
    "signed_payload_json_from_record",
    "unsigned_document_payload",
]
