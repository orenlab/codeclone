# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Observability write API.

``bootstrap`` freezes the enabled decision once per process. When disabled,
``operation``/``span`` yield a cheap inert handle and return immediately — no
clock, no id, no contextvar, no store import (the near-zero-overhead contract).
When enabled, spans accumulate on their operation and the whole operation is
flushed in a single transaction on exit. A process terminated by SIGKILL can
therefore lose its active operation; this is an accepted property of
non-authoritative diagnostics, not a streaming-durability guarantee.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Final

from ..config.observability import resolve_observability_config
from ..models import DEFAULT_OBSERVABILITY_TOKEN_ESTIMATOR, ObservabilityConfig
from .db_fingerprint import fingerprint_sql
from .models import OperationRecord, ProfileSample, SpanRecord
from .reason_kind import ReasonKind
from .vocabulary import (
    DB_COUNTER_VERSION,
    PLANE_RUNTIME,
    resolve_operation_plane,
    validate_counter_key,
    validate_span_name,
)

if TYPE_CHECKING:
    from sqlite3 import _Parameters as _SqlParams

# Bound how many distinct SQL shapes a span persists; the diagnostic value is in
# the few high-count statements, not the long tail.
_DB_FINGERPRINT_TOP_N = 8

# Which spans the per-operation budget spends when it cannot keep them all.
#
# Spans are appended in CLOSE order, so a keep-first cap discards the outermost
# spans first -- the worst possible choice for a diagnostic store, because the
# spans that close last are the ones that summarise the run. Measured on a warm
# 578-file CLI run: 606 spans closed, 579 of them one repeated name
# (cache.backend.load_generation), the other 27 names appeared exactly once, and
# every one of the 16 names closing after index 589 was a phase summary. A cap
# of 100 kept 89 repetitions of a single name and lost both cache summary spans
# and every pipeline.* summary.
#
# This rule spends a repetition instead: at capacity an arriving span evicts the
# last retained occurrence of the most repeated retained name, but only while
# that name is repeated more often than the arriving one -- so a name the
# operation has never recorded always displaces a duplicate, and a window of
# entirely distinct names degrades to keep-first rather than churning. Exactly
# one span is lost per over-cap append either way, so spans_dropped stays an
# exact count of what the operation observed and could not keep.
#
# Persisted per operation next to the count. The rule is a property of the build
# that wrote the row, not of the build that reads it, so a reader reports what
# actually ran rather than assuming its own policy applied.
SPAN_RETENTION_RULE: Final = "protect_distinct_names"

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
        max_spans_per_operation: int,
        plane: str,
    ) -> None:
        self.operation_id = operation_id
        self.correlation_id = correlation_id
        self.plane = plane
        self._surface = surface
        self._name = name
        self._started_at_utc = started_at_utc
        self._parent_operation_id = parent_operation_id
        self._session_id = session_id
        self._repo_root_digest = repo_root_digest
        self._max_spans_per_operation = max_spans_per_operation
        self._status = "ok"
        self._error_kind: str | None = None
        self._request_bytes: int | None = None
        self._response_bytes: int | None = None
        self._request_tokens: int | None = None
        self._response_tokens: int | None = None
        self._spans: list[SpanRecord] = []
        self._span_name_counts: dict[str, int] = {}
        self._spans_dropped = 0

    def _retain(self, record: SpanRecord) -> None:
        self._spans.append(record)
        self._span_name_counts[record.name] = (
            self._span_name_counts.get(record.name, 0) + 1
        )

    def _append_span(self, record: SpanRecord) -> None:
        """Admit a closed span under SPAN_RETENTION_RULE (see its comment)."""
        if len(self._spans) < self._max_spans_per_operation:
            self._retain(record)
            return
        # One span is lost on every over-cap append; which one is decided below.
        self._spans_dropped += 1
        # Deterministic victim regardless of dict order: (count, name) is a
        # total order over the retained names.
        victim_name, victim_count = max(
            self._span_name_counts.items(), key=lambda item: (item[1], item[0])
        )
        if victim_count <= self._span_name_counts.get(record.name, 0) + 1:
            # No retained name is more repeated than the arriving one, so
            # evicting would not buy diversity: the arriving span is what goes.
            return
        index = max(
            position
            for position, span_record in enumerate(self._spans)
            if span_record.name == victim_name
        )
        del self._spans[index]
        self._span_name_counts[victim_name] = victim_count - 1
        self._retain(record)

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
            plane=self.plane,
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
            spans_dropped=self._spans_dropped,
            # Named only when it actually acted: an untruncated operation must
            # not read as though a retention rule chose anything for it.
            span_retention_rule=(SPAN_RETENTION_RULE if self._spans_dropped else None),
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
        self._db_fingerprints: dict[str, int] = {}

    # set_counter is wired by the 29.10 worker instrumentation; add_counter by
    # the 29.DB query-trace hook (record_db_query).
    def add_counter(self, key: str, value: int = 1) -> None:
        validate_counter_key(key)
        self._counters[key] = self._counters.get(key, 0) + value

    def set_counter(self, key: str, value: int) -> None:
        validate_counter_key(key)
        self._counters[key] = value

    # Wired by the 29.DB query-trace hook (record_db_query): accumulate the
    # normalized SQL shape so _to_record can flush the top-N per span.
    def add_db_fingerprint(self, fingerprint: str) -> None:
        self._db_fingerprints[fingerprint] = (
            self._db_fingerprints.get(fingerprint, 0) + 1
        )

    def _top_db_fingerprints(self) -> dict[str, int]:
        if not self._db_fingerprints:
            return {}
        ranked = sorted(self._db_fingerprints.items(), key=lambda kv: (-kv[1], kv[0]))
        return dict(ranked[:_DB_FINGERPRINT_TOP_N])

    # Post-hoc reason classification, wired by the semantic rebuild
    # workflow once the report says why the rebuild ran.
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
            db_fingerprints=self._top_db_fingerprints(),
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
        max_spans_per_operation=1,
        plane=PLANE_RUNTIME,
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
        # Per-plane, not shared: the write budget is a retention bound, and a
        # shared one let observer calls spend it so the runtime operations that
        # followed were never persisted at all.
        self._persisted_operations: dict[str, int] = {}
        if self.config.persist and self._root is not None:
            self._open_store()

    def bind_root(self, root: Path) -> None:
        # First rooted call wins: an MCP server bootstraps root-less, then binds
        # the store to the root of the first tool that carries one.
        if self._root is None:
            self._root = root
            if self.config.persist:
                self._open_store()

    def persist(self, record: OperationRecord) -> None:
        # Persisted to the per-root store; a root-less enabled session simply
        # drops the record (no in-memory ring in the MVP).
        persisted = self._persisted_operations.get(record.plane, 0)
        if (
            self.config.persist
            and self._root is not None
            and persisted < self.config.max_operations_per_process
        ):
            self._write(record)
            self._persisted_operations[record.plane] = persisted + 1

    def _open_store(self) -> sqlite3.Connection:
        from .store.schema import observability_store_path, open_observability_store
        from .store.writer import run_retention_gc

        if self._conn is None:
            assert self._root is not None
            self._conn = open_observability_store(observability_store_path(self._root))
            assert isinstance(self._conn, sqlite3.Connection)
            run_retention_gc(
                self._conn,
                retention_days=self.config.retention_days,
            )
        assert isinstance(self._conn, sqlite3.Connection)
        return self._conn

    def _write(self, record: OperationRecord) -> None:
        from .store.writer import write_operation

        write_operation(self._open_store(), record)

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


