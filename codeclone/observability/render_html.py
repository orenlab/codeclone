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

from collections.abc import Iterable, Mapping
from html import escape

from .views import (
    AgentTokenRow,
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

# A no-op span only deserves a "costly" warning once it has actually spent time.
_NOOP_COSTLY_MS = 50.0
_KNOWN_SURFACES = frozenset({"mcp", "cli", "memory"})
_ANALYSIS_PHASE_LABELS = {
    "parse": "Parse (ast.parse)",
    "qualname": "Qualname index",
    "module_walk": "Module walk",
    "relationship": "Relationship facts",
    "suppressions": "Suppressions",
    "unit_cfg": "CFG build",
    "unit_normalize_cfg": "Normalize (CFG blocks)",
    "unit_structural": "Structural scan",
    "unit_normalize_stmt": "Normalize (statements)",
    "unit_blocks": "Block extract",
    "unit_segments": "Segment extract",
    "class_metrics": "Class metrics",
    "dead_code": "Dead-code collect",
    "module_passes": "Module passes",
}

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
--radius-sm:4px;--radius-md:6px;--radius-lg:8px;--radius-xl:12px;
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
border-radius:var(--radius-xl);overflow:hidden}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));
gap:10px;margin-bottom:12px}
.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;
margin-bottom:12px}
@media (max-width:760px){.stats{grid-template-columns:repeat(2,minmax(0,1fr))}}
.card{background:var(--surface);border:1px solid var(--border);
border-radius:var(--radius-xl);padding:14px 16px}
.card .v{font-size:24px;font-weight:600;letter-spacing:-0.02em;
font-family:var(--mono)}
.card .l{color:var(--mute);font-size:10.5px;text-transform:uppercase;
letter-spacing:0.07em;margin-top:4px}
.card.warn{border-color:var(--warn-soft)}
.card.warn .v{color:var(--warn)}
.card.accent .v{color:var(--accent)}
.hipanel{padding:6px 16px 10px}
.hirow{display:grid;grid-template-columns:minmax(128px,152px) minmax(0,1fr) auto;
align-items:start;gap:10px 16px;padding:12px 0;border-top:1px solid var(--border)}
.hirow:first-child{border-top:none}
.hilabel{color:var(--mute);font-size:11px;text-transform:uppercase;
letter-spacing:0.05em;padding-top:2px}
.hibody{min-width:0}
.hiprimary{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.hmono{font-family:var(--mono);font-size:13px;line-height:1.45}
.hctx{font-family:var(--mono);font-size:11.5px;color:var(--mute);margin-top:4px;
line-height:1.45}
.himetric{font-family:var(--mono);font-size:13px;font-weight:600;white-space:nowrap;
text-align:right;padding-top:2px;line-height:1.45}
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
border-radius:var(--radius-sm);text-transform:uppercase;letter-spacing:0.03em;flex-shrink:0;
background:color-mix(in oklch,var(--c,var(--accent)) 16%,transparent);
color:var(--c,var(--accent))}
.surf-mcp{--c:var(--mcp)}.surf-cli{--c:var(--cli)}.surf-memory{--c:var(--memory)}
.chip{font-size:10.5px;font-family:var(--mono);padding:1px 8px;
border-radius:var(--radius-sm);
background:var(--surface-2);color:var(--dim);border:1px solid var(--border);
white-space:nowrap}
.chip.warn{color:var(--warn);border-color:transparent;background:var(--warn-soft);
font-weight:600}
.bar{display:block;width:100%;height:6px}
.dur{font-family:var(--mono);font-size:12.5px;text-align:right;white-space:nowrap;
color:var(--dim)}
.mem{font-family:var(--mono);font-size:11.5px;color:var(--warn);font-weight:550;
text-align:right;white-space:nowrap;overflow:hidden}
.extra{display:flex;align-items:center;justify-content:flex-end;gap:6px;
min-width:0;overflow:hidden}
.pay{font-family:var(--mono);font-size:11px;color:var(--mute);white-space:nowrap}
.chain{padding:6px 16px 12px}
.group{padding:13px 0;border-top:1px solid var(--border)}
.group:first-child{border-top:none}
.crumb{display:flex;align-items:center;flex-wrap:wrap;gap:9px;margin-bottom:10px}
.crumb .node{display:flex;align-items:center;gap:7px}
.crumb .cname{font-family:var(--mono);font-size:12px;color:var(--text)}
.crumb .arrow{color:var(--mute);font-size:13px}
.oprow,.spanrow{display:grid;
grid-template-columns:minmax(0,1fr) 104px 56px 70px 120px;
align-items:center;column-gap:13px;row-gap:2px;padding:5px 0}
.lead-cell{display:flex;align-items:center;gap:9px;min-width:0}
.opname{font-family:var(--mono);font-size:13px;font-weight:550;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.spanname{font-family:var(--mono);font-size:12px;color:var(--dim);overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.tick{color:var(--accent);opacity:0.6;font-size:11px;flex-shrink:0}
.spanrow .counters{grid-column:2/-1;font-family:var(--mono);font-size:10.5px;
color:var(--mute);display:flex;flex-direction:column;gap:2px;margin-top:4px;
padding-left:17px}
.cgroup{display:block;line-height:1.55}
.cgroup>b{display:inline-block;min-width:54px;margin-right:8px;color:var(--mute);
font-weight:700;text-transform:uppercase;letter-spacing:0.04em;font-size:9px}
.spans{padding-left:17px}
.kids{margin-left:13px;padding-left:17px;border-left:2px solid var(--accent-soft)}
.wf{padding:8px 16px 12px}
.wf-group{padding:13px 0;border-top:1px solid var(--border)}
.wf-group:first-child{border-top:none}
.wf-cap{display:flex;align-items:center;gap:8px;margin-bottom:9px;
font-family:var(--mono);font-size:11px;color:var(--mute)}
.wf-cap b{color:var(--dim);font-weight:600}
.wf-row{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,520px) 58px;
align-items:center;column-gap:12px;padding:2px 0}
.wf-label{font-family:var(--mono);font-size:11.5px;overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.wf-label.op{color:var(--text);font-weight:550}
.wf-label.span{color:var(--dim)}
.wf-track{position:relative;height:6px;background:var(--track);border-radius:2px}
.wf-bar{position:absolute;top:0;height:6px;border-radius:2px;
background:var(--accent)}
.wf-bar.span{opacity:0.6}
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
/* "Most expensive" — one delicate idiom: accent left rule + faint tint */
tr.lead td{background:color-mix(in oklch,var(--accent) 7%,transparent)}
tr.lead td:first-child{box-shadow:inset 2px 0 0 var(--accent)}
.shape{font-family:var(--font);font-size:12.5px}
.sqlraw{font-family:var(--mono);font-size:11px;color:var(--mute);max-width:440px;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px}
tr.flag td{background:var(--warn-soft)}
.muted{color:var(--mute)}
/* Analysis micro-phases — ranked share bars (core's most important timings) */
.ph{padding:6px 16px 14px}
.ph-row{display:grid;
grid-template-columns:minmax(150px,210px) minmax(0,360px) 66px 50px auto;
align-items:center;column-gap:14px;padding:8px 0;border-top:1px solid var(--border)}
.ph-row:first-child{border-top:none}
.ph-namecell{display:flex;flex-direction:column;min-width:0}
.ph-name{font-family:var(--font);font-size:13px;color:var(--text);overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.ph-row.lead{box-shadow:inset 2px 0 0 var(--accent)}
.ph-row.lead .ph-name{font-weight:600}
.ph-raw{font-family:var(--mono);font-size:10.5px;color:var(--mute);overflow:hidden;
text-overflow:ellipsis;white-space:nowrap}
.ph-dur{font-family:var(--mono);font-size:12.5px;color:var(--dim);text-align:right;
white-space:nowrap}
.ph-share{font-family:var(--mono);font-size:13px;font-weight:600;text-align:right;
white-space:nowrap}
.ph-row.lead .ph-share{color:var(--accent)}
.ph-sig{display:flex;justify-content:flex-end}
.empty{padding:30px;text-align:center;color:var(--mute);font-size:13px}
.foot{margin-top:38px;color:var(--mute);font-size:11px;text-align:center;
font-family:var(--mono)}
/* Tabbed information architecture — CSS-only, radio-driven (no JS) */
.obs-tab-input{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
.obs-tabs{display:flex;flex-wrap:wrap;gap:2px;margin:0 0 24px;
border-bottom:1px solid var(--border);position:sticky;top:0;z-index:5;
background:var(--bg);padding-top:6px}
.obs-tab{padding:9px 15px;font-size:12.5px;font-weight:550;color:var(--mute);
cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;
border-radius:var(--radius-sm) var(--radius-sm) 0 0;user-select:none;
transition:color 0.15s,border-color 0.15s}
.obs-tab:hover{color:var(--text)}
.obs-tab-input:focus-visible+.obs-tab{outline:2px solid var(--accent);
outline-offset:-2px}
.obs-panel{display:none}
.obs-panel>section:first-child{margin-top:0}
.obs-lead{font-size:13px;color:var(--dim);line-height:1.55;
margin:2px 0 22px;max-width:74ch}
#t-overview:checked~.obs-tabs .obs-tab[for="t-overview"],
#t-timeline:checked~.obs-tabs .obs-tab[for="t-timeline"],
#t-operations:checked~.obs-tabs .obs-tab[for="t-operations"],
#t-cost:checked~.obs-tabs .obs-tab[for="t-cost"],
#t-phases:checked~.obs-tabs .obs-tab[for="t-phases"]{
color:var(--accent);border-bottom-color:var(--accent)}
#t-overview:checked~.obs-panels #p-overview,
#t-timeline:checked~.obs-panels #p-timeline,
#t-operations:checked~.obs-panels #p-operations,
#t-cost:checked~.obs-panels #p-cost,
#t-phases:checked~.obs-panels #p-phases{display:block}
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
        '<svg class="bar" viewBox="0 0 100 6" preserveAspectRatio="none" '
        'aria-hidden="true">'
        '<rect width="100" height="6" rx="2" fill="var(--track)"/>'
        f'<rect width="{fill}" height="6" rx="2" fill="{color}"/></svg>'
    )


def _surface_badge(surface: str) -> str:
    cls = f"surf-{surface}" if surface in _KNOWN_SURFACES else ""
    return f'<span class="badge {cls}">{_esc(surface)}</span>'


def _reason_chip(reason_kind: str | None) -> str:
    if not reason_kind:
        return ""
    extra = " warn" if reason_kind == "unknown" else ""
    return f'<span class="chip{extra}">{_esc(reason_kind)}</span>'


# Operations shows the FULL span counter set, grouped + formatted (never an
# alphabetical raw dump, never silently dropped). Each group: (label, ((key,
# short-label), …)). phase_* microsecond timings are converted to ms and ranked;
# any key not mapped below still appears under "other" so nothing is lost.
_COUNTER_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "files",
        (
            ("files_analyzed", "analyzed"),
            ("files_timed", "timed"),
            ("failed_files", "failed"),
        ),
    ),
    (
        "units",
        (
            ("units_seen", "seen"),
            ("units_eligible", "eligible"),
            ("units_fingerprinted", "fingerprinted"),
        ),
    ),
    ("output", (("blocks_emitted", "blocks"), ("segments_emitted", "segments"))),
    ("db", (("db_queries", "reads"), ("db_writes", "writes"))),
)


