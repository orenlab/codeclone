# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..budget.estimator import (
    TOKEN_ESTIMATOR_CHARS_APPROX,
    TOKEN_ESTIMATOR_MODES,
    TOKEN_ESTIMATOR_TIKTOKEN,
    TokenEstimatorMode,
)
from ..utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from .events import (
    KNOWN_EVENT_TYPES,
    PAYLOAD_MODES,
    SUMMARY_TEXT_LIMIT,
    AuditPayloadMode,
    AuditSeverity,
)

AUDIT_SCHEMA_VERSION = "3"
DEFAULT_AUDIT_PATH = ".codeclone/db/audit.sqlite3"
DEFAULT_AUDIT_PAYLOADS: AuditPayloadMode = "compact"
DEFAULT_AUDIT_RETENTION_DAYS = 30
DEFAULT_AUDIT_TOKEN_ESTIMATOR: TokenEstimatorMode = TOKEN_ESTIMATOR_CHARS_APPROX
MIN_AUDIT_RETENTION_DAYS = 1
MAX_AUDIT_RETENTION_DAYS = 365

_VALID_AUDIT_SUFFIXES = frozenset({".sqlite3", ".db"})
_MAX_EVENT_ID_LEN = 48
_MAX_EVENT_TYPE_LEN = 64
_MAX_SEVERITY_LEN = 8
_MAX_TIMESTAMP_LEN = 40
_MAX_DIGEST_LEN = 128
_MAX_RUN_ID_LEN = 128
_MAX_INTENT_ID_LEN = 128
_MAX_AGENT_LABEL_LEN = 128
_MAX_STATUS_LEN = 32
MAX_PAYLOAD_JSON_LEN = 262_144


class AuditConfigError(ValueError):
    """Raised for invalid audit configuration."""


class AuditValidationError(ValueError):
    """Raised when an audit event row violates the storage contract."""


class AuditSchemaError(RuntimeError):
    """Raised for unsupported or corrupt audit database schemas."""


