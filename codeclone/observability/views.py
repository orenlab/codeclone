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


@dataclass(frozen=True, slots=True)
class AggregatesView:
    operation_count: int
    slowest: tuple[OperationView, ...] = ()
    largest_responses: tuple[OperationView, ...] = ()
    max_rss_delta_mb: float | None = None
    anomaly_count: int = 0
    unknown_expensive_rebuild_count: int = 0
    mcp_tools: tuple[McpToolAggregate, ...] = ()


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


__all__ = [
    "AggregatesView",
    "McpToolAggregate",
    "OperationView",
    "SpanView",
    "TraceView",
]
