# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read-model views.

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
    rss_mb: float | None = None
    peak_rss_mb: float | None = None
    peak_rss_delta_mb: float | None = None
    started_at_utc: str = ""
    # Top-N literal-free SQL shapes seen on this span -> occurrence count.
    db_fingerprints: Mapping[str, int] = field(default_factory=dict)


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
    rss_mb: float | None = None
    peak_rss_mb: float | None = None
    peak_rss_delta_mb: float | None = None
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
    # None when the row predates the plane mark — unattributed, not runtime.
    plane: str | None = None
    parent_operation_id: str | None = None
    error_kind: str | None = None
    request_bytes: int | None = None
    response_bytes: int | None = None
    request_tokens: int | None = None
    response_tokens: int | None = None
    rss_delta_mb: float | None = None
    rss_mb: float | None = None
    peak_rss_mb: float | None = None
    peak_rss_delta_mb: float | None = None
    spans: tuple[SpanView, ...] = ()
    children: tuple[OperationView, ...] = ()
    cpu_user_ms: float | None = None
    cpu_system_ms: float | None = None
    # None when the row predates span-retention accounting — truncation
    # unknown, never read as "nothing was dropped". ``span_retention_rule`` is
    # set only on an operation a rule actually acted on.
    spans_dropped: int | None = None
    span_retention_rule: str | None = None


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

    Aggregated from span db_queries/db_writes/db_rows counters (v2 semantics:
    logical statements, not per-row trace fires). ``max_queries`` is the worst
    single instance; ``total_rows`` exposes executemany amplification, and a
    high statement count with little produced is the N+1 shape."""

    span_name: str
    surface: str
    span_count: int
    total_queries: int
    total_writes: int
    total_rows: int
    max_queries: int


@dataclass(frozen=True, slots=True)
class DbFingerprintRow:
    """One literal-free SQL shape attributed to a span class, with how often it
    ran — the decomposition of a span's ``db_queries`` total into named
    statements, so an N+1 reads as "1200x SELECT evidence by memory_id" instead
    of a bare count. ``table_hint`` is re-derived from the stored shape."""

    span_name: str
    surface: str
    fingerprint: str
    table_hint: str | None
    count: int
    kind: str = "other"
    # Human predicate summary, e.g. "count by repo_root_digest, workflow_id".
    summary: str = ""


@dataclass(frozen=True, slots=True)
class AnalysisPhaseRow:
    phase: str
    worker_elapsed_ms: float
    share_permille: int
    verdict: str


@dataclass(frozen=True, slots=True)
class AgentTokenRow:
    """One MCP tool's cumulative context-unit economics across the window.

    Field names keep the historical ``*_tokens`` spelling for storage/query
    compatibility; values are deterministic context-unit estimates.
    """

    name: str
    calls: int
    request_tokens: int
    response_tokens: int


@dataclass(frozen=True, slots=True)
class AgentView:
    """Agentic context economics: context units MCP tools pushed back into the
    agent context (``response_tokens`` = legacy field for context pressure),
    ranked by the biggest consumer. Built only when MCP operations are present."""

    mcp_calls: int = 0
    request_tokens: int = 0
    response_tokens: int = 0
    consumers: tuple[AgentTokenRow, ...] = ()


@dataclass(frozen=True, slots=True)
class WasteItem:
    """One ranked "fix candidate": resources spent without payoff — a no-op
    rebuild that ran but produced nothing, or a payload-heavy call. ``severity``
    is the descending sort key (magnitude of the wasted cost)."""

    kind: str
    subject: str
    surface: str
    detail: str
    severity: float = 0.0


@dataclass(frozen=True, slots=True)
class PipelineGroup:
    """Operations rolled up by subsystem (memory / analysis / controller / …),
    showing where the run spends wall time and CPU."""

    name: str
    op_count: int
    duration_ms: float
    cpu_ms: float


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
    max_rss_absolute_mb: float | None = None
    max_peak_rss_mb: float | None = None
    db_costs: tuple[DbCostRow, ...] = ()
    agent: AgentView | None = None
    waste: tuple[WasteItem, ...] = ()
    heaviest_cpu: OperationView | None = None
    pipeline: tuple[PipelineGroup, ...] = ()
    db_fingerprints: tuple[DbFingerprintRow, ...] = ()
    analysis_phases: tuple[AnalysisPhaseRow, ...] = ()
    analysis_phase_worker_elapsed_total_ms: float | None = None
    analysis_phase_pipeline_wall_ms: float | None = None
    analysis_phase_source_spans: int = 0
    analysis_phase_files_timed: int = 0
    analysis_phase_units_eligible: int = 0


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
    # Which plane this window read, and how the whole store divides between the
    # planes regardless of what the window returned.
    # ``plane_column_available`` false means the store was written by a build
    # with no plane mark: every row is unattributed and no window can honestly
    # call any of them runtime.
    plane: str = "runtime"
    plane_column_available: bool = True
    runtime_plane_operations: int = 0
    observer_plane_operations: int = 0
    unattributed_plane_operations: int = 0
    # What the per-operation span budget spent across this window.
    #
    # A bounded buffer that discards without saying so makes every aggregate
    # above it a statement about the spans that survived, worded as a statement
    # about the run. These are that omission, carried beside the numbers it
    # bounds. Flat fields rather than a nested view on purpose:
    # codeclone.observability is not a model store and the Phase 39S boundary
    # allowlist is shrink-only.
    #
    # ``span_retention_cap`` is derived, never configured: a truncated
    # operation retained exactly ``max_spans_per_operation`` spans, so its
    # retained count IS the cap the writing process ran under. None when the
    # window holds no truncated operation, or when truncated operations
    # disagree — the reader never substitutes its own configuration for the
    # writer's. ``span_retention_unknown_operations`` counts rows written
    # before the accounting existed: unknown, not "nothing dropped".
    spans_retained: int = 0
    spans_dropped: int = 0
    span_retention_truncated_operations: int = 0
    span_retention_unknown_operations: int = 0
    span_retention_cap: int | None = None
    span_retention_rule: str | None = None
    repo_root_digest: str | None = None
    focus_operation: OperationView | None = None
    operation_tree: tuple[OperationView, ...] = ()
    correlated_operations: tuple[OperationView, ...] = ()
    waterfall: tuple[WaterfallGroup, ...] = ()

    @property
    def span_retention_truncated(self) -> bool:
        """Did the span budget discard anything in this window?"""
        return self.span_retention_truncated_operations > 0

    @property
    def spans_observed(self) -> int:
        """Spans the window's operations closed, retained or not."""
        return self.spans_retained + self.spans_dropped


__all__ = [
    "AgentTokenRow",
    "AgentView",
    "AggregatesView",
    "AnalysisPhaseRow",
    "DbCostRow",
    "DbFingerprintRow",
    "McpToolAggregate",
    "OperationView",
    "PipelineGroup",
    "SpanCostView",
    "SpanView",
    "TraceView",
    "WasteItem",
    "WaterfallGroup",
    "WaterfallRow",
]