def _us_ms(micros: int) -> str:
    ms = micros / 1000
    return f"{ms:.0f}ms" if ms >= 10 else f"{ms:.1f}ms"


def _counter_group(label: str, pairs: list[str]) -> str:
    if not pairs:
        return ""
    return f'<span class="cgroup"><b>{_esc(label)}</b>{" · ".join(pairs)}</span>'


def _counters(counters: Mapping[str, int]) -> str:
    if not counters:
        return ""
    seen: set[str] = set()
    groups: list[str] = []
    for label, keys in _COUNTER_GROUPS:
        pairs: list[str] = []
        for key, short in keys:
            if key in counters:
                seen.add(key)
                pairs.append(f"{short} {counters[key]:,}")
        groups.append(_counter_group(label, pairs))
    phases = sorted(
        ((key, value) for key, value in counters.items() if key.startswith("phase_")),
        key=lambda kv: kv[1],
        reverse=True,
    )
    if phases:
        seen.update(key for key, _ in phases)
        groups.append(
            _counter_group(
                "phases",
                [
                    f"{_esc(key.removeprefix('phase_').removesuffix('_us'))} "
                    f"{_us_ms(value)}"
                    for key, value in phases
                ],
            )
        )
    other = sorted((key, value) for key, value in counters.items() if key not in seen)
    if other:
        groups.append(
            _counter_group("other", [f"{_esc(key)} {value:,}" for key, value in other])
        )
    body = "".join(group for group in groups if group)
    return f'<span class="counters">{body}</span>' if body else ""


