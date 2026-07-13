# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Bounded, batched observability writer.

A whole operation — its row plus every span — is persisted in a single sqlite
transaction. We do NOT copy the audit per-emit commit-per-row pattern. An
operation still in memory is intentionally lost on SIGKILL; telemetry is
non-authoritative and incremental flush is outside this contract.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ...utils.json_io import json_text
from ..models import OperationRecord, ProfileSample, SpanRecord

_PROFILE_NULL: tuple[None, ...] = (None,) * 8

_OPERATION_SQL = (
    "INSERT OR REPLACE INTO platform_operations("
    "operation_id, parent_operation_id, correlation_id, surface, name, "
    "started_at_utc, duration_ms, status, error_kind, session_id, "
    "repo_root_digest, request_bytes, response_bytes, request_tokens, "
    "response_tokens, rss_mb, rss_delta_mb, peak_rss_mb, peak_rss_delta_mb, "
    "cpu_user_ms, cpu_system_ms, open_fds, thread_count) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

_SPAN_SQL = (
    "INSERT OR REPLACE INTO platform_spans("
    "span_id, operation_id, parent_span_id, name, started_at_utc, duration_ms, "
    "status, reason_kind, reason, dedupe_key, counters_json, db_fingerprints, "
    "rss_mb, rss_delta_mb, peak_rss_mb, peak_rss_delta_mb, cpu_user_ms, "
    "cpu_system_ms, open_fds, thread_count) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def _profile_cols(
    profile: ProfileSample | None,
) -> tuple[object, ...]:
    if profile is None:
        return _PROFILE_NULL
    return (
        profile.rss_mb,
        profile.rss_delta_mb,
        profile.peak_rss_mb,
        profile.peak_rss_delta_mb,
        profile.cpu_user_ms,
        profile.cpu_system_ms,
        profile.open_fds,
        profile.thread_count,
    )


def _operation_row(operation: OperationRecord) -> tuple[object, ...]:
    return (
        operation.operation_id,
        operation.parent_operation_id,
        operation.correlation_id,
        operation.surface,
        operation.name,
        operation.started_at_utc,
        operation.duration_ms,
        operation.status,
        operation.error_kind,
        operation.session_id,
        operation.repo_root_digest,
        operation.request_bytes,
        operation.response_bytes,
        operation.request_tokens,
        operation.response_tokens,
        *_profile_cols(operation.profile),
    )


def _span_row(span: SpanRecord) -> tuple[object, ...]:
    counters_json = (
        json_text(dict(span.counters), sort_keys=True) if span.counters else None
    )
    db_fingerprints_json = (
        json_text(dict(span.db_fingerprints), sort_keys=True)
        if span.db_fingerprints
        else None
    )
    return (
        span.span_id,
        span.operation_id,
        span.parent_span_id,
        span.name,
        span.started_at_utc,
        span.duration_ms,
        span.status,
        span.reason_kind,
        span.reason,
        span.dedupe_key,
        counters_json,
        db_fingerprints_json,
        *_profile_cols(span.profile),
    )


def write_operation(conn: sqlite3.Connection, operation: OperationRecord) -> None:
    """Persist the operation and all its spans in one transaction."""
    with conn:
        conn.execute(_OPERATION_SQL, _operation_row(operation))
        if operation.spans:
            conn.executemany(_SPAN_SQL, [_span_row(span) for span in operation.spans])


def run_retention_gc(
    conn: sqlite3.Connection,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete expired operations and their spans in stable oldest-first order."""
    current = now if now is not None else datetime.now(timezone.utc)
    cutoff = current - timedelta(days=retention_days)
    cutoff_text = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rows = conn.execute(
        "SELECT operation_id FROM platform_operations "
        "WHERE started_at_utc < ? ORDER BY started_at_utc, operation_id",
        (cutoff_text,),
    ).fetchall()
    operation_ids = [(str(row[0]),) for row in rows]
    if not operation_ids:
        return 0
    with conn:
        conn.executemany(
            "DELETE FROM platform_spans WHERE operation_id=?",
            operation_ids,
        )
        conn.executemany(
            "DELETE FROM platform_operations WHERE operation_id=?",
            operation_ids,
        )
    return len(operation_ids)


__all__ = ["run_retention_gc", "write_operation"]
