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
    SpanView,
    TraceView,
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
