# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Orchestrator: build_context → render all sections → template.substitute."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import TYPE_CHECKING

from .. import __version__, _coerce
from .._html_css import build_css
from .._html_escape import _escape_html
from .._html_js import build_js
from .._html_snippets import _FileCache, _pygments_css
from ..contracts import DOCS_URL, ISSUES_URL, REPOSITORY_URL
from ..domain.quality import CONFIDENCE_HIGH
from ..structural_findings import normalize_structural_findings
from ..templates import FONT_CSS_URL, REPORT_TEMPLATE
from ._context import _meta_pick, build_context
from ._icons import BRAND_LOGO, ICONS
from ._sections._clones import render_clones_panel
from ._sections._coupling import render_quality_panel
from ._sections._dead_code import render_dead_code_panel
from ._sections._dependencies import render_dependencies_panel
from ._sections._meta import render_meta_panel
from ._sections._overview import render_overview_panel
from ._sections._structural import render_structural_panel
from ._sections._suggestions import render_suggestions_panel

if TYPE_CHECKING:
    from ..models import GroupMapLike, MetricsDiff, StructuralFindingGroup, Suggestion


def build_html_report(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    segment_groups: GroupMapLike,
    block_group_facts: dict[str, dict[str, str]],
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    report_meta: Mapping[str, object] | None = None,
    metrics: Mapping[str, object] | None = None,
    suggestions: Sequence[Suggestion] | None = None,
    structural_findings: Sequence[StructuralFindingGroup] | None = None,
    report_document: Mapping[str, object] | None = None,
    metrics_diff: MetricsDiff | None = None,
    title: str = "CodeClone Report",
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> str:
    """Build a self-contained HTML report string.

    This is the sole public entry point. The signature is frozen.
    """
    file_cache = _FileCache()

    ctx = build_context(
        func_groups=func_groups,
        block_groups=block_groups,
        segment_groups=segment_groups,
        block_group_facts=block_group_facts,
        new_function_group_keys=new_function_group_keys,
        new_block_group_keys=new_block_group_keys,
        report_meta=report_meta,
        metrics=metrics,
        suggestions=suggestions,
        structural_findings=structural_findings,
        report_document=report_document,
        metrics_diff=metrics_diff,
        file_cache=file_cache,
        context_lines=context_lines,
        max_snippet_lines=max_snippet_lines,
    )

    # -- Render sections --
    overview_html = render_overview_panel(ctx)
    clones_html, _novelty_enabled, _total_new, _total_known = render_clones_panel(ctx)
    quality_html = render_quality_panel(ctx)
    dependencies_html = render_dependencies_panel(ctx)
    dead_code_html = render_dead_code_panel(ctx)
    suggestions_html = render_suggestions_panel(ctx)
    structural_html = render_structural_panel(ctx)
    meta_html = render_meta_panel(ctx)

    # -- Tab counters --
    _as_mapping = _coerce.as_mapping
    _as_sequence = _coerce.as_sequence
    _as_int = _coerce.as_int
    dead_summary = _as_mapping(ctx.dead_code_map.get("summary"))
    dead_total = _as_int(dead_summary.get("total"))
    dead_high_conf = _as_int(
        dead_summary.get("high_confidence", dead_summary.get("critical"))
    )
    if dead_total > 0 and dead_high_conf == 0:
        dead_high_conf = sum(
            1
            for item in _as_sequence(ctx.dead_code_map.get("items"))
            if str(_as_mapping(item).get("confidence", "")).strip().lower()
            == CONFIDENCE_HIGH
        )
    dep_cycles = len(_as_sequence(ctx.dependencies_map.get("cycles")))
    structural_count = len(
        tuple(normalize_structural_findings(ctx.structural_findings))
    )
    quality_issues = (
        _as_int(_as_mapping(ctx.complexity_map.get("summary")).get("high_risk"))
        + _as_int(_as_mapping(ctx.coupling_map.get("summary")).get("high_risk"))
        + _as_int(_as_mapping(ctx.cohesion_map.get("summary")).get("low_cohesion"))
    )

    def _tab_badge(count: int) -> str:
        if count == 0:
            return ""
        return f'<span class="tab-count">{count}</span>'

    # -- Main tab navigation --
    tab_defs = [
        ("overview", "Overview", overview_html, ""),
        ("clones", "Clones", clones_html, _tab_badge(ctx.clone_groups_total)),
        ("quality", "Quality", quality_html, _tab_badge(quality_issues)),
        ("dependencies", "Dependencies", dependencies_html, _tab_badge(dep_cycles)),
        ("dead-code", "Dead Code", dead_code_html, _tab_badge(dead_high_conf)),
        (
            "suggestions",
            "Suggestions",
            suggestions_html,
            _tab_badge(len(ctx.suggestions)),
        ),
        (
            "structural-findings",
            "Findings",
            structural_html,
            _tab_badge(structural_count),
        ),
    ]

    # Extra data attrs for specific tabs (contract hooks)
    tab_extra_attrs: dict[str, str] = {
        "clones": f'data-main-clones-count="{ctx.clone_groups_total}"',
    }

    tab_buttons: list[str] = []
    tab_panels: list[str] = []
    for idx, (tab_id, tab_label, panel_html, badge) in enumerate(tab_defs):
        selected = "true" if idx == 0 else "false"
        extra = tab_extra_attrs.get(tab_id, "")
        if extra:
            extra = " " + extra
        tab_buttons.append(
            f'<button class="main-tab" role="tab" data-tab="{tab_id}" '
            f'aria-selected="{selected}" aria-controls="panel-{tab_id}"{extra}>'
            f"{tab_label}{badge}</button>"
        )
        active = " active" if idx == 0 else ""
        tab_panels.append(
            f'<div class="tab-panel{active}" id="panel-{tab_id}" role="tabpanel">'
            f"{panel_html}</div>"
        )

    tabs_html = (
        '<div class="main-tabs-wrap">'
        '<nav class="main-tabs" role="tablist" aria-label="Report sections">'
        + "".join(tab_buttons)
        + "</nav></div>"
    )
    panels_html = "".join(tab_panels)

    # -- Provenance dot color --
    _bl_verified = _meta_pick(
        ctx.meta.get("baseline_payload_sha256_verified"),
        ctx.baseline_meta.get("payload_sha256_verified"),
    )
    _bl_loaded = _meta_pick(
        ctx.meta.get("baseline_loaded"),
        ctx.baseline_meta.get("loaded"),
    )
    if _bl_verified:
        prov_dot_cls = "dot-green"
    elif _bl_loaded is True and _bl_verified is not True:
        prov_dot_cls = "dot-red"
    elif _bl_loaded is False or _bl_loaded is None:
        prov_dot_cls = "dot-amber"
    else:
        prov_dot_cls = "dot-neutral"

    # -- Topbar --
    topbar_html = (
        '<header class="topbar"><div class="topbar-inner">'
        '<div class="brand">'
        f"{BRAND_LOGO}"
        '<div class="brand-text">'
        f"<h1>CodeClone Report{ctx.brand_project_html}</h1>"
        f'<div class="brand-meta">{ctx.brand_meta}</div>'
        "</div></div>"
        '<div class="topbar-actions">'
        f'<button class="btn btn-prov" type="button" data-prov-open>'
        f'<span class="prov-dot {prov_dot_cls}"></span>Report Provenance</button>'
        '<button class="btn" type="button" data-export-json>Export JSON</button>'
        f'<button class="theme-toggle" type="button" title="Toggle theme">'
        f"{ICONS['theme']}Theme</button>"
        "</div></div></header>"
    )

    # -- Footer --
    version = str(ctx.meta.get("codeclone_version", __version__))
    footer_html = (
        '<footer class="report-footer">'
        f'<a href="{REPOSITORY_URL}" target="_blank" rel="noopener">CodeClone</a> '
        f'<span class="muted">v{version}</span> · '
        f'<a href="{DOCS_URL}" target="_blank" rel="noopener">Docs</a> · '
        f'<a href="{ISSUES_URL}" target="_blank" rel="noopener">Issues</a>'
        "</footer>"
    )

    # -- Command palette shell --
    cmd_palette_html = (
        '<div class="cmd-palette">'
        '<div class="cmd-palette-box">'
        '<input class="cmd-palette-input" type="text" '
        'placeholder="Search commands… (Ctrl+K)" autocomplete="off"/>'
        '<div class="cmd-palette-list"></div>'
        "</div></div>"
    )
    finding_why_modal_html = (
        '<dialog class="finding-why-modal" id="finding-why-modal" '
        'aria-label="Why This Finding Was Reported">'
        '<div class="modal-head">'
        "<h2>Why This Finding Was Reported</h2>"
        '<button class="modal-close" type="button" data-finding-why-close '
        'aria-label="Close">&times;</button>'
        "</div>"
        '<div class="modal-body"></div>'
        "</dialog>"
    )
    help_modal_html = (
        '<dialog class="help-modal" id="help-modal" '
        'aria-label="Help & Support">'
        '<div class="modal-head">'
        "<h2>Help &amp; Support</h2>"
        '<button class="modal-close" type="button" data-help-close '
        'aria-label="Close">&times;</button>'
        "</div>"
        '<div class="modal-body">'
        '<div class="help-section">'
        "<p>Use keyboard shortcuts and the command palette to move quickly "
        "around the report.</p>"
        "</div>"
        '<div class="help-section">'
        "<h3>Shortcuts</h3>"
        '<div class="help-shortcuts">'
        '<div class="help-shortcut-row"><span>Command palette</span>'
        '<kbd data-shortcut="mod+K">\u2318K / Ctrl+K</kbd></div>'
        '<div class="help-shortcut-row"><span>Open help</span>'
        '<kbd data-shortcut="mod+I">\u2318I / Ctrl+I</kbd></div>'
        "</div>"
        "</div>"
        '<div class="help-section">'
        "<h3>Resources</h3>"
        '<div class="help-links">'
        f'<a href="{DOCS_URL}" target="_blank" rel="noopener noreferrer">'
        "Documentation</a>"
        f'<a href="{ISSUES_URL}" target="_blank" rel="noopener noreferrer">'
        "Issue tracker</a>"
        f'<a href="{REPOSITORY_URL}" target="_blank" rel="noopener noreferrer">'
        "Repository</a>"
        "</div>"
        "</div>"
        "</div>"
        "</dialog>"
    )

    # -- Body assembly --
    body_html = (
        topbar_html
        + '<div class="container">'
        + tabs_html
        + panels_html
        + footer_html
        + "</div>"
        + meta_html  # <dialog>, positioned by browser
        + finding_why_modal_html
        + help_modal_html
        + cmd_palette_html
    )

    # -- CSS assembly --
    pygments_dark = _pygments_css("monokai")
    pygments_light = _pygments_css("default")

    def _codebox_rules(css: str) -> str:
        """Extract only .codebox-scoped rules (drop bare pre/td/span rules)."""
        out: list[str] = []
        for line in css.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("/*"):
                continue
            if not stripped.startswith(".codebox"):
                continue
            out.append(stripped)
        return "\n".join(out)

    def _scope(rules: str, prefix: str) -> str:
        """Prepend *prefix* before every `.codebox` selector."""
        return rules.replace(".codebox", f"{prefix} .codebox")

    css_parts = [build_css()]

    # Dark Pygments (monokai) — unscoped base, dark-first design
    if pygments_dark:
        css_parts.append(pygments_dark)

    # Light Pygments — comprehensive theme override
    #
    # Problem: Pygments "default" style doesn't define rules for every
    # token class that "monokai" does (.n, .p, .esc, .g, .l, .x, …).
    # Those monokai rules set color:#F8F8F2 (white) which becomes
    # invisible on a light background.
    #
    # Solution: a CSS reset that clears ALL span styling inside .codebox
    # back to inherit, then the light Pygments rules re-apply colors
    # only for tokens the light theme cares about.
    if pygments_light:
        light_rules = _codebox_rules(pygments_light)
        if light_rules:
            # Reset: clear monokai colors for tokens light theme omits.
            # NB: color must be var(--text-primary), NOT inherit — because
            # the parent .codebox still carries monokai's color:#F8F8F2
            # (white) and inherit would propagate that invisible color.
            _reset = (
                "color:var(--text-primary);font-style:inherit;"
                "font-weight:inherit;"
                "background-color:transparent;border:none"
            )

            # Override .codebox itself: monokai sets color:#F8F8F2 on
            # .codebox — light theme needs dark text for non-span content
            _cb_override = "color:var(--text-primary);background:var(--bg-body)"

            # 1) Explicit [data-theme="light"]
            explicit_reset = (
                f'[data-theme="light"] .codebox{{{_cb_override}}}\n'
                f'[data-theme="light"] .codebox span{{{_reset}}}'
            )
            explicit_rules = _scope(light_rules, '[data-theme="light"]')
            css_parts.append(explicit_reset)
            css_parts.append(explicit_rules)

            # 2) Auto-detect: OS prefers light + no explicit dark
            _auto_pfx = ':root:not([data-theme="dark"])'
            auto_reset = (
                f"{_auto_pfx} .codebox{{{_cb_override}}}\n"
                f"{_auto_pfx} .codebox span{{{_reset}}}"
            )
            auto_rules = _scope(light_rules, _auto_pfx)
            css_parts.append(
                f"@media (prefers-color-scheme:light){{{auto_reset}\n{auto_rules}}}"
            )
    css_html = "\n".join(css_parts)

    # -- JS --
    js_html = build_js()

    return REPORT_TEMPLATE.safe_substitute(
        title=_escape_html(title),
        font_css_url=FONT_CSS_URL,
        css=css_html,
        js=js_html,
        body=body_html,
    )
