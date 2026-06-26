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
    AgentTokenRow,
    AgentView,
    AggregatesView,
    AnalysisPhaseRow,
    DbCostRow,
    DbFingerprintRow,
    McpToolAggregate,
    OperationView,
    PipelineGroup,
    SpanCostView,
    SpanView,
    TraceView,
    WasteItem,
    WaterfallGroup,
    WaterfallRow,
)
from codeclone.surfaces.cli.observability import observability_main


def _assert_html_contains(html: str, *needles: str) -> None:
    missing = [needle for needle in needles if needle not in html]
    assert not missing, f"missing html fragments: {missing}"


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


def test_render_trace_html_shows_db_query_shapes() -> None:
    agg = AggregatesView(
        operation_count=1,
        db_fingerprints=(
            DbFingerprintRow(
                span_name="memory.experience.distill",
                surface="memory",
                fingerprint="select * from memory_evidence where memory_id = ?",
                table_hint="memory_evidence",
                count=1200,
                kind="select",
                summary="by memory_id",
            ),
        ),
    )
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="2026-06-10T04:00:00Z",
        window_ended_at_utc="2026-06-10T04:00:01Z",
        aggregates=agg,
    )
    html = render_trace_html(trace)
    # Interpreted columns (shape/kind/table) plus the raw shape as a secondary line.
    for needle in (
        "DB query shapes",
        "by memory_id",
        ">SELECT<",
        "memory_evidence",
        "select * from memory_evidence where memory_id = ?",
    ):
        assert needle in html


def test_render_trace_html_shows_analysis_phase_section() -> None:
    agg = AggregatesView(
        operation_count=1,
        analysis_phases=(
            AnalysisPhaseRow(
                phase="unit_cfg",
                worker_elapsed_ms=2.5,
                share_permille=833,
                verdict="phase_heavy",
            ),
            AnalysisPhaseRow(
                phase="parse",
                worker_elapsed_ms=0.5,
                share_permille=167,
                verdict="ok",
            ),
        ),
        analysis_phase_worker_elapsed_total_ms=3.0,
        analysis_phase_pipeline_wall_ms=2.0,
        analysis_phase_source_spans=1,
        analysis_phase_files_timed=2,
        analysis_phase_units_eligible=3,
    )
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="2026-06-10T04:00:00Z",
        window_ended_at_utc="2026-06-10T04:00:01Z",
        aggregates=agg,
    )

    html = render_trace_html(trace)
    _assert_html_contains(
        html,
        "Hottest extract phase",
        "Analysis extract phases",
        "CFG build",
        "Parse (ast.parse)",
        # phase rows are ranked bars; the heaviest is the accent "lead" (peak)
        'class="ph-row',
        "ph-row lead",
        ">peak<",
        "Worker elapsed (summed): 3ms",
        "pipeline.process wall: 2ms",
        "files timed: 2",
        "units eligible: 3",
    )
    payload = json.loads(render_trace_json(trace))
    assert payload["aggregates"]["analysis_phases"][0]["phase"] == "unit_cfg"


def test_render_trace_html_explains_cache_only_analysis_phase_window() -> None:
    process_span = SpanView(
        span_id="sp",
        name="pipeline.process",
        duration_ms=1.0,
        status="ok",
        counters={"files_analyzed": 0, "failed_files": 0},
    )
    op = OperationView(
        operation_id="op",
        correlation_id="op",
        surface="cli",
        name="cli.analyze",
        started_at_utc="2026-06-10T04:00:00Z",
        duration_ms=10.0,
        status="ok",
        spans=(process_span,),
    )
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="2026-06-10T04:00:00Z",
        window_ended_at_utc="2026-06-10T04:00:01Z",
        aggregates=AggregatesView(operation_count=1),
        operation_tree=(op,),
    )

    html = render_trace_html(trace)
    _assert_html_contains(
        html,
        "Analysis extract phases",
        "No uncached files were processed",
        "served from cache",
        "files_analyzed=0",
        "failed_files=0",
    )


def _cockpit_trace() -> TraceView:
    reindex = SpanView(
        span_id="sx",
        name="memory.semantic.rebuild",
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
        name="memory.semantic.rebuild",
        surface="memory",
        operation_id="W",
        operation_name="memory.projection.job",
        duration_ms=850.0,
        reason_kind="manual_rebuild",
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
    _assert_html_contains(
        html,
        "Runtime summary",
        "Correlated event chains",
        "Memory pipeline cost",
        "MCP tool matrix",
        "finish_controlled_change",
        "memory.projection.job",
        "→",
        'class="kids"',
        'class="hirow"',
        'class="hmono"',
        "no-op",
        "Hottest span",
        "51 B",
        "resp ctx p95",
        "469 cu",
    )


def test_render_peak_memory_contributor() -> None:
    consumer = SpanCostView(
        span_id="s",
        name="memory.semantic.rebuild",
        surface="memory",
        operation_id="W",
        operation_name="memory.projection.job",
        duration_ms=1700.0,
        rss_delta_mb=480.0,
    )
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="t",
        window_ended_at_utc="t",
        aggregates=AggregatesView(
            operation_count=1,
            max_rss_delta_mb=600.0,
            peak_memory_span=consumer,
        ),
    )
    html = render_trace_html(trace)
    # The peak-memory highlight names the consumer + its share, not a bare number.
    assert "Top memory consumer" in html
    assert "memory.semantic.rebuild" in html
    assert "80%" in html  # 480 / 600 = 80%


