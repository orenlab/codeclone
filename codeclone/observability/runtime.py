# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Observability write API (Phase 29 §4.3).

``bootstrap`` freezes the enabled decision once per process. When disabled,
``operation``/``span`` yield a cheap inert handle and return immediately — no
clock, no id, no contextvar, no store import (the near-zero-overhead contract).
When enabled, spans accumulate on their operation and the whole operation is
flushed in a single transaction on exit.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from ..config.observability import ObservabilityConfig, resolve_observability_config
from .models import OperationRecord, ProfileSample, SpanRecord
from .reason_kind import ReasonKind

_ENABLED: bool = False
_RUNTIME: _ActiveRuntime | None = None
_CURRENT_OP: ContextVar[OperationHandle | None] = ContextVar("_obs_op", default=None)
_CURRENT_SPAN: ContextVar[SpanHandle | None] = ContextVar("_obs_span", default=None)


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_id() -> str:
    return uuid.uuid4().hex


class OperationHandle:
    """Mutable accumulator for a surface operation and its spans."""

    def __init__(
        self,
        *,
        operation_id: str,
        correlation_id: str,
        surface: str,
        name: str,
        started_at_utc: str,
        parent_operation_id: str | None,
        session_id: str | None,
        repo_root_digest: str | None,
    ) -> None:
        self.operation_id = operation_id
        self.correlation_id = correlation_id
        self._surface = surface
        self._name = name
        self._started_at_utc = started_at_utc
        self._parent_operation_id = parent_operation_id
        self._session_id = session_id
        self._repo_root_digest = repo_root_digest
        self._status = "ok"
        self._error_kind: str | None = None
        self._request_bytes: int | None = None
        self._response_bytes: int | None = None
        self._request_tokens: int | None = None
        self._response_tokens: int | None = None
        self._spans: list[SpanRecord] = []

    # Wired by the 29.9 MCP registrar (per-tool request/response payload sizes).
    def set_request(
        self, *, request_bytes: int | None = None, request_tokens: int | None = None
    ) -> None:
        if request_bytes is not None:
            self._request_bytes = request_bytes
        if request_tokens is not None:
            self._request_tokens = request_tokens

    def set_response(
        self, *, response_bytes: int | None = None, response_tokens: int | None = None
    ) -> None:
        if response_bytes is not None:
            self._response_bytes = response_bytes
        if response_tokens is not None:
            self._response_tokens = response_tokens

    def _to_record(
        self, *, duration_ms: float, profile: ProfileSample | None = None
    ) -> OperationRecord:
        return OperationRecord(
            operation_id=self.operation_id,
            correlation_id=self.correlation_id,
            surface=self._surface,
            name=self._name,
            started_at_utc=self._started_at_utc,
            duration_ms=duration_ms,
            status=self._status,
            parent_operation_id=self._parent_operation_id,
            error_kind=self._error_kind,
            session_id=self._session_id,
            repo_root_digest=self._repo_root_digest,
            request_bytes=self._request_bytes,
            response_bytes=self._response_bytes,
            request_tokens=self._request_tokens,
            response_tokens=self._response_tokens,
            profile=profile,
            spans=tuple(self._spans),
        )


class SpanHandle:
    """Mutable accumulator for a single span (stage/subsystem)."""

    def __init__(
        self,
        *,
        span_id: str,
        operation_id: str,
        name: str,
        started_at_utc: str,
        parent_span_id: str | None,
        reason_kind: ReasonKind | None,
        reason: str | None,
        dedupe_key: str | None,
    ) -> None:
        self.span_id = span_id
        self._operation_id = operation_id
        self._name = name
        self._started_at_utc = started_at_utc
        self._parent_span_id = parent_span_id
        self._reason_kind = reason_kind
        self._reason = reason
        self._dedupe_key = dedupe_key
        self._status = "ok"
        self._counters: dict[str, int] = {}

    # set_counter is wired by the 29.10 worker instrumentation; add_counter by
    # the 29.DB query-trace hook (record_db_query). set_reason_kind stays
    # forward-declared until a caller needs post-hoc reason classification.
    def add_counter(self, key: str, value: int = 1) -> None:
        self._counters[key] = self._counters.get(key, 0) + value

    def set_counter(self, key: str, value: int) -> None:
        self._counters[key] = value

    # codeclone: ignore[dead-code]
    def set_reason_kind(self, reason_kind: ReasonKind) -> None:
        self._reason_kind = reason_kind

    def _to_record(
        self, *, duration_ms: float, profile: ProfileSample | None = None
    ) -> SpanRecord:
        return SpanRecord(
            span_id=self.span_id,
            operation_id=self._operation_id,
            name=self._name,
            started_at_utc=self._started_at_utc,
            duration_ms=duration_ms,
            status=self._status,
            parent_span_id=self._parent_span_id,
            reason_kind=self._reason_kind,
            reason=self._reason,
            dedupe_key=self._dedupe_key,
            counters=dict(self._counters),
            profile=profile,
        )


