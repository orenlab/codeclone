# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from ..report.meta import current_report_timestamp_utc
from .events import (
    AuditEvent,
    AuditPayloadMode,
    compact_payload_for_event,
    generate_event_id,
)
from .schema import open_audit_db
from .validation import EventRow, validate_event_row

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
    agent_label,
    agent_pid,
    status,
    payload_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class AuditWriter(Protocol):
    def emit(self, event: AuditEvent) -> None: ...
    def close(self) -> None: ...


class NullAuditWriter:
    def emit(self, event: AuditEvent) -> None:
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
    ) -> None:
        self._conn = open_audit_db(db_path)
        self._payloads = payloads
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._closed = False
        self._gc_counter = 0
        self._gc_interval = 100
        self._conn.execute(
            "INSERT OR REPLACE INTO audit_meta(key, value) VALUES (?, ?)",
            ("retention_days", str(retention_days)),
        )
        self._conn.commit()

    def emit(self, event: AuditEvent) -> None:
        try:
            self._emit_impl(event)
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

    def _emit_impl(self, event: AuditEvent) -> None:
        row = event_to_row(event=event, payloads=self._payloads)
        validate_event_row(row)
        with self._lock:
            if self._closed:
                return
            self._conn.execute(_INSERT_SQL, row.as_tuple())
            self._conn.commit()
            self._gc_counter += 1
            if self._gc_counter >= self._gc_interval:
                self._run_retention_gc()
                self._gc_counter = 0

    def _run_retention_gc(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_text = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self._conn.execute(
            "DELETE FROM controller_events WHERE created_at_utc < ?",
            (cutoff_text,),
        )
        self._conn.commit()


def event_to_row(*, event: AuditEvent, payloads: AuditPayloadMode) -> EventRow:
    payload_json = _payload_json(event=event, payloads=payloads)
    return EventRow(
        event_id=generate_event_id(),
        event_type=event.event_type,
        severity=event.severity,
        created_at_utc=current_report_timestamp_utc(),
        repo_root_digest=event.repo_root_digest,
        run_id=event.run_id,
        intent_id=event.intent_id,
        report_digest=event.report_digest,
        agent_label=event.agent_label,
        agent_pid=event.agent_pid,
        status=event.status,
        payload_json=payload_json,
    )


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
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
    except (TypeError, ValueError):
        return "{}"


__all__ = [
    "AuditWriter",
    "NullAuditWriter",
    "SqliteAuditWriter",
    "event_to_row",
]
