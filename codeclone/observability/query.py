# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``query_platform_observability`` — a sectioned, read-only diagnostics slicer
over runtime telemetry.

A **slicer, not a trace export API**: each call returns one bounded *section*
projected from the already-computed ``AggregatesView``; no response embeds the
full trace. Dev-only telemetry about the runtime of *CodeClone itself* — it is
NOT a repository-quality signal and MUST NOT affect reports, gates, baselines,
memory facts, or edit authorization. Numeric metrics only: no raw SQL, no raw
payload bodies, no prompts.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

from ..config.observability import resolve_observability_config
from .runtime import DB_COUNTER_VERSION
from .store.reader import build_trace_view, open_observability_store_readonly
from .views import AggregatesView, OperationView, SpanView, TraceView

_DETAIL_LEVELS = ("compact", "normal", "full")
_LIMIT_MIN = 1
_LIMIT_MAX = 100
_LIMIT_DEFAULT = 10
_COMPACT_ROWS = 5
_CHAIN_CHILD_CAP = 12
_MAX_DIAGNOSTICS = 3

# Heuristic thresholds — telemetry hints, NOT report findings.
_DB_CHATTY_QPC = 200
_CONTEXT_HEAVY_PCT = 25
_MEMORY_HEAVY_MB = 200.0
_CONTEXT_PRESSURE_UNITS = 8000
_ANALYSIS_HEAVY_WORKER_MS = 2000.0

_AGGREGATE_SECTIONS = (
    "summary",
    "slow_operations",
    "memory_pipeline_cost",
    "db_cost",
    "agent_context",
    "mcp_tool_matrix",
    "correlated_chains",
    "costly_noops",
    "pipeline",
    "analysis_phase_cost",
)
# Per-object detail sections: full per-span fields for one operation / span by id,
# parity with the HTML trace. They consume operation_id / span_id and support
# detail_level=full (aggregate sections downgrade full to normal).
_DETAIL_SECTIONS = ("operation_detail", "span_detail")