def _inert_operation() -> OperationHandle:
    return OperationHandle(
        operation_id="",
        correlation_id="",
        surface="",
        name="",
        started_at_utc="",
        parent_operation_id=None,
        session_id=None,
        repo_root_digest=None,
    )


def _inert_span() -> SpanHandle:
    return SpanHandle(
        span_id="",
        operation_id="",
        name="",
        started_at_utc="",
        parent_span_id=None,
        reason_kind=None,
        reason=None,
        dedupe_key=None,
    )


class _ActiveRuntime:
    """Holds the config + lazily-opened store; flushes finished operations.

    The store modules are imported only here (never at module load), so a
    disabled process never imports the observability store.
    """

    def __init__(self, config: ObservabilityConfig, *, root: Path | None) -> None:
        self.config = config
        self.session_id: str | None = None
        self._root = root
        self._conn: object | None = None

    def bind_root(self, root: Path) -> None:
        # First rooted call wins: an MCP server bootstraps root-less, then binds
        # the store to the root of the first tool that carries one.
        if self._root is None:
            self._root = root

    def persist(self, record: OperationRecord) -> None:
        # Persisted to the per-root store; a root-less enabled session simply
        # drops the record (no in-memory ring in the MVP).
        if self.config.persist and self._root is not None:
            self._write(record)

    def _write(self, record: OperationRecord) -> None:
        from .store.schema import observability_store_path, open_observability_store
        from .store.writer import write_operation

        if self._conn is None:
            assert self._root is not None
            self._conn = open_observability_store(observability_store_path(self._root))
        import sqlite3

        assert isinstance(self._conn, sqlite3.Connection)
        write_operation(self._conn, record)

    def close(self) -> None:
        if self._conn is not None:
            import sqlite3

            if isinstance(self._conn, sqlite3.Connection):
                self._conn.close()
            self._conn = None


def bootstrap(
    config: ObservabilityConfig | None = None,
    *,
    root: Path | None = None,
    session_id: str | None = None,
) -> None:
    """Freeze the enabled decision for this process and install the runtime."""
    global _ENABLED, _RUNTIME
    cfg = config if config is not None else resolve_observability_config()
    _ENABLED = cfg.enabled
    if cfg.enabled:
        runtime = _ActiveRuntime(cfg, root=root)
        runtime.session_id = session_id
        _RUNTIME = runtime
    else:
        _RUNTIME = None


def shutdown() -> None:
    """Close the store and reset process state (mainly for tests)."""
    global _ENABLED, _RUNTIME
    if _RUNTIME is not None:
        _RUNTIME.close()
    _ENABLED = False
    _RUNTIME = None


def is_observability_enabled() -> bool:
    return _ENABLED


def current_operation_context() -> tuple[str, str] | None:
    """Return ``(operation_id, correlation_id)`` of the active operation for
    cross-process handoff, or ``None`` when disabled or outside an operation.
    """
    op = _CURRENT_OP.get()
    if op is None or not op.operation_id:
        return None
    return op.operation_id, op.correlation_id


def bind_root(root: Path) -> None:
    """Bind the store to ``root`` if the active runtime has none yet (no-op when
    disabled). Lets a root-less MCP-server session open its store on the first
    tool call that carries a ``root``.
    """
    runtime = _RUNTIME
    if _ENABLED and runtime is not None:
        runtime.bind_root(root)


def payload_capture_enabled() -> bool:
    """True when enabled and payload-size capture is configured on."""
    runtime = _RUNTIME
    return bool(
        _ENABLED and runtime is not None and runtime.config.capture_payload_sizes
    )