def _rss_text(
    delta: float | None,
    *,
    end: float | None = None,
    peak: float | None = None,
    peak_delta: float | None = None,
) -> str:
    parts: list[str] = []
    if end is not None and end >= 0.05:
        parts.append(f"end {_mb(end)}")
    if peak is not None and peak >= 0.05:
        parts.append(f"peak {_mb(peak)}")
    if peak_delta is not None and peak_delta >= 0.05:
        parts.append(f"peakΔ{_mb(peak_delta)}")
    elif delta is not None and delta >= 0.05:
        parts.append(f"Δ{_mb(delta)}")
    return " · ".join(parts)


def _view_rss_text(view: OperationView | SpanView | SpanCostView) -> str:
    return _rss_text(
        view.rss_delta_mb,
        end=view.rss_mb,
        peak=view.peak_rss_mb,
        peak_delta=view.peak_rss_delta_mb,
    )


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


def _highlight_row(
    label: str,
    *,
    badge_html: str,
    primary: str,
    metric_html: str,
    context: str | None = None,
    chips_html: str = "",
) -> str:
    ctx = f'<div class="hctx">in {_esc(context)}</div>' if context else ""
    return (
        f'<div class="hirow"><span class="hilabel">{_esc(label)}</span>'
        f'<div class="hibody"><div class="hiprimary">{badge_html}'
        f'<span class="hmono">{_esc(primary)}</span>{chips_html}</div>{ctx}</div>'
        f'<div class="himetric">{metric_html}</div></div>'
    )