def test_render_cpu_highlight_and_pipeline() -> None:
    op = OperationView(
        operation_id="W",
        correlation_id="W",
        surface="memory",
        name="memory.projection.job",
        started_at_utc="t",
        duration_ms=1000.0,
        status="ok",
        cpu_user_ms=1800.0,
        cpu_system_ms=200.0,
    )
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="t",
        window_ended_at_utc="t",
        aggregates=AggregatesView(
            operation_count=1,
            heaviest_cpu=op,
            pipeline=(
                PipelineGroup(
                    name="memory", op_count=2, duration_ms=2500.0, cpu_ms=3000.0
                ),
            ),
        ),
    )
    html = render_trace_html(trace)
    assert "Heaviest CPU" in html
    assert "2.0x wall" in html  # 2000ms CPU / 1000ms wall
    assert "Pipeline" in html
    assert "memory" in html


def test_render_agent_context() -> None:
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="t",
        window_ended_at_utc="t",
        aggregates=AggregatesView(
            operation_count=2,
            agent=AgentView(
                mcp_calls=5,
                request_tokens=300,
                response_tokens=1000,
                consumers=(
                    AgentTokenRow(
                        name="get_relevant_memory",
                        calls=4,
                        request_tokens=200,
                        response_tokens=800,
                    ),
                    AgentTokenRow(
                        name="finish_controlled_change",
                        calls=1,
                        request_tokens=100,
                        response_tokens=200,
                    ),
                ),
            ),
        ),
    )
    html = render_trace_html(trace)
    assert "Agent context" in html
    assert "context pressure" in html
    assert "1.0k cu" in html
    assert "get_relevant_memory" in html
    assert "80%" in html  # 800 / 1000 context share for the top consumer


def test_render_waste_section() -> None:
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="t",
        window_ended_at_utc="t",
        aggregates=AggregatesView(
            operation_count=1,
            waste=(
                WasteItem(
                    kind="high payload",
                    subject="get_relevant_memory",
                    surface="mcp",
                    detail="p95 20 KB resp · 11000 cu",
                    severity=20480.0,
                ),
                WasteItem(
                    kind="no-op",
                    subject="memory.semantic.rebuild",
                    surface="memory",
                    detail="ran 800ms, skipped 826",
                    severity=800.0,
                ),
            ),
        ),
    )
    html = render_trace_html(trace)
    assert "Waste" in html
    assert "no-op" in html
    assert "high payload" in html
    assert "skipped 826" in html
    assert "get_relevant_memory" in html


def test_render_db_cost() -> None:
    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="t",
        window_ended_at_utc="t",
        aggregates=AggregatesView(
            operation_count=1,
            db_costs=(
                DbCostRow(
                    span_name="memory.semantic.rebuild",
                    surface="memory",
                    span_count=2,
                    total_queries=1306,
                    total_writes=0,
                    total_rows=1306,
                    max_queries=1000,
                ),
            ),
        ),
    )
    html = render_trace_html(trace)
    assert "DB cost" in html
    assert "memory.semantic.rebuild" in html
    assert "1306" in html
    assert "653" in html  # 1306 / 2 queries per call


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


def test_html_format_helpers_and_semantic_cost_rows() -> None:
    from dataclasses import replace

    from codeclone.observability.render_html import (
        _bytes,
        _context_units,
        _mb,
        _semantic_row,
    )

    assert _mb(None) == "—"
    assert "GB" in _mb(2048.0)
    assert "MB" in _mb(512.0)
    assert _bytes(None) == "—"
    assert "MB" in _bytes(1024 * 1024)
    assert "KB" in _bytes(2048)
    assert _bytes(12).endswith(" B")
    assert _context_units(None) == "—"
    assert _context_units(0) == "—"
    assert _context_units(1500) == "1.5k cu"

    costly = SpanCostView(
        span_id="s1",
        name="memory.semantic.rebuild",
        surface="memory",
        operation_id="op",
        operation_name="memory.projection.job",
        duration_ms=6000.0,
        no_op=True,
        reason_kind="schema_version_changed",
    )
    costly_html = _semantic_row(costly, lead=False)
    assert "no-op · costly" in costly_html
    assert "schema_version_changed" in costly_html

    noop = replace(costly, duration_ms=10.0)
    assert "no-op" in _semantic_row(noop, lead=False)
    assert "costly" not in _semantic_row(noop, lead=False)

    productive = replace(noop, no_op=False, reason_kind=None)
    assert "productive" in _semantic_row(productive, lead=False)


def test_rss_text_includes_end_peak_and_peak_delta() -> None:
    from codeclone.observability.render_html import _rss_text

    rendered = _rss_text(
        1.0,
        end=0.5,
        peak=2.0,
        peak_delta=0.75,
    )
    assert "end" in rendered
    assert "peak" in rendered
    assert "peakΔ" in rendered


def test_render_highlights_process_peak_rss_without_span_consumer() -> None:
    from codeclone.observability.render_html import render_trace_html
    from codeclone.observability.views import AggregatesView, TraceView

    trace = TraceView(
        schema_version="1.0",
        window_started_at_utc="t0",
        window_ended_at_utc="t1",
        aggregates=AggregatesView(operation_count=1, max_peak_rss_mb=512.0),
    )
    html = render_trace_html(trace)
    assert "Process peak RSS" in html
    assert "high-water resident set" in html
