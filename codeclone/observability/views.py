# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read-model views (Phase 29 §4.6).

``TraceView`` is the primary artifact; JSON/text/HTML renderers are projections
over it and must not drive the schema. Pure data, built by ``store/reader.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SpanView:
    span_id: str
    name: str
    duration_ms: float
    status: str
    parent_span_id: str | None = None
    reason_kind: str | None = None
    reason: str | None = None
    dedupe_key: str | None = None
    counters: Mapping[str, int] = field(default_factory=dict)
    rss_delta_mb: float | None = None
    started_at_utc: str = ""


@dataclass(frozen=True, slots=True)
class SpanCostView:
    """A span flattened with its owning operation's identity, for the cockpit
    cost views (slowest-span highlight, semantic/memory cost table).

    ``no_op`` is the deterministic answer to "did this span do productive work?":
    true when the span declares productive counters and they sum to zero — a
    rebuild/reindex that touched nothing yet still spent wall time and memory.
    """

    span_id: str
    name: str
    surface: str
    operation_id: str
    operation_name: str
    duration_ms: float
    reason_kind: str | None = None
    rss_delta_mb: float | None = None
    produced: int = 0
    skipped: int = 0
    no_op: bool = False


@dataclass(frozen=True, slots=True)
class OperationView:
    operation_id: str
    correlation_id: str
    surface: str
    name: str
    started_at_utc: str
    duration_ms: float
    status: str
    parent_operation_id: str | None = None
    error_kind: str | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    request_tokens: int | None = None
    response_tokens: int | None = None
    rss_delta_mb: float | None = None
    spans: tuple[SpanView, ...] = ()
    children: tuple[OperationView, ...] = ()


@dataclass(frozen=True, slots=True)
class McpToolAggregate:
    name: str
    count: int
    p50_duration_ms: float
    p95_duration_ms: float
    p95_response_bytes: int
    p95_request_bytes: int = 0
    p95_response_tokens: int = 0


@dataclass(frozen=True, slots=True)
class DbCostRow:
    """SQLite work attributed to a span class (performance-truth, not audit).

    Aggregated from span db_queries/db_writes counters; ``max_queries`` is the
    worst single instance and ``queries`` ÷ a per-row productive count exposes
    N+1-shaped access (many reads, little produced)."""

    span_name: str
    surface: str
    span_count: int
    total_queries: int
    total_writes: int
    max_queries: int


@dataclass(frozen=True, slots=True)
class AgentTokenRow:
    """One MCP tool's cumulative token economics across the window."""

    name: str
    calls: int
    request_tokens: int
    response_tokens: int


@dataclass(frozen=True, slots=True)
class AgentView:
    """Agentic context economics: how many tokens MCP tools pushed back into
    the agent's context (``response_tokens`` = context pressure), ranked by the
    biggest consumer. Built only when MCP operations are present."""

    mcp_calls: int = 0
    request_tokens: int = 0
    response_tokens: int = 0
    consumers: tuple[AgentTokenRow, ...] = ()


@dataclass(frozen=True, slots=True)
class AggregatesView:
    operation_count: int
    slowest: tuple[OperationView, ...] = ()
    largest_responses: tuple[OperationView, ...] = ()
    max_rss_delta_mb: float | None = None
    anomaly_count: int = 0
    unknown_expensive_rebuild_count: int = 0
    mcp_tools: tuple[McpToolAggregate, ...] = ()
    slowest_span: SpanCostView | None = None
    semantic_costs: tuple[SpanCostView, ...] = ()
    peak_memory_span: SpanCostView | None = None
    db_costs: tuple[DbCostRow, ...] = ()
    agent: AgentView | None = None


@dataclass(frozen=True, slots=True)
class WaterfallRow:
    """One time-positioned bar in a waterfall: a span or operation placed at
    ``offset_ms`` after its group's start, ``duration_ms`` wide. ``depth`` nests
    spans under their operation and child operations under their parent."""

    label: str
    surface: str
    kind: str  # "operation" | "span"
    depth: int
    offset_ms: float
    duration_ms: float
    reason_kind: str | None = None
    status: str = "ok"


@dataclass(frozen=True, slots=True)
class WaterfallGroup:
    """One correlated causal chain rendered as a self-contained timeline; every
    row's ``offset_ms`` is relative to ``started_at_utc`` and bounded by
    ``duration_ms`` (the group's own window, not the whole trace)."""

    correlation_id: str
    started_at_utc: str
    duration_ms: float
    rows: tuple[WaterfallRow, ...] = ()


@dataclass(frozen=True, slots=True)
class TraceView:
    schema_version: str
    window_started_at_utc: str
    window_ended_at_utc: str
    aggregates: AggregatesView
    repo_root_digest: str | None = None
    focus_operation: OperationView | None = None
    operation_tree: tuple[OperationView, ...] = ()
    correlated_operations: tuple[OperationView, ...] = ()
    waterfall: tuple[WaterfallGroup, ...] = ()


__all__ = [
    "AgentTokenRow",
    "AgentView",
    "AggregatesView",
    "DbCostRow",
    "McpToolAggregate",
    "OperationView",
    "SpanCostView",
    "SpanView",
    "TraceView",
    "WaterfallGroup",
    "WaterfallRow",
]
