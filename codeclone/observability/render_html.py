# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Branded HTML renderer for the observability ``TraceView`` (Phase 29 output).

A single self-contained page rendered as a *runtime-diagnosis cockpit*, not a
data dump. It is laid out for a top-down reading trajectory that answers the
operator's questions in order: an executive summary that names where time and
memory went; the correlated finish->worker event chains (a horizontal causality
breadcrumb plus indented detail — nesting is shown with an indent rail, never a
card inside a card); a memory-pipeline cost table that flags spans that ran but
produced nothing; and an MCP tool matrix that surfaces payload noise.

CodeClone brand mark + brand tokens (Inter / JetBrains Mono / oklch indigo, auto
dark-light), inline SVG bars, no JS, no external assets, no ``report`` import.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape

from .views import (
    AggregatesView,
    McpToolAggregate,
    OperationView,
    SpanCostView,
    SpanView,
    TraceView,
    WaterfallGroup,
    WaterfallRow,
)

# A no-op span only deserves a "costly" warning once it has actually spent time.
_NOOP_COSTLY_MS = 50.0
_KNOWN_SURFACES = frozenset({"mcp", "cli", "memory"})

# Reuse of the CodeClone brand mark (report/html/widgets/icons.py:BRAND_LOGO).
_LOGO = (
    '<svg class="logo" width="30" height="30" viewBox="0 0 64 64" fill="none">'
    '<rect x="24" y="10" width="31" height="40" rx="7" '
    'fill="var(--accent)" opacity="0.22"/>'
    '<rect x="16" y="18" width="31" height="40" rx="7" fill="var(--accent)"/>'
    '<path d="M27 32.5L21 38.5L27 44.5" stroke="#fff" stroke-width="4" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M36.5 32.5L42.5 38.5L36.5 44.5" stroke="#fff" stroke-width="4" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{
--bg:oklch(15% 0.018 275);--surface:oklch(20% 0.022 275);
--surface-2:oklch(24% 0.026 275);--border:oklch(31% 0.034 275);
--text:oklch(96% 0.010 275);--dim:oklch(74% 0.028 275);--mute:oklch(56% 0.028 275);
--accent:#818cf8;--accent-soft:color-mix(in oklch,#818cf8 30%,transparent);
--track:oklch(28% 0.02 275);--warn:#f59e0b;
--warn-soft:color-mix(in oklch,#f59e0b 14%,transparent);
--mcp:#818cf8;--cli:#2dd4bf;--memory:#fbbf24;
--font:"Inter","Inter Variable",-apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:light){:root{
--bg:oklch(98.5% 0.006 275);--surface:#fff;--surface-2:oklch(97.3% 0.006 275);
--border:oklch(89% 0.018 275);--text:oklch(24% 0.040 275);
--dim:oklch(44% 0.046 275);--mute:oklch(55% 0.040 275);
--accent:#4f46e5;--accent-soft:color-mix(in oklch,#4f46e5 26%,transparent);
--track:oklch(92% 0.012 275);--warn:#b45309;
--warn-soft:color-mix(in oklch,#b45309 12%,transparent);
--mcp:#4f46e5;--cli:#0d9488;--memory:#b45309;
}}
html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--text);font-family:var(--font);
font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;
padding:36px 22px 90px}
.wrap{max-width:1040px;margin:0 auto}
.head{display:flex;align-items:center;gap:13px;margin-bottom:5px}
.logo{flex-shrink:0}
h1{font-size:20px;font-weight:600;letter-spacing:-0.01em}
.sub{color:var(--dim);font-size:12.5px;margin:0 0 30px 43px;font-family:var(--mono)}
.sub b{color:var(--text);font-weight:550}
section{margin-bottom:30px}
h2{font-size:11px;text-transform:uppercase;letter-spacing:0.09em;
color:var(--mute);font-weight:600;margin:0 0 4px 2px}
.shint{color:var(--mute);font-size:12px;margin:0 0 11px 2px}
.panel{background:var(--surface);border:1px solid var(--border);
border-radius:11px;overflow:hidden}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.card{background:var(--surface);border:1px solid var(--border);
border-radius:11px;padding:14px 16px}
.card .v{font-size:24px;font-weight:600;letter-spacing:-0.02em;
font-family:var(--mono)}
.card .l{color:var(--mute);font-size:10.5px;text-transform:uppercase;
letter-spacing:0.07em;margin-top:4px}
.card.warn{border-color:var(--warn-soft)}
.card.warn .v{color:var(--warn)}
.card.accent .v{color:var(--accent)}
.lead{padding:4px 16px}
.lrow{display:grid;grid-template-columns:158px minmax(0,1fr) auto;align-items:center;
gap:14px;padding:11px 0;border-top:1px solid var(--border)}
.lrow:first-child{border-top:none}
.llabel{color:var(--mute);font-size:11px;text-transform:uppercase;
letter-spacing:0.05em}
.lval{display:flex;align-items:center;gap:9px;min-width:0}
.lname{font-family:var(--mono);font-size:13px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.lin{color:var(--mute);font-size:11.5px;font-family:var(--mono)}
.lmetric{font-family:var(--mono);font-size:14px;font-weight:600;white-space:nowrap}
.badge{font-size:10px;font-weight:600;font-family:var(--mono);padding:2px 7px;
border-radius:5px;text-transform:uppercase;letter-spacing:0.03em;flex-shrink:0;
background:color-mix(in oklch,var(--c,var(--accent)) 16%,transparent);
color:var(--c,var(--accent))}
.surf-mcp{--c:var(--mcp)}.surf-cli{--c:var(--cli)}.surf-memory{--c:var(--memory)}
.chip{font-size:10.5px;font-family:var(--mono);padding:1px 8px;border-radius:20px;
background:var(--surface-2);color:var(--dim);border:1px solid var(--border);
white-space:nowrap}
.chip.warn{color:var(--warn);border-color:transparent;background:var(--warn-soft);
font-weight:600}
.bar{display:block;width:100%;height:7px}
.dur{font-family:var(--mono);font-size:12.5px;text-align:right;white-space:nowrap;
color:var(--dim)}
.rss{font-family:var(--mono);font-size:11.5px;color:var(--warn);white-space:nowrap;
font-weight:550}
.meta{display:flex;align-items:center;justify-content:flex-end;gap:8px;min-width:0}
.pay{font-family:var(--mono);font-size:11px;color:var(--mute);white-space:nowrap}
.chain{padding:6px 16px 12px}
.group{padding:13px 0;border-top:1px solid var(--border)}
.group:first-child{border-top:none}
.crumb{display:flex;align-items:center;flex-wrap:wrap;gap:9px;margin-bottom:10px}
.crumb .node{display:flex;align-items:center;gap:7px}
.crumb .cname{font-family:var(--mono);font-size:12px;color:var(--text)}
.crumb .arrow{color:var(--mute);font-size:13px}
.oprow,.spanrow{display:grid;
grid-template-columns:minmax(0,1fr) 160px 64px minmax(92px,auto);
align-items:center;column-gap:14px;row-gap:2px;padding:5px 0}
.lead-cell{display:flex;align-items:center;gap:9px;min-width:0}
.opname{font-family:var(--mono);font-size:13px;font-weight:550;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.spanname{font-family:var(--mono);font-size:12px;color:var(--dim);overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.tick{color:var(--accent);opacity:0.6;font-size:11px;flex-shrink:0}
.spanrow .counters{grid-column:2/-1;font-family:var(--mono);font-size:10.5px;
color:var(--mute);display:flex;flex-wrap:wrap;gap:0 15px}
.counters b{color:var(--dim);font-weight:550;margin-right:4px}
.spans{padding-left:17px}
.kids{margin-left:13px;padding-left:17px;border-left:2px solid var(--accent-soft)}
.wf{padding:8px 16px 12px}
.wf-group{padding:13px 0;border-top:1px solid var(--border)}
.wf-group:first-child{border-top:none}
.wf-cap{display:flex;align-items:center;gap:8px;margin-bottom:9px;
font-family:var(--mono);font-size:11px;color:var(--mute)}
.wf-cap b{color:var(--dim);font-weight:600}
.wf-row{display:grid;grid-template-columns:minmax(150px,238px) minmax(0,1fr) 58px;
align-items:center;column-gap:12px;padding:2px 0}
.wf-label{font-family:var(--mono);font-size:11.5px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.wf-label.op{color:var(--text);font-weight:550}
.wf-label.span{color:var(--dim)}
.wf-track{position:relative;height:14px;background:var(--track);border-radius:4px}
.wf-bar{position:absolute;top:2px;height:10px;border-radius:3px;
background:var(--c,var(--accent))}
.wf-bar.span{top:3px;height:8px;opacity:0.8}
.wf-dur{font-family:var(--mono);font-size:11px;color:var(--mute);text-align:right;
white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;padding:9px 16px;color:var(--mute);font-size:10.5px;
text-transform:uppercase;letter-spacing:0.05em;
border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:9px 16px;border-top:1px solid var(--border);font-family:var(--mono);
white-space:nowrap}
td.t{font-family:var(--font)}
th.r,td.r{text-align:right}
tr.flag td{background:var(--warn-soft)}
.muted{color:var(--mute)}
.empty{padding:30px;text-align:center;color:var(--mute);font-size:13px}
.foot{margin-top:38px;color:var(--mute);font-size:11px;text-align:center;
font-family:var(--mono)}
"""


def _esc(value: object) -> str:
    return escape(str(value))


def _ms(value: float) -> str:
    return f"{value / 1000:.2f}s" if value >= 1000 else f"{value:.0f}ms"


def _mb(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value / 1024:.1f} GB" if value >= 1024 else f"{value:.1f} MB"


def _bytes(value: int | None) -> str:
    if value is None:
        return "—"
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"


def _tokens(value: int | None) -> str:
    if not value:
        return "—"
    return f"{value / 1000:.1f}k" if value >= 1000 else str(value)


def _bar(value: float, maximum: float, *, color: str = "var(--accent)") -> str:
    frac = value / maximum if maximum > 0 else 0.0
    fill = max(1.5, round(frac * 100, 1))
    return (
        '<svg class="bar" viewBox="0 0 100 7" preserveAspectRatio="none" '
        'aria-hidden="true">'
        '<rect width="100" height="7" rx="3.5" fill="var(--track)"/>'
        f'<rect width="{fill}" height="7" rx="3.5" fill="{color}"/></svg>'
    )


def _surface_badge(surface: str) -> str:
    cls = f"surf-{surface}" if surface in _KNOWN_SURFACES else ""
    return f'<span class="badge {cls}">{_esc(surface)}</span>'


def _reason_chip(reason_kind: str | None) -> str:
    if not reason_kind:
        return ""
    extra = " warn" if reason_kind == "unknown" else ""
    return f'<span class="chip{extra}">{_esc(reason_kind)}</span>'


def _counters(counters: Mapping[str, int]) -> str:
    if not counters:
        return ""
    items = "".join(
        f"<span><b>{_esc(key)}</b>{value}</span>"
        for key, value in sorted(counters.items())
    )
    return f'<span class="counters">{items}</span>'


def _rss_text(value: float | None) -> str:
    return "" if value is None or value < 0.05 else f"Δ{_mb(value)}"


def _rss_badge(value: float | None) -> str:
    text = _rss_text(value)
    return f'<span class="rss">{text}</span>' if text else ""


def _payload(op: OperationView) -> str:
    parts = []
    if op.request_bytes is not None:
        parts.append(f"↑{_bytes(op.request_bytes)}")
    if op.response_bytes is not None:
        parts.append(f"↓{_bytes(op.response_bytes)}")
    return f'<span class="pay">{" ".join(parts)}</span>' if parts else ""


def _header(trace: TraceView) -> str:
    agg = trace.aggregates
    window = (
        f"{_esc(trace.window_started_at_utc)} → {_esc(trace.window_ended_at_utc)}"
        if trace.window_started_at_utc
        else "no operations recorded"
    )
    digest = f" · repo {_esc(trace.repo_root_digest)}" if trace.repo_root_digest else ""
    return (
        f'<div class="head">{_LOGO}<h1>Platform Observability</h1></div>'
        f'<p class="sub"><b>{agg.operation_count}</b> operations · '
        f"{window}{digest}</p>"
    )


def _stat(value: str, label: str, variant: str = "") -> str:
    cls = f"card {variant}".strip()
    return (
        f'<div class="{cls}"><div class="v">{value}</div>'
        f'<div class="l">{label}</div></div>'
    )


def _section(title: str, body: str, *, subtitle: str = "") -> str:
    hint = f'<p class="shint">{_esc(subtitle)}</p>' if subtitle else ""
    return f"<section><h2>{_esc(title)}</h2>{hint}{body}</section>"


def _table(headers: tuple[tuple[str, bool], ...], rows: str) -> str:
    ths = "".join(
        f'<th class="r">{_esc(label)}</th>' if right else f"<th>{_esc(label)}</th>"
        for label, right in headers
    )
    return (
        f'<div class="panel"><table><thead><tr>{ths}</tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def _lead_row(label: str, value_html: str, metric: str) -> str:
    return (
        f'<div class="lrow"><span class="llabel">{_esc(label)}</span>'
        f'<span class="lval">{value_html}</span>'
        f'<span class="lmetric">{_esc(metric)}</span></div>'
    )


def _highlights(agg: AggregatesView) -> str:
    rows: list[str] = []
    if agg.slowest:
        op = agg.slowest[0]
        rows.append(
            _lead_row(
                "Slowest operation",
                f"{_surface_badge(op.surface)}"
                f'<span class="lname">{_esc(op.name)}</span>',
                _ms(op.duration_ms),
            )
        )
    if agg.slowest_span is not None:
        span = agg.slowest_span
        reason = _reason_chip(span.reason_kind)
        rows.append(
            _lead_row(
                "Hottest span",
                f"{_surface_badge(span.surface)}"
                f'<span class="lname">{_esc(span.name)}</span>'
                f'<span class="lin">in {_esc(span.operation_name)}</span>{reason}',
                _ms(span.duration_ms),
            )
        )
    if agg.peak_memory_span is not None and agg.max_rss_delta_mb:
        # Name who took the memory, not just how much — the metric becomes a
        # conclusion ("X grew the RSS", with its share of the peak).
        peak = agg.peak_memory_span
        share = round((peak.rss_delta_mb or 0.0) / agg.max_rss_delta_mb * 100)
        rows.append(
            _lead_row(
                "Top memory consumer",
                f"{_surface_badge(peak.surface)}"
                f'<span class="lname">{_esc(peak.name)}</span>'
                f'<span class="lin">in {_esc(peak.operation_name)}</span>',
                f"{_mb(peak.rss_delta_mb)} · {share}%",
            )
        )
    elif agg.max_rss_delta_mb is not None:
        rows.append(
            _lead_row(
                "Peak memory Δ",
                '<span class="lname">resident set growth</span>',
                _mb(agg.max_rss_delta_mb),
            )
        )
    return f'<div class="panel lead">{"".join(rows)}</div>' if rows else ""


def _summary(trace: TraceView) -> str:
    agg = trace.aggregates
    costly = sum(
        1
        for span in agg.semantic_costs
        if span.no_op and span.duration_ms >= _NOOP_COSTLY_MS
    )
    unknown = agg.unknown_expensive_rebuild_count
    cards = (
        '<div class="grid">'
        + _stat(str(agg.operation_count), "operations", "accent")
        + _stat(_mb(agg.max_rss_delta_mb), "peak rss Δ")
        + _stat(str(costly), "costly no-ops", "warn" if costly else "")
        + _stat(str(unknown), "unknown reason", "warn" if unknown else "")
        + "</div>"
    )
    return _section("Runtime summary", cards + _highlights(agg))


def _op_lineage(op: OperationView) -> list[OperationView]:
    flat = [op]
    for child in op.children:
        flat.extend(_op_lineage(child))
    return flat


def _breadcrumb(lineage: list[OperationView]) -> str:
    if len(lineage) < 2:
        return ""
    nodes = ' <span class="arrow">→</span> '.join(
        f'<span class="node">{_surface_badge(op.surface)}'
        f'<span class="cname">{_esc(op.name)}</span></span>'
        for op in lineage
    )
    return f'<div class="crumb">{nodes}</div>'


def _op_row(op: OperationView, group_max: float) -> str:
    return (
        '<div class="oprow"><span class="lead-cell">'
        f'{_surface_badge(op.surface)}<span class="opname">{_esc(op.name)}</span>'
        f"</span>{_bar(op.duration_ms, group_max)}"
        f'<span class="dur">{_ms(op.duration_ms)}</span>'
        f'<span class="meta">{_rss_badge(op.rss_delta_mb)}{_payload(op)}</span></div>'
    )


def _span_row(span: SpanView, op_duration: float) -> str:
    color = "var(--warn)" if span.reason_kind == "unknown" else "var(--accent)"
    meta = f"{_reason_chip(span.reason_kind)}{_rss_badge(span.rss_delta_mb)}"
    return (
        '<div class="spanrow"><span class="lead-cell">'
        f'<span class="tick">▸</span>'
        f'<span class="spanname">{_esc(span.name)}</span></span>'
        f"{_bar(span.duration_ms, op_duration, color=color)}"
        f'<span class="dur">{_ms(span.duration_ms)}</span>'
        f'<span class="meta">{meta}</span>{_counters(span.counters)}</div>'
    )


def _op_block(op: OperationView, group_max: float) -> str:
    op_duration = op.duration_ms or 1.0
    spans = "".join(_span_row(span, op_duration) for span in op.spans)
    spans_block = f'<div class="spans">{spans}</div>' if spans else ""
    kids = "".join(_op_block(child, group_max) for child in op.children)
    kids_block = f'<div class="kids">{kids}</div>' if kids else ""
    return (
        f'<div class="opnode">{_op_row(op, group_max)}{spans_block}</div>{kids_block}'
    )


def _chain_group(root: OperationView) -> str:
    lineage = _op_lineage(root)
    group_max = max((op.duration_ms for op in lineage), default=1.0) or 1.0
    return (
        f'<div class="group">{_breadcrumb(lineage)}{_op_block(root, group_max)}</div>'
    )


def _chain(trace: TraceView) -> str:
    if not trace.operation_tree:
        body = (
            '<div class="panel"><div class="empty">'
            "No operations recorded yet.</div></div>"
        )
        return _section("Correlated event chains", body)
    groups = "".join(_chain_group(op) for op in trace.operation_tree)
    return _section(
        "Correlated event chains",
        f'<div class="panel chain">{groups}</div>',
        subtitle="What triggered what, across processes — finish → spawned worker.",
    )


def _semantic_row(span: SpanCostView) -> str:
    costly = span.no_op and span.duration_ms >= _NOOP_COSTLY_MS
    if costly:
        verdict = '<span class="chip warn">no-op · costly</span>'
    elif span.no_op:
        verdict = '<span class="chip warn">no-op</span>'
    else:
        verdict = '<span class="muted">productive</span>'
    reason = (
        _esc(span.reason_kind) if span.reason_kind else '<span class="muted">—</span>'
    )
    return (
        f'<tr class="{"flag" if costly else ""}">'
        f'<td class="t">{_esc(span.name)}</td>'
        f'<td class="t muted">{_esc(span.operation_name)}</td>'
        f"<td>{reason}</td>"
        f'<td class="r">{span.produced}</td>'
        f'<td class="r">{span.skipped}</td>'
        f'<td class="r">{_ms(span.duration_ms)}</td>'
        f'<td class="r">{_mb(span.rss_delta_mb)}</td>'
        f"<td>{verdict}</td></tr>"
    )


def _semantic(agg: AggregatesView) -> str:
    if not agg.semantic_costs:
        return ""
    rows = "".join(_semantic_row(span) for span in agg.semantic_costs)
    headers = (
        ("Span", False),
        ("Operation", False),
        ("Reason", False),
        ("Produced", True),
        ("Skipped", True),
        ("Duration", True),
        ("RSS Δ", True),
        ("Verdict", False),
    )
    return _section(
        "Memory pipeline cost",
        _table(headers, rows),
        subtitle="Reindex and rebuild spans — flags work that ran but "
        "produced nothing.",
    )


def _mcp_row(tool: McpToolAggregate) -> str:
    return (
        f'<tr><td class="t">{_esc(tool.name)}</td>'
        f'<td class="r">{tool.count}</td>'
        f'<td class="r">{_ms(tool.p50_duration_ms)}</td>'
        f'<td class="r">{_ms(tool.p95_duration_ms)}</td>'
        f'<td class="r">{_bytes(tool.p95_request_bytes)}</td>'
        f'<td class="r">{_bytes(tool.p95_response_bytes)}</td>'
        f'<td class="r">{_tokens(tool.p95_response_tokens)}</td></tr>'
    )


def _mcp(tools: tuple[McpToolAggregate, ...]) -> str:
    if not tools:
        return ""
    rows = "".join(_mcp_row(tool) for tool in tools)
    headers = (
        ("Tool", False),
        ("Calls", True),
        ("p50", True),
        ("p95", True),
        ("↑ req p95", True),
        ("↓ resp p95", True),
        ("resp tok p95", True),
    )
    return _section(
        "MCP tool matrix",
        _table(headers, rows),
        subtitle="Per-tool latency and payload — spot tools that flood request "
        "or response bytes.",
    )


def _wf_bar(row: WaterfallRow, total_ms: float) -> str:
    span = total_ms if total_ms > 0 else 1.0
    left = round(min(row.offset_ms / span * 100, 99.0), 2)
    width = max(0.6, round(row.duration_ms / span * 100, 2))
    kind = "op" if row.kind == "operation" else "span"
    surf = f"surf-{row.surface}" if row.surface in _KNOWN_SURFACES else ""
    tick = '<span class="tick">▸</span>' if kind == "span" else ""
    return (
        '<div class="wf-row">'
        f'<span class="wf-label {kind}" style="padding-left:{row.depth * 13}px">'
        f"{tick}{_esc(row.label)}</span>"
        f'<div class="wf-track"><div class="wf-bar {kind} {surf}" '
        f'style="left:{left}%;width:{width}%"></div></div>'
        f'<span class="wf-dur">{_ms(row.duration_ms)}</span></div>'
    )


def _wf_group(group: WaterfallGroup) -> str:
    rows = "".join(_wf_bar(row, group.duration_ms) for row in group.rows)
    cid = group.correlation_id[:8] if group.correlation_id else "—"
    return (
        f'<div class="wf-group"><div class="wf-cap"><b>{_esc(cid)}</b>'
        f"<span>{_esc(group.started_at_utc)}</span>"
        f"<span>span {_ms(group.duration_ms)}</span></div>{rows}</div>"
    )


def _waterfall(trace: TraceView) -> str:
    if not trace.waterfall:
        return ""
    groups = "".join(_wf_group(group) for group in trace.waterfall)
    return _section(
        "Timeline",
        f'<div class="panel wf">{groups}</div>',
        subtitle="Each causal chain on its own time axis — bars placed by start "
        "offset, width by duration; a gap before a worker bar is the spawn handoff.",
    )


def render_trace_html(trace: TraceView) -> str:
    """Render a ``TraceView`` as a self-contained, branded diagnosis cockpit."""
    foot = f"CodeClone · platform observability · schema {_esc(trace.schema_version)}"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>CodeClone · Platform Observability</title>"
        f'<style>{_CSS}</style></head><body><div class="wrap">'
        + _header(trace)
        + _summary(trace)
        + _waterfall(trace)
        + _chain(trace)
        + _semantic(trace.aggregates)
        + _mcp(trace.aggregates.mcp_tools)
        + f'<p class="foot">{foot}</p>'
        + "</div></body></html>"
    )


__all__ = ["render_trace_html"]
