# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Branded HTML renderer for the observability ``TraceView`` (Phase 29 output).

Self-contained single page: the CodeClone brand logo + brand tokens (Inter /
JetBrains Mono / oklch indigo, auto dark-light), a focused embedded stylesheet,
and inline SVG bars — no external assets, no ``report`` import, no JS required.
The trace is a column-aligned grid: names, bars, durations and metrics line up
across every row, and an operation's child operations nest under it.
"""

from __future__ import annotations

from collections.abc import Mapping
from html import escape

from .views import AggregatesView, McpToolAggregate, OperationView, SpanView, TraceView

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
--mcp:#818cf8;--cli:#2dd4bf;--memory:#fbbf24;
--font:"Inter","Inter Variable",-apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:light){:root{
--bg:oklch(98.5% 0.006 275);--surface:#fff;--surface-2:oklch(97.3% 0.006 275);
--border:oklch(89% 0.018 275);--text:oklch(24% 0.040 275);
--dim:oklch(44% 0.046 275);--mute:oklch(55% 0.040 275);
--accent:#4f46e5;--accent-soft:color-mix(in oklch,#4f46e5 28%,transparent);
--track:oklch(92% 0.012 275);--mcp:#4f46e5;--cli:#0d9488;--memory:#b45309;
}}
html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--text);font-family:var(--font);
font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased;
padding:34px 20px 80px}
.wrap{max-width:1000px;margin:0 auto}
.head{display:flex;align-items:center;gap:13px;margin-bottom:5px}
.logo{flex-shrink:0}
h1{font-size:20px;font-weight:600;letter-spacing:-0.01em}
.sub{color:var(--dim);font-size:12.5px;margin:0 0 28px 43px;font-family:var(--mono)}
.sub b{color:var(--text);font-weight:550}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:32px}
.card{background:var(--surface);border:1px solid var(--border);
border-radius:10px;padding:14px 16px}
.card .v{font-size:23px;font-weight:600;letter-spacing:-0.02em;font-family:var(--mono)}
.card .l{color:var(--mute);font-size:10.5px;text-transform:uppercase;
letter-spacing:0.07em;margin-top:4px}
.card.warn .v{color:var(--warn)}
.card.accent .v{color:var(--accent)}
h2{font-size:11px;text-transform:uppercase;letter-spacing:0.08em;
color:var(--mute);font-weight:600;margin:0 0 10px 2px}
section{margin-bottom:30px}
.panel{background:var(--surface);border:1px solid var(--border);
border-radius:10px;overflow:hidden}
.badge{font-size:10px;font-weight:600;font-family:var(--mono);padding:2px 6px;
border-radius:5px;text-transform:uppercase;letter-spacing:0.03em;
justify-self:start;
background:color-mix(in oklch,var(--c,var(--accent)) 15%,transparent);
color:var(--c,var(--accent))}
.surf-mcp{--c:var(--mcp)}.surf-cli{--c:var(--cli)}.surf-memory{--c:var(--memory)}
.name{font-family:var(--mono);font-size:12.5px;min-width:0;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dur{font-family:var(--mono);font-size:12.5px;text-align:right;
white-space:nowrap}
.rss{font-family:var(--mono);font-size:11.5px;color:var(--warn);
text-align:right;white-space:nowrap;font-weight:550}
.bar{display:block;width:100%;height:7px}
.chip{font-size:10.5px;font-family:var(--mono);padding:1px 7px;border-radius:20px;
background:var(--surface-2);color:var(--dim);border:1px solid var(--border);
white-space:nowrap}
.chip.unknown{color:var(--warn);border-color:transparent;
background:color-mix(in oklch,var(--warn) 13%,transparent)}
.slow{display:grid;
grid-template-columns:58px minmax(0,1fr) 150px 56px 78px;
align-items:center;column-gap:13px;padding:9px 16px;
border-top:1px solid var(--border)}
.slow:first-child{border-top:none}
.slow .name{color:var(--text)}
.slow .dur{color:var(--dim)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;padding:9px 16px;color:var(--mute);font-size:10.5px;
text-transform:uppercase;letter-spacing:0.05em;
border-bottom:1px solid var(--border)}
td{padding:8px 16px;border-top:1px solid var(--border);font-family:var(--mono)}
td.t{font-family:var(--font)}
th.r,td.r{text-align:right}
.tree{padding:8px}
.op{border:1px solid var(--border);border-radius:9px;overflow:hidden;
margin:7px 0;background:var(--surface)}
.op:first-child{margin-top:0}
.op .op{margin:8px 10px 10px 22px;border-left:2px solid var(--accent-soft)}
.op-head{display:flex;align-items:center;gap:10px;padding:9px 13px;
background:var(--surface-2)}
.op-head .name{flex:1;font-size:13px;font-weight:550;color:var(--text)}
.op-head .pay{font-family:var(--mono);font-size:11px;color:var(--mute);
white-space:nowrap}
.spans{padding:3px 0 5px}
.span{display:grid;
grid-template-columns:minmax(0,1fr) 150px 56px minmax(120px,0.9fr);
align-items:center;column-gap:13px;row-gap:1px;padding:4px 14px 4px 16px}
.span .name{grid-column:1;grid-row:1;color:var(--dim)}
.span .bar{grid-column:2;grid-row:1}
.span .dur{grid-column:3;grid-row:1;color:var(--dim)}
.span .smeta{grid-column:4;grid-row:1;display:flex;align-items:center;
gap:8px;min-width:0;overflow:hidden}
.span .counters{grid-column:2/-1;grid-row:2;font-family:var(--mono);
font-size:10.5px;color:var(--mute);display:flex;flex-wrap:wrap;gap:0 15px}
.kv b{color:var(--dim);font-weight:550;margin-right:4px}
.empty{padding:28px;text-align:center;color:var(--mute);font-size:13px}
.foot{margin-top:36px;color:var(--mute);font-size:11px;text-align:center;
font-family:var(--mono)}
"""


