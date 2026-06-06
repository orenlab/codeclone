# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..report.meta import current_report_timestamp_utc
from .events import (
    AUDIT_EVENT_CORE_VERSION,
    AuditEvent,
    AuditPayloadMode,
    compact_payload_for_event,
    derive_workflow_id,
    event_core_for_event,
    event_summary,
    generate_event_id,
    normalize_audit_surface,
)
from .schema import open_audit_db
from .validation import EventRow, validate_event_row

if TYPE_CHECKING:
    from ..budget.estimator import TokenEstimate, TokenEstimatorMode

_INSERT_SQL = """
INSERT INTO controller_events(
    event_id,
    event_type,
    severity,
    created_at_utc,
    repo_root_digest,
    run_id,
    intent_id,
    report_digest,
    workflow_id,
    surface,
    tool_name,
    event_core_json,
    event_core_sha256,
    payload_sha256,
    agent_label,
    agent_pid,
    status,
    payload_json,
    agent_start_epoch,
    estimated_tokens,
    token_encoding,
    payload_characters,
    summary
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class AuditWriter(Protocol):
    def emit(self, event: AuditEvent) -> int | None: ...
    def close(self) -> None: ...


class NullAuditWriter:
    def emit(self, event: AuditEvent) -> int | None:
        return None

    def close(self) -> None:
        return None


class SqliteAuditWriter:
    def __init__(
        self,
        *,
        db_path: Path,
        payloads: AuditPayloadMode,
        retention_days: int,
        token_estimator: TokenEstimatorMode = "chars_approx",
    ) -> None:
        self._conn = open_audit_db(db_path)
        self._payloads = payloads
        self._retention_days = retention_days
        self._token_estimator = token_estimator
        self._lock = threading.Lock()
        self._closed = False
        self._gc_counter = 0
        self._gc_interval = 100
        self._conn.execute(
            "INSERT OR REPLACE INTO audit_meta(key, value) VALUES (?, ?)",
            ("retention_days", str(retention_days)),
        )
        self._conn.commit()

    def emit(self, event: AuditEvent) -> int | None:
        try:
            return self._emit_impl(event)
        except Exception:
            return None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self._run_retention_gc()
            finally:
                self._conn.close()
                self._closed = True

    def _emit_impl(self, event: AuditEvent) -> int | None:
        row = event_to_row(
            event=event,
            payloads=self._payloads,
            token_estimator=self._token_estimator,
        )
        validate_event_row(row)
        with self._lock:
            if self._closed:
                return None
            cursor = self._conn.execute(_INSERT_SQL, row.as_tuple())
            self._conn.commit()
            self._gc_counter += 1
            if self._gc_counter >= self._gc_interval:
                self._run_retention_gc()
                self._gc_counter = 0
            return cursor.lastrowid

    def _run_retention_gc(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_text = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self._conn.execute(
            "DELETE FROM controller_events WHERE created_at_utc < ?",
            (cutoff_text,),
        )
        self._conn.commit()


def event_to_row(
    *,
    event: AuditEvent,
    payloads: AuditPayloadMode,
    token_estimator: TokenEstimatorMode = "chars_approx",
) -> EventRow:
    event_id = generate_event_id()
    payload_json = _payload_json(event=event, payloads=payloads)
    event_core_json = _event_core_json(event)
    token_estimate = _estimate_payload_tokens(
        event.payload,
        token_estimator=token_estimator,
    )
    return EventRow(
        event_id=event_id,
        event_type=event.event_type,
        severity=event.severity,
        created_at_utc=current_report_timestamp_utc(),
        repo_root_digest=event.repo_root_digest,
        run_id=event.run_id,
        intent_id=event.intent_id,
        report_digest=event.report_digest,
        workflow_id=derive_workflow_id(event, event_id),
        surface=normalize_audit_surface(event.surface, payload=event.payload),
        tool_name=_normalized_tool_name(event.tool_name),
        event_core_json=event_core_json,
        event_core_sha256=_sha256_text(event_core_json),
        payload_sha256=None if payloads == "off" else _sha256_text(payload_json),
        agent_label=event.agent_label,
        agent_pid=event.agent_pid,
        status=event.status,
        payload_json=payload_json,
        agent_start_epoch=event.agent_start_epoch,
        estimated_tokens=token_estimate.tokens if token_estimate else None,
        token_encoding=token_estimate.encoding if token_estimate else None,
        payload_characters=token_estimate.characters if token_estimate else None,
        summary=event_summary(event.event_type, event.payload),
    )


def _estimate_payload_tokens(
    payload: Mapping[str, object] | None,
    *,
    token_estimator: TokenEstimatorMode = "chars_approx",
) -> TokenEstimate | None:
    """Estimate token count for the full original payload.

    Lazy import of ``codeclone.budget.estimator``.  Any failure
    (ImportError, encoding error, etc.) returns None — the audit writer
    never fails because of token estimation.
    """
    if payload is None:
        return None
    try:
        from ..budget.estimator import estimate_payload

        return estimate_payload(payload, estimator=token_estimator)
    except Exception:
        return None


def _payload_json(*, event: AuditEvent, payloads: AuditPayloadMode) -> str:
    if payloads == "off":
        return "{}"
    payload = (
        event.payload
        if payloads == "full"
        else compact_payload_for_event(
            event_type=event.event_type,
            payload=event.payload,
        )
    )
    if payload is None:
        return "{}"
    try:
        return _canonical_json(payload)
    except (TypeError, ValueError):
        return "{}"


def _event_core_json(event: AuditEvent) -> str:
    try:
        return _canonical_json(event_core_for_event(event))
    except (TypeError, ValueError):
        return _canonical_json(
            {
                "core_schema_version": AUDIT_EVENT_CORE_VERSION,
                "event_family": "unknown",
                "event_type": event.event_type,
                "status": event.status or "",
                "facts": {},
                "truncated": True,
            }
        )


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_tool_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


__all__ = [
    "AuditWriter",
    "NullAuditWriter",
    "SqliteAuditWriter",
    "event_to_row",
]
