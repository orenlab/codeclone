# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
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
from ._icons import BRAND_LOGO, ICONS, section_icon_html
from ._sections._clones import render_clones_panel
from ._sections._coupling import render_quality_panel
from ._sections._dead_code import render_dead_code_panel
from ._sections._dependencies import render_dependencies_panel
from ._sections._meta import build_topbar_provenance_summary, render_meta_panel
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
    coverage_join_summary = _as_mapping(
        _as_mapping(ctx.metrics_map.get("coverage_join")).get("summary")
    )
    coverage_review_items = (
        _as_int(coverage_join_summary.get("coverage_hotspots"))
        + _as_int(coverage_join_summary.get("scope_gap_hotspots"))
        if str(coverage_join_summary.get("status", "")).strip() == "ok"
        else 0
    )
    quality_issues = (
        _as_int(_as_mapping(ctx.complexity_map.get("summary")).get("high_risk"))
        + _as_int(_as_mapping(ctx.coupling_map.get("summary")).get("high_risk"))
        + _as_int(_as_mapping(ctx.cohesion_map.get("summary")).get("low_cohesion"))
        + _as_int(
            _as_mapping(ctx.overloaded_modules_map.get("summary")).get("candidates")
        )
        + coverage_review_items
    )

    def _tab_badge(count: int) -> str:
        if count == 0:
            return ""
        return f'<span class="tab-count">{count}</span>'

    # -- Main tab navigation --
    tab_icon_keys: dict[str, str] = {
        "overview": "overview",
        "clones": "clones",
        "quality": "quality",
        "dependencies": "dependencies",
        "dead-code": "dead-code",
        "suggestions": "suggestions",
        "structural-findings": "structural-findings",
    }
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
        tab_icon = section_icon_html(
            tab_icon_keys.get(tab_id, ""),
            class_name="main-tab-icon",
            size=15,
        )
        tab_buttons.append(
            f'<button class="main-tab" role="tab" data-tab="{tab_id}" '
            f'aria-selected="{selected}" aria-controls="panel-{tab_id}"{extra}>'
            f'{tab_icon}<span class="main-tab-label">{tab_label}</span>{badge}</button>'
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

    # -- Provenance summary for topbar pill --
    prov_status_label, prov_status_color, prov_tooltip = (
        build_topbar_provenance_summary(ctx)
    )

    # -- IDE picker menu --
    ide_options = [
        ("pycharm", "PyCharm"),
        ("idea", "IntelliJ IDEA"),
        ("vscode", "VS Code"),
        ("cursor", "Cursor"),
        ("fleet", "Fleet"),
        ("zed", "Zed"),
        ("", "None"),
    ]
    ide_menu_items = "".join(
        f'<li><button type="button" data-ide="{ide_id}" role="menuitemradio" '
        f'aria-checked="false">{label}</button></li>'
        for ide_id, label in ide_options
    )

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
        '<div class="ide-picker">'
        '<button class="ide-picker-btn" type="button" aria-expanded="false" '
        f'aria-haspopup="true" title="Open in IDE">{ICONS["ide"]}'
        '<span class="ide-picker-label">IDE</span></button>'
        f'<ul class="ide-menu" role="menu">{ide_menu_items}</ul></div>'
        f'<button class="btn btn-prov prov-pill prov-pill--{prov_status_color}" '
        f'type="button" data-prov-open '
        f'aria-label="Report Provenance" '
        f'title="Report Provenance \u2014 {_escape_html(prov_tooltip)}">'
        f'<svg class="prov-pill-icon" viewBox="0 0 16 16" width="16" height="16" '
        f'fill="none" stroke="currentColor" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<path d="M8 1.5L2.5 3.5v4.2c0 3.3 2.3 5.7 5.5 6.8 3.2-1.1 5.5-3.5 '
        '5.5-6.8V3.5z"/>'
        f'<path d="M5.5 8l1.8 1.8L10.5 6"/></svg>'
        f'<span class="prov-pill-label">{_escape_html(prov_status_label)}</span>'
        f"</button>"
        f'<button class="theme-toggle" type="button" title="Toggle theme" '
        f'aria-label="Toggle theme">'
        f"{ICONS['theme_sun']}{ICONS['theme_moon']}Theme</button>"
        "</div></div></header>"
    )

    # -- Footer --
    version = str(ctx.meta.get("codeclone_version", __version__))
    _report_schema = ctx.report_schema_version
    _baseline_schema = _meta_pick(
        ctx.meta.get("baseline_schema_version"),
        ctx.baseline_meta.get("schema_version"),
    )
    _cache_schema = _meta_pick(
        ctx.meta.get("cache_schema_version"),
        ctx.cache_meta.get("schema_version"),
    )
    _schema_parts: list[str] = []
    if _report_schema:
        _schema_parts.append(f"Report schema {_escape_html(str(_report_schema))}")
    if _baseline_schema:
        _schema_parts.append(f"Baseline schema {_escape_html(str(_baseline_schema))}")
    if _cache_schema:
        _schema_parts.append(f"Cache schema {_escape_html(str(_cache_schema))}")
    _schema_line = (
        f'<div class="report-footer-schemas muted">{" · ".join(_schema_parts)}</div>'
        if _schema_parts
        else ""
    )
    footer_html = (
        '<footer class="report-footer">'
        '<div class="report-footer-main">'
        f'<a href="{REPOSITORY_URL}" target="_blank" rel="noopener">CodeClone</a> '
        f'<span class="muted">v{_escape_html(version)}</span> · '
        f'<a href="{DOCS_URL}" target="_blank" rel="noopener">Docs</a> · '
        f'<a href="{ISSUES_URL}" target="_blank" rel="noopener">Issues</a>'
        "</div>"
        f"{_schema_line}"
        "</footer>"
    )

    cmd_palette_html = ""  # removed
    finding_why_modal_html = (
        '<dialog class="finding-why-modal" id="finding-why-modal" '
        'aria-label="Finding Details">'
        '<div class="modal-head">'
        "<h2>Finding Details</h2>"
        '<button class="modal-close" type="button" data-finding-why-close '
        'aria-label="Close">&times;</button>'
        "</div>"
        '<div class="modal-body"></div>'
        "</dialog>"
    )
    help_modal_html = ""  # removed

    badge_modal_html = (
        '<dialog class="badge-modal" id="badge-modal" aria-label="Get Badge">'
        '<div class="modal-head">'
        "<h2>Get Badge</h2>"
        '<button class="modal-close" type="button" data-badge-close '
        'aria-label="Close">&times;</button>'
        "</div>"
        '<div class="modal-body">'
        # -- variant tabs --
        '<div class="badge-tabs" role="tablist">'
        '<button class="badge-tab badge-tab--active" role="tab" '
        'aria-selected="true" data-badge-tab="grade">Grade only</button>'
        '<button class="badge-tab" role="tab" '
        'aria-selected="false" data-badge-tab="full">Score + Grade</button>'
        "</div>"
        # -- preview --
        '<div class="badge-preview" id="badge-preview"></div>'
        '<p class="badge-disclaimer">'
        "Badge reflects the current report snapshot.</p>"
        # -- embed fields --
        '<label class="badge-field-label">Markdown</label>'
        '<div class="badge-code-wrap">'
        '<code class="badge-code" id="badge-code-md"></code>'
        '<button class="badge-copy-btn" type="button" '
        'data-badge-copy="md">Copy</button></div>'
        '<label class="badge-field-label">HTML</label>'
        '<div class="badge-code-wrap">'
        '<code class="badge-code" id="badge-code-html"></code>'
        '<button class="badge-copy-btn" type="button" '
        'data-badge-copy="html">Copy</button></div>'
        "</div></dialog>"
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
        + badge_modal_html
    )

    # -- CSS assembly --
    pygments_dark = _pygments_css("monokai")
    pygments_light = _pygments_css("default")

    def _codebox_rules(css: str) -> str:
        """Extract only .codebox-scoped rules (drop bare pre/td/span rules)."""
        out: list[str] = []
        for line in css.splitlines():
            stripped = line.strip()
            if (
                not stripped
                or stripped.startswith("/*")
                or not stripped.startswith(".codebox")
            ):
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
            _auto_pfx = ":root:not([data-theme])"
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
        scan_root=_escape_html(ctx.scan_root),
    )