def _round1(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _db_per_call(total_queries: int, span_count: int) -> int:
    return round(total_queries / span_count) if span_count else 0


def _envelope(section: str, detail_level: str, window: str) -> dict[str, object]:
    return {
        "surface": "platform_observability",
        "audience": "codeclone_development",
        "user_facing": False,
        "affects_analysis_truth": False,
        "affects_edit_permission": False,
        "section": section,
        "detail_level": detail_level,
        "window": window,
    }


def _resolve_detail(detail_level: str, section: str, warnings: list[str]) -> str:
    if detail_level not in _DETAIL_LEVELS:
        warnings.append(f"unknown detail_level {detail_level!r}; using compact")
        return "compact"
    if detail_level == "full" and section not in _DETAIL_SECTIONS:
        # Only the per-object detail sections support full; aggregate sections
        # downgrade rather than error so an agent never stalls mid-diagnosis.
        warnings.append(
            "full detail is only available for operation_detail/span_detail; "
            "downgraded to normal"
        )
        return "normal"
    return detail_level


def _clamp_limit(limit: int, warnings: list[str]) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < _LIMIT_MIN:
        warnings.append(f"limit {limit!r} invalid; using {_LIMIT_DEFAULT}")
        return _LIMIT_DEFAULT
    if limit > _LIMIT_MAX:
        warnings.append(f"limit {limit} clamped to {_LIMIT_MAX}")
        return _LIMIT_MAX
    return limit


def _ignored_parameters(
    section: str, operation_id: str | None, span_id: str | None
) -> list[str]:
    # operation_detail consumes operation_id; span_detail consumes span_id; every
    # aggregate section ignores both. Echo the unused selector so the caller knows.
    consumed = {
        "operation_detail": "operation_id",
        "span_detail": "span_id",
    }.get(section)
    ignored = []
    if operation_id is not None and consumed != "operation_id":
        ignored.append("operation_id")
    if span_id is not None and consumed != "span_id":
        ignored.append("span_id")
    return ignored


def _absent_status() -> str:
    # Two distinct diagnoses: observability is configured off ("disabled") vs.
    # it could collect but no store exists for this root yet ("no_store").
    return "no_store" if resolve_observability_config().enabled else "disabled"


def _build_trace(conn: object, window: str) -> TraceView:
    if window == "latest":
        return build_trace_view(conn)  # type: ignore[arg-type]
    return build_trace_view(conn, correlation_id=window)  # type: ignore[arg-type]


def _slow_operations(agg: AggregatesView, cap: int) -> list[dict[str, object]]:
    return [
        {
            "operation_id": op.operation_id,
            "operation": op.name,
            "surface": op.surface,
            "duration_ms": round(op.duration_ms, 1),
            "rss_delta_mb": _round1(op.rss_delta_mb),
        }
        for op in agg.slowest[:cap]
    ]


def _memory_pipeline_cost(agg: AggregatesView, cap: int) -> list[dict[str, object]]:
    return [
        {
            "span_id": s.span_id,
            "operation_id": s.operation_id,
            "span": s.name,
            "operation": s.operation_name,
            "duration_ms": round(s.duration_ms, 1),
            "produced": s.produced,
            "skipped": s.skipped,
            "no_op": s.no_op,
        }
        for s in agg.semantic_costs[:cap]
    ]


def _db_cost(agg: AggregatesView, cap: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for r in agg.db_costs[:cap]:
        per_call = _db_per_call(r.total_queries, r.span_count)
        rows.append(
            {
                "span": r.span_name,
                "calls": r.span_count,
                "queries": r.total_queries,
                "writes": r.total_writes,
                "rows": r.total_rows,
                "queries_per_call": per_call,
                "verdict": "query_chatty" if per_call >= _DB_CHATTY_QPC else "ok",
            }
        )
    return rows


def _mcp_tool_matrix(agg: AggregatesView, cap: int) -> list[dict[str, object]]:
    return [
        {
            "tool": t.name,
            "calls": t.count,
            "p50_ms": round(t.p50_duration_ms, 1),
            "p95_ms": round(t.p95_duration_ms, 1),
            "p95_request_bytes": t.p95_request_bytes,
            "p95_response_bytes": t.p95_response_bytes,
            "p95_response_tokens": t.p95_response_tokens,
        }
        for t in agg.mcp_tools[:cap]
    ]


def _costly_noops(agg: AggregatesView, cap: int) -> list[dict[str, object]]:
    noops = [s for s in agg.semantic_costs if s.no_op]
    return [
        {
            "span_id": s.span_id,
            "operation_id": s.operation_id,
            "span": s.name,
            "operation": s.operation_name,
            "duration_ms": round(s.duration_ms, 1),
            "rss_delta_mb": _round1(s.rss_delta_mb),
        }
        for s in noops[:cap]
    ]


def _pipeline(agg: AggregatesView, cap: int) -> list[dict[str, object]]:
    return [
        {
            "subsystem": g.name,
            "operations": g.op_count,
            "duration_ms": round(g.duration_ms, 1),
            "cpu_ms": round(g.cpu_ms, 1),
        }
        for g in agg.pipeline[:cap]
    ]


def _agent_context_body(agg: AggregatesView, cap: int) -> dict[str, object]:
    agent = agg.agent
    if agent is None:
        return {
            "total_response_tokens": 0,
            "total_response_context_units": 0,
            "rows": [],
        }
    total = agent.response_tokens
    rows = [
        {
            "tool": c.name,
            "calls": c.calls,
            "response_tokens": c.response_tokens,
            "response_context_units": c.response_tokens,
            "context_percent": round(100 * c.response_tokens / total) if total else 0,
            "verdict": (
                "context_heavy"
                if total and 100 * c.response_tokens / total >= _CONTEXT_HEAVY_PCT
                else "ok"
            ),
        }
        for c in agent.consumers[:cap]
    ]
    return {
        "total_response_tokens": total,
        "total_response_context_units": total,
        "rows": rows,
    }


def _analysis_phase_body(agg: AggregatesView, cap: int) -> dict[str, object]:
    rows = [
        {
            "phase": row.phase,
            "worker_elapsed_ms": row.worker_elapsed_ms,
            "share_permille": row.share_permille,
            "verdict": row.verdict,
        }
        for row in agg.analysis_phases[:cap]
    ]
    body: dict[str, object] = {
        "phase_worker_elapsed_total_ms": (agg.analysis_phase_worker_elapsed_total_ms),
        "pipeline_process_wall_ms": agg.analysis_phase_pipeline_wall_ms,
        "source_spans": agg.analysis_phase_source_spans,
        "files_timed": agg.analysis_phase_files_timed,
        "units_eligible": agg.analysis_phase_units_eligible,
        "rows": rows,
    }
    if not rows:
        body["message"] = (
            "no analysis phase counters in window; run with "
            "CODECLONE_OBSERVABILITY_ENABLED=1 and a full analyze."
        )
    return body


def _chain_descendant_names(op: OperationView) -> list[str]:
    names: list[str] = []
    for child in op.children:
        names.append(child.name)
        names.extend(span.name for span in child.spans)
        names.extend(_chain_descendant_names(child))
    return names


def _chain_peak_rss(op: OperationView) -> float | None:
    values = [op.rss_delta_mb] if op.rss_delta_mb is not None else []
    values.extend(s.rss_delta_mb for s in op.spans if s.rss_delta_mb is not None)
    for child in op.children:
        child_peak = _chain_peak_rss(child)
        if child_peak is not None:
            values.append(child_peak)
    return max(values) if values else None


def _chain_peak_rss_absolute(op: OperationView) -> float | None:
    values: list[float] = [
        candidate for candidate in (op.peak_rss_mb, op.rss_mb) if candidate is not None
    ]
    for span in op.spans:
        values.extend(
            candidate
            for candidate in (span.peak_rss_mb, span.rss_mb)
            if candidate is not None
        )
    for child in op.children:
        child_peak = _chain_peak_rss_absolute(child)
        if child_peak is not None:
            values.append(child_peak)
    return max(values) if values else None


def _correlated_chains(trace: TraceView, cap: int) -> list[dict[str, object]]:
    return [
        {
            "operation_id": root.operation_id,
            "root": root.name,
            "children": _chain_descendant_names(root)[:_CHAIN_CHILD_CAP],
            "duration_ms": round(root.duration_ms, 1),
            "peak_rss_delta_mb": _round1(_chain_peak_rss(root)),
            "peak_rss_mb": _round1(_chain_peak_rss_absolute(root)),
        }
        for root in trace.operation_tree[:cap]
    ]


def _span_row(span: SpanView) -> dict[str, object]:
    return {
        "span_id": span.span_id,
        "name": span.name,
        "duration_ms": round(span.duration_ms, 1),
        "span_status": span.status,
        "parent_span_id": span.parent_span_id,
        "reason_kind": span.reason_kind,
        "started_at_utc": span.started_at_utc,
        "rss_mb": _round1(span.rss_mb),
        "peak_rss_mb": _round1(span.peak_rss_mb),
        "rss_delta_mb": _round1(span.rss_delta_mb),
        "peak_rss_delta_mb": _round1(span.peak_rss_delta_mb),
        "counters": dict(span.counters),
        "db_fingerprints": dict(span.db_fingerprints),
    }


def _iter_operations(ops: tuple[OperationView, ...]) -> Iterator[OperationView]:
    for op in ops:
        yield op
        yield from _iter_operations(op.children)


def _operation_detail_body(
    trace: TraceView, operation_id: str, cap: int
) -> dict[str, object]:
    op = next(
        (
            candidate
            for candidate in _iter_operations(trace.operation_tree)
            if candidate.operation_id == operation_id
        ),
        None,
    )
    if op is None:
        return {"status": "not_found", "operation_id": operation_id, "spans": []}
    return {
        "status": "ok",
        "operation_id": op.operation_id,
        "name": op.name,
        "surface": op.surface,
        "duration_ms": round(op.duration_ms, 1),
        "op_status": op.status,
        "rss_mb": _round1(op.rss_mb),
        "peak_rss_mb": _round1(op.peak_rss_mb),
        "rss_delta_mb": _round1(op.rss_delta_mb),
        "peak_rss_delta_mb": _round1(op.peak_rss_delta_mb),
        "cpu_user_ms": _round1(op.cpu_user_ms),
        "cpu_system_ms": _round1(op.cpu_system_ms),
        "span_count": len(op.spans),
        "spans": [_span_row(span) for span in op.spans[:cap]],
    }


def _span_detail_body(trace: TraceView, span_id: str) -> dict[str, object]:
    for op in _iter_operations(trace.operation_tree):
        for span in op.spans:
            if span.span_id == span_id:
                row = _span_row(span)
                row["status"] = "ok"
                row["operation_id"] = op.operation_id
                row["operation_name"] = op.name
                return row
    return {"status": "not_found", "span_id": span_id}


def _memory_diagnostic(agg: AggregatesView) -> dict[str, object] | None:
    span = agg.peak_memory_span
    if span is None:
        return None
    peak = span.peak_rss_mb or span.rss_mb
    delta = span.peak_rss_delta_mb or span.rss_delta_mb
    if peak is None and delta is None:
        return None
    if (
        delta is not None
        and delta < _MEMORY_HEAVY_MB
        and (peak is None or peak < _MEMORY_HEAVY_MB)
    ):
        return None
    detail = []
    if peak is not None:
        detail.append(f"peak {round(peak)} MB")
    if delta is not None:
        detail.append(f"Δ{round(delta)} MB")
    return {
        "kind": "memory",
        "message": (
            f"{span.name} used {' · '.join(detail)} (produced {span.produced})."
        ),
    }


def _db_diagnostic(agg: AggregatesView) -> dict[str, object] | None:
    if not agg.db_costs:
        return None
    top = agg.db_costs[0]
    per_call = _db_per_call(top.total_queries, top.span_count)
    if per_call < _DB_CHATTY_QPC:
        return None
    return {
        "kind": "db",
        "message": f"{top.span_name} executed {per_call} queries per call.",
    }


def _context_diagnostic(agg: AggregatesView) -> dict[str, object] | None:
    agent = agg.agent
    if agent is None or not agent.consumers or not agent.response_tokens:
        return None
    lead = agent.consumers[0]
    pct = round(100 * lead.response_tokens / agent.response_tokens)
    if pct < _CONTEXT_HEAVY_PCT:
        return None
    return {
        "kind": "context",
        "message": f"{lead.name} consumed {pct}% of returned context units.",
    }


def _analysis_diagnostic(agg: AggregatesView) -> dict[str, object] | None:
    if not agg.analysis_phases:
        return None
    top = agg.analysis_phases[0]
    if top.verdict != "phase_heavy":
        return None
    return {
        "kind": "analysis",
        "message": (
            f"{top.phase} consumed {top.share_permille / 10:.0f}% of measured "
            f"extract time ({top.worker_elapsed_ms:.0f} ms)."
        ),
    }


def _top_diagnostics(agg: AggregatesView) -> list[dict[str, object]]:
    candidates = (
        _memory_diagnostic(agg),
        _db_diagnostic(agg),
        _context_diagnostic(agg),
        _analysis_diagnostic(agg),
    )
    return [d for d in candidates if d is not None][:_MAX_DIAGNOSTICS]


def _summary_body(trace: TraceView) -> dict[str, object]:
    agg = trace.aggregates
    body: dict[str, object] = {
        "operations": agg.operation_count,
        "db_counter_version": DB_COUNTER_VERSION,
        "peak_rss_delta_mb": _round1(agg.max_rss_delta_mb),
        "peak_rss_mb": _round1(agg.max_peak_rss_mb),
        "context_pressure_tokens": agg.agent.response_tokens if agg.agent else 0,
        "context_pressure_units": agg.agent.response_tokens if agg.agent else 0,
        "costly_noops": sum(1 for s in agg.semantic_costs if s.no_op),
        "top_diagnostics": _top_diagnostics(agg),
    }
    if agg.analysis_phases:
        body["analysis_phase_worker_elapsed_total_ms"] = (
            agg.analysis_phase_worker_elapsed_total_ms
        )
        body["top_analysis_phases"] = [
            {
                "phase": row.phase,
                "share_permille": row.share_permille,
            }
            for row in agg.analysis_phases[:_MAX_DIAGNOSTICS]
        ]
    return body


def _recommended_next_sections(
    section: str, agg: AggregatesView
) -> list[dict[str, object]]:
    if section != "summary":
        return []
    recs: list[dict[str, object]] = []
    if agg.db_costs:
        top = agg.db_costs[0]
        if _db_per_call(top.total_queries, top.span_count) >= _DB_CHATTY_QPC:
            recs.append(
                {
                    "section": "db_cost",
                    "reason": f"high query count in {top.span_name}.",
                }
            )
    if agg.agent and agg.agent.response_tokens >= _CONTEXT_PRESSURE_UNITS:
        recs.append(
            {"section": "agent_context", "reason": "high context-unit pressure."}
        )
    if any(s.no_op for s in agg.semantic_costs):
        recs.append(
            {"section": "costly_noops", "reason": "a span ran but produced nothing."}
        )
    if (
        agg.analysis_phase_worker_elapsed_total_ms is not None
        and agg.analysis_phase_worker_elapsed_total_ms >= _ANALYSIS_HEAVY_WORKER_MS
    ) or any(row.verdict == "phase_heavy" for row in agg.analysis_phases):
        recs.append(
            {
                "section": "analysis_phase_cost",
                "reason": "pipeline.process phase breakdown available.",
            }
        )
    return recs


_ROW_SECTIONS: dict[str, Callable[[AggregatesView, int], list[dict[str, object]]]] = {
    "slow_operations": _slow_operations,
    "memory_pipeline_cost": _memory_pipeline_cost,
    "db_cost": _db_cost,
    "mcp_tool_matrix": _mcp_tool_matrix,
    "costly_noops": _costly_noops,
    "pipeline": _pipeline,
}


def query_platform_observability(
    *,
    root: str | Path,
    section: str,
    detail_level: str = "compact",
    limit: int = _LIMIT_DEFAULT,
    window: str = "latest",
    operation_id: str | None = None,
    span_id: str | None = None,
) -> dict[str, object]:
    """Return one bounded telemetry section. Read-only; never raises on missing
    data — an absent store yields an inert ``disabled``/``no_store`` envelope.
    """
    warnings: list[str] = []
    detail = _resolve_detail(detail_level, section, warnings)
    clamped = _clamp_limit(limit, warnings)
    row_cap = min(clamped, _COMPACT_ROWS) if detail == "compact" else clamped

    response = _envelope(section, detail, window)
    if detail != detail_level:
        response["requested_detail_level"] = detail_level
    ignored = _ignored_parameters(section, operation_id, span_id)
    if ignored:
        response["ignored_parameters"] = ignored

    if section not in _AGGREGATE_SECTIONS and section not in _DETAIL_SECTIONS:
        response["status"] = "invalid_section"
        response["error"] = f"unknown section {section!r}"
        response["available_sections"] = [
            *_AGGREGATE_SECTIONS,
            *_DETAIL_SECTIONS,
        ]
        response["rows"] = []
        return _finalize(response, warnings)

    if section == "operation_detail" and not operation_id:
        response["status"] = "invalid_selector"
        response["error"] = "operation_detail requires operation_id"
        response["spans"] = []
        return _finalize(response, warnings)
    if section == "span_detail" and not span_id:
        response["status"] = "invalid_selector"
        response["error"] = "span_detail requires span_id"
        return _finalize(response, warnings)

    conn = open_observability_store_readonly(Path(root))
    if conn is None:
        response["status"] = _absent_status()
        response["rows"] = []
        return _finalize(response, warnings)
    try:
        trace = _build_trace(conn, window)
    finally:
        conn.close()

    agg = trace.aggregates
    if section == "operation_detail":
        assert operation_id is not None
        response.update(_operation_detail_body(trace, operation_id, row_cap))
    elif section == "span_detail":
        assert span_id is not None
        response.update(_span_detail_body(trace, span_id))
    elif section == "summary":
        response.update(_summary_body(trace))
    elif section == "agent_context":
        response.update(_agent_context_body(agg, row_cap))
    elif section == "analysis_phase_cost":
        response.update(_analysis_phase_body(agg, row_cap))
    elif section == "correlated_chains":
        response["rows"] = _correlated_chains(trace, row_cap)
    else:
        response["rows"] = _ROW_SECTIONS[section](agg, row_cap)

    recommended = _recommended_next_sections(section, agg)
    if recommended:
        response["recommended_next_sections"] = recommended
    return _finalize(response, warnings)


def _finalize(response: dict[str, object], warnings: list[str]) -> dict[str, object]:
    if warnings:
        response["warnings"] = warnings
    return response


__all__ = ["query_platform_observability"]