def payload_token_estimator() -> str:
    """Effective payload token-estimator mode frozen for this process.

    Frozen at ``bootstrap`` like the enabled decision, not resolved per call: a
    payload footprint whose unit changed halfway through a session is not a
    measurement. Returns the approximation default when observability is off,
    so callers need no separate disabled branch.
    """
    runtime = _RUNTIME
    if not _ENABLED or runtime is None:
        return DEFAULT_OBSERVABILITY_TOKEN_ESTIMATOR
    return runtime.config.token_estimator


def _profile_baseline() -> tuple[int, float, float, int | None] | None:
    """Capture an rss/cpu/peak baseline when profiling is on (else None, no psutil)."""
    runtime = _RUNTIME
    if _ENABLED and runtime is not None and runtime.config.profile:
        from .profile import capture_profile_baseline

        return capture_profile_baseline()
    return None


def _profile_sample(
    baseline: tuple[int, float, float, int | None] | None,
) -> ProfileSample | None:
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
        max_spans_per_operation=runtime.config.max_spans_per_operation,
        plane=resolve_operation_plane(name),
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
    validate_span_name(name)
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
        parent_op._append_span(
            handle._to_record(
                duration_ms=duration_ms, profile=_profile_sample(baseline)
            )
        )


def record_elapsed_span(
    name: str,
    *,
    started_at_utc: str,
    duration_ms: float,
    reason_kind: ReasonKind | None = None,
) -> None:
    """Attach a span with explicit timing to the active operation, for work that
    finished before instrumentation could wrap it (e.g. a worker's cold-start).
    No-op when disabled or outside an operation.
    """
    validate_span_name(name)
    parent_op = _CURRENT_OP.get()
    if not _ENABLED or parent_op is None:
        return
    handle = SpanHandle(
        span_id=_new_id(),
        operation_id=parent_op.operation_id,
        name=name,
        started_at_utc=started_at_utc,
        parent_span_id=None,
        reason_kind=reason_kind,
        reason=None,
        dedupe_key=None,
    )
    parent_op._append_span(handle._to_record(duration_ms=duration_ms))


