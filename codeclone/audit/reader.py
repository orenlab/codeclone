# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .schema import ensure_schema, get_meta
from .validation import AuditReadError, AuditSchemaError


@dataclass(frozen=True, slots=True)
class AuditRecord:
    event_id: str
    event_type: str
    severity: str
    created_at_utc: str
    run_id: str | None
    intent_id: str | None
    status: str | None
    agent_label: str


@dataclass(frozen=True, slots=True)
class AuditSummary:
    db_path: Path
    db_size_bytes: int
    retention_days: int | None
    total_events: int
    intent_events: int
    contract_events: int
    receipt_events: int
    violation_events: int
    oldest_event_utc: str | None
    latest_event_utc: str | None
    events: tuple[AuditRecord, ...]


def read_audit_summary(*, db_path: Path, limit: int = 50) -> AuditSummary:
    if not db_path.is_file():
        raise AuditReadError("no audit data")
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.Error as exc:
        raise AuditReadError(f"cannot open audit database: {exc}") from exc
    try:
        ensure_schema(conn)
        retention_days = _int_meta(conn, "retention_days")
        total = _count(conn, "SELECT COUNT(*) FROM controller_events")
        intent_events = _count(
            conn,
            "SELECT COUNT(*) FROM controller_events WHERE event_type LIKE 'intent.%'",
        )
        contract_events = _count(
            conn,
            "SELECT COUNT(*) FROM controller_events "
            "WHERE event_type IN ("
            "'patch_budget.computed',"
            "'patch_contract.verified',"
            "'patch_contract.violated',"
            "'patch_contract.expired'"
            ")",
        )
        receipt_events = _count(
            conn,
            "SELECT COUNT(*) FROM controller_events "
            "WHERE event_type = 'review_receipt.created'",
        )
        violation_events = _count(
            conn,
            "SELECT COUNT(*) FROM controller_events "
            "WHERE severity IN ('warn', 'error')",
        )
        oldest = _text_scalar(conn, "SELECT MIN(created_at_utc) FROM controller_events")
        latest = _text_scalar(conn, "SELECT MAX(created_at_utc) FROM controller_events")
        rows = conn.execute(
            "SELECT event_id, event_type, severity, created_at_utc, run_id, "
            "intent_id, status, agent_label "
            "FROM controller_events "
            "ORDER BY created_at_utc DESC, id DESC "
            "LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    except (sqlite3.Error, AuditSchemaError) as exc:
        raise AuditReadError(f"cannot read audit database: {exc}") from exc
    finally:
        conn.close()
    return AuditSummary(
        db_path=db_path,
        db_size_bytes=_db_size(db_path),
        retention_days=retention_days,
        total_events=total,
        intent_events=intent_events,
        contract_events=contract_events,
        receipt_events=receipt_events,
        violation_events=violation_events,
        oldest_event_utc=oldest,
        latest_event_utc=latest,
        events=tuple(_record_from_row(row) for row in rows),
    )


def _record_from_row(row: tuple[object, ...]) -> AuditRecord:
    return AuditRecord(
        event_id=_str_or_empty(row[0]),
        event_type=_str_or_empty(row[1]),
        severity=_str_or_empty(row[2]),
        created_at_utc=_str_or_empty(row[3]),
        run_id=_str_or_none(row[4]),
        intent_id=_str_or_none(row[5]),
        status=_str_or_none(row[6]),
        agent_label=_str_or_empty(row[7]),
    )


def _count(conn: sqlite3.Connection, sql: str) -> int:
    value = conn.execute(sql).fetchone()
    if value is None:
        return 0
    item = value[0]
    return item if isinstance(item, int) else 0


def _text_scalar(conn: sqlite3.Connection, sql: str) -> str | None:
    row = conn.execute(sql).fetchone()
    if row is None:
        return None
    return _str_or_none(row[0])


def _int_meta(conn: sqlite3.Connection, key: str) -> int | None:
    value = get_meta(conn, key)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _db_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _str_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


__all__ = ["AuditRecord", "AuditSummary", "read_audit_summary"]
