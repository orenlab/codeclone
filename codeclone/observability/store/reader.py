# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read path: build the primary ``TraceView`` from the observability store.

Read-only — never creates the store or its schema. Deterministic ordering and
deterministic percentiles (sorted-index, no numpy).
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import cast

import orjson

from ...contracts import PLATFORM_OBSERVABILITY_SCHEMA_VERSION
from ..views import (
    AggregatesView,
    DbCostRow,
    McpToolAggregate,
    OperationView,
    SpanCostView,
    SpanView,
    TraceView,
    WaterfallGroup,
    WaterfallRow,
)
from .schema import observability_store_path

_DEFAULT_WINDOW = 20

# Counters whose presence marks a span as *meant* to do productive work; when
# they are all present-and-zero the span ran but touched nothing (a no-op).
_PRODUCTIVE_COUNTER_KEYS = ("embedded", "workflows_seen", "experiences_distilled")
_SEMANTIC_COST_LIMIT = 8


def open_observability_store_readonly(root: Path) -> sqlite3.Connection | None:
    """Open the store read-only, or None when it does not exist yet."""
    path = observability_store_path(root)
    if not path.is_file():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round(q * (len(ordered) - 1))
    return ordered[min(index, len(ordered) - 1)]


def _parse_counters(raw: object) -> dict[str, int]:
    if not raw:
        return {}
    parsed = orjson.loads(cast("str", raw))
    return (
        {str(k): int(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}
    )


def _span_view(row: sqlite3.Row) -> SpanView:
    return SpanView(
        span_id=str(row["span_id"]),
        name=str(row["name"]),
        duration_ms=float(row["duration_ms"]),
        status=str(row["status"]),
        parent_span_id=row["parent_span_id"],
        reason_kind=row["reason_kind"],
        reason=row["reason"],
        dedupe_key=row["dedupe_key"],
        counters=_parse_counters(row["counters_json"]),
        rss_delta_mb=row["rss_delta_mb"],
        started_at_utc=str(row["started_at_utc"]),
    )


def _span_views(
    conn: sqlite3.Connection, operation_ids: list[str]
) -> dict[str, tuple[SpanView, ...]]:
    if not operation_ids:
        return {}
    placeholders = ",".join("?" * len(operation_ids))
    rows = conn.execute(
        f"SELECT * FROM platform_spans WHERE operation_id IN ({placeholders}) "
        "ORDER BY started_at_utc ASC, span_id ASC",
        tuple(operation_ids),
    ).fetchall()
    grouped: dict[str, list[SpanView]] = defaultdict(list)
    for row in rows:
        grouped[str(row["operation_id"])].append(_span_view(row))
    return {key: tuple(value) for key, value in grouped.items()}


def _operation_view(
    row: sqlite3.Row,
    spans: tuple[SpanView, ...],
    children: tuple[OperationView, ...],
) -> OperationView:
    return OperationView(
        operation_id=str(row["operation_id"]),
        correlation_id=str(row["correlation_id"]),
        surface=str(row["surface"]),
        name=str(row["name"]),
        started_at_utc=str(row["started_at_utc"]),
        duration_ms=float(row["duration_ms"]),
        status=str(row["status"]),
        parent_operation_id=row["parent_operation_id"],
        error_kind=row["error_kind"],
        request_bytes=row["request_bytes"],
        response_bytes=row["response_bytes"],
        request_tokens=row["request_tokens"],
        response_tokens=row["response_tokens"],
        rss_delta_mb=row["rss_delta_mb"],
        spans=spans,
        children=children,
    )


def _by_correlations(
    conn: sqlite3.Connection, correlation_ids: list[str]
) -> list[sqlite3.Row]:
    if not correlation_ids:
        return []
    placeholders = ",".join("?" * len(correlation_ids))
    return list(
        conn.execute(
            "SELECT * FROM platform_operations "
            f"WHERE correlation_id IN ({placeholders}) "
            "ORDER BY started_at_utc ASC, operation_id ASC",
            tuple(correlation_ids),
        ).fetchall()
    )


def _select_operations(
    conn: sqlite3.Connection,
    *,
    operation_id: str | None,
    correlation_id: str | None,
    session_id: str | None,
    last: int | None,
) -> tuple[list[sqlite3.Row], str | None]:
    if operation_id is not None:
        row = conn.execute(
            "SELECT correlation_id FROM platform_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return [], None
        return _by_correlations(conn, [str(row["correlation_id"])]), operation_id
    if correlation_id is not None:
        return _by_correlations(conn, [correlation_id]), None
    if session_id is not None:
        rows = conn.execute(
            "SELECT * FROM platform_operations WHERE session_id=? "
            "ORDER BY started_at_utc ASC, operation_id ASC",
            (session_id,),
        ).fetchall()
        return list(rows), None
    root_rows = conn.execute(
        "SELECT operation_id, correlation_id FROM platform_operations "
        "WHERE parent_operation_id IS NULL "
        "ORDER BY started_at_utc DESC, operation_id DESC LIMIT ?",
        (last if last is not None else _DEFAULT_WINDOW,),
    ).fetchall()
    if not root_rows:
        return [], None
    correlations = sorted({str(row["correlation_id"]) for row in root_rows})
    return _by_correlations(conn, correlations), str(root_rows[0]["operation_id"])


def _build_forest(
    rows: list[sqlite3.Row], spans_by_op: dict[str, tuple[SpanView, ...]]
) -> tuple[OperationView, ...]:
    by_id = {str(row["operation_id"]): row for row in rows}
    children_ids: dict[str | None, list[str]] = defaultdict(list)
    for row in rows:
        parent = row["parent_operation_id"]
        parent_key = (
            str(parent) if parent is not None and str(parent) in by_id else None
        )
        children_ids[parent_key].append(str(row["operation_id"]))

    def _order(operation_id: str) -> tuple[str, str]:
        return (str(by_id[operation_id]["started_at_utc"]), operation_id)

    def build(operation_id: str) -> OperationView:
        children = tuple(
            build(child) for child in sorted(children_ids[operation_id], key=_order)
        )
        return _operation_view(
            by_id[operation_id], spans_by_op.get(operation_id, ()), children
        )

    return tuple(build(root) for root in sorted(children_ids[None], key=_order))


def _span_cost_view(op: OperationView, span: SpanView) -> SpanCostView:
    """Flatten a span with its owning operation's identity and classify whether
    it did productive work (see ``SpanCostView.no_op``)."""
    productive = [
        span.counters[key] for key in _PRODUCTIVE_COUNTER_KEYS if key in span.counters
    ]
    produced = sum(productive)
    return SpanCostView(
        span_id=span.span_id,
        name=span.name,
        surface=op.surface,
        operation_id=op.operation_id,
        operation_name=op.name,
        duration_ms=span.duration_ms,
        reason_kind=span.reason_kind,
        rss_delta_mb=span.rss_delta_mb,
        produced=produced,
        skipped=int(span.counters.get("skipped_unchanged", 0)),
        no_op=bool(productive) and produced == 0,
    )


def _mcp_tool_aggregates(flat: list[OperationView]) -> tuple[McpToolAggregate, ...]:
    by_name: dict[str, list[OperationView]] = defaultdict(list)
    for view in flat:
        if view.surface == "mcp":
            by_name[view.name].append(view)
    aggregates: list[McpToolAggregate] = []
    for name in sorted(by_name):
        ops = by_name[name]
        durations = [op.duration_ms for op in ops]
        requests = [
            float(op.request_bytes) for op in ops if op.request_bytes is not None
        ]
        responses = [
            float(op.response_bytes) for op in ops if op.response_bytes is not None
        ]
        response_tokens = [
            float(op.response_tokens) for op in ops if op.response_tokens is not None
        ]
        aggregates.append(
            McpToolAggregate(
                name=name,
                count=len(ops),
                p50_duration_ms=_percentile(durations, 0.5),
                p95_duration_ms=_percentile(durations, 0.95),
                p95_response_bytes=int(_percentile(responses, 0.95)),
                p95_request_bytes=int(_percentile(requests, 0.95)),
                p95_response_tokens=int(_percentile(response_tokens, 0.95)),
            )
        )
    return tuple(aggregates)


def _db_costs(flat: list[OperationView]) -> tuple[DbCostRow, ...]:
    grouped: dict[str, list[SpanView]] = defaultdict(list)
    surface_of: dict[str, str] = {}
    for op in flat:
        for span in op.spans:
            if "db_queries" in span.counters:
                grouped[span.name].append(span)
                surface_of.setdefault(span.name, op.surface)
    rows = [
        DbCostRow(
            span_name=name,
            surface=surface_of[name],
            span_count=len(spans),
            total_queries=sum(s.counters.get("db_queries", 0) for s in spans),
            total_writes=sum(s.counters.get("db_writes", 0) for s in spans),
            max_queries=max(s.counters.get("db_queries", 0) for s in spans),
        )
        for name, spans in grouped.items()
    ]
    return tuple(sorted(rows, key=lambda r: (-r.total_queries, r.span_name)))


def _aggregates(
    flat: list[OperationView], spans_by_op: dict[str, tuple[SpanView, ...]]
) -> AggregatesView:
    slowest = tuple(sorted(flat, key=lambda v: (-v.duration_ms, v.operation_id))[:5])
    with_response = [v for v in flat if v.response_bytes is not None]
    largest = tuple(
        sorted(with_response, key=lambda v: (-(v.response_bytes or 0), v.operation_id))[
            :5
        ]
    )
    rss = [v.rss_delta_mb for v in flat if v.rss_delta_mb is not None]
    rss.extend(
        span.rss_delta_mb
        for spans in spans_by_op.values()
        for span in spans
        if span.rss_delta_mb is not None
    )
    unknown = sum(
        1
        for spans in spans_by_op.values()
        for span in spans
        if span.reason_kind == "unknown"
    )
    span_costs = sorted(
        (_span_cost_view(op, span) for op in flat for span in op.spans),
        key=lambda s: (-s.duration_ms, s.operation_id, s.span_id),
    )
    semantic_costs = tuple(s for s in span_costs if s.surface == "memory")
    memory_ranked = sorted(
        (s for s in span_costs if s.rss_delta_mb is not None),
        key=lambda s: (-(s.rss_delta_mb or 0.0), s.operation_id, s.span_id),
    )
    return AggregatesView(
        operation_count=len(flat),
        slowest=slowest,
        largest_responses=largest,
        max_rss_delta_mb=max(rss) if rss else None,
        anomaly_count=0,
        unknown_expensive_rebuild_count=unknown,
        mcp_tools=_mcp_tool_aggregates(flat),
        slowest_span=span_costs[0] if span_costs else None,
        semantic_costs=semantic_costs[:_SEMANTIC_COST_LIMIT],
        peak_memory_span=memory_ranked[0] if memory_ranked else None,
        db_costs=_db_costs(flat),
    )


def _epoch_ms(iso: str) -> float:
    """Parse a store timestamp to epoch milliseconds (0.0 when absent/unparsable)."""
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000.0
    except ValueError:
        return 0.0


def _wf_row(
    *,
    label: str,
    surface: str,
    kind: str,
    depth: int,
    start_iso: str,
    duration_ms: float,
    base_ms: float,
    reason_kind: str | None = None,
    status: str = "ok",
) -> WaterfallRow:
    return WaterfallRow(
        label=label,
        surface=surface,
        kind=kind,
        depth=depth,
        offset_ms=max(0.0, _epoch_ms(start_iso) - base_ms),
        duration_ms=duration_ms,
        reason_kind=reason_kind,
        status=status,
    )


def _waterfall_rows(
    op: OperationView, depth: int, base_ms: float
) -> list[WaterfallRow]:
    rows = [
        _wf_row(
            label=op.name,
            surface=op.surface,
            kind="operation",
            depth=depth,
            start_iso=op.started_at_utc,
            duration_ms=op.duration_ms,
            base_ms=base_ms,
            status=op.status,
        )
    ]
    rows.extend(
        _wf_row(
            label=span.name,
            surface=op.surface,
            kind="span",
            depth=depth + 1,
            start_iso=span.started_at_utc,
            duration_ms=span.duration_ms,
            base_ms=base_ms,
            reason_kind=span.reason_kind,
            status=span.status,
        )
        for span in op.spans
    )
    for child in op.children:
        rows.extend(_waterfall_rows(child, depth + 1, base_ms))
    return rows


def _waterfall_groups(tree: tuple[OperationView, ...]) -> tuple[WaterfallGroup, ...]:
    """One self-contained timeline per causal chain (tree root); offsets are
    relative to that root's start so a long-idle window never crushes the bars."""
    groups: list[WaterfallGroup] = []
    for root in tree:
        base_ms = _epoch_ms(root.started_at_utc)
        rows = tuple(_waterfall_rows(root, 0, base_ms))
        span_ms = max((row.offset_ms + row.duration_ms for row in rows), default=0.0)
        groups.append(
            WaterfallGroup(
                correlation_id=root.correlation_id,
                started_at_utc=root.started_at_utc,
                duration_ms=span_ms,
                rows=rows,
            )
        )
    return tuple(groups)


def build_trace_view(
    conn: sqlite3.Connection,
    *,
    operation_id: str | None = None,
    correlation_id: str | None = None,
    session_id: str | None = None,
    last: int | None = None,
) -> TraceView:
    rows, focus_id = _select_operations(
        conn,
        operation_id=operation_id,
        correlation_id=correlation_id,
        session_id=session_id,
        last=last,
    )
    operation_ids = [str(row["operation_id"]) for row in rows]
    spans_by_op = _span_views(conn, operation_ids)
    flat = [
        _operation_view(row, spans_by_op.get(str(row["operation_id"]), ()), ())
        for row in rows
    ]
    by_id = {view.operation_id: view for view in flat}
    starts = [str(row["started_at_utc"]) for row in rows]
    operation_tree = _build_forest(rows, spans_by_op)
    return TraceView(
        schema_version=PLATFORM_OBSERVABILITY_SCHEMA_VERSION,
        window_started_at_utc=min(starts) if starts else "",
        window_ended_at_utc=max(starts) if starts else "",
        aggregates=_aggregates(flat, spans_by_op),
        focus_operation=by_id.get(focus_id) if focus_id is not None else None,
        operation_tree=operation_tree,
        correlated_operations=tuple(flat),
        waterfall=_waterfall_groups(operation_tree),
    )


__all__ = ["build_trace_view", "open_observability_store_readonly"]