_DB_WRITE_KINDS = frozenset({"insert", "update", "delete", "replace"})


# Counter-semantics version. v1 counted db_queries/db_writes per *row*:
# sqlite3.set_trace_callback fires once per executemany row, so a single batched
# executemany was indistinguishable from an N+1 loop and tripped false
# query_chatty verdicts. v2 (the _CountingConnection below) counts logical
# *statements* — db_queries/db_writes are execute/executemany calls and db_rows
# is the row volume. Bump on any counter-meaning change; old observer DBs carry
# the previous semantics and are disposable (delete to avoid mixed history).
def _classify_sql(sql: str) -> str:
    stripped = sql.lstrip()
    if not stripped:
        return ""
    return stripped.split(None, 1)[0].lower()


def _record_db_statement(sql: str, *, rows: int) -> None:
    """Attribute one logical SQL statement to the active span: ``db_queries`` +1
    (``db_writes`` +1 for mutations) and ``db_rows`` += ``rows`` (1 for
    ``execute``, len(params) for ``executemany``). No-op outside a span.
    Performance telemetry only — never audit or contract truth.
    """
    span_handle = _CURRENT_SPAN.get()
    if span_handle is None:
        return
    span_handle.add_counter("db_queries", 1)
    span_handle.add_counter("db_rows", rows)
    if _classify_sql(sql) in _DB_WRITE_KINDS:
        span_handle.add_counter("db_writes", 1)
    fingerprint = fingerprint_sql(sql).fingerprint
    if fingerprint:
        span_handle.add_db_fingerprint(fingerprint)


def record_db_query(sql: str) -> None:
    """Record one logical query (1 statement, 1 row) on the active span.

    Retained as the manual entry point for code that does DB work the counting
    connection does not see (and used by tests). Equivalent to a single
    ``execute`` for counting purposes.
    """
    _record_db_statement(sql, rows=1)


def record_counter(key: str, value: int = 1) -> None:
    """Add ``value`` to the named counter on the active span. No-op outside a
    span (or when disabled). Companion to ``record_db_query`` for non-SQL
    counters — e.g. retrieval lane hits emitted by the memory query path.
    Performance telemetry only — never audit or contract truth.
    """
    validate_counter_key(key)
    span_handle = _CURRENT_SPAN.get()
    if span_handle is None:
        return
    span_handle.add_counter(key, value)


class _CountingConnection(sqlite3.Connection):
    """``sqlite3.Connection`` that counts logical statements on the active span.

    Overriding ``execute``/``executemany`` — instead of ``set_trace_callback``,
    which fires once per executemany *row* — is what makes ``db_queries`` a true
    statement count: one batched ``executemany`` is one query over many rows,
    distinguishable from an N+1 loop. All store access goes through these entry
    points (no bare cursors), so nothing escapes the count. Counting no-ops
    outside a span, so connection open (pragmas, schema) is not attributed.
    """

    def execute(self, sql: str, parameters: _SqlParams = (), /) -> sqlite3.Cursor:
        _record_db_statement(sql, rows=1)
        return super().execute(sql, parameters)

    def executemany(
        self, sql: str, parameters: Iterable[_SqlParams], /
    ) -> sqlite3.Cursor:
        materialized = list(parameters)
        _record_db_statement(sql, rows=len(materialized))
        return super().executemany(sql, materialized)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        _record_db_statement(sql_script, rows=1)
        return super().executescript(sql_script)


def counting_connection_factory() -> type[sqlite3.Connection] | None:
    """Return the per-span counting connection class when observability is
    enabled, else ``None`` so callers open a plain connection with no overhead.
    """
    return _CountingConnection if _ENABLED else None


__all__ = [
    "DB_COUNTER_VERSION",
    "SPAN_RETENTION_RULE",
    "OperationHandle",
    "SpanHandle",
    "bind_root",
    "bootstrap",
    "counting_connection_factory",
    "current_operation_context",
    "is_observability_enabled",
    "operation",
    "payload_capture_enabled",
    "payload_token_estimator",
    "record_counter",
    "record_db_query",
    "record_elapsed_span",
    "shutdown",
    "span",
]