def _highlights(agg: AggregatesView) -> str:
    rows: list[str] = []
    if agg.slowest:
        op = agg.slowest[0]
        rows.append(
            _highlight_row(
                "Slowest operation",
                badge_html=_surface_badge(op.surface),
                primary=op.name,
                metric_html=_esc(_ms(op.duration_ms)),
            )
        )
    if agg.slowest_span is not None:
        span = agg.slowest_span
        rows.append(
            _highlight_row(
                "Hottest span",
                badge_html=_surface_badge(span.surface),
                primary=span.name,
                context=span.operation_name,
                chips_html=_reason_chip(span.reason_kind),
                metric_html=_esc(_ms(span.duration_ms)),
            )
        )
    if agg.peak_memory_span is not None and (
        agg.max_rss_delta_mb or agg.max_peak_rss_mb or agg.max_rss_absolute_mb
    ):
        peak = agg.peak_memory_span
        metric = (
            peak.peak_rss_mb
            or peak.rss_mb
            or peak.peak_rss_delta_mb
            or peak.rss_delta_mb
        )
        denom = (
            agg.max_peak_rss_mb
            or agg.max_rss_absolute_mb
            or agg.max_rss_delta_mb
            or 1.0
        )
        share = round((metric or 0.0) / denom * 100)
        detail = _rss_text(
            peak.rss_delta_mb,
            end=peak.rss_mb,
            peak=peak.peak_rss_mb,
            peak_delta=peak.peak_rss_delta_mb,
        )
        rows.append(
            _highlight_row(
                "Top memory consumer",
                badge_html=_surface_badge(peak.surface),
                primary=peak.name,
                context=peak.operation_name,
                metric_html=f"{_esc(detail)} · {share}%",
            )
        )
    elif agg.max_peak_rss_mb is not None:
        rows.append(
            _highlight_row(
                "Process peak RSS",
                badge_html="",
                primary="high-water resident set",
                metric_html=_esc(_mb(agg.max_peak_rss_mb)),
            )
        )
    elif agg.max_rss_delta_mb is not None:
        rows.append(
            _highlight_row(
                "Peak memory Δ",
                badge_html="",
                primary="resident set growth",
                metric_html=_esc(_mb(agg.max_rss_delta_mb)),
            )
        )
    if agg.heaviest_cpu is not None:
        op = agg.heaviest_cpu
        cpu_ms = (op.cpu_user_ms or 0.0) + (op.cpu_system_ms or 0.0)
        ratio = cpu_ms / op.duration_ms if op.duration_ms else 0.0
        rows.append(
            _highlight_row(
                "Heaviest CPU",
                badge_html=_surface_badge(op.surface),
                primary=op.name,
                metric_html=f"{_esc(_ms(cpu_ms))} · {ratio:.1f}x wall",
            )
        )
    if agg.analysis_phases:
        top = agg.analysis_phases[0]
        rows.append(
            _highlight_row(
                "Hottest extract phase",
                badge_html="",
                primary=top.phase,
                context=_ANALYSIS_PHASE_LABELS.get(top.phase, top.phase),
                metric_html=(
                    f"{_esc(_ms(top.worker_elapsed_ms))} · "
                    f"{top.share_permille / 10:.1f}%"
                ),
            )
        )
    return f'<div class="panel hipanel">{"".join(rows)}</div>' if rows else ""