def _esc(value: object) -> str:
    return escape(str(value))


def _ms(value: float) -> str:
    return f"{value / 1000:.2f}s" if value >= 1000 else f"{value:.0f}ms"


def _mb(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} MB"


def _bytes(value: int | None) -> str:
    if value is None:
        return "—"
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"


def _bar(value: float, maximum: float, *, color: str = "var(--accent)") -> str:
    frac = value / maximum if maximum > 0 else 0.0
    fill = max(1.5, round(frac * 100, 1))
    return (
        '<svg class="bar" viewBox="0 0 100 7" preserveAspectRatio="none" '
        'aria-hidden="true">'
        '<rect width="100" height="7" rx="3.5" fill="var(--track)"/>'
        f'<rect width="{fill}" height="7" rx="3.5" fill="{color}"/></svg>'
    )


_KNOWN_SURFACES = frozenset({"mcp", "cli", "memory"})


def _surface_badge(surface: str) -> str:
    cls = f"surf-{surface}" if surface in _KNOWN_SURFACES else ""
    return f'<span class="badge {cls}">{_esc(surface)}</span>'


def _reason_chip(reason_kind: str | None) -> str:
    if not reason_kind:
        return ""
    extra = " unknown" if reason_kind == "unknown" else ""
    return f'<span class="chip{extra}">{_esc(reason_kind)}</span>'


def _counters(counters: Mapping[str, int]) -> str:
    if not counters:
        return ""
    items = "".join(
        f"<span><b>{_esc(key)}</b>{value}</span>"
        for key, value in sorted(counters.items())
    )
    return f'<span class="counters">{items}</span>'


def _rss(value: float | None) -> str:
    if value is None or value < 0.05:
        return ""
    return f'<span class="rss">Δ{value:.1f} MB</span>'


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


def _stats(agg: AggregatesView) -> str:
    unknown_variant = "warn" if agg.unknown_expensive_rebuild_count else ""
    anomaly_variant = "warn" if agg.anomaly_count else ""
    return (
        '<div class="grid">'
        + _stat(str(agg.operation_count), "operations", "accent")
        + _stat(_mb(agg.max_rss_delta_mb), "peak rss Δ")
        + _stat(
            str(agg.unknown_expensive_rebuild_count),
            "unknown heavy",
            unknown_variant,
        )
        + _stat(str(agg.anomaly_count), "anomalies", anomaly_variant)
        + "</div>"
    )