def _profile_baseline() -> tuple[int, float, float] | None:
    """Capture an rss/cpu baseline when profiling is on (else None, no psutil)."""
    runtime = _RUNTIME
    if _ENABLED and runtime is not None and runtime.config.profile:
        from .profile import capture_rss_cpu

        return capture_rss_cpu()
    return None


def _profile_sample(baseline: tuple[int, float, float] | None) -> ProfileSample | None:
    if baseline is None:
        return None
    from .profile import build_profile_sample

    return build_profile_sample(baseline)


@contextmanager
def operation(
    *,
    name: str,
    surface: str,
    correlation_id: str | None = None,
    parent_operation_id: str | None = None,
    session_id: str | None = None,
    repo_root_digest: str | None = None,
) -> Iterator[OperationHandle]:
    runtime = _RUNTIME
    if not _ENABLED or runtime is None:
        yield _inert_operation()
        return
    operation_id = _new_id()
    handle = OperationHandle(
        operation_id=operation_id,
        correlation_id=correlation_id or operation_id,
        surface=surface,
        name=name,
        started_at_utc=_now_utc(),
        parent_operation_id=parent_operation_id,
        session_id=session_id or runtime.session_id,
        repo_root_digest=repo_root_digest,
    )
    token = _CURRENT_OP.set(handle)
    baseline = _profile_baseline()
    start = time.perf_counter()
    try:
        yield handle
    except Exception as exc:
        handle._status = "error"
        handle._error_kind = type(exc).__name__
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _CURRENT_OP.reset(token)
        runtime.persist(
            handle._to_record(
                duration_ms=duration_ms, profile=_profile_sample(baseline)
            )
        )


@contextmanager
def span(
    *,
    name: str,
    reason: str | None = None,
    reason_kind: ReasonKind | None = None,
    dedupe_key: str | None = None,
) -> Iterator[SpanHandle]:
    runtime = _RUNTIME
    parent_op = _CURRENT_OP.get()
    if not _ENABLED or runtime is None or parent_op is None:
        yield _inert_span()
        return
    parent_span = _CURRENT_SPAN.get()
    handle = SpanHandle(
        span_id=_new_id(),
        operation_id=parent_op.operation_id,
        name=name,
        started_at_utc=_now_utc(),
        parent_span_id=parent_span.span_id if parent_span is not None else None,
        reason_kind=reason_kind,
        reason=reason,
        dedupe_key=dedupe_key,
    )
    token = _CURRENT_SPAN.set(handle)
    baseline = _profile_baseline()
    start = time.perf_counter()
    try:
        yield handle
    except Exception:
        handle._status = "error"
        raise
    finally:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _CURRENT_SPAN.reset(token)
        parent_op._spans.append(
            handle._to_record(
                duration_ms=duration_ms, profile=_profile_sample(baseline)
            )
        )


_DB_WRITE_KINDS = frozenset({"insert", "update", "delete", "replace"})


def _classify_sql(sql: str) -> str:
    stripped = sql.lstrip()
    if not stripped:
        return ""
    return stripped.split(None, 1)[0].lower()


def record_db_query(sql: str) -> None:
    """Trace-callback sink: attribute one SQL statement to the active span as a
    ``db_queries`` counter (plus ``db_writes`` for mutations). No-op outside a
    span. Performance telemetry only — never audit or contract truth.
    """
    span_handle = _CURRENT_SPAN.get()
    if span_handle is None:
        return
    span_handle.add_counter("db_queries", 1)
    if _classify_sql(sql) in _DB_WRITE_KINDS:
        span_handle.add_counter("db_writes", 1)


def instrument_db_connection(conn: sqlite3.Connection) -> None:
    """Attach the per-span DB-query counter to ``conn``. No-op (and no per-query
    trace overhead) when observability is disabled for this process.
    """
    if _ENABLED:
        conn.set_trace_callback(record_db_query)


__all__ = [
    "OperationHandle",
    "SpanHandle",
    "bind_root",
    "bootstrap",
    "current_operation_context",
    "instrument_db_connection",
    "is_observability_enabled",
    "operation",
    "payload_capture_enabled",
    "record_db_query",
    "shutdown",
    "span",
]