class AuditReadError(RuntimeError):
    """Raised when a CLI audit read cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class EventRow:
    event_id: str
    event_type: str
    severity: AuditSeverity
    created_at_utc: str
    repo_root_digest: str
    run_id: str | None
    intent_id: str | None
    report_digest: str | None
    agent_label: str
    agent_pid: int
    status: str | None
    payload_json: str
    agent_start_epoch: int | None = None
    estimated_tokens: int | None = None
    token_encoding: str | None = None
    payload_characters: int | None = None
    summary: str | None = None

    def as_tuple(self) -> tuple[object, ...]:
        return (
            self.event_id,
            self.event_type,
            self.severity,
            self.created_at_utc,
            self.repo_root_digest,
            self.run_id,
            self.intent_id,
            self.report_digest,
            self.agent_label,
            self.agent_pid,
            self.status,
            self.payload_json,
            self.agent_start_epoch,
            self.estimated_tokens,
            self.token_encoding,
            self.payload_characters,
            self.summary,
        )


def resolve_audit_path(*, root_path: Path, value: object) -> Path:
    if not isinstance(value, str):
        raise AuditConfigError("audit_path must be a string")
    raw = value.strip()
    if not raw:
        raise AuditConfigError("audit_path must not be empty")
    path = Path(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise AuditConfigError("audit_path must not contain empty, '.', or '..' parts")
    if path.suffix not in _VALID_AUDIT_SUFFIXES:
        raise AuditConfigError("audit_path must end with .sqlite3 or .db")
    try:
        return resolve_under_repo_root(
            root_path,
            path,
            policy=RepoPathPolicy(),
        )
    except PathOutsideRepoError as exc:
        raise AuditConfigError(
            "audit_path must be relative to the repository root"
        ) from exc
    except RepoPathError as exc:
        raise AuditConfigError(f"invalid audit_path: {exc}") from exc


def validate_payload_mode(value: object) -> AuditPayloadMode:
    if value not in PAYLOAD_MODES:
        expected = ", ".join(sorted(PAYLOAD_MODES))
        raise AuditConfigError(f"audit_payloads must be one of: {expected}")
    if value == "off":
        return "off"
    if value == "full":
        return "full"
    return "compact"


def validate_retention_days(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise AuditConfigError("audit_retention_days must be an integer")
    if not MIN_AUDIT_RETENTION_DAYS <= value <= MAX_AUDIT_RETENTION_DAYS:
        raise AuditConfigError(
            "audit_retention_days must be between "
            f"{MIN_AUDIT_RETENTION_DAYS} and {MAX_AUDIT_RETENTION_DAYS}"
        )
    return value


def validate_token_estimator(value: object) -> TokenEstimatorMode:
    if value not in TOKEN_ESTIMATOR_MODES:
        expected = ", ".join(sorted(TOKEN_ESTIMATOR_MODES))
        raise AuditConfigError(f"audit_token_estimator must be one of: {expected}")
    if value == TOKEN_ESTIMATOR_TIKTOKEN:
        return TOKEN_ESTIMATOR_TIKTOKEN
    return TOKEN_ESTIMATOR_CHARS_APPROX


def validate_event_row(row: EventRow) -> None:
    _validate_text(row.event_id, "event_id", max_len=_MAX_EVENT_ID_LEN)
    _validate_text(row.event_type, "event_type", max_len=_MAX_EVENT_TYPE_LEN)
    if row.event_type not in KNOWN_EVENT_TYPES:
        raise AuditValidationError(f"unknown event_type: {row.event_type}")
    _validate_text(row.severity, "severity", max_len=_MAX_SEVERITY_LEN)
    if row.severity not in {"info", "warn", "error"}:
        raise AuditValidationError(f"invalid severity: {row.severity}")
    _validate_text(row.created_at_utc, "created_at_utc", max_len=_MAX_TIMESTAMP_LEN)
    _validate_text(row.repo_root_digest, "repo_root_digest", max_len=_MAX_DIGEST_LEN)
    _validate_optional_text(row.run_id, "run_id", max_len=_MAX_RUN_ID_LEN)
    _validate_optional_text(row.intent_id, "intent_id", max_len=_MAX_INTENT_ID_LEN)
    _validate_optional_text(row.report_digest, "report_digest", max_len=_MAX_DIGEST_LEN)
    _validate_text(row.agent_label, "agent_label", max_len=_MAX_AGENT_LABEL_LEN)
    if not isinstance(row.agent_pid, int) or isinstance(row.agent_pid, bool):
        raise AuditValidationError("agent_pid must be an integer")
    if row.agent_pid <= 0:
        raise AuditValidationError("agent_pid must be positive")
    if row.agent_start_epoch is not None:
        if not isinstance(row.agent_start_epoch, int) or isinstance(
            row.agent_start_epoch, bool
        ):
            raise AuditValidationError("agent_start_epoch must be an integer")
        if row.agent_start_epoch < 0:
            raise AuditValidationError("agent_start_epoch must be non-negative")
    _validate_optional_text(row.status, "status", max_len=_MAX_STATUS_LEN)
    _validate_text(row.payload_json, "payload_json", max_len=MAX_PAYLOAD_JSON_LEN)
    _validate_optional_text(row.summary, "summary", max_len=SUMMARY_TEXT_LIMIT)


def _validate_optional_text(value: str | None, field: str, *, max_len: int) -> None:
    if value is None:
        return
    _validate_text(value, field, max_len=max_len)


def _validate_text(value: str, field: str, *, max_len: int) -> None:
    if not isinstance(value, str):
        raise AuditValidationError(f"{field} must be a string")
    if not value and field not in {"agent_label", "payload_json"}:
        raise AuditValidationError(f"{field} must not be empty")
    if len(value) > max_len:
        raise AuditValidationError(f"{field} too long")
    if "\x00" in value:
        raise AuditValidationError(f"{field} contains NUL byte")


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "DEFAULT_AUDIT_PATH",
    "DEFAULT_AUDIT_PAYLOADS",
    "DEFAULT_AUDIT_RETENTION_DAYS",
    "DEFAULT_AUDIT_TOKEN_ESTIMATOR",
    "MAX_PAYLOAD_JSON_LEN",
    "AuditConfigError",
    "AuditReadError",
    "AuditSchemaError",
    "AuditValidationError",
    "EventRow",
    "resolve_audit_path",
    "validate_event_row",
    "validate_payload_mode",
    "validate_retention_days",
    "validate_token_estimator",
]
