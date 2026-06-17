# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from ..audit.reader import (
    AuditSummary,
    payload_footprint_to_dict,
    read_audit_summary,
)
from ..audit.validation import (
    DEFAULT_AUDIT_PATH,
    AuditConfigError,
    AuditReadError,
    resolve_audit_path,
)
from ..config.pyproject_loader import load_pyproject_config

AUDIT_NOT_ENABLED_MESSAGE = (
    "Controller audit trail is disabled. Set audit_enabled=true in pyproject.toml "
    "to record MCP controller events."
)


def _load_audit_db_path(root_path: Path, audit_path_value: str | None) -> Path:
    config = load_pyproject_config(root_path)
    if not bool(config.get("audit_enabled", False)):
        raise AuditConfigError(AUDIT_NOT_ENABLED_MESSAGE)
    configured = audit_path_value or config.get("audit_path", DEFAULT_AUDIT_PATH)
    return resolve_audit_path(root_path=root_path, value=configured)


def audit_summary_to_payload(summary: AuditSummary) -> dict[str, object]:
    events = [
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "severity": event.severity,
            "created_at_utc": event.created_at_utc,
            "run_id": event.run_id,
            "intent_id": event.intent_id,
            "status": event.status,
            "agent_label": event.agent_label,
            "summary": event.summary,
            "estimated_tokens": event.estimated_tokens,
            "token_encoding": event.token_encoding,
            "payload_characters": event.payload_characters,
        }
        for event in summary.events
    ]
    footprint = (
        payload_footprint_to_dict(summary.payload_footprint)
        if summary.payload_footprint is not None
        else None
    )
    return {
        "status": "ok",
        "database": {
            "path": str(summary.db_path),
            "size_bytes": summary.db_size_bytes,
            "retention_days": summary.retention_days,
        },
        "counts": {
            "total_events": summary.total_events,
            "intent_events": summary.intent_events,
            "contract_events": summary.contract_events,
            "receipt_events": summary.receipt_events,
            "violation_events": summary.violation_events,
        },
        "time_range": {
            "oldest_event_utc": summary.oldest_event_utc,
            "latest_event_utc": summary.latest_event_utc,
        },
        "token_summary": {
            "total_estimated_tokens": summary.total_estimated_tokens,
            "token_encoding": summary.token_encoding,
            "token_event_count": summary.token_event_count,
        },
        "payload_footprint": footprint,
        "events": events,
    }


def controller_audit_trail_payload(
    root_path: Path,
    *,
    limit: int = 50,
    audit_path_value: str | None = None,
) -> dict[str, object]:
    try:
        db_path = _load_audit_db_path(root_path, audit_path_value)
        summary = read_audit_summary(db_path=db_path, limit=limit)
    except AuditConfigError as exc:
        return {
            "status": "disabled",
            "message": str(exc),
            "counts": {
                "total_events": 0,
                "intent_events": 0,
                "contract_events": 0,
                "receipt_events": 0,
                "violation_events": 0,
            },
            "events": [],
            "payload_footprint": None,
        }
    except AuditReadError as exc:
        return {
            "status": "empty",
            "message": str(exc),
            "counts": {
                "total_events": 0,
                "intent_events": 0,
                "contract_events": 0,
                "receipt_events": 0,
                "violation_events": 0,
            },
            "events": [],
            "payload_footprint": None,
        }
    return audit_summary_to_payload(summary)


__all__ = [
    "AUDIT_NOT_ENABLED_MESSAGE",
    "audit_summary_to_payload",
    "controller_audit_trail_payload",
]