def _summary(trace: TraceView) -> str:
    agg = trace.aggregates
    costly = sum(
        1
        for span in agg.semantic_costs
        if span.no_op and span.duration_ms >= _NOOP_COSTLY_MS
    )
    unknown = agg.unknown_expensive_rebuild_count
    cards = (
        '<div class="stats">'
        + _stat(str(agg.operation_count), "operations", "accent")
        + _stat(_mb(agg.max_peak_rss_mb or agg.max_rss_absolute_mb), "peak rss")
        + _stat(_mb(agg.max_rss_delta_mb), "peak rss Δ")
        + _stat(str(costly), "costly no-ops", "warn" if costly else "")
        + _stat(str(unknown), "unknown reason", "warn" if unknown else "")
        + "</div>"
    )
    highlights = _highlights(agg)
    body = cards + highlights if highlights else cards
    return _section(
        "Runtime summary",
        body,
        subtitle="Headline counters, then where time and memory actually went.",
    )


def _waste_row(item: WasteItem) -> str:
    return (
        '<tr class="flag"><td>'
        f'<span class="chip warn">{_esc(item.kind)}</span></td>'
        f'<td class="t">{_surface_badge(item.surface)} {_esc(item.subject)}</td>'
        f'<td class="t muted">{_esc(item.detail)}</td></tr>'
    )


def _waste_section(agg: AggregatesView) -> str:
    if not agg.waste:
        return ""
    rows = "".join(_waste_row(item) for item in agg.waste)
    headers = (("Kind", False), ("What", False), ("Cost", False))
    return _section(
        "Waste",
        _table(headers, rows),
        subtitle="Resources spent without payoff — no-op rebuilds and "
        "payload-heavy calls. Ranked fix candidates.",
    )


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
    # Fixed metric columns: name | bar | dur | mem | extra. Splitting rss (mem)
    # and payload (extra) into their own cells keeps every column right-anchored
    # so bars and durations line up across nesting depths.
    return (
        '<div class="oprow"><span class="lead-cell">'
        f'{_surface_badge(op.surface)}<span class="opname">{_esc(op.name)}</span>'
        f"</span>{_bar(op.duration_ms, group_max)}"
        f'<span class="dur">{_ms(op.duration_ms)}</span>'
        f'<span class="mem">{_view_rss_text(op)}</span>'
        f'<span class="extra">{_payload(op)}</span></div>'
    )


def _span_row(span: SpanView, op_duration: float) -> str:
    color = "var(--warn)" if span.reason_kind == "unknown" else "var(--accent)"
    return (
        '<div class="spanrow"><span class="lead-cell">'
        f'<span class="tick">▸</span>'
        f'<span class="spanname">{_esc(span.name)}</span></span>'
        f"{_bar(span.duration_ms, op_duration, color=color)}"
        f'<span class="dur">{_ms(span.duration_ms)}</span>'
        f'<span class="mem">{_view_rss_text(span)}</span>'
        f'<span class="extra">{_reason_chip(span.reason_kind)}</span>'
        f"{_counters(span.counters)}</div>"
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
        subtitle="What triggered what, across processes — finish → spawned worker. "
        "Bars are magnitude — each step's share of its chain's slowest step, not a "
        "time axis; for start order and timing see the Timeline tab.",
    )


def _semantic_row(span: SpanCostView, *, lead: bool) -> str:
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
    cls = " ".join(
        name for name, on in (("flag", costly), ("lead", lead)) if on
    )
    return (
        f'<tr class="{cls}">'
        f'<td class="t">{_esc(span.name)}</td>'
        f'<td class="t muted">{_esc(span.operation_name)}</td>'
        f"<td>{reason}</td>"
        f'<td class="r">{span.produced}</td>'
        f'<td class="r">{span.skipped}</td>'
        f'<td class="r">{_ms(span.duration_ms)}</td>'
        f'<td class="r">{_view_rss_text(span)}</td>'
        f"<td>{verdict}</td></tr>"
    )


def _semantic(agg: AggregatesView) -> str:
    if not agg.semantic_costs:
        return ""
    lead = max(
        range(len(agg.semantic_costs)),
        key=lambda i: agg.semantic_costs[i].duration_ms,
        default=-1,
    )
    rows = "".join(
        _semantic_row(span, lead=(i == lead))
        for i, span in enumerate(agg.semantic_costs)
    )
    headers = (
        ("Span", False),
        ("Operation", False),
        ("Reason", False),
        ("Produced", True),
        ("Skipped", True),
        ("Duration", True),
        ("Memory", True),
        ("Verdict", False),
    )
    return _section(
        "Memory pipeline cost",
        _table(headers, rows),
        subtitle="Semantic and memory-product spans — flags work that ran but "
        "produced nothing (including CLI-triggered rebuilds).",
    )


