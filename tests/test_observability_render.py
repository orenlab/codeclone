# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeclone.observability.models import OperationRecord, SpanRecord
from codeclone.observability.render_html import render_trace_html
from codeclone.observability.render_json import render_trace_json
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import write_operation
from codeclone.observability.views import (
    AggregatesView,
    McpToolAggregate,
    OperationView,
    SpanCostView,
    SpanView,
    TraceView,
    WaterfallGroup,
    WaterfallRow,
)
from codeclone.surfaces.cli.observability import observability_main


def _trace() -> TraceView:
    span = SpanView(
        span_id="s1",
        name="pipeline.analyze",
        duration_ms=188.0,
        status="ok",
        reason_kind="content_changed",
        counters={"embedded": 1},
        rss_delta_mb=6.7,
    )
    op = OperationView(
        operation_id="o1",
        correlation_id="o1",
        surface="cli",
        name="cli.analyze",
        started_at_utc="2026-06-10T04:00:00Z",
        duration_ms=285.0,
        status="ok",
        rss_delta_mb=13.1,
        spans=(span,),
    )
    agg = AggregatesView(
        operation_count=1,
        slowest=(op,),
        max_rss_delta_mb=13.1,
        mcp_tools=(
            McpToolAggregate("finish_controlled_change", 4, 700.0, 820.0, 14200),
        ),
    )
    return TraceView(
        schema_version="1.0",
        window_started_at_utc="2026-06-10T04:00:00Z",
        window_ended_at_utc="2026-06-10T04:00:01Z",
        aggregates=agg,
        repo_root_digest="abc123",
        operation_tree=(op,),
        correlated_operations=(op,),
    )


def test_render_trace_json_is_valid_and_complete() -> None:
    payload = json.loads(render_trace_json(_trace()))
    assert payload["schema_version"] == "1.0"
    assert payload["aggregates"]["operation_count"] == 1
    assert payload["operation_tree"][0]["name"] == "cli.analyze"
    assert payload["operation_tree"][0]["spans"][0]["name"] == "pipeline.analyze"
    assert payload["aggregates"]["mcp_tools"][0]["p95_response_bytes"] == 14200


def test_render_trace_html_is_branded() -> None:
    html = render_trace_html(_trace())
    assert html.startswith("<!doctype html>")
    assert 'class="logo"' in html  # brand mark reused
    assert "Platform Observability" in html
    assert "cli.analyze" in html
    assert "pipeline.analyze" in html
    assert "content_changed" in html
    assert "finish_controlled_change" in html


def _cockpit_trace() -> TraceView:
    reindex = SpanView(
        span_id="sx",
        name="memory.semantic.reindex",
        duration_ms=850.0,
        status="ok",
        reason_kind="content_changed",
        counters={"embedded": 0, "skipped_unchanged": 1423},
    )
    worker = OperationView(
        operation_id="W",
        correlation_id="A",
        surface="memory",
        name="memory.projection.job",
        started_at_utc="2026-06-10T04:00:01Z",
        duration_ms=900.0,
        status="ok",
        parent_operation_id="A",
        rss_delta_mb=512.0,
        spans=(reindex,),
    )
    finish = OperationView(
        operation_id="A",
        correlation_id="A",
        surface="mcp",
        name="finish_controlled_change",
        started_at_utc="2026-06-10T04:00:00Z",
        duration_ms=120.0,
        status="ok",
        request_bytes=51,
        response_bytes=1873,
        children=(worker,),
    )
    costly = SpanCostView(
        span_id="sx",
        name="memory.semantic.reindex",
        surface="memory",
        operation_id="W",
        operation_name="memory.projection.job",
        duration_ms=850.0,
        reason_kind="content_changed",
        produced=0,
        skipped=1423,
        no_op=True,
    )
    agg = AggregatesView(
        operation_count=2,
        slowest=(worker, finish),
        max_rss_delta_mb=512.0,
        mcp_tools=(
            McpToolAggregate(
                "finish_controlled_change",
                3,
                80.0,
                120.0,
                1873,
                p95_request_bytes=51,
                p95_response_tokens=469,
            ),
        ),
        slowest_span=costly,
        semantic_costs=(costly,),
    )
    return TraceView(
        schema_version="1.0",
        window_started_at_utc="2026-06-10T04:00:00Z",
        window_ended_at_utc="2026-06-10T04:00:02Z",
        aggregates=agg,
        operation_tree=(finish,),
        correlated_operations=(finish, worker),
    )


