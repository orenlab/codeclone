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

from ._workspace_intent_contract import (
    DEFAULT_LEASE_SECONDS,
    LEGACY_REGISTRY_VERSION,
    MAX_LEASE_SECONDS,
    MIN_LEASE_SECONDS,
    WorkspaceIntentRecord,
    compute_intent_digest,
    compute_scope_digest,
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


def _normalize_path_list(value: list[str], *, required: bool) -> list[str]:
    paths: list[str] = []
    for item in value:
        path = item.replace("\\", "/").strip()
        if not path:
            continue
        violation = _scope_path_violation(path)
        if violation is not None:
            raise ValueError(violation)
        paths.append(path.rstrip("/"))
    deduped = sorted(set(paths))
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
        return _normalize_path_list(value, required=True)

    @field_validator("allowed_related", "forbidden")
    @classmethod
    def validate_optional_paths(cls, value: list[str]) -> list[str]:
        return _normalize_path_list(value, required=False)


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

    registry_version: Literal["1", "2"]
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
    integrity: IntentIntegrityModel

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
    return payload


def parse_workspace_document(data: object) -> WorkspaceIntentDocument | None:
    if not isinstance(data, dict):
        return None
    try:
        return WorkspaceIntentDocument.model_validate(data)
    except (ValidationError, TypeError, ValueError):
        return None


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
    )


def signed_payload_dict_from_record(record: object) -> dict[str, object]:
    if not isinstance(record, WorkspaceIntentRecord):
        msg = "record must be a WorkspaceIntentRecord"
        raise TypeError(msg)
    unsigned = record.unsigned_payload()
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
    "WorkspaceIntentDocument",
    "WorkspaceIntentRowModel",
    "document_to_record_fields",
    "parse_workspace_document",
    "parse_workspace_document_json",
    "record_from_document",
    "signed_payload_dict_from_record",
    "signed_payload_json_from_record",
    "unsigned_document_payload",
]
