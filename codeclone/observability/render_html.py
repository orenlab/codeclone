# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Branded HTML renderer for the observability ``TraceView`` (Phase 29 output).

Self-contained single page: the CodeClone brand logo + brand tokens (Inter /
JetBrains Mono / oklch indigo, auto dark-light), a focused embedded stylesheet,
and inline SVG bars — no external assets, no ``report`` import, no JS required.
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
--text:oklch(96% 0.010 275);--dim:oklch(74% 0.028 275);--mute:oklch(58% 0.030 275);
--accent:#818cf8;--track:oklch(28% 0.02 275);
--warn:#f59e0b;--ok:#34d399;
--mcp:#818cf8;--cli:#2dd4bf;--memory:#fbbf24;
--font:"Inter","Inter Variable",-apple-system,BlinkMacSystemFont,"Segoe UI",
Roboto,sans-serif;
--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--r:10px;
}
@media (prefers-color-scheme:light){:root{
--bg:oklch(98.5% 0.006 275);--surface:#fff;--surface-2:oklch(97.5% 0.006 275);
--border:oklch(89% 0.018 275);--text:oklch(24% 0.040 275);
--dim:oklch(44% 0.046 275);--mute:oklch(56% 0.040 275);
--accent:#4f46e5;--track:oklch(92% 0.012 275);--mcp:#4f46e5;
--cli:#0d9488;--memory:#b45309;
}}
html{-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--text);font-family:var(--font);
font-size:14px;line-height:1.55;-webkit-font-smoothing:antialiased;
padding:34px 20px 80px}
.wrap{max-width:980px;margin:0 auto}
a{color:var(--accent)}
.head{display:flex;align-items:center;gap:14px;margin-bottom:6px}
.logo{flex-shrink:0}
h1{font-size:20px;font-weight:650;letter-spacing:-0.01em}
.sub{color:var(--dim);font-size:13px;margin:0 0 26px 44px;
font-family:var(--mono)}
.sub b{color:var(--text);font-weight:550}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;
margin-bottom:30px}
.card{background:var(--surface);border:1px solid var(--border);
border-radius:var(--r);padding:15px 16px}
.card .v{font-size:24px;font-weight:650;letter-spacing:-0.02em;
font-family:var(--mono)}
.card .l{color:var(--mute);font-size:11px;text-transform:uppercase;
letter-spacing:0.06em;margin-top:3px}
.card.warn .v{color:var(--warn)}
.card.accent .v{color:var(--accent)}
h2{font-size:12px;text-transform:uppercase;letter-spacing:0.07em;
color:var(--mute);font-weight:600;margin:0 0 11px 2px}
section{margin-bottom:28px}
.panel{background:var(--surface);border:1px solid var(--border);
border-radius:var(--r);overflow:hidden}
.row{display:flex;align-items:center;gap:11px;padding:9px 15px;
border-top:1px solid var(--border)}
.row:first-child{border-top:none}
.badge{font-size:10.5px;font-weight:600;font-family:var(--mono);
padding:2px 7px;border-radius:5px;text-transform:uppercase;
letter-spacing:0.03em;flex-shrink:0;
background:color-mix(in oklch,var(--c,var(--accent)) 16%,transparent);
color:var(--c,var(--accent))}
.surf-mcp{--c:var(--mcp)}.surf-cli{--c:var(--cli)}.surf-memory{--c:var(--memory)}
.name{font-family:var(--mono);font-size:13px;flex:1;min-width:0;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.num{font-family:var(--mono);font-size:12.5px;color:var(--dim);
flex-shrink:0;text-align:right}
.bar{flex-shrink:0;display:block}
.rss{font-family:var(--mono);font-size:11.5px;color:var(--warn);
flex-shrink:0;font-weight:550}
.chip{font-size:11px;font-family:var(--mono);padding:1px 7px;border-radius:20px;
background:var(--surface-2);color:var(--dim);flex-shrink:0;
border:1px solid var(--border)}
.chip.unknown{color:var(--warn);
background:color-mix(in oklch,var(--warn) 12%,transparent);border-color:transparent}
.kv{font-family:var(--mono);font-size:11px;color:var(--mute);margin-right:9px}
.kv b{color:var(--dim);font-weight:550}
.counters{flex-basis:100%;padding-left:1px;margin-top:-2px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 15px;color:var(--mute);font-size:11px;
text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid var(--border)}
td{padding:8px 15px;border-top:1px solid var(--border);font-family:var(--mono)}
td.t{font-family:var(--font)}
th.r,td.r{text-align:right}
.tree{padding:6px 4px}
.op{margin:3px 0;border-radius:8px}
.op-head{display:flex;align-items:center;gap:11px;padding:8px 11px;
background:var(--surface-2);border-radius:8px;border:1px solid var(--border)}
.op>.span,.op>.op{margin-left:18px}
.span{display:flex;align-items:center;gap:11px;padding:6px 11px;flex-wrap:wrap}
.span .name{font-size:12.5px;color:var(--dim);flex:0 0 188px}
.empty{padding:26px;text-align:center;color:var(--mute);font-size:13px}
.foot{margin-top:34px;color:var(--mute);font-size:11.5px;text-align:center;
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
    width = 150
    frac = value / maximum if maximum > 0 else 0.0
    fill = max(2.0, round(frac * width, 1))
    return (
        f'<svg class="bar" width="{width}" height="8" viewBox="0 0 {width} 8" '
        'preserveAspectRatio="none" aria-hidden="true">'
        f'<rect width="{width}" height="8" rx="4" fill="var(--track)"/>'
        f'<rect width="{fill}" height="8" rx="4" fill="{color}"/></svg>'
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
        f'<span class="kv"><b>{_esc(key)}</b> {value}</span>'
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
    rss = _mb(agg.max_rss_delta_mb)
    unknown_variant = "warn" if agg.unknown_expensive_rebuild_count else ""
    anomaly_variant = "warn" if agg.anomaly_count else ""
    return (
        '<div class="grid">'
        + _stat(str(agg.operation_count), "operations", "accent")
        + _stat(rss, "peak rss Δ")
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
        f'<div class="row">{_surface_badge(op.surface)}'
        f'<span class="name">{_esc(op.name)}</span>'
        f"{_bar(op.duration_ms, top)}"
        f'<span class="num">{_ms(op.duration_ms)}</span>{_rss(op.rss_delta_mb)}</div>'
        for op in agg.slowest
    )
    return (
        f'<section><h2>Slowest operations</h2><div class="panel">{rows}</div></section>'
    )


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
    if op.response_bytes is None and op.request_bytes is None:
        return ""
    parts = []
    if op.request_bytes is not None:
        parts.append(f"↑{_bytes(op.request_bytes)}")
    if op.response_bytes is not None:
        parts.append(f"↓{_bytes(op.response_bytes)}")
    return f'<span class="num">{" ".join(parts)}</span>'


def _span_row(span: SpanView, op_duration: float) -> str:
    color = "var(--warn)" if span.reason_kind == "unknown" else "var(--cli)"
    return (
        f'<div class="span"><span class="name">{_esc(span.name)}</span>'
        f"{_bar(span.duration_ms, op_duration, color=color)}"
        f'<span class="num">{_ms(span.duration_ms)}</span>'
        f"{_reason_chip(span.reason_kind)}{_rss(span.rss_delta_mb)}"
        f"{_counters(span.counters)}</div>"
    )


def _op_card(op: OperationView) -> str:
    op_duration = op.duration_ms or 1.0
    spans = "".join(_span_row(span, op_duration) for span in op.spans)
    children = "".join(_op_card(child) for child in op.children)
    return (
        f'<div class="op"><div class="op-head">{_surface_badge(op.surface)}'
        f'<span class="name">{_esc(op.name)}</span>'
        f'<span class="num">{_ms(op.duration_ms)}</span>'
        f"{_rss(op.rss_delta_mb)}{_payload(op)}</div>{spans}{children}</div>"
    )


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