def _mcp_row(tool: McpToolAggregate, *, lead: bool) -> str:
    return (
        f'<tr class="{"lead" if lead else ""}"><td class="t">{_esc(tool.name)}</td>'
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
    lead = max(
        range(len(tools)),
        key=lambda i: tools[i].p95_response_bytes or 0,
        default=-1,
    )
    rows = "".join(_mcp_row(tool, lead=(i == lead)) for i, tool in enumerate(tools))
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
    tick = '<span class="tick">▸</span>' if kind == "span" else ""
    return (
        '<div class="wf-row">'
        f'<span class="wf-label {kind}" style="padding-left:{row.depth * 13}px">'
        f"{tick}{_esc(row.label)}</span>"
        f'<div class="wf-track"><div class="wf-bar {kind}" '
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


def _agent_row(row: AgentTokenRow, total_response: int, *, lead: bool) -> str:
    share = round(row.response_tokens / total_response * 100) if total_response else 0
    return (
        f'<tr class="{"lead" if lead else ""}"><td class="t">{_esc(row.name)}</td>'
        f'<td class="r">{row.calls}</td>'
        f'<td class="r">{_tokens(row.request_tokens)}</td>'
        f'<td class="r">{_tokens(row.response_tokens)}</td>'
        f'<td class="r">{share}%</td></tr>'
    )


def _agent(agg: AggregatesView) -> str:
    view = agg.agent
    if view is None:
        return ""
    cards = (
        '<div class="stats">'
        + _stat(_tokens(view.response_tokens), "context pressure (tok)", "accent")
        + _stat(_tokens(view.request_tokens), "sent (tok)")
        + _stat(str(view.mcp_calls), "mcp calls")
        + _stat(str(len(view.consumers)), "tools")
        + "</div>"
    )
    lead = max(
        range(len(view.consumers)),
        key=lambda i: view.consumers[i].response_tokens,
        default=-1,
    )
    rows = "".join(
        _agent_row(row, view.response_tokens, lead=(i == lead))
        for i, row in enumerate(view.consumers)
    )
    headers = (
        ("Tool", False),
        ("Calls", True),
        ("↑ tok", True),
        ("↓ tok", True),
        ("Context %", True),
    )
    return _section(
        "Agent context",
        cards + _table(headers, rows),
        subtitle="Tokens MCP tools push back into the agent's context — the real "
        "per-call cost for an LLM. The top row is your biggest context consumer.",
    )


def _db_row(row: DbCostRow, *, lead: bool) -> str:
    per_call = round(row.total_queries / row.span_count) if row.span_count else 0
    return (
        f'<tr class="{"lead" if lead else ""}"><td class="t">{_esc(row.span_name)}</td>'
        f'<td class="r">{row.span_count}</td>'
        f'<td class="r">{row.total_queries}</td>'
        f'<td class="r">{row.total_writes}</td>'
        f'<td class="r">{per_call}</td>'
        f'<td class="r">{row.max_queries}</td></tr>'
    )


def _db_cost(agg: AggregatesView) -> str:
    if not agg.db_costs:
        return ""
    lead = max(
        range(len(agg.db_costs)),
        key=lambda i: agg.db_costs[i].total_queries,
        default=-1,
    )
    rows = "".join(
        _db_row(row, lead=(i == lead)) for i, row in enumerate(agg.db_costs)
    )
    headers = (
        ("Span", False),
        ("Spans", True),
        ("Queries", True),
        ("Writes", True),
        ("Q / call", True),
        ("Max", True),
    )
    return _section(
        "DB cost",
        _table(headers, rows),
        subtitle="SQLite work per span (performance-truth) — a high Q/call is "
        "N+1-shaped: many reads for little produced.",
    )


def _db_fingerprint_row(row: DbFingerprintRow, *, lead: bool) -> str:
    table = _esc(row.table_hint) if row.table_hint else "—"
    shape = _esc(row.summary) if row.summary else "—"
    raw = _esc(row.fingerprint)
    return (
        f'<tr class="{"lead" if lead else ""}"><td class="t">{_esc(row.span_name)}</td>'
        f"<td>{table}</td>"
        f'<td class="muted">{_esc(row.kind.upper())}</td>'
        f'<td class="r">{row.count}</td>'
        f'<td class="t"><div class="shape">{shape}</div>'
        f'<div class="sqlraw" title="{raw}">{raw}</div></td></tr>'
    )


def _db_fingerprints(agg: AggregatesView) -> str:
    if not agg.db_fingerprints:
        return ""
    lead = max(
        range(len(agg.db_fingerprints)),
        key=lambda i: agg.db_fingerprints[i].count,
        default=-1,
    )
    rows = "".join(
        _db_fingerprint_row(row, lead=(i == lead))
        for i, row in enumerate(agg.db_fingerprints)
    )
    headers = (
        ("Span", False),
        ("Table", False),
        ("Kind", False),
        ("Count", True),
        ("Shape", False),
    )
    return _section(
        "DB query shapes",
        _table(headers, rows),
        subtitle="Each query count decoded into what it filters on — the high-count "
        "rows name the N+1 to batch. Raw shape is the second line.",
    )


def _pipeline_row(group: PipelineGroup, *, lead: bool) -> str:
    return (
        f'<tr class="{"lead" if lead else ""}"><td class="t">{_esc(group.name)}</td>'
        f'<td class="r">{group.op_count}</td>'
        f'<td class="r">{_ms(group.duration_ms)}</td>'
        f'<td class="r">{_ms(group.cpu_ms)}</td></tr>'
    )


def _pipeline_section(agg: AggregatesView) -> str:
    if not agg.pipeline:
        return ""
    lead = max(
        range(len(agg.pipeline)),
        key=lambda i: agg.pipeline[i].duration_ms,
        default=-1,
    )
    rows = "".join(
        _pipeline_row(group, lead=(i == lead))
        for i, group in enumerate(agg.pipeline)
    )
    headers = (("Subsystem", False), ("Ops", True), ("Wall", True), ("CPU", True))
    return _section(
        "Pipeline",
        _table(headers, rows),
        subtitle="Where the run spends wall time and CPU, grouped by subsystem.",
    )


def _analysis_phase_row(row: AnalysisPhaseRow, max_permille: int, *, lead: bool) -> str:
    label = _ANALYSIS_PHASE_LABELS.get(row.phase, row.phase)
    sig = '<span class="chip">peak</span>' if lead else ""
    return (
        f'<div class="ph-row{" lead" if lead else ""}">'
        f'<span class="ph-namecell"><span class="ph-name">{_esc(label)}</span>'
        f'<span class="ph-raw">{_esc(row.phase)}</span></span>'
        f"{_bar(row.share_permille, max_permille)}"
        f'<span class="ph-dur">{_esc(_ms(row.worker_elapsed_ms))}</span>'
        f'<span class="ph-share">{row.share_permille / 10:.1f}%</span>'
        f'<span class="ph-sig">{sig}</span></div>'
    )


def _iter_operation_tree(ops: tuple[OperationView, ...]) -> Iterable[OperationView]:
    for op in ops:
        yield op
        yield from _iter_operation_tree(op.children)


def _pipeline_process_spans(trace: TraceView) -> tuple[SpanView, ...]:
    roots = trace.operation_tree or trace.correlated_operations
    spans: list[SpanView] = []
    seen: set[str] = set()
    for op in _iter_operation_tree(roots):
        for span in op.spans:
            if span.name == "pipeline.process" and span.span_id not in seen:
                spans.append(span)
                seen.add(span.span_id)
    return tuple(spans)


def _empty_analysis_phase_section(trace: TraceView) -> str:
    process_spans = _pipeline_process_spans(trace)
    if not process_spans:
        return ""
    files_analyzed = sum(
        span.counters.get("files_analyzed", 0) for span in process_spans
    )
    failed_files = sum(span.counters.get("failed_files", 0) for span in process_spans)
    if files_analyzed == 0:
        reason = (
            "No uncached files were processed in this window; the analysis was "
            "served from cache, so file extraction micro-stages did not run. "
            "Use a cold cache or changed files to capture phase timings."
        )
    else:
        reason = (
            "pipeline.process ran, but no analysis phase counters were recorded. "
            "Restart the producing process with CODECLONE_OBSERVABILITY_ENABLED=1 "
            "and Phase 33 instrumentation."
        )
    counters = (
        f"pipeline.process files_analyzed={files_analyzed} · "
        f"failed_files={failed_files}"
    )
    body = (
        '<div class="panel"><div class="empty">'
        f"{_esc(reason)}"
        f'<div class="sqlraw">{_esc(counters)}</div>'
        "</div></div>"
    )
    return _section(
        "Analysis extract phases",
        body,
        subtitle=(
            "Summed per-file worker elapsed time inside pipeline.process "
            "(parse, walk, CFG, normalize). Dev-only; not repository quality."
        ),
    )


def _analysis_phases_section(trace: TraceView) -> str:
    agg = trace.aggregates
    if not agg.analysis_phases:
        return _empty_analysis_phase_section(trace)
    max_permille = max((row.share_permille for row in agg.analysis_phases), default=1)
    max_permille = max_permille or 1
    lead_idx = max(
        range(len(agg.analysis_phases)),
        key=lambda i: agg.analysis_phases[i].share_permille,
        default=-1,
    )
    rows = "".join(
        _analysis_phase_row(row, max_permille, lead=(i == lead_idx))
        for i, row in enumerate(agg.analysis_phases)
    )
    footer = (
        f"Worker elapsed (summed): "
        f"{_ms(agg.analysis_phase_worker_elapsed_total_ms or 0.0)} · "
        f"pipeline.process wall: {_ms(agg.analysis_phase_pipeline_wall_ms or 0.0)} · "
        f"files timed: {agg.analysis_phase_files_timed} · "
        f"units eligible: {agg.analysis_phase_units_eligible}"
    )
    body = f'<div class="panel ph">{rows}</div><p class="shint">{_esc(footer)}</p>'
    return _section(
        "Analysis extract phases",
        body,
        subtitle=(
            "Where the core spends its per-file extract time, ranked by share — "
            "bars are scaled to the heaviest phase. Summed worker elapsed inside "
            "pipeline.process; dev-only, not repository quality, and may exceed "
            "parent pipeline wall under parallel execution."
        ),
    )


_TABS: tuple[tuple[str, str], ...] = (
    ("overview", "Overview"),
    ("timeline", "Timeline"),
    ("operations", "Operations"),
    ("cost", "Cost"),
    ("phases", "Phases"),
)

# One plain-language lead per tab: what the view answers, what to look at first.
_TAB_LEADS: Mapping[str, str] = {
    "overview": "Start here — what this run did, and where its time and memory "
    "actually went.",
    "timeline": "When everything happened — operations and their spans on one "
    "shared time axis.",
    "operations": "What ran — the finish→worker causality chains, nested by call "
    "depth.",
    "cost": "What it cost — language-model tokens, MCP payloads, and database work.",
    "phases": "Inside analysis — pipeline stages and per-phase extract cost.",
}


def _tab_shell(panels: Mapping[str, str]) -> str:
    """Wrap the section panels in CSS-only radio tabs.

    The radio inputs are emitted first so the ``:checked ~`` sibling selectors
    can light the active tab label and reveal the matching panel without any
    script. An empty panel falls back to a placeholder so a view is never blank.
    """
    inputs = "".join(
        f'<input type="radio" name="obs-tab" class="obs-tab-input" '
        f'id="t-{tid}"{" checked" if idx == 0 else ""}>'
        for idx, (tid, _) in enumerate(_TABS)
    )
    nav = (
        '<nav class="obs-tabs" aria-label="Observability views">'
        + "".join(
            f'<label class="obs-tab" for="t-{tid}">{_esc(label)}</label>'
            for tid, label in _TABS
        )
        + "</nav>"
    )
    sections: list[str] = []
    for tid, label in _TABS:
        inner = panels.get(tid, "")
        if not inner.strip():
            inner = (
                f'<div class="panel empty">No {_esc(label.lower())} data '
                f"recorded for this window.</div>"
            )
        lead = _TAB_LEADS.get(tid, "")
        lead_html = f'<p class="obs-lead">{_esc(lead)}</p>' if lead else ""
        sections.append(
            f'<section class="obs-panel" id="p-{tid}">{lead_html}{inner}</section>'
        )
    return f'{inputs}{nav}<div class="obs-panels">{"".join(sections)}</div>'


def render_trace_html(trace: TraceView) -> str:
    """Render a ``TraceView`` as a self-contained, branded diagnosis cockpit."""
    agg = trace.aggregates
    foot = f"CodeClone · platform observability · schema {_esc(trace.schema_version)}"
    panels = {
        "overview": _summary(trace) + _waste_section(agg),
        "timeline": _waterfall(trace),
        "operations": _chain(trace),
        "cost": (
            _semantic(agg)
            + _db_cost(agg)
            + _db_fingerprints(agg)
            + _agent(agg)
            + _mcp(agg.mcp_tools)
        ),
        "phases": _pipeline_section(agg) + _analysis_phases_section(trace),
    }
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>CodeClone · Platform Observability</title>"
        f'<style>{_CSS}</style></head><body><div class="wrap">'
        + _header(trace)
        + _tab_shell(panels)
        + f'<p class="foot">{foot}</p>'
        + "</div></body></html>"
    )


__all__ = ["render_trace_html"]
