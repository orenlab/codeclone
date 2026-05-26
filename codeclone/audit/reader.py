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
    estimated_tokens: int | None = None
    token_encoding: str | None = None
    payload_characters: int | None = None


@dataclass(frozen=True, slots=True)
class TypeTokenProfile:
    """Token stats for one event type."""

    event_type: str
    call_count: int
    total_tokens: int
    max_tokens: int


@dataclass(frozen=True, slots=True)
class TopPayload:
    """A single expensive audit payload."""

    event_type: str
    event_id: str
    estimated_tokens: int
    created_at_utc: str


@dataclass(frozen=True, slots=True)
class PayloadFootprint:
    """Aggregate payload cost analytics."""

    encoding: str
    tool_calls: int
    total_tokens: int
    avg_tokens: int
    p95_tokens: int
    max_tokens: int
    by_type: tuple[TypeTokenProfile, ...]
    top_payloads: tuple[TopPayload, ...]


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
    total_estimated_tokens: int | None = None
    token_encoding: str | None = None
    token_event_count: int = 0
    payload_footprint: PayloadFootprint | None = None


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
        token_cols = _has_token_columns(conn)
        if token_cols:
            rows = conn.execute(
                "SELECT event_id, event_type, severity, created_at_utc, run_id, "
                "intent_id, status, agent_label, "
                "estimated_tokens, token_encoding, payload_characters "
                "FROM controller_events "
                "ORDER BY created_at_utc DESC, id DESC "
                "LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            token_summary = _token_summary(conn)
        else:
            rows = conn.execute(
                "SELECT event_id, event_type, severity, created_at_utc, run_id, "
                "intent_id, status, agent_label "
                "FROM controller_events "
                "ORDER BY created_at_utc DESC, id DESC "
                "LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            token_summary = (None, None, 0)
        footprint = _read_payload_footprint(conn) if token_cols else None
    except (sqlite3.Error, AuditSchemaError) as exc:
        raise AuditReadError(f"cannot read audit database: {exc}") from exc
    finally:
        conn.close()
    total_tokens, token_enc, token_event_cnt = token_summary
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
        total_estimated_tokens=total_tokens,
        token_encoding=token_enc,
        token_event_count=token_event_cnt,
        payload_footprint=footprint,
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
        estimated_tokens=_int_or_none(row[8]) if len(row) > 8 else None,
        token_encoding=_str_or_none(row[9]) if len(row) > 9 else None,
        payload_characters=_int_or_none(row[10]) if len(row) > 10 else None,
    )


def _has_token_columns(conn: sqlite3.Connection) -> bool:
    """Check whether the controller_events table has token columns."""
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(controller_events)").fetchall()
    }
    return "estimated_tokens" in columns


def _token_summary(
    conn: sqlite3.Connection,
) -> tuple[int | None, str | None, int]:
    """Aggregate token estimation data across all events."""
    row = conn.execute(
        "SELECT SUM(estimated_tokens), COUNT(estimated_tokens) "
        "FROM controller_events WHERE estimated_tokens IS NOT NULL"
    ).fetchone()
    if row is None or row[1] == 0:
        return None, None, 0
    total_tokens = row[0] if isinstance(row[0], int) else None
    event_count = row[1] if isinstance(row[1], int) else 0
    enc_row = conn.execute(
        "SELECT token_encoding FROM controller_events "
        "WHERE token_encoding IS NOT NULL LIMIT 1"
    ).fetchone()
    encoding = _str_or_none(enc_row[0]) if enc_row else None
    return total_tokens, encoding, event_count