def _slowest(agg: AggregatesView) -> str:
    if not agg.slowest:
        return ""
    top = agg.slowest[0].duration_ms or 1.0
    rows = "".join(
        f'<div class="slow">{_surface_badge(op.surface)}'
        f'<span class="name">{_esc(op.name)}</span>{_bar(op.duration_ms, top)}'
        f'<span class="dur">{_ms(op.duration_ms)}</span>'
        f'<span class="rss">{_rss_value(op.rss_delta_mb)}</span></div>'
        for op in agg.slowest
    )
    return (
        f'<section><h2>Slowest operations</h2><div class="panel">{rows}</div></section>'
    )


def _rss_value(value: float | None) -> str:
    return "" if value is None or value < 0.05 else f"Δ{value:.1f} MB"


def _mcp(tools: tuple[McpToolAggregate, ...]) -> str:
    if not tools:
        return ""
    rows = "".join(
        f'<tr><td class="t">{_esc(tool.name)}</td><td class="r">{tool.count}</td>'
        f'<td class="r">{_ms(tool.p50_duration_ms)}</td>'
        f'<td class="r">{_ms(tool.p95_duration_ms)}</td>'
        f'<td class="r">{_bytes(tool.p95_response_bytes)}</td></tr>'
        for tool in tools
    )
    return (
        '<section><h2>MCP tool payloads</h2><div class="panel"><table>'
        '<thead><tr><th>Tool</th><th class="r">Calls</th>'
        '<th class="r">p50</th><th class="r">p95</th>'
        '<th class="r">p95 response</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div></section>"
    )


def _payload(op: OperationView) -> str:
    parts = []
    if op.request_bytes is not None:
        parts.append(f"↑{_bytes(op.request_bytes)}")
    if op.response_bytes is not None:
        parts.append(f"↓{_bytes(op.response_bytes)}")
    return f'<span class="pay">{" ".join(parts)}</span>' if parts else ""


def _span_row(span: SpanView, op_duration: float) -> str:
    color = "var(--warn)" if span.reason_kind == "unknown" else "var(--cli)"
    meta = _reason_chip(span.reason_kind) + _rss(span.rss_delta_mb)
    return (
        f'<div class="span"><span class="name">{_esc(span.name)}</span>'
        f"{_bar(span.duration_ms, op_duration, color=color)}"
        f'<span class="dur">{_ms(span.duration_ms)}</span>'
        f'<span class="smeta">{meta}</span>'
        f"{_counters(span.counters)}</div>"
    )


def _op_card(op: OperationView) -> str:
    op_duration = op.duration_ms or 1.0
    head = (
        f'<div class="op-head">{_surface_badge(op.surface)}'
        f'<span class="name">{_esc(op.name)}</span>'
        f'<span class="dur">{_ms(op.duration_ms)}</span>'
        f"{_rss(op.rss_delta_mb)}{_payload(op)}</div>"
    )
    spans = (
        f'<div class="spans">{"".join(_span_row(s, op_duration) for s in op.spans)}'
        "</div>"
        if op.spans
        else ""
    )
    children = "".join(_op_card(child) for child in op.children)
    return f'<div class="op">{head}{spans}{children}</div>'


def _tree(trace: TraceView) -> str:
    if not trace.operation_tree:
        return (
            '<section><h2>Trace</h2><div class="panel">'
            '<div class="empty">No operations recorded yet.</div>'
            "</div></section>"
        )
    cards = "".join(_op_card(op) for op in trace.operation_tree)
    return f'<section><h2>Trace</h2><div class="panel tree">{cards}</div></section>'


def render_trace_html(trace: TraceView) -> str:
    """Render a ``TraceView`` as a self-contained, branded HTML document."""
    foot = f"CodeClone · platform observability · schema {_esc(trace.schema_version)}"
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>CodeClone · Platform Observability</title>"
        f'<style>{_CSS}</style></head><body><div class="wrap">'
        + _header(trace)
        + _stats(trace.aggregates)
        + _slowest(trace.aggregates)
        + _mcp(trace.aggregates.mcp_tools)
        + _tree(trace)
        + f'<p class="foot">{foot}</p>'
        + "</div></body></html>"
    )


__all__ = ["render_trace_html"]