def test_render_cockpit_sections() -> None:
    html = render_trace_html(_cockpit_trace())
    # Section trajectory: summary -> chain -> memory cost -> MCP matrix.
    assert "Runtime summary" in html
    assert "Correlated event chains" in html
    assert "Memory pipeline cost" in html
    assert "MCP tool matrix" in html
    # Cross-process correlation: a breadcrumb chains finish -> worker, and the
    # worker nests under it via the indent rail (not a card inside a card).
    assert "finish_controlled_change" in html
    assert "memory.projection.job" in html
    assert "→" in html
    assert 'class="kids"' in html
    # The reindex ran but embedded nothing -> flagged as a costly no-op.
    assert "no-op" in html
    assert "Hottest span" in html
    # MCP matrix carries request bytes and response tokens, not just response bytes.
    assert "51 B" in html
    assert "469" in html


def test_render_waterfall_timeline() -> None:
    group = WaterfallGroup(
        correlation_id="corr1234abcd",
        started_at_utc="2026-06-10T04:00:00Z",
        duration_ms=1000.0,
        rows=(
            WaterfallRow(
                label="finish_controlled_change",
                surface="mcp",
                kind="operation",
                depth=0,
                offset_ms=0.0,
                duration_ms=120.0,
            ),
            WaterfallRow(
                label="memory.projection.job",
                surface="memory",
                kind="operation",
                depth=1,
                offset_ms=300.0,
                duration_ms=700.0,
            ),
        ),
    )
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="2026-06-10T04:00:00Z",
        window_ended_at_utc="2026-06-10T04:00:01Z",
        aggregates=AggregatesView(operation_count=2),
        waterfall=(group,),
    )
    html = render_trace_html(trace)
    assert "Timeline" in html
    assert "wf-bar" in html
    # The worker bar is offset 300/1000 = 30% and 700/1000 = 70% wide.
    assert "left:30.0%" in html
    assert "width:70.0%" in html
    assert "memory.projection.job" in html


def test_render_trace_html_escapes_user_text() -> None:
    span = SpanView(
        span_id="s", name="<script>x</script>", duration_ms=1.0, status="ok"
    )
    op = OperationView(
        operation_id="o",
        correlation_id="o",
        surface="cli",
        name="a&b",
        started_at_utc="t",
        duration_ms=1.0,
        status="ok",
        spans=(span,),
    )
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="t",
        window_ended_at_utc="t",
        aggregates=AggregatesView(operation_count=1, slowest=(op,)),
        operation_tree=(op,),
    )
    html = render_trace_html(trace)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a&amp;b" in html


def test_observability_main_writes_json_and_html(tmp_path: Path) -> None:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="A",
                correlation_id="A",
                surface="cli",
                name="cli.analyze",
                started_at_utc="2026-06-10T04:00:00Z",
                duration_ms=285.0,
                status="ok",
                spans=(
                    SpanRecord(
                        span_id="s",
                        operation_id="A",
                        name="pipeline.analyze",
                        started_at_utc="2026-06-10T04:00:00Z",
                        duration_ms=188.0,
                        status="ok",
                    ),
                ),
            ),
        )
    finally:
        conn.close()
    json_path = tmp_path / "trace.json"
    html_path = tmp_path / "trace.html"
    code = observability_main(
        [
            "trace",
            "--root",
            str(tmp_path),
            "--json",
            str(json_path),
            "--html",
            str(html_path),
        ]
    )
    assert code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["operation_tree"][0]["name"] == "cli.analyze"
    assert "Platform Observability" in html_path.read_text(encoding="utf-8")


def test_observability_main_no_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = observability_main(["trace", "--root", str(tmp_path)])
    assert code == 0
    assert "No observability store" in capsys.readouterr().out