def payload_footprint_to_dict(fp: PayloadFootprint) -> dict[str, object]:
    """Serialize PayloadFootprint to a JSON-safe dict."""
    return {
        "encoding": fp.encoding,
        "tool_calls": fp.tool_calls,
        "total_tokens": fp.total_tokens,
        "avg_tokens": fp.avg_tokens,
        "p95_tokens": fp.p95_tokens,
        "max_tokens": fp.max_tokens,
        "by_type": {
            tp.event_type: {
                "count": tp.call_count,
                "tokens": tp.total_tokens,
                "max": tp.max_tokens,
            }
            for tp in fp.by_type
        },
        "top_payloads": [
            {
                "event_type": tp.event_type,
                "tokens": tp.estimated_tokens,
                "created_at_utc": tp.created_at_utc,
            }
            for tp in fp.top_payloads
        ],
    }


def _read_payload_footprint(conn: sqlite3.Connection) -> PayloadFootprint | None:
    """Build aggregate payload analytics from token columns."""
    agg = conn.execute(
        "SELECT COUNT(*), SUM(estimated_tokens), MAX(estimated_tokens) "
        "FROM controller_events WHERE estimated_tokens IS NOT NULL"
    ).fetchone()
    if agg is None or agg[0] == 0:
        return None
    tool_calls = agg[0] if isinstance(agg[0], int) else 0
    total_tokens = agg[1] if isinstance(agg[1], int) else 0
    max_tokens = agg[2] if isinstance(agg[2], int) else 0
    avg_tokens = total_tokens // tool_calls if tool_calls else 0

    # p95: skip top 5% rows, take the next one
    p95_offset = max(0, tool_calls * 5 // 100)
    p95_row = conn.execute(
        "SELECT estimated_tokens FROM controller_events "
        "WHERE estimated_tokens IS NOT NULL "
        "ORDER BY estimated_tokens DESC "
        "LIMIT 1 OFFSET ?",
        (p95_offset,),
    ).fetchone()
    p95_tokens = p95_row[0] if p95_row and isinstance(p95_row[0], int) else max_tokens

    # Breakdown by event_type
    type_rows = conn.execute(
        "SELECT event_type, COUNT(*), SUM(estimated_tokens), MAX(estimated_tokens) "
        "FROM controller_events WHERE estimated_tokens IS NOT NULL "
        "GROUP BY event_type ORDER BY SUM(estimated_tokens) DESC"
    ).fetchall()
    by_type = tuple(
        TypeTokenProfile(
            event_type=_str_or_empty(r[0]),
            call_count=r[1] if isinstance(r[1], int) else 0,
            total_tokens=r[2] if isinstance(r[2], int) else 0,
            max_tokens=r[3] if isinstance(r[3], int) else 0,
        )
        for r in type_rows
    )

    # Top 5 most expensive payloads
    top_rows = conn.execute(
        "SELECT event_type, event_id, estimated_tokens, created_at_utc "
        "FROM controller_events WHERE estimated_tokens IS NOT NULL "
        "ORDER BY estimated_tokens DESC LIMIT 5"
    ).fetchall()
    top_payloads = tuple(
        TopPayload(
            event_type=_str_or_empty(r[0]),
            event_id=_str_or_empty(r[1]),
            estimated_tokens=r[2] if isinstance(r[2], int) else 0,
            created_at_utc=_str_or_empty(r[3]),
        )
        for r in top_rows
    )

    # Encoding (single value for the session)
    enc_row = conn.execute(
        "SELECT token_encoding FROM controller_events "
        "WHERE token_encoding IS NOT NULL LIMIT 1"
    ).fetchone()
    encoding = _str_or_none(enc_row[0]) if enc_row else "unknown"

    return PayloadFootprint(
        encoding=encoding or "unknown",
        tool_calls=tool_calls,
        total_tokens=total_tokens,
        avg_tokens=avg_tokens,
        p95_tokens=p95_tokens,
        max_tokens=max_tokens,
        by_type=by_type,
        top_payloads=top_payloads,
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


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "AuditRecord",
    "AuditSummary",
    "PayloadFootprint",
    "TopPayload",
    "TypeTokenProfile",
    "payload_footprint_to_dict",
    "read_audit_summary",
]
