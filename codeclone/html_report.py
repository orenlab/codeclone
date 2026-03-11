# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from . import __version__
from ._html_escape import _escape_attr, _escape_html, _meta_display
from ._html_snippets import (
    _FileCache,
    _prefix_css,
    _pygments_css,
    _render_code_block,
    _try_pygments,
)
from .contracts import DOCS_URL, ISSUES_URL, REPORT_SCHEMA_VERSION, REPOSITORY_URL
from .models import GroupItemLike, GroupMapLike, StructuralFindingGroup, Suggestion
from .report.derived import (
    combine_source_kinds,
    group_spread,
    report_location_from_group_item,
)
from .report.explain_contract import format_group_instance_compare_meta
from .report.findings import build_structural_findings_html_panel
from .report.overview import build_report_overview
from .report.suggestions import classify_clone_type
from .structural_findings import normalize_structural_findings
from .templates import FONT_CSS_URL, REPORT_TEMPLATE

__all__ = [
    "_FileCache",
    "_prefix_css",
    "_pygments_css",
    "_render_code_block",
    "_try_pygments",
    "build_html_report",
]

# ============================
# HTML report builder
# ============================


def _group_sort_key(items: Collection[GroupItemLike]) -> tuple[int]:
    return (-len(items),)


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


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
    title: str = "CodeClone Report",
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> str:
    file_cache = _FileCache()
    resolved_block_group_facts = block_group_facts

    def _path_basename(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        normalized = text.replace("\\", "/").rstrip("/")
        if not normalized:
            return None
        return normalized.rsplit("/", maxsplit=1)[-1]

    meta = dict(report_meta or {})
    baseline_meta = _as_mapping(meta.get("baseline"))
    cache_meta = _as_mapping(meta.get("cache"))
    metrics_baseline_meta = _as_mapping(meta.get("metrics_baseline"))
    runtime_meta = _as_mapping(meta.get("runtime"))
    report_document_map = _as_mapping(report_document)
    derived_map = _as_mapping(report_document_map.get("derived"))
    integrity_map = _as_mapping(report_document_map.get("integrity"))

    def _meta_pick(*values: object) -> object | None:
        for value in values:
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
        return None

    report_schema_version = str(
        meta.get("report_schema_version") or REPORT_SCHEMA_VERSION
    )
    report_generated_at = str(
        _meta_pick(
            meta.get("report_generated_at_utc"),
            runtime_meta.get("report_generated_at_utc"),
        )
        or ""
    ).strip()
    brand_meta = (
        f"Generated at {report_generated_at}"
        if report_generated_at
        else f"Report schema {report_schema_version}"
    )
    scan_root_raw = str(
        _meta_pick(meta.get("scan_root"), runtime_meta.get("scan_root_absolute")) or ""
    ).strip()
    project_name_raw = str(meta.get("project_name", "")).strip()
    brand_project_html = (
        f' <span class="brand-project">for '
        f'<code class="brand-project-name">{_escape_html(project_name_raw)}</code>'
        f"</span>"
        if project_name_raw
        else ""
    )

    def _relative_path(abspath: str) -> str:
        """Strip scan_root prefix to get a concise project-relative path."""
        if not scan_root_raw or not abspath:
            return abspath
        text = abspath.replace("\\", "/")
        root = scan_root_raw.replace("\\", "/").rstrip("/") + "/"
        if text.startswith(root):
            return text[len(root) :]
        return abspath

    def _bare_qualname(qualname: str, filepath: str) -> str:
        """Strip file-derived module prefix from qualname, keeping local name."""
        if not qualname:
            return qualname
        # Handle colon-separated format: module.path:LocalName.method
        if ":" in qualname:
            return qualname.rsplit(":", maxsplit=1)[-1]
        if "." not in qualname:
            return qualname
        rel = _relative_path(filepath)
        for suffix in ("/__init__.py", ".py"):
            if rel.endswith(suffix):
                rel = rel[: -len(suffix)]
                break
        prefix = rel.replace("/", ".") + "."
        if qualname.startswith(prefix):
            bare = qualname[len(prefix) :]
            if bare:
                return bare
        return qualname

    _EFFORT_MAP = {"easy": "success", "moderate": "warning", "hard": "error"}
    _Tone = Literal["ok", "warn", "risk", "info"]

    def _risk_badge_html(risk_text: str) -> str:
        """Render risk/severity/confidence/effort as a styled badge."""
        r = risk_text.strip().lower()
        if r in ("low", "high", "medium"):
            return (
                f'<span class="risk-badge risk-{_escape_attr(r)}">'
                f"{_escape_html(r)}</span>"
            )
        if r in ("critical", "warning", "info"):
            return (
                f'<span class="severity-badge severity-{_escape_attr(r)}">'
                f"{_escape_html(r)}</span>"
            )
        effort_cls = _EFFORT_MAP.get(r)
        if effort_cls:
            return (
                f'<span class="risk-badge risk-{_escape_attr(r)}">'
                f"{_escape_html(r)}</span>"
            )
        return _escape_html(risk_text)

    def _source_kind_label(source_kind: str) -> str:
        return {
            "production": "Production",
            "tests": "Tests",
            "fixtures": "Fixtures",
            "mixed": "Mixed",
            "other": "Other",
        }.get(source_kind, source_kind.title() or "Other")

    def _source_kind_badge_html(source_kind: str) -> str:
        normalized = source_kind.strip().lower() or "other"
        return (
            f'<span class="source-kind-badge source-kind-{_escape_attr(normalized)}">'
            f"{_escape_html(_source_kind_label(normalized))}</span>"
        )

    def _format_source_breakdown(
        source_breakdown: Mapping[str, object] | Sequence[object],
    ) -> str:
        rows: list[tuple[str, int]] = []
        if isinstance(source_breakdown, Mapping):
            rows = [
                (str(key), _as_int(value))
                for key, value in source_breakdown.items()
                if _as_int(value) > 0
            ]
        else:
            rows = [
                (str(pair[0]), _as_int(pair[1]))
                for pair in source_breakdown
                if isinstance(pair, Sequence)
                and len(pair) == 2
                and _as_int(pair[1]) > 0
            ]
        rows.sort(key=lambda item: (item[0], item[1]))
        return " · ".join(
            f"{_source_kind_label(kind)} {count}" for kind, count in rows if count > 0
        )

    baseline_loaded = bool(meta.get("baseline_loaded"))
    baseline_status = str(meta.get("baseline_status", "")).strip().lower()

    if baseline_loaded and baseline_status == "ok":
        baseline_split_note = (
            "Split is based on baseline: known duplicates are already "
            "recorded in baseline, new duplicates are absent from baseline."
        )
    else:
        baseline_split_note = (
            "Baseline is not loaded or not trusted: "
            "all duplicates are treated as new versus an empty baseline."
        )

    func_sorted = sorted(
        func_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0])
    )
    block_sorted = sorted(
        block_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0])
    )
    segment_sorted = sorted(
        segment_groups.items(), key=lambda kv: (*_group_sort_key(kv[1]), kv[0])
    )

    has_any = bool(func_sorted) or bool(block_sorted) or bool(segment_sorted)

    # Pygments CSS (scoped). Use modern GitHub-like styles when available.
    # We scope per theme to support toggle without reloading.
    pyg_dark_raw = _pygments_css("github-dark")
    if not pyg_dark_raw:
        pyg_dark_raw = _pygments_css("monokai")
    pyg_light_raw = _pygments_css("github-light")
    if not pyg_light_raw:
        pyg_light_raw = _pygments_css("friendly")

    pyg_dark = _prefix_css(pyg_dark_raw, "html[data-theme='dark']")
    pyg_light = _prefix_css(pyg_light_raw, "html[data-theme='light']")

    # ============================
    # Icons (Inline SVG)
    # ============================
    def _svg_icon(size: int, stroke_width: str, body: str) -> str:
        return (
            f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="{stroke_width}" '
            'stroke-linecap="round" stroke-linejoin="round">'
            f"{body}</svg>"
        )

    ICONS = {
        "search": _svg_icon(
            16,
            "2.5",
            '<circle cx="11" cy="11" r="8"></circle>'
            '<line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
        ),
        "clear": _svg_icon(
            16,
            "2.5",
            '<line x1="18" y1="6" x2="6" y2="18"></line>'
            '<line x1="6" y1="6" x2="18" y2="18"></line>',
        ),
        "chev_down": _svg_icon(
            16,
            "2.5",
            '<polyline points="6 9 12 15 18 9"></polyline>',
        ),
        # ICON_CHEV_RIGHT = (
        #     '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" '
        #     'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" '
        #     'stroke-linejoin="round">'
        #     '<polyline points="9 18 15 12 9 6"></polyline>'
        #     "</svg>"
        # )
        "theme": _svg_icon(
            16,
            "2",
            '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>',
        ),
        "check": _svg_icon(
            48,
            "2",
            '<polyline points="20 6 9 17 4 12"></polyline>',
        ),
        "prev": _svg_icon(
            16,
            "2",
            '<polyline points="15 18 9 12 15 6"></polyline>',
        ),
        "next": _svg_icon(
            16,
            "2",
            '<polyline points="9 18 15 12 9 6"></polyline>',
        ),
    }

    # ----------------------------
    # Section renderer
    # ----------------------------

    def _display_group_key(
        section_id: str, group_key: str, block_meta: dict[str, str] | None = None
    ) -> str:
        if section_id != "blocks":
            return group_key

        if block_meta and block_meta.get("pattern_display"):
            return str(block_meta["pattern_display"])

        return group_key

    def _block_group_explanation_meta(
        section_id: str, group_key: str
    ) -> dict[str, str]:
        if section_id != "blocks":
            return {}

        raw = resolved_block_group_facts.get(group_key, {})
        return {str(k): str(v) for k, v in raw.items() if v is not None}

    def _render_group_explanation(meta: Mapping[str, object]) -> str:
        if not meta:
            return ""

        explain_items: list[tuple[str, str]] = []
        if meta.get("match_rule"):
            explain_items.append(
                (f"match_rule: {meta['match_rule']}", "group-explain-item")
            )
        if meta.get("block_size"):
            explain_items.append(
                (f"block_size: {meta['block_size']}", "group-explain-item")
            )
        if meta.get("signature_kind"):
            explain_items.append(
                (f"signature_kind: {meta['signature_kind']}", "group-explain-item")
            )
        if meta.get("merged_regions"):
            explain_items.append(
                (f"merged_regions: {meta['merged_regions']}", "group-explain-item")
            )
        pattern_value = str(meta.get("pattern", "")).strip()
        if pattern_value:
            pattern_label = str(meta.get("pattern_label", pattern_value)).strip()
            pattern_display = str(meta.get("pattern_display", "")).strip()
            if pattern_display:
                explain_items.append(
                    (
                        f"pattern: {pattern_label} ({pattern_display})",
                        "group-explain-item",
                    )
                )
            else:
                explain_items.append(
                    (f"pattern: {pattern_label}", "group-explain-item")
                )

        hint_id = str(meta.get("hint", "")).strip()
        if hint_id:
            hint_label = str(meta.get("hint_label", hint_id)).strip()
            explain_items.append(
                (f"hint: {hint_label}", "group-explain-item group-explain-warn")
            )
            if meta.get("hint_confidence"):
                explain_items.append(
                    (
                        f"hint_confidence: {meta['hint_confidence']}",
                        "group-explain-item group-explain-muted",
                    )
                )
            if meta.get("assert_ratio"):
                explain_items.append(
                    (
                        f"assert_ratio: {meta['assert_ratio']}",
                        "group-explain-item group-explain-muted",
                    )
                )
            if meta.get("consecutive_asserts"):
                explain_items.append(
                    (
                        f"consecutive_asserts: {meta['consecutive_asserts']}",
                        "group-explain-item group-explain-muted",
                    )
                )
            hint_context_label = str(meta.get("hint_context_label", "")).strip()
            if hint_context_label:
                explain_items.append(
                    (
                        hint_context_label,
                        "group-explain-item group-explain-muted",
                    )
                )

        attrs = {
            "data-match-rule": str(meta.get("match_rule", "")),
            "data-block-size": str(meta.get("block_size", "")),
            "data-signature-kind": str(meta.get("signature_kind", "")),
            "data-merged-regions": str(meta.get("merged_regions", "")),
            "data-pattern": str(meta.get("pattern", "")),
            "data-pattern-label": str(meta.get("pattern_label", "")),
            "data-hint": str(meta.get("hint", "")),
            "data-hint-label": str(meta.get("hint_label", "")),
            "data-hint-context-label": str(meta.get("hint_context_label", "")),
            "data-hint-confidence": str(meta.get("hint_confidence", "")),
            "data-assert-ratio": str(meta.get("assert_ratio", "")),
            "data-consecutive-asserts": str(meta.get("consecutive_asserts", "")),
        }
        attr_html = " ".join(
            f'{key}="{_escape_attr(value)}"' for key, value in attrs.items() if value
        )
        parts = [
            f'<span class="{css_class}">{_escape_html(text)}</span>'
            for text, css_class in explain_items
        ]
        note = ""
        if isinstance(meta.get("hint_note"), str):
            note_text = _escape_html(str(meta["hint_note"]))
            note = f'<p class="group-explain-note">{note_text}</p>'
        return f'<div class="group-explain" {attr_html}>{"".join(parts)}{note}</div>'

    def render_section(
        section_id: str,
        section_title: str,
        groups: Sequence[tuple[str, Sequence[GroupItemLike]]],
        pill_cls: str,
        *,
        novelty_by_group: Mapping[str, str] | None = None,
    ) -> str:
        if not groups:
            return ""

        def _block_group_name(display_key: str, meta: dict[str, str]) -> str:
            if meta.get("group_display_name"):
                return str(meta["group_display_name"])
            if len(display_key) > 56:
                return f"{display_key[:24]}...{display_key[-16:]}"
            return display_key

        def _group_name(display_key: str, meta: dict[str, str]) -> str:
            if section_id == "blocks":
                return _block_group_name(display_key, meta)
            return display_key

        def _item_span_size(item: GroupItemLike) -> int:
            start_line = _as_int(item.get("start_line", 0))
            end_line = _as_int(item.get("end_line", 0))
            return max(0, end_line - start_line + 1)

        def _group_span_size(items: Sequence[GroupItemLike]) -> int:
            return max((_item_span_size(item) for item in items), default=0)

        section_novelty = novelty_by_group or {}
        has_novelty_filter = bool(section_novelty)

        out: list[str] = [
            f'<section id="{section_id}" class="section" data-section="{section_id}" '
            f'data-has-novelty-filter="{"true" if has_novelty_filter else "false"}" '
            f'data-total-groups="{len(groups)}">',
            f"""
<div class="toolbar" role="toolbar" aria-label="{_escape_attr(section_title)} controls">
  <div class="toolbar-left">
    <div class="search-box">
      <span class="search-ico">{ICONS["search"]}</span>
      <input
        type="text"
        id="search-{section_id}"
        placeholder="Search..."
        autocomplete="off"
      />
      <button
        class="clear-btn"
        type="button"
        data-clear="{section_id}"
        title="Clear search"
      >{ICONS["clear"]}</button>
    </div>
    <button class="btn" type="button" data-collapse-all="{section_id}">Collapse</button>
    <button class="btn" type="button" data-expand-all="{section_id}">Expand</button>
    <label class="muted" for="source-kind-{section_id}">Context:</label>
    <select
      class="select"
      id="source-kind-{section_id}"
      data-source-kind-filter="{section_id}"
    >
      <option value="all">all</option>
      <option value="production">production</option>
      <option value="tests">tests</option>
      <option value="fixtures">fixtures</option>
      <option value="mixed">mixed</option>
    </select>
    <label class="muted" for="clone-type-{section_id}">Type:</label>
    <select
      class="select"
      id="clone-type-{section_id}"
      data-clone-type-filter="{section_id}"
    >
      <option value="all">all</option>
      <option value="Type-1">Type-1</option>
      <option value="Type-2">Type-2</option>
      <option value="Type-3">Type-3</option>
      <option value="Type-4">Type-4</option>
    </select>
    <label class="muted" for="spread-{section_id}">Spread:</label>
    <select class="select" id="spread-{section_id}" data-spread-filter="{section_id}">
      <option value="all">all</option>
      <option value="high">high</option>
      <option value="low">low</option>
    </select>
    <label class="inline-check">
      <input type="checkbox" data-min-occurrences-filter="{section_id}" />
      <span>4+ occurrences</span>
    </label>
  </div>

  <div class="toolbar-right">
    <div class="pagination">
      <button class="btn" type="button" data-prev="{section_id}">
        {ICONS["prev"]}
      </button>
      <span class="page-meta" data-page-meta="{section_id}">
        Page 1 / 1 • {len(groups)} groups
      </span>
      <button class="btn" type="button" data-next="{section_id}">
        {ICONS["next"]}
      </button>
    </div>
    <select
      class="select"
      data-pagesize="{section_id}"
      aria-label="Items per page"
      title="Groups per page"
    >
      <option value="5">5 / page</option>
      <option value="10" selected>10 / page</option>
      <option value="20">20 / page</option>
      <option value="50">50 / page</option>
    </select>
  </div>
</div>
""",
            '<div class="section-body">',
        ]

        for idx, (gkey, items) in enumerate(groups, start=1):
            group_id = f"{section_id}-{idx}"
            search_parts: list[str] = [str(gkey)]
            for it in items:
                search_parts.append(str(it.get("qualname", "")))
                search_parts.append(str(it.get("filepath", "")))
            search_blob = " ".join(search_parts).lower()
            search_blob_escaped = _escape_attr(search_blob)
            block_meta = _block_group_explanation_meta(section_id, gkey)
            display_key = _display_group_key(section_id, gkey, block_meta)
            group_name = _group_name(display_key, block_meta)
            group_span_size = _group_span_size(items)
            group_arity = len(items)
            if section_id == "blocks":
                block_size_raw = block_meta.get("block_size", "").strip()
                if block_size_raw.isdigit():
                    group_span_size = int(block_size_raw)
                arity_raw = block_meta.get("group_arity", "").strip()
                if arity_raw.isdigit() and int(arity_raw) > 0:
                    group_arity = int(arity_raw)
            group_summary = (
                f"{group_arity} instances • block size {group_span_size}"
                if group_span_size > 0
                else f"{group_arity} instances"
            )
            clone_kind: Literal["function", "block", "segment"] = (
                "function"
                if section_id == "functions"
                else "block"
                if section_id == "blocks"
                else "segment"
            )
            clone_type = classify_clone_type(items=items, kind=clone_kind)
            group_locations = tuple(
                report_location_from_group_item(item, scan_root=scan_root_raw)
                for item in items
            )
            group_source_kind = combine_source_kinds(
                location.source_kind for location in group_locations
            )
            spread_files, spread_functions = group_spread(group_locations)
            spread_bucket = (
                "high" if spread_files > 1 or spread_functions > 1 else "low"
            )
            group_summary += f" • spread {spread_functions} fn / {spread_files} files"
            block_group_attrs = ""
            if block_meta:
                attrs = {
                    "data-group-id": group_id,
                    "data-clone-size": str(group_span_size),
                    "data-items-count": str(group_arity),
                    "data-match-rule": block_meta.get("match_rule"),
                    "data-block-size": block_meta.get("block_size"),
                    "data-signature-kind": block_meta.get("signature_kind"),
                    "data-merged-regions": block_meta.get("merged_regions"),
                    "data-pattern": block_meta.get("pattern"),
                    "data-pattern-label": block_meta.get("pattern_label"),
                    "data-hint": block_meta.get("hint"),
                    "data-hint-label": block_meta.get("hint_label"),
                    "data-hint-context-label": block_meta.get("hint_context_label"),
                    "data-hint-confidence": block_meta.get("hint_confidence"),
                    "data-assert-ratio": block_meta.get("assert_ratio"),
                    "data-consecutive-asserts": block_meta.get("consecutive_asserts"),
                    "data-boilerplate-asserts": block_meta.get("boilerplate_asserts"),
                }
                block_group_attrs = " ".join(
                    f'{name}="{_escape_attr(value)}"'
                    for name, value in attrs.items()
                    if value
                )
            if block_group_attrs:
                block_group_attrs = f" {block_group_attrs}"
            if 'data-group-id="' not in block_group_attrs:
                group_id_attr = _escape_attr(group_id)
                block_group_attrs = (
                    f' data-group-id="{group_id_attr}"{block_group_attrs}'
                )
            if 'data-clone-size="' not in block_group_attrs:
                clone_size_attr = _escape_attr(str(group_span_size))
                block_group_attrs += f' data-clone-size="{clone_size_attr}"'
            if 'data-items-count="' not in block_group_attrs:
                items_count_attr = _escape_attr(str(group_arity))
                block_group_attrs += f' data-items-count="{items_count_attr}"'
            arity_attr = _escape_attr(str(group_arity))
            block_group_attrs += f' data-group-arity="{arity_attr}"'
            block_group_attrs += f' data-clone-type="{_escape_attr(clone_type)}"'
            block_group_attrs += (
                f' data-source-kind="{_escape_attr(group_source_kind)}"'
            )
            block_group_attrs += f' data-spread-bucket="{_escape_attr(spread_bucket)}"'
            block_group_attrs += (
                f' data-spread-files="{_escape_attr(str(spread_files))}"'
            )
            block_group_attrs += (
                f' data-spread-functions="{_escape_attr(str(spread_functions))}"'
            )

            metrics_button = ""
            if section_id == "blocks":
                metrics_button = (
                    f'<button class="btn ghost" type="button" '
                    f'data-metrics-btn="{_escape_attr(group_id)}">Info</button>'
                )
            group_novelty = section_novelty.get(gkey, "all")
            out.append(
                f'<div class="group" data-group="{section_id}" '
                f'data-group-index="{idx}" '
                f'data-group-key="{_escape_attr(gkey)}" '
                f'data-novelty="{_escape_attr(group_novelty)}" '
                f'data-search="{search_blob_escaped}"{block_group_attrs}>'
            )

            out.append(
                '<div class="group-head">'
                '<div class="group-head-left">'
                f'<button class="group-toggle" type="button" aria-label="Toggle group" '
                f'data-toggle-group="{group_id}">{ICONS["chev_down"]}</button>'
                '<div class="group-info">'
                f'<div class="group-name">{_escape_html(group_name)}</div>'
                f'<div class="group-summary">{_escape_html(group_summary)}</div>'
                "</div>"
                "</div>"
                '<div class="group-head-right">'
                f"{_source_kind_badge_html(group_source_kind)}"
                f'<span class="clone-type-badge">{_escape_html(clone_type)}</span>'
                f'<span class="clone-count-badge">{group_arity}</span>'
                f"{metrics_button}"
                "</div>"
                "</div>"
            )
            if section_id == "blocks" and group_arity > 2:
                compare_note = block_meta.get("group_compare_note", "").strip()
                if compare_note:
                    out.append(
                        '<div class="group-compare-note">'
                        f"{_escape_html(compare_note)}"
                        "</div>"
                    )

            if section_id == "blocks":
                explanation_html = _render_group_explanation(block_meta)
                if explanation_html:
                    out.append(explanation_html)

            out.append(f'<div class="group-body items" id="group-body-{group_id}">')
            for item_index, item in enumerate(items, start=1):
                item_filepath = str(item.get("filepath", ""))
                item_qualname = str(item.get("qualname", ""))
                item_start_line = _as_int(item.get("start_line", 0))
                item_end_line = _as_int(item.get("end_line", 0))
                snippet = _render_code_block(
                    filepath=item_filepath,
                    start_line=item_start_line,
                    end_line=item_end_line,
                    file_cache=file_cache,
                    context=context_lines,
                    max_lines=max_snippet_lines,
                )
                display_qualname = _bare_qualname(item_qualname, item_filepath)
                qualname = _escape_html(display_qualname)
                qualname_attr = _escape_attr(item_qualname)
                display_filepath = _relative_path(item_filepath)
                filepath = _escape_html(display_filepath)
                filepath_attr = _escape_attr(item_filepath)
                start_line = item_start_line
                end_line = item_end_line
                peer_count = 0
                peer_count_raw = block_meta.get("instance_peer_count", "").strip()
                if peer_count_raw.isdigit() and int(peer_count_raw) >= 0:
                    peer_count = int(peer_count_raw)
                compare_meta_html = ""
                if section_id == "blocks" and "group_arity" in block_meta:
                    compare_text = format_group_instance_compare_meta(
                        instance_index=item_index,
                        group_arity=group_arity,
                        peer_count=peer_count,
                    )
                    compare_meta_html = (
                        f'<div class="item-compare-meta">{compare_text}</div>'
                    )
                out.append(
                    f'<div class="item" data-qualname="{qualname_attr}" '
                    f'data-filepath="{filepath_attr}" '
                    f'data-start-line="{start_line}" '
                    f'data-end-line="{end_line}" '
                    f'data-peer-count="{peer_count}" '
                    f'data-instance-index="{item_index}">'
                    '<div class="item-header">'
                    f'<div class="item-title" title="{qualname_attr}">{qualname}</div>'
                    f'<div class="item-loc" '
                    f'title="{filepath_attr}:{start_line}-{end_line}">'
                    f"{filepath}:{start_line}-{end_line}"
                    "</div>"
                    "</div>"
                    f"{compare_meta_html}"
                    f"{snippet.code_html}"
                    "</div>"
                )
            out.append("</div>")  # group-body
            out.append("</div>")  # group

        out.append("</div>")  # section-body
        out.append("</section>")
        return "\n".join(out)

    # ============================
    # HTML Rendering
    # ============================

    def _insight_block(
        *,
        question: str,
        answer: str,
        tone: _Tone = "info",
    ) -> str:
        return (
            f'<div class="insight-banner insight-{_escape_attr(tone)}">'
            f'<div class="insight-question">{_escape_html(question)}</div>'
            f'<div class="insight-answer">{_escape_html(answer)}</div>'
            "</div>"
        )

    def _tab_badge(value: int) -> str:
        return f'<span class="tab-count">{value}</span>'

    def _build_clone_sections() -> tuple[
        str,
        str,
        str,
        str,
        str,
        bool,
        int,
        int,
        str,
    ]:
        empty_state_html_local = ""
        if not has_any:
            empty_state_html_local = f"""
<div class="empty">
  <div class="empty-card">
    <div class="empty-icon">{ICONS["check"]}</div>
    <h2>No code clones detected</h2>
    <p>
      No structural, block-level, or segment-level duplication was found above
      configured thresholds.
    </p>
    <p class="muted">This usually indicates healthy abstraction boundaries.</p>
  </div>
</div>
"""

        new_function_key_set = set(new_function_group_keys or ())
        new_block_key_set = set(new_block_group_keys or ())
        function_novelty_local = {
            group_key: ("new" if group_key in new_function_key_set else "known")
            for group_key, _ in func_sorted
        }
        block_novelty_local = {
            group_key: ("new" if group_key in new_block_key_set else "known")
            for group_key, _ in block_sorted
        }
        novelty_enabled_local = bool(function_novelty_local) or bool(
            block_novelty_local
        )
        total_new_groups_local = sum(
            1 for value in function_novelty_local.values() if value == "new"
        )
        total_new_groups_local += sum(
            1 for value in block_novelty_local.values() if value == "new"
        )
        total_known_groups_local = sum(
            1 for value in function_novelty_local.values() if value == "known"
        )
        total_known_groups_local += sum(
            1 for value in block_novelty_local.values() if value == "known"
        )
        default_novelty = "new" if total_new_groups_local > 0 else "known"
        global_novelty_html_local = ""
        if novelty_enabled_local:
            global_novelty_html_local = (
                '<section class="global-novelty" id="global-novelty-controls" '
                f'data-default-novelty="{default_novelty}">'
                '<div class="global-novelty-head">'
                "<h2>Duplicate Scope</h2>"
                '<div class="novelty-tabs" role="tablist" '
                'aria-label="Baseline split filter">'
                '<button class="btn novelty-tab" type="button" '
                'data-global-novelty="new">'
                "New duplicates "
                f'<span class="novelty-count">{total_new_groups_local}</span>'
                "</button>"
                '<button class="btn novelty-tab" type="button" '
                'data-global-novelty="known">'
                "Known duplicates "
                f'<span class="novelty-count">{total_known_groups_local}</span>'
                "</button>"
                "</div>"
                "</div>"
                f'<p class="novelty-note">{_escape_html(baseline_split_note)}</p>'
                "</section>"
            )

        func_section_local = render_section(
            "functions",
            "Function clones",
            func_sorted,
            "pill-func",
            novelty_by_group=function_novelty_local,
        )
        block_section_local = render_section(
            "blocks",
            "Block clones",
            block_sorted,
            "pill-block",
            novelty_by_group=block_novelty_local,
        )
        segment_section_local = render_section(
            "segments", "Segment clones", segment_sorted, "pill-segment"
        )
        clone_sub_tabs: list[tuple[str, str, int, str]] = []
        if func_sorted:
            clone_sub_tabs.append(
                ("functions", "Functions", len(func_sorted), func_section_local)
            )
        if block_sorted:
            clone_sub_tabs.append(
                ("blocks", "Blocks", len(block_sorted), block_section_local)
            )
        if segment_sorted:
            clone_sub_tabs.append(
                ("segments", "Segments", len(segment_sorted), segment_section_local)
            )

        if clone_sub_tabs:
            nav_parts = ['<nav class="clone-nav" role="tablist">']
            for tab_index, (tab_id, tab_label, tab_count, _) in enumerate(
                clone_sub_tabs
            ):
                active_cls = " active" if tab_index == 0 else ""
                nav_parts.append(
                    f'<button class="clone-nav-btn{active_cls}" '
                    f'data-clone-tab="{tab_id}" type="button">'
                    f"{_escape_html(tab_label)} "
                    f'<span class="tab-count" data-clone-tab-count="{tab_id}" '
                    f'data-total-groups="{tab_count}">{tab_count}</span>'
                    f"</button>"
                )
            nav_parts.append("</nav>")
            clone_nav_html = "".join(nav_parts)

            panel_parts: list[str] = []
            for tab_index, (tab_id, _, _, panel_html) in enumerate(clone_sub_tabs):
                active_cls = " active" if tab_index == 0 else ""
                panel_parts.append(
                    f'<div class="clone-panel{active_cls}" '
                    f'data-clone-panel="{tab_id}">{panel_html}</div>'
                )
            clone_panels_html = "".join(panel_parts)
            clones_panel_html_local = (
                f"{global_novelty_html_local}{clone_nav_html}{clone_panels_html}"
            )
        else:
            clones_panel_html_local = empty_state_html_local

        return (
            empty_state_html_local,
            global_novelty_html_local,
            func_section_local,
            block_section_local,
            segment_section_local,
            novelty_enabled_local,
            total_new_groups_local,
            total_known_groups_local,
            clones_panel_html_local,
        )

    (
        empty_state_html,
        global_novelty_html,
        func_section,
        block_section,
        segment_section,
        novelty_enabled,
        total_new_groups,
        total_known_groups,
        clones_panel_html,
    ) = _build_clone_sections()

    metrics_map = _as_mapping(metrics)
    complexity_map = _as_mapping(metrics_map.get("complexity"))
    coupling_map = _as_mapping(metrics_map.get("coupling"))
    cohesion_map = _as_mapping(metrics_map.get("cohesion"))
    dependencies_map = _as_mapping(metrics_map.get("dependencies"))
    dead_code_map = _as_mapping(metrics_map.get("dead_code"))
    health_map = _as_mapping(metrics_map.get("health"))

    complexity_summary = _as_mapping(complexity_map.get("summary"))
    coupling_summary = _as_mapping(coupling_map.get("summary"))
    cohesion_summary = _as_mapping(cohesion_map.get("summary"))
    dead_code_summary = _as_mapping(dead_code_map.get("summary"))

    _RISK_HEADERS = {"risk", "confidence", "severity", "effort"}
    _PATH_HEADERS = {"file", "location"}
    _NAME_HEADERS = {"function", "class", "name"}

    _COL_WIDTHS: dict[str, str] = {
        "cc": "62px",
        "cbo": "62px",
        "lcom4": "70px",
        "nesting": "76px",
        "line": "60px",
        "length": "68px",
        "methods": "80px",
        "fields": "68px",
        "priority": "74px",
        "risk": "78px",
        "confidence": "94px",
        "severity": "82px",
        "effort": "78px",
        "category": "100px",
        "kind": "76px",
        "steps": "120px",
        "coupled classes": "360px",
    }

    _GLOSSARY: dict[str, str] = {
        # Table headers — complexity
        "function": "Fully-qualified function or method name",
        "class": "Fully-qualified class name",
        "name": "Symbol name (function, class, or variable)",
        "file": "Source file path relative to scan root",
        "location": "File and line range where the symbol is defined",
        "cc": "Cyclomatic complexity — number of independent execution paths",
        "nesting": "Maximum nesting depth of control-flow statements",
        "risk": "Risk level based on metric thresholds (low / medium / high)",
        # Table headers — coupling / cohesion
        "cbo": "Coupling Between Objects — number of classes this class depends on",
        "coupled classes": (
            "Resolved class dependencies used to compute CBO for this class"
        ),
        "lcom4": (
            "Lack of Cohesion of Methods — connected components in method/field graph"
        ),
        "methods": "Number of methods defined in the class",
        "fields": "Number of instance variables (attributes) in the class",
        # Table headers — dead code
        "line": "Source line number where the symbol starts",
        "kind": "Symbol type: function, class, import, or variable",
        "confidence": "Detection confidence (low / medium / high / critical)",
        # Table headers — dependencies
        "longest chain": "Longest transitive import chain between modules",
        "length": "Number of modules in the dependency chain",
        "cycle": "Circular import dependency between modules",
        # Table headers — suggestions
        "priority": "Computed priority score (higher = more urgent)",
        "severity": "Issue severity: critical, warning, or info",
        "category": (
            "Metric category: clone, complexity, coupling, cohesion, "
            "dead_code, dependency"
        ),
        "title": "Brief description of the suggested improvement",
        "effort": "Estimated effort to fix: easy, moderate, or hard",
        "steps": "Actionable steps to resolve the issue",
        # Dependency stat cards
        "modules": "Total number of Python modules analyzed",
        "edges": "Total number of import relationships between modules",
        "max depth": "Longest chain of transitive imports",
        "cycles": "Number of circular import dependencies detected",
    }

    def _build_column_classes() -> dict[str, str]:
        col_cls: dict[str, str] = {}
        for header in ("function", "class", "name"):
            col_cls[header] = "col-name"
        for header in ("file", "location"):
            col_cls[header] = "col-path"
        for header in (
            "cc",
            "cbo",
            "lcom4",
            "nesting",
            "line",
            "length",
            "methods",
            "fields",
            "priority",
        ):
            col_cls[header] = "col-num"
        for header in ("risk", "confidence", "severity", "effort"):
            col_cls[header] = "col-badge"
        for header in ("category", "kind"):
            col_cls[header] = "col-cat"
        for header in ("cycle", "longest chain", "title", "coupled classes"):
            col_cls[header] = "col-wide"
        col_cls["steps"] = "col-steps"
        return col_cls

    _COL_CLS = _build_column_classes()

    _CHECK_CIRCLE_SVG = (
        '<svg class="tab-empty-icon" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
        'stroke-linejoin="round">'
        '<circle cx="12" cy="12" r="10"/>'
        '<polyline points="16 9 10.5 15 8 12.5"/>'
        "</svg>"
    )

    def _tab_empty(message: str) -> str:
        return (
            '<div class="tab-empty">'
            f"{_CHECK_CIRCLE_SVG}"
            f'<div class="tab-empty-title">{_escape_html(message)}</div>'
            '<div class="tab-empty-desc">'
            "Nothing to report - keep up the good work."
            "</div>"
            "</div>"
        )

    def _render_rows_table(
        *,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        empty_message: str,
        raw_html_headers: Collection[str] = (),
    ) -> str:
        if not rows:
            return _tab_empty(empty_message)

        lower_headers = [h.lower() for h in headers]
        raw_html_header_set = {header.lower() for header in raw_html_headers}

        colgroup_parts = ["<colgroup>"]
        for h in lower_headers:
            w = _COL_WIDTHS.get(h)
            if w:
                colgroup_parts.append(f'<col style="width:{w}">')
            else:
                colgroup_parts.append("<col>")
        colgroup_parts.append("</colgroup>")
        colgroup_html = "".join(colgroup_parts)

        def _th(header: str) -> str:
            return f"<th>{_escape_html(header)}{_glossary_tip(header)}</th>"

        header_html = "".join(_th(header) for header in headers)

        def _render_cell(col_idx: int, cell: str) -> str:
            h = lower_headers[col_idx] if col_idx < len(lower_headers) else ""
            cls = _COL_CLS.get(h, "")
            cls_attr = f' class="{cls}"' if cls else ""
            if h in raw_html_header_set:
                return f"<td{cls_attr}>{cell}</td>"
            if h in _RISK_HEADERS:
                return f"<td{cls_attr}>{_risk_badge_html(cell)}</td>"
            if h in _PATH_HEADERS:
                short = _relative_path(cell)
                return (
                    f'<td{cls_attr} title="{_escape_attr(cell)}">'
                    f"{_escape_html(short)}</td>"
                )
            return f"<td{cls_attr}>{_escape_html(cell)}</td>"

        body_html = "".join(
            "<tr>"
            + "".join(_render_cell(i, cell) for i, cell in enumerate(row))
            + "</tr>"
            for row in rows
        )
        return (
            '<div class="table-wrap"><table class="table">'
            f"{colgroup_html}"
            f"<thead><tr>{header_html}</tr></thead>"
            f"<tbody>{body_html}</tbody>"
            "</table></div>"
        )

    def _render_coupled_classes_cell(row_data: Mapping[str, object]) -> str:
        def _short_coupled_label(name: str) -> str:
            parts = name.rsplit(".", maxsplit=1)
            label = parts[-1] if len(parts) > 1 else name
            if len(label) > 20:
                return f"{label[:8]}..{label[-8:]}"
            return label

        def _render_coupled_flow(values: Sequence[str]) -> str:
            nodes = "".join(
                f'<span class="chain-node" title="{_escape_attr(name)}">'
                f"{_escape_html(_short_coupled_label(name))}</span>"
                for name in values
            )
            return f'<span class="chain-flow">{nodes}</span>'

        raw_values = _as_sequence(row_data.get("coupled_classes"))
        names = sorted(
            {
                str(value).strip()
                for value in raw_values
                if isinstance(value, str) and str(value).strip()
            }
        )
        if not names:
            return "-"
        if len(names) <= 3:
            return _render_coupled_flow(names)

        preview_flow = _render_coupled_flow(names[:3])
        full_flow = _render_coupled_flow(names)
        remaining = len(names) - 3
        return (
            '<details class="coupled-details">'
            '<summary class="coupled-summary">'
            f"{preview_flow}"
            f'<span class="coupled-more">(+{remaining} more)</span>'
            "</summary>"
            f'<div class="coupled-expanded">{full_flow}</div>'
            "</details>"
        )

    complexity_rows_data = _as_sequence(complexity_map.get("functions"))
    complexity_rows = [
        (
            _bare_qualname(
                str(_as_mapping(row).get("qualname", "")),
                str(_as_mapping(row).get("filepath", "")),
            ),
            str(_as_mapping(row).get("filepath", "")),
            str(_as_mapping(row).get("cyclomatic_complexity", "")),
            str(_as_mapping(row).get("nesting_depth", "")),
            str(_as_mapping(row).get("risk", "")),
        )
        for row in complexity_rows_data[:50]
    ]
    coupling_rows_data = _as_sequence(coupling_map.get("classes"))
    coupling_rows = [
        (
            _bare_qualname(
                str(_as_mapping(row).get("qualname", "")),
                str(_as_mapping(row).get("filepath", "")),
            ),
            str(_as_mapping(row).get("filepath", "")),
            str(_as_mapping(row).get("cbo", "")),
            str(_as_mapping(row).get("risk", "")),
            _render_coupled_classes_cell(_as_mapping(row)),
        )
        for row in coupling_rows_data[:50]
    ]
    cohesion_rows_data = _as_sequence(cohesion_map.get("classes"))
    cohesion_rows = [
        (
            _bare_qualname(
                str(_as_mapping(row).get("qualname", "")),
                str(_as_mapping(row).get("filepath", "")),
            ),
            str(_as_mapping(row).get("filepath", "")),
            str(_as_mapping(row).get("lcom4", "")),
            str(_as_mapping(row).get("risk", "")),
            str(_as_mapping(row).get("method_count", "")),
            str(_as_mapping(row).get("instance_var_count", "")),
        )
        for row in cohesion_rows_data[:50]
    ]

    dep_cycles = _as_sequence(dependencies_map.get("cycles"))

    def _collect_cycle_nodes(cycles: Sequence[object]) -> set[str]:
        cycle_nodes: set[str] = set()
        for cycle in cycles:
            for part in _as_sequence(cycle):
                cycle_nodes.add(str(part))
        return cycle_nodes

    _cycle_node_set = _collect_cycle_nodes(dep_cycles)

    def _short_label(name: str) -> str:
        parts = name.rsplit(".", maxsplit=1)
        label = parts[-1] if len(parts) > 1 else name
        if len(label) > 20:
            return f"{label[:8]}..{label[-8:]}"
        return label

    def _render_chain_visual(chain_parts: Sequence[str]) -> str:
        parts: list[str] = []
        for i, mod in enumerate(chain_parts):
            short = _short_label(str(mod))
            parts.append(
                f'<span class="chain-node" title="{_escape_attr(str(mod))}">'
                f"{_escape_html(short)}</span>"
            )
            if i < len(chain_parts) - 1:
                parts.append('<span class="chain-arrow">\u2192</span>')
        return f'<span class="chain-flow">{"".join(parts)}</span>'

    dep_cycle_rows = [
        (_render_chain_visual([str(part) for part in _as_sequence(cycle)]),)
        for cycle in dep_cycles
    ]
    dep_longest_chains = _as_sequence(dependencies_map.get("longest_chains"))
    dep_chain_rows = [
        (
            _render_chain_visual([str(p) for p in _as_sequence(chain)]),
            str(len(_as_sequence(chain))),
        )
        for chain in dep_longest_chains
    ]
    dep_edge_rows_data = _as_sequence(dependencies_map.get("edge_list"))
    dep_edges = [
        (
            str(_as_mapping(row).get("source", "")),
            str(_as_mapping(row).get("target", "")),
        )
        for row in dep_edge_rows_data
        if _as_mapping(row).get("source") and _as_mapping(row).get("target")
    ]

    dead_items_data = _as_sequence(dead_code_map.get("items"))
    dead_rows = [
        (
            _bare_qualname(
                str(_as_mapping(item).get("qualname", "")),
                str(_as_mapping(item).get("filepath", "")),
            ),
            str(_as_mapping(item).get("filepath", "")),
            str(_as_mapping(item).get("start_line", "")),
            str(_as_mapping(item).get("kind", "")),
            str(_as_mapping(item).get("confidence", "")),
        )
        for item in dead_items_data[:200]
    ]
    dead_high_confidence_items = sum(
        1
        for item in dead_items_data
        if str(_as_mapping(item).get("confidence", "")).strip().lower() == "high"
    )

    suggestions_rows = list(suggestions or ())
    overview_data = _as_mapping(derived_map.get("overview"))
    if not overview_data:
        overview_data = build_report_overview(
            suggestions=suggestions_rows,
            metrics=metrics_map,
        )

    def _glossary_tip(label: str) -> str:
        tip = _GLOSSARY.get(label.lower(), "")
        if not tip:
            return ""
        return f' <span class="kpi-help" data-tip="{_escape_attr(tip)}">?</span>'

    def _meta_card(label: str, value: object) -> str:
        tip_html = _glossary_tip(label)
        return (
            '<div class="meta-item">'
            f'<div class="meta-label">{_escape_html(label)}{tip_html}</div>'
            f'<div class="meta-value">{_escape_html(str(value))}</div>'
            "</div>"
        )

    clone_groups_total = len(func_sorted) + len(block_sorted) + len(segment_sorted)
    clone_instances_total = sum(len(items) for _, items in func_sorted)
    clone_instances_total += sum(len(items) for _, items in block_sorted)
    clone_instances_total += sum(len(items) for _, items in segment_sorted)

    if novelty_enabled:
        clones_answer = (
            f"{clone_groups_total} groups total; "
            f"{total_new_groups} new vs {total_known_groups} known."
        )
    else:
        clones_answer = (
            f"{clone_groups_total} groups and {clone_instances_total} instances."
        )
    clones_panel_html = (
        _insight_block(
            question="Where is duplication concentrated right now?",
            answer=clones_answer,
            tone=("warn" if clone_groups_total > 0 else "ok"),
        )
        + clones_panel_html
    )

    metrics_available = bool(metrics_map)
    complexity_high_risk = _as_int(complexity_summary.get("high_risk"))
    coupling_high_risk = _as_int(coupling_summary.get("high_risk"))
    cohesion_low = _as_int(cohesion_summary.get("low_cohesion"))
    dependency_cycle_count = len(dep_cycles)
    dependency_max_depth = _as_int(dependencies_map.get("max_depth"))
    dead_total = _as_int(dead_code_summary.get("total"))
    dead_summary_high_confidence = _as_int(
        dead_code_summary.get("high_confidence", dead_code_summary.get("critical"))
    )
    dead_high_confidence = dead_summary_high_confidence
    if dead_total > 0 and dead_high_confidence == 0 and dead_high_confidence_items > 0:
        dead_high_confidence = min(dead_total, dead_high_confidence_items)

    health_score_raw = health_map.get("score")
    health_score_known = (
        health_score_raw is not None and str(health_score_raw).strip() != ""
    )
    health_score = _as_float(health_score_raw) if health_score_known else -1.0
    health_grade = str(health_map.get("grade", "n/a"))

    def _overview_answer_and_tone() -> tuple[str, _Tone]:
        if metrics_available and health_score_known:
            answer = (
                f"Health {health_score:.0f}/100 ({health_grade}); "
                f"{clone_groups_total} clone groups; "
                f"{dead_total} dead-code items; "
                f"{dependency_cycle_count} dependency cycles."
            )
            if health_score >= 80.0:
                tone: _Tone = "ok"
            elif health_score >= 60.0:
                tone = "warn"
            else:
                tone = "risk"
            return answer, tone
        if metrics_available:
            answer = (
                f"{clone_groups_total} clone groups; "
                f"{dead_total} dead-code items; "
                f"{dependency_cycle_count} dependency cycles."
            )
            return answer, "info"
        return (
            f"{clone_groups_total} clone groups; metrics were skipped for this run.",
            "info",
        )

    overview_answer, overview_tone = _overview_answer_and_tone()

    def _health_gauge_html(score: float, grade: str) -> str:
        """Render an SVG ring gauge for health score."""
        if score < 0:
            return _meta_card("Health", "n/a")
        circumference = 2.0 * math.pi * 42.0
        offset = circumference * (1.0 - score / 100.0)
        if score >= 80:
            color = "var(--success)"
        elif score >= 60:
            color = "var(--warning)"
        else:
            color = "var(--error)"
        return (
            '<div class="health-gauge">'
            '<div class="health-ring">'
            '<svg viewBox="0 0 100 100">'
            '<circle class="health-ring-bg" cx="50" cy="50" r="42"/>'
            f'<circle class="health-ring-fg" cx="50" cy="50" r="42" '
            f'stroke="{color}" '
            f'stroke-dasharray="{circumference:.1f}" '
            f'stroke-dashoffset="{offset:.1f}"/>'
            "</svg>"
            '<div class="health-ring-label">'
            f'<div class="health-ring-score">{score:.0f}</div>'
            f'<div class="health-ring-grade">Grade {_escape_html(grade)}</div>'
            "</div>"
            "</div>"
            "</div>"
        )

    def _overview_kpi(
        label: str,
        value: object,
        *,
        detail: str = "",
        tip: str = "",
    ) -> str:
        tip_html = (
            f'<span class="kpi-help" data-tip="{_escape_attr(tip)}">?</span>'
            if tip
            else ""
        )
        detail_html = (
            f'<div class="kpi-detail">{_escape_html(detail)}</div>' if detail else ""
        )
        return (
            '<div class="overview-kpi">'
            '<div class="kpi-head">'
            f'<span class="overview-kpi-label">{_escape_html(label)}</span>'
            f"{tip_html}"
            "</div>"
            f'<div class="overview-kpi-value">{_escape_html(str(value))}</div>'
            f"{detail_html}"
            "</div>"
        )

    overview_kpis = [
        _overview_kpi(
            "Clone Groups",
            clone_groups_total,
            detail=(
                f"{len(func_sorted)} func · "
                f"{len(block_sorted)} block · "
                f"{len(segment_sorted)} seg"
            ),
            tip="Detected code clone groups by detection level",
        ),
        _overview_kpi(
            "High Complexity",
            complexity_high_risk,
            detail=(
                f"avg {complexity_summary.get('average', 'n/a')} · "
                f"max {complexity_summary.get('max', 'n/a')}"
            ),
            tip="Functions with cyclomatic complexity above threshold",
        ),
        _overview_kpi(
            "High Coupling",
            coupling_high_risk,
            detail=(
                f"avg {coupling_summary.get('average', 'n/a')} · "
                f"max {coupling_summary.get('max', 'n/a')}"
            ),
            tip="Classes with high coupling between objects (CBO)",
        ),
        _overview_kpi(
            "Low Cohesion",
            cohesion_low,
            detail=(
                f"avg {cohesion_summary.get('average', 'n/a')} · "
                f"max {cohesion_summary.get('max', 'n/a')}"
            ),
            tip="Classes with low internal cohesion (high LCOM4)",
        ),
        _overview_kpi(
            "Dep. Cycles",
            dependency_cycle_count,
            detail=f"max depth {dependency_max_depth}",
            tip="Circular dependencies between project modules",
        ),
        _overview_kpi(
            "Dead Code",
            dead_total,
            detail=f"{dead_high_confidence} high-confidence",
            tip="Potentially unused functions, classes, or imports",
        ),
    ]

    def _overview_cluster_header(title: str, subtitle: str | None = None) -> str:
        subtitle_html = (
            f'<p class="overview-cluster-copy">{_escape_html(subtitle)}</p>'
            if subtitle
            else ""
        )
        return (
            '<div class="overview-cluster-header">'
            f'<h3 class="subsection-title">{_escape_html(title)}</h3>'
            f"{subtitle_html}"
            "</div>"
        )

    def _overview_summary_list_html(items: Sequence[str]) -> str:
        cleaned = [str(item).strip() for item in items if str(item).strip()]
        if not cleaned:
            return '<div class="overview-summary-value">none</div>'
        return (
            '<ul class="overview-summary-list">'
            + "".join(f"<li>{_escape_html(item)}</li>" for item in cleaned)
            + "</ul>"
        )

    def _overview_source_breakdown_html(
        breakdown: Mapping[str, object],
    ) -> str:
        rows = tuple(
            f"{_source_kind_label(str(kind))} {_as_int(count)}"
            for kind, count in sorted(
                breakdown.items(),
                key=lambda item: (str(item[0]), _as_int(item[1])),
            )
            if _as_int(count) > 0
        )
        if rows:
            return _overview_summary_list_html(rows)
        return '<div class="overview-summary-value">n/a</div>'

    def _overview_summary_item_html(
        *,
        label: str,
        body_html: str,
    ) -> str:
        return (
            '<article class="overview-summary-item">'
            f'<div class="overview-summary-label">{_escape_html(label)}</div>'
            f"{body_html}"
            "</article>"
        )

    def _summary_chip_row(parts: Sequence[str], *, css_class: str) -> str:
        cleaned = [str(part).strip() for part in parts if str(part).strip()]
        if not cleaned:
            return ""
        return (
            f'<div class="{css_class}">'
            + "".join(
                f'<span class="group-explain-item">{_escape_html(part)}</span>'
                for part in cleaned
            )
            + "</div>"
        )

    def _overview_row_html(card: Mapping[str, object]) -> str:
        severity = str(card.get("severity", "info"))
        source_kind = str(card.get("source_kind", "other"))
        category = str(card.get("category", ""))
        title = str(card.get("title", ""))
        summary_text = str(card.get("summary", ""))
        confidence_text = str(card.get("confidence", ""))
        location_text = str(card.get("location", ""))
        count = _as_int(card.get("count"))
        spread = _as_mapping(card.get("spread"))
        spread_files = _as_int(spread.get("files"))
        spread_functions = _as_int(spread.get("functions"))
        clone_type = str(card.get("clone_type", "")).strip()
        context_parts = [
            severity,
            _source_kind_label(source_kind),
            category.replace("_", " "),
        ]
        if clone_type:
            context_parts.append(clone_type)
        context_text = " · ".join(part for part in context_parts if part)
        stats_html = _summary_chip_row(
            (
                f"count={count}",
                f"spread={spread_functions} fn / {spread_files} files",
                f"confidence={confidence_text}",
            ),
            css_class="overview-row-stats",
        )
        return (
            '<article class="overview-row" '
            f'data-severity="{_escape_attr(severity)}" '
            f'data-source-kind="{_escape_attr(source_kind)}">'
            '<div class="overview-row-main">'
            f'<div class="overview-row-title">{_escape_html(title)}</div>'
            f'<div class="overview-row-summary">{_escape_html(summary_text)}</div>'
            "</div>"
            '<div class="overview-row-side">'
            f'<div class="overview-row-context">{_escape_html(context_text)}</div>'
            f"{stats_html}"
            f'<div class="overview-row-location">{_escape_html(location_text)}</div>'
            "</div>"
            "</article>"
        )

    def _overview_section_html(
        *,
        title: str,
        subtitle: str,
        cards: Sequence[object],
        empty_message: str,
    ) -> str:
        typed_cards = [_as_mapping(card) for card in cards if _as_mapping(card)]
        if not typed_cards:
            return (
                '<section class="overview-cluster">'
                f"{_overview_cluster_header(title, subtitle)}"
                '<div class="overview-cluster-empty">'
                f"{_escape_html(empty_message)}"
                "</div>"
                "</section>"
            )
        return (
            '<section class="overview-cluster">'
            f"{_overview_cluster_header(title, subtitle)}"
            '<div class="overview-list">'
            + "".join(_overview_row_html(card) for card in typed_cards)
            + "</div></section>"
        )

    health_overview = _as_mapping(overview_data.get("health"))
    top_risks = [
        str(item).strip()
        for item in _as_sequence(overview_data.get("top_risks"))
        if str(item).strip()
    ]
    strongest_dimension = str(
        health_overview.get("strongest_dimension", "n/a")
    ).replace("_", " ")
    weakest_dimension = str(health_overview.get("weakest_dimension", "n/a")).replace(
        "_", " "
    )
    family_counts = _as_mapping(overview_data.get("families"))
    executive_summary = (
        '<section class="overview-cluster">'
        + _overview_cluster_header(
            "Executive Summary",
            "Project-wide context derived from the full scanned root.",
        )
        + '<div class="overview-summary-grid">'
        + _overview_summary_item_html(
            label="Families",
            body_html=_overview_summary_list_html(
                (
                    f"{_as_int(family_counts.get('clone_groups'))} clone groups",
                    (
                        f"{_as_int(family_counts.get('structural_findings'))} "
                        "structural findings"
                    ),
                    f"{_as_int(family_counts.get('dead_code'))} dead code items",
                    f"{_as_int(family_counts.get('metric_hotspots'))} metric hotspots",
                )
            ),
        )
        + _overview_summary_item_html(
            label="Top risks",
            body_html=_overview_summary_list_html(tuple(top_risks)),
        )
        + _overview_summary_item_html(
            label="Health snapshot",
            body_html=_overview_summary_list_html(
                (
                    "Score "
                    f"{_escape_html(str(health_overview.get('score', 'n/a')))}"
                    " / grade "
                    f"{_escape_html(str(health_overview.get('grade', 'n/a')))}",
                    f"Strongest dimension: {strongest_dimension}",
                    f"Weakest dimension: {weakest_dimension}",
                )
            ),
        )
        + _overview_summary_item_html(
            label="Source breakdown",
            body_html=_overview_source_breakdown_html(
                _as_mapping(overview_data.get("source_breakdown"))
            ),
        )
        + "</div>"
        + "</section>"
    )
    health_gauge = _health_gauge_html(health_score, health_grade)
    overview_panel = (
        _insight_block(
            question="What is the current code-health snapshot?",
            answer=overview_answer,
            tone=overview_tone,
        )
        + '<div class="overview-dashboard">'
        + '<div class="overview-hero">'
        + health_gauge
        + "</div>"
        + '<div class="overview-kpi-grid">'
        + "".join(overview_kpis)
        + "</div>"
        + "</div>"
        + executive_summary
        + _overview_section_html(
            title="Highest Spread",
            subtitle="Findings that touch the widest surface area first.",
            cards=_as_sequence(overview_data.get("highest_spread")),
            empty_message="No spread-heavy findings were recorded.",
        )
        + _overview_section_html(
            title="Production Hotspots",
            subtitle="Runtime-facing hotspots across production code.",
            cards=_as_sequence(overview_data.get("production_hotspots")),
            empty_message="No production-coded hotspots were identified.",
        )
        + _overview_section_html(
            title="Test/Fixture Hotspots",
            subtitle="Context-rich hotspots rooted in tests and fixtures.",
            cards=_as_sequence(overview_data.get("test_fixture_hotspots")),
            empty_message="No hotspots from tests or fixtures were identified.",
        )
    )

    def _complexity_answer_and_tone() -> tuple[str, _Tone]:
        if not metrics_available:
            return "Metrics are skipped for this run.", "info"
        complexity_max = _as_int(complexity_summary.get("max"))
        complexity_total = _as_int(complexity_summary.get("total"))
        answer = (
            f"Max CC {complexity_max}; "
            f"high-risk functions {complexity_high_risk}/{complexity_total}."
        )
        if complexity_max > 40:
            return answer, "risk"
        if complexity_high_risk > 0 or complexity_max > 20:
            return answer, "warn"
        return answer, "ok"

    complexity_answer, complexity_tone = _complexity_answer_and_tone()

    complexity_panel = _insight_block(
        question="Do we have risky functions by complexity?",
        answer=complexity_answer,
        tone=complexity_tone,
    ) + _render_rows_table(
        headers=("Function", "File", "CC", "Nesting", "Risk"),
        rows=complexity_rows,
        empty_message="Complexity metrics are not available.",
    )

    def _coupling_answer_and_tone() -> tuple[str, _Tone]:
        if not metrics_available:
            return "Metrics are skipped for this run.", "info"
        answer = (
            f"High-coupling classes: {coupling_high_risk}; "
            f"low-cohesion classes: {cohesion_low}; "
            f"max CBO {coupling_summary.get('max', 'n/a')}; "
            f"max LCOM4 {cohesion_summary.get('max', 'n/a')}."
        )
        if coupling_high_risk > 0 and cohesion_low > 0:
            return answer, "risk"
        if coupling_high_risk > 0 or cohesion_low > 0:
            return answer, "warn"
        return answer, "ok"

    coupling_answer, coupling_tone = _coupling_answer_and_tone()

    coupling_panel = (
        _insight_block(
            question="Are classes over-coupled or low-cohesion?",
            answer=coupling_answer,
            tone=coupling_tone,
        )
        + '<h3 class="subsection-title">Coupling (CBO)</h3>'
        + _render_rows_table(
            headers=("Class", "File", "CBO", "Risk", "Coupled classes"),
            rows=coupling_rows,
            empty_message="Coupling metrics are not available.",
            raw_html_headers=("Coupled classes",),
        )
        + '<h3 class="subsection-title">Cohesion (LCOM4)</h3>'
        + _render_rows_table(
            headers=("Class", "File", "LCOM4", "Risk", "Methods", "Fields"),
            rows=cohesion_rows,
            empty_message="Cohesion metrics are not available.",
        )
    )

    def _dep_stat_card(
        label: str, value: object, *, detail: str = "", tone: str = ""
    ) -> str:
        tip_html = _glossary_tip(label)
        tone_cls = f" dep-stat-{tone}" if tone else ""
        detail_html = (
            f'<div class="dep-stat-detail">{_escape_html(detail)}</div>'
            if detail
            else ""
        )
        return (
            f'<div class="meta-item{tone_cls}">'
            f'<div class="meta-label">{_escape_html(label)}{tip_html}</div>'
            f'<div class="meta-value">{_escape_html(str(value))}</div>'
            f"{detail_html}"
            "</div>"
        )

    dep_module_count = _as_int(dependencies_map.get("modules"))
    dep_edge_count = _as_int(dependencies_map.get("edges"))
    dependency_max_depth = _as_int(dependencies_map.get("max_depth"))
    dependency_cycle_count = len(dep_cycles)
    dep_avg = (
        f"{dep_edge_count / dep_module_count:.1f} avg/module"
        if dep_module_count > 0
        else ""
    )
    dependency_cards = [
        _dep_stat_card("Modules", dep_module_count, detail=f"{dep_edge_count} imports"),
        _dep_stat_card("Edges", dep_edge_count, detail=dep_avg),
        _dep_stat_card(
            "Max depth",
            dependency_max_depth,
            detail="target: < 8",
            tone="warn" if dependency_max_depth > 8 else "ok",
        ),
        _dep_stat_card(
            "Cycles",
            dependency_cycle_count,
            detail=(
                f"{len(_cycle_node_set)} modules involved"
                if dependency_cycle_count > 0
                else "No circular imports"
            ),
            tone="risk" if dependency_cycle_count > 0 else "ok",
        ),
    ]

    def _render_dependency_svg(edges: Sequence[tuple[str, str]]) -> str:
        import math as _math

        if not edges:
            return _tab_empty("Dependency graph is not available.")

        unique_nodes = sorted({part for edge in edges for part in edge})
        nodes = unique_nodes[:30]
        node_set = set(nodes)
        filtered_edges = [(s, t) for s, t in edges if s in node_set and t in node_set][
            :120
        ]

        in_deg: dict[str, int] = dict.fromkeys(nodes, 0)
        out_deg: dict[str, int] = dict.fromkeys(nodes, 0)
        for s, t in filtered_edges:
            in_deg[t] += 1
            out_deg[s] += 1

        # ---- Topological layered layout ----
        children: dict[str, list[str]] = {n: [] for n in nodes}
        for s, t in filtered_edges:
            children[s].append(t)

        layers: dict[str, int] = {}
        roots = sorted(n for n in nodes if in_deg[n] == 0)
        if not roots:
            roots = sorted(nodes, key=lambda n: -out_deg.get(n, 0))[:1]
        queue = list(roots)
        for n in queue:
            layers.setdefault(n, 0)
        while queue:
            node = queue.pop(0)
            for child in children.get(node, []):
                if child not in layers:
                    layers[child] = layers[node] + 1
                    queue.append(child)
        max_layer = max(layers.values(), default=0)
        for n in nodes:
            if n not in layers:
                layers[n] = max_layer + 1

        # Group by layer, sort within layer alphabetically
        layer_groups: dict[int, list[str]] = {}
        for n, lyr in layers.items():
            layer_groups.setdefault(lyr, []).append(n)
        for lyr in layer_groups:
            layer_groups[lyr].sort()

        num_layers = max(layer_groups.keys(), default=0) + 1

        width = 1000
        height = max(320, num_layers * 80 + 80)
        pad_x, pad_y = 80.0, 50.0

        positions: dict[str, tuple[float, float]] = {}
        node_r: dict[str, float] = {}
        for lyr_idx in range(num_layers):
            members = layer_groups.get(lyr_idx, [])
            count = len(members)
            y = pad_y + lyr_idx * ((height - 2 * pad_y) / max(1, num_layers - 1))
            for i, n in enumerate(members):
                x = pad_x + (i + 0.5) * ((width - 2 * pad_x) / max(1, count))
                positions[n] = (x, y)

        # ---- Node roles ----
        degrees = [in_deg.get(n, 0) + out_deg.get(n, 0) for n in nodes]
        degrees_sorted = sorted(degrees, reverse=True)
        hub_threshold = (
            degrees_sorted[max(0, len(degrees_sorted) // 5)] if degrees_sorted else 99
        )

        for n in nodes:
            deg = in_deg.get(n, 0) + out_deg.get(n, 0)
            if n in _cycle_node_set:
                node_r[n] = min(8.0, max(5.0, 3.5 + deg * 0.4))
            elif deg >= hub_threshold and deg > 2:
                node_r[n] = min(10.0, max(6.0, 4.0 + deg * 0.5))
            elif deg <= 1:
                node_r[n] = 3.0
            else:
                node_r[n] = min(6.0, max(3.5, 3.0 + deg * 0.3))

        # ---- SVG defs ----
        defs_svg = (
            "<defs>"
            '<marker id="dep-arrow" viewBox="0 0 10 7" refX="10" refY="3.5" '
            'markerWidth="5" markerHeight="4" orient="auto-start-reverse">'
            '<polygon points="0 0,10 3.5,0 7" fill="var(--border-strong)" '
            'fill-opacity="0.5"/></marker>'
            '<marker id="dep-arrow-cycle" viewBox="0 0 10 7" refX="10" refY="3.5" '
            'markerWidth="5" markerHeight="4" orient="auto-start-reverse">'
            '<polygon points="0 0,10 3.5,0 7" fill="var(--danger)" '
            'fill-opacity="0.7"/></marker>'
            '<filter id="glow"><feGaussianBlur stdDeviation="2.5" result="g"/>'
            '<feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/>'
            "</feMerge></filter>"
            "</defs>"
        )

        # ---- Edges ----
        cycle_edge_set = set()
        for _cyc in dep_cycles:
            parts = [str(p) for p in _as_sequence(_cyc)]
            for i in range(len(parts)):
                cycle_edge_set.add((parts[i], parts[(i + 1) % len(parts)]))

        edge_svg: list[str] = []
        for s, t in filtered_edges:
            x1, y1 = positions[s]
            x2, y2 = positions[t]
            r_s, r_t = node_r[s], node_r[t]
            dx, dy = x2 - x1, y2 - y1
            dist = _math.sqrt(dx * dx + dy * dy) or 1.0
            ux, uy = dx / dist, dy / dist
            x1a = x1 + ux * (r_s + 2)
            y1a = y1 + uy * (r_s + 2)
            x2a = x2 - ux * (r_t + 4)
            y2a = y2 - uy * (r_t + 4)
            mid_x = (x1a + x2a) / 2 - (y2a - y1a) * 0.06
            mid_y = (y1a + y2a) / 2 + (x2a - x1a) * 0.06
            is_cycle_edge = (s, t) in cycle_edge_set
            stroke = "var(--danger)" if is_cycle_edge else "var(--border-strong)"
            opacity = "0.6" if is_cycle_edge else "0.3"
            marker = "dep-arrow-cycle" if is_cycle_edge else "dep-arrow"
            edge_svg.append(
                f'<path class="dep-edge" '
                f'data-source="{_escape_attr(s)}" data-target="{_escape_attr(t)}" '
                f'd="M{x1a:.1f},{y1a:.1f} Q{mid_x:.1f},{mid_y:.1f} '
                f'{x2a:.1f},{y2a:.1f}" '
                f'fill="none" stroke="{stroke}" stroke-opacity="{opacity}" '
                f'stroke-width="1" marker-end="url(#{marker})"/>'
            )

        # ---- Nodes + Labels ----
        node_svg: list[str] = []
        label_svg: list[str] = []
        for n in nodes:
            x, y = positions[n]
            r = node_r[n]
            deg = in_deg.get(n, 0) + out_deg.get(n, 0)
            label = _short_label(n)
            is_cycle = n in _cycle_node_set
            is_hub = deg >= hub_threshold and deg > 2

            if is_cycle:
                fill = "var(--danger)"
                fill_op = "0.85"
                extra = (
                    'stroke="var(--danger)" stroke-width="1.5" stroke-dasharray="3,2"'
                )
            elif is_hub:
                fill = "var(--accent-primary)"
                fill_op = "1"
                extra = 'filter="url(#glow)"'
            elif deg <= 1:
                fill = "var(--text-muted)"
                fill_op = "0.4"
                extra = ""
            else:
                fill = "var(--accent-primary)"
                fill_op = "0.7"
                extra = ""

            node_svg.append(
                f'<circle class="dep-node" data-node="{_escape_attr(n)}" '
                f'cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                f'fill="{fill}" fill-opacity="{fill_op}" {extra}/>'
            )
            fs = "10" if is_hub else "9"
            label_svg.append(
                f'<text class="dep-label" data-node="{_escape_attr(n)}" '
                f'x="{x:.1f}" y="{y - r - 5:.1f}" '
                f'font-size="{fs}" text-anchor="middle">'
                f"<title>{_escape_html(n)}</title>"
                f"{_escape_html(label)}</text>"
            )

        return (
            '<div class="dep-graph-wrap">'
            f'<svg viewBox="0 0 {width} {height}" '
            'class="dep-graph-svg" role="img" '
            'aria-label="Module dependency graph">'
            f"{defs_svg}"
            f"{''.join(edge_svg)}"
            f"{''.join(node_svg)}"
            f"{''.join(label_svg)}"
            "</svg></div>"
        )

    dependency_graph_svg = _render_dependency_svg(dep_edges)

    def _dependencies_answer_and_tone() -> tuple[str, _Tone]:
        if not metrics_available:
            return "Metrics are skipped for this run.", "info"
        answer = (
            f"Cycles: {dependency_cycle_count}; "
            f"max dependency depth: {dependency_max_depth}."
        )
        if dependency_cycle_count > 0:
            return answer, "risk"
        if dependency_max_depth > 8:
            return answer, "warn"
        return answer, "ok"

    dependencies_answer, dependencies_tone = _dependencies_answer_and_tone()

    # ---- Top hubs bar ----
    dep_degrees = dict.fromkeys(
        sorted({part for edge in dep_edges for part in edge}),
        0,
    )
    for source, target in dep_edges:
        dep_degrees[source] += 1
        dep_degrees[target] += 1
    _dep_all_nodes = sorted(
        dep_degrees,
        key=lambda node: (-dep_degrees[node], node),
    )[:5]
    _dep_hub_pills = "".join(
        f'<span class="dep-hub-pill">'
        f'<span class="dep-hub-name">{_escape_html(_short_label(n))}</span>'
        f'<span class="dep-hub-deg">'
        f"{dep_degrees[n]}"
        f"</span></span>"
        for n in _dep_all_nodes
    )
    dep_hub_bar = (
        '<div class="dep-hub-bar">'
        f'<span class="dep-hub-label">Top connected</span>{_dep_hub_pills}'
        "</div>"
        if _dep_all_nodes
        else ""
    )

    # ---- Legend ----
    dep_legend = (
        '<div class="dep-legend">'
        '<span class="dep-legend-item">'
        '<svg width="12" height="12"><circle cx="6" cy="6" r="5" '
        'fill="var(--accent-primary)"/></svg> Hub</span>'
        '<span class="dep-legend-item">'
        '<svg width="12" height="12"><circle cx="6" cy="6" r="3" '
        'fill="var(--text-muted)" fill-opacity="0.4"/></svg> Leaf</span>'
        '<span class="dep-legend-item">'
        '<svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="none" '
        'stroke="var(--danger)" stroke-width="1.5" stroke-dasharray="3,2"/>'
        "</svg> Cycle</span></div>"
    )

    dependencies_panel = (
        _insight_block(
            question="Do module dependencies form cycles?",
            answer=dependencies_answer,
            tone=dependencies_tone,
        )
        + f'<div class="dep-stats">{"".join(dependency_cards)}</div>'
        + dep_hub_bar
        + dependency_graph_svg
        + dep_legend
        + '<h3 class="subsection-title">Longest chains</h3>'
        + _render_rows_table(
            headers=("Longest chain", "Length"),
            rows=dep_chain_rows,
            empty_message="No dependency chains detected.",
            raw_html_headers=("Longest chain",),
        )
        + '<h3 class="subsection-title">Detected cycles</h3>'
        + _render_rows_table(
            headers=("Cycle",),
            rows=dep_cycle_rows,
            empty_message="No dependency cycles detected.",
            raw_html_headers=("Cycle",),
        )
    )

    def _dead_code_answer_and_tone() -> tuple[str, _Tone]:
        if not metrics_available:
            return "Metrics are skipped for this run.", "info"
        answer = (
            f"{dead_total} candidates total; "
            f"{dead_high_confidence} high-confidence items."
        )
        if dead_high_confidence > 0:
            return answer, "risk"
        if dead_total > 0:
            return answer, "warn"
        return answer, "ok"

    dead_code_answer, dead_code_tone = _dead_code_answer_and_tone()

    dead_code_panel = _insight_block(
        question="Do we have actionable unused code?",
        answer=dead_code_answer,
        tone=dead_code_tone,
    ) + _render_rows_table(
        headers=("Name", "File", "Line", "Kind", "Confidence"),
        rows=dead_rows,
        empty_message="No dead code detected.",
    )

    def _suggestion_locations_html(suggestion: Suggestion) -> str:
        if not suggestion.representative_locations:
            return '<div class="suggestion-empty">No representative locations.</div>'
        example_count = len(suggestion.representative_locations)
        items_html = "".join(
            "<li>"
            f'<span class="suggestion-location-path">'
            f"{_escape_html(location.relative_path)}"
            f":{location.start_line}-{location.end_line}</span>"
            f'<span class="suggestion-location-qualname">'
            f"{_escape_html(_bare_qualname(location.qualname, location.filepath))}"
            "</span>"
            "</li>"
            for location in suggestion.representative_locations
        )
        return (
            '<details class="suggestion-disclosure suggestion-location-details">'
            "<summary>"
            "<span>Example locations</span>"
            f'<span class="suggestion-disclosure-count">{example_count}</span>'
            "</summary>"
            f'<ul class="suggestion-location-list">{items_html}</ul>'
            "</details>"
        )

    def _render_suggestion_card(suggestion: Suggestion) -> str:
        actionable = "true" if suggestion.severity != "info" else "false"
        spread_bucket = (
            "high"
            if suggestion.spread_files > 1 or suggestion.spread_functions > 1
            else "low"
        )
        source_breakdown_text = _format_source_breakdown(suggestion.source_breakdown)
        facts_title = _escape_html(suggestion.fact_kind or suggestion.category)
        facts_summary = _escape_html(suggestion.fact_summary)
        facts_spread = (
            f"{suggestion.spread_functions} functions / {suggestion.spread_files} files"
        )
        facts_source = _escape_html(
            source_breakdown_text or _source_kind_label(suggestion.source_kind)
        )
        facts_location = _escape_html(suggestion.location_label or suggestion.location)
        context_parts = [
            suggestion.severity,
            _source_kind_label(suggestion.source_kind),
            suggestion.category.replace("_", " "),
        ]
        if suggestion.clone_type:
            context_parts.append(suggestion.clone_type)
        context_text = " · ".join(part for part in context_parts if part)
        steps_html = "".join(
            f"<li>{_escape_html(step)}</li>" for step in suggestion.steps
        )
        spread_label = (
            f"spread={suggestion.spread_functions} fn / {suggestion.spread_files} files"
        )
        stats_html = _summary_chip_row(
            (
                f"count={suggestion.fact_count}",
                spread_label,
                f"confidence={suggestion.confidence}",
                f"priority={suggestion.priority:.2f}",
                f"effort={suggestion.effort}",
            ),
            css_class="suggestion-card-stats",
        )
        next_step = (
            _escape_html(suggestion.steps[0])
            if suggestion.steps
            else "No explicit refactoring steps provided."
        )
        steps_disclosure_html = (
            '<details class="suggestion-disclosure">'
            "<summary>"
            "<span>Refactoring steps</span>"
            f'<span class="suggestion-disclosure-count">{len(suggestion.steps)}</span>'
            "</summary>"
            f'<ol class="suggestion-steps">{steps_html}</ol>'
            "</details>"
            if suggestion.steps
            else ""
        )
        return (
            '<article class="suggestion-card" '
            'data-suggestion-card="true" '
            f'data-severity="{_escape_attr(suggestion.severity)}" '
            f'data-category="{_escape_attr(suggestion.category)}" '
            f'data-family="{_escape_attr(suggestion.finding_family)}" '
            f'data-source-kind="{_escape_attr(suggestion.source_kind)}" '
            f'data-clone-type="{_escape_attr(suggestion.clone_type)}" '
            f'data-actionable="{actionable}" '
            f'data-spread-bucket="{spread_bucket}" '
            f'data-count="{_escape_attr(str(suggestion.fact_count))}">'
            '<div class="suggestion-card-head">'
            f'<div class="suggestion-card-title">{_escape_html(suggestion.title)}</div>'
            f'<div class="suggestion-card-context">{_escape_html(context_text)}</div>'
            "</div>"
            f'<div class="suggestion-card-summary">{facts_summary}</div>'
            f"{stats_html}"
            '<div class="suggestion-sections">'
            '<section class="suggestion-section">'
            '<div class="suggestion-section-title">Facts</div>'
            '<dl class="suggestion-fact-list">'
            f"<div><dt>Finding</dt><dd>{facts_title}</dd></div>"
            f"<div><dt>Summary</dt><dd>{facts_summary}</dd></div>"
            f"<div><dt>Spread</dt><dd>{_escape_html(facts_spread)}</dd></div>"
            f"<div><dt>Source breakdown</dt><dd>{facts_source}</dd></div>"
            f"<div><dt>Representative scope</dt><dd>{facts_location}</dd></div>"
            "</dl>"
            "</section>"
            '<section class="suggestion-section">'
            '<div class="suggestion-section-title">Assessment</div>'
            '<dl class="suggestion-fact-list">'
            f"<div><dt>Severity</dt><dd>{_escape_html(suggestion.severity)}</dd></div>"
            f"<div><dt>Confidence</dt><dd>{_escape_html(suggestion.confidence)}</dd></div>"
            f"<div><dt>Priority</dt><dd>{_escape_html(f'{suggestion.priority:.2f}')}</dd></div>"
            f"<div><dt>Family</dt><dd>{_escape_html(suggestion.finding_family)}</dd></div>"
            "</dl>"
            "</section>"
            '<section class="suggestion-section">'
            '<div class="suggestion-section-title">Suggested action</div>'
            '<dl class="suggestion-fact-list">'
            f"<div><dt>Effort</dt><dd>{_escape_html(suggestion.effort)}</dd></div>"
            f"<div><dt>Next step</dt><dd>{next_step}</dd></div>"
            "</dl>"
            "</section>"
            "</div>"
            '<div class="suggestion-disclosures">'
            f"{_suggestion_locations_html(suggestion)}"
            f"{steps_disclosure_html}"
            "</div>"
            "</article>"
        )

    def _build_suggestions_panel() -> str:
        suggestions_critical = sum(
            1 for suggestion in suggestions_rows if suggestion.severity == "critical"
        )
        suggestions_warning = sum(
            1 for suggestion in suggestions_rows if suggestion.severity == "warning"
        )
        suggestions_info = sum(
            1 for suggestion in suggestions_rows if suggestion.severity == "info"
        )
        if not suggestions_rows:
            suggestions_intro = _insight_block(
                question="What should be prioritized next?",
                answer="No suggestions were generated for this run.",
                tone="ok",
            )
            return suggestions_intro + _tab_empty("No suggestions generated.")

        suggestions_intro = _insight_block(
            question="What should be prioritized next?",
            answer=(
                f"{len(suggestions_rows)} suggestions: "
                f"{suggestions_critical} critical, "
                f"{suggestions_warning} warning, "
                f"{suggestions_info} info."
            ),
            tone=("risk" if suggestions_critical > 0 else "warn"),
        )
        cards_html = "".join(
            _render_suggestion_card(suggestion) for suggestion in suggestions_rows
        )
        return (
            suggestions_intro
            + '<div class="toolbar" role="toolbar" aria-label="Suggestion filters">'
            '<div class="toolbar-left">'
            '<label class="muted" for="suggestions-severity">Severity:</label>'
            '<select class="select" id="suggestions-severity" '
            "data-suggestions-severity>"
            '<option value="all">All</option>'
            '<option value="critical">critical</option>'
            '<option value="warning">warning</option>'
            '<option value="info">info</option>'
            "</select>"
            '<label class="muted" for="suggestions-category">Category:</label>'
            '<select class="select" id="suggestions-category" '
            "data-suggestions-category>"
            '<option value="all">All</option>'
            '<option value="clone">clone</option>'
            '<option value="complexity">complexity</option>'
            '<option value="coupling">coupling</option>'
            '<option value="cohesion">cohesion</option>'
            '<option value="dead_code">dead_code</option>'
            '<option value="dependency">dependency</option>'
            '<option value="structural">structural</option>'
            "</select>"
            '<label class="muted" for="suggestions-family">Family:</label>'
            '<select class="select" id="suggestions-family" '
            "data-suggestions-family>"
            '<option value="all">All</option>'
            '<option value="clones">clones</option>'
            '<option value="structural">structural</option>'
            '<option value="metrics">metrics</option>'
            "</select>"
            '<label class="muted" for="suggestions-source-kind">Context:</label>'
            '<select class="select" id="suggestions-source-kind" '
            "data-suggestions-source-kind>"
            '<option value="all">All</option>'
            '<option value="production">production</option>'
            '<option value="tests">tests</option>'
            '<option value="fixtures">fixtures</option>'
            '<option value="mixed">mixed</option>'
            "</select>"
            '<label class="muted" for="suggestions-spread">Spread:</label>'
            '<select class="select" id="suggestions-spread" '
            "data-suggestions-spread>"
            '<option value="all">All</option>'
            '<option value="high">high</option>'
            '<option value="low">low</option>'
            "</select>"
            '<label class="inline-check">'
            '<input type="checkbox" data-suggestions-actionable />'
            "<span>Only actionable</span>"
            "</label>"
            "</div>"
            '<div class="toolbar-right">'
            '<span class="page-meta" data-suggestions-count>'
            f"{len(suggestions_rows)} shown"
            "</span>"
            "</div>"
            "</div>"
            '<div class="suggestions-grid" data-suggestions-body>'
            f"{cards_html}"
            "</div>"
        )

    suggestions_panel = _build_suggestions_panel()

    sf_groups = list(normalize_structural_findings(structural_findings or ()))
    sf_files: list[str] = sorted(
        {occ.file_path for group in sf_groups for occ in group.items}
    )
    structural_findings_panel = build_structural_findings_html_panel(
        sf_groups,
        sf_files,
        scan_root=scan_root_raw,
        file_cache=file_cache,
        context_lines=context_lines,
        max_snippet_lines=max_snippet_lines,
    )

    tab_defs = (
        ("overview", "Overview", overview_panel, ""),
        (
            "clones",
            "Clones",
            clones_panel_html,
            (
                '<span class="tab-count" data-main-clones-count '
                f'data-total-groups="{clone_groups_total}">{clone_groups_total}</span>'
            ),
        ),
        (
            "complexity",
            "Complexity",
            complexity_panel,
            _tab_badge(complexity_high_risk if metrics_available else 0),
        ),
        (
            "coupling",
            "Coupling",
            coupling_panel,
            _tab_badge((coupling_high_risk + cohesion_low) if metrics_available else 0),
        ),
        (
            "dependencies",
            "Dependencies",
            dependencies_panel,
            _tab_badge(dependency_cycle_count if metrics_available else 0),
        ),
        (
            "dead-code",
            "Dead Code",
            dead_code_panel,
            _tab_badge(dead_high_confidence if metrics_available else 0),
        ),
        (
            "suggestions",
            "Suggestions",
            suggestions_panel,
            _tab_badge(len(suggestions_rows)),
        ),
        (
            "structural-findings",
            "Structural Findings",
            structural_findings_panel,
            _tab_badge(len(sf_groups)),
        ),
    )
    tab_buttons_html = "".join(
        (
            f'<button class="tab-btn{" active" if idx == 0 else ""}" '
            f'data-tab="{tab_id}" role="tab" '
            f'aria-selected="{"true" if idx == 0 else "false"}">'
            f"{_escape_html(tab_label)}{tab_badge}"
            "</button>"
        )
        for idx, (tab_id, tab_label, _panel_html, tab_badge) in enumerate(tab_defs)
    )
    tab_panels_html = "".join(
        (
            f'<div class="tab-panel{" active" if idx == 0 else ""}" '
            f'data-tab-panel="{tab_id}">'
            f"{panel_html}"
            "</div>"
        )
        for idx, (tab_id, _tab_label, panel_html, _tab_badge_html) in enumerate(
            tab_defs
        )
    )
    analysis_tabs_html = (
        f'<nav class="tab-bar" role="tablist">{tab_buttons_html}</nav>{tab_panels_html}'
    )

    def _build_report_meta_panel() -> str:
        baseline_path_value = _meta_pick(
            meta.get("baseline_path"),
            baseline_meta.get("path"),
            runtime_meta.get("baseline_path_absolute"),
        )
        cache_path_value = _meta_pick(
            meta.get("cache_path"),
            cache_meta.get("path"),
            runtime_meta.get("cache_path_absolute"),
        )
        metrics_baseline_path_value = _meta_pick(
            meta.get("metrics_baseline_path"),
            metrics_baseline_meta.get("path"),
            runtime_meta.get("metrics_baseline_path_absolute"),
        )
        scan_root_value = _meta_pick(
            meta.get("scan_root"),
            runtime_meta.get("scan_root_absolute"),
        )
        python_tag_value = _meta_pick(meta.get("python_tag"))
        report_mode_value = _meta_pick(meta.get("report_mode"), "full")
        metrics_computed_value = _meta_pick(
            meta.get("metrics_computed"),
            meta.get("computed_metric_families"),
        )
        integrity_canonicalization = _as_mapping(integrity_map.get("canonicalization"))
        integrity_digest = _as_mapping(integrity_map.get("digest"))
        canonical_sections = ", ".join(
            str(item)
            for item in _as_sequence(integrity_canonicalization.get("sections"))
            if str(item).strip()
        )
        general_meta_rows: list[tuple[str, object]] = [
            ("CodeClone", _meta_pick(meta.get("codeclone_version"), __version__)),
            ("Project", _meta_pick(meta.get("project_name"))),
            ("Report schema", report_schema_version),
            ("Scan root", scan_root_value),
            ("Python", _meta_pick(meta.get("python_version"))),
            ("Python tag", python_tag_value),
            ("Analysis mode", _meta_pick(meta.get("analysis_mode"))),
            ("Report mode", report_mode_value),
            ("Report generated (UTC)", report_generated_at),
            (
                "Metrics computed",
                ", ".join(str(item) for item in _as_sequence(metrics_computed_value)),
            ),
            ("Health score", _meta_pick(meta.get("health_score"))),
            ("Health grade", _meta_pick(meta.get("health_grade"))),
            ("Source IO skipped", _meta_pick(meta.get("files_skipped_source_io"))),
        ]
        clone_baseline_rows: list[tuple[str, object]] = [
            ("Baseline file", _path_basename(baseline_path_value)),
            ("Baseline path", baseline_path_value),
            (
                "Baseline status",
                _meta_pick(meta.get("baseline_status"), baseline_meta.get("status")),
            ),
            (
                "Baseline loaded",
                _meta_pick(meta.get("baseline_loaded"), baseline_meta.get("loaded")),
            ),
            (
                "Baseline fingerprint",
                _meta_pick(
                    meta.get("baseline_fingerprint_version"),
                    baseline_meta.get("fingerprint_version"),
                ),
            ),
            (
                "Baseline schema",
                _meta_pick(
                    meta.get("baseline_schema_version"),
                    baseline_meta.get("schema_version"),
                ),
            ),
            (
                "Baseline Python tag",
                _meta_pick(
                    meta.get("baseline_python_tag"),
                    baseline_meta.get("python_tag"),
                ),
            ),
            (
                "Baseline generator name",
                _meta_pick(
                    meta.get("baseline_generator_name"),
                    baseline_meta.get("generator_name"),
                ),
            ),
            (
                "Baseline generator version",
                _meta_pick(
                    meta.get("baseline_generator_version"),
                    baseline_meta.get("generator_version"),
                ),
            ),
            (
                "Baseline payload sha256",
                _meta_pick(
                    meta.get("baseline_payload_sha256"),
                    baseline_meta.get("payload_sha256"),
                ),
            ),
            (
                "Baseline payload verified",
                _meta_pick(
                    meta.get("baseline_payload_sha256_verified"),
                    baseline_meta.get("payload_sha256_verified"),
                ),
            ),
        ]
        metrics_baseline_rows: list[tuple[str, object]] = [
            ("Metrics baseline path", metrics_baseline_path_value),
            (
                "Metrics baseline loaded",
                _meta_pick(
                    meta.get("metrics_baseline_loaded"),
                    metrics_baseline_meta.get("loaded"),
                ),
            ),
            (
                "Metrics baseline status",
                _meta_pick(
                    meta.get("metrics_baseline_status"),
                    metrics_baseline_meta.get("status"),
                ),
            ),
            (
                "Metrics baseline schema",
                _meta_pick(
                    meta.get("metrics_baseline_schema_version"),
                    metrics_baseline_meta.get("schema_version"),
                ),
            ),
            (
                "Metrics baseline payload sha256",
                _meta_pick(
                    meta.get("metrics_baseline_payload_sha256"),
                    metrics_baseline_meta.get("payload_sha256"),
                ),
            ),
            (
                "Metrics baseline payload verified",
                _meta_pick(
                    meta.get("metrics_baseline_payload_sha256_verified"),
                    metrics_baseline_meta.get("payload_sha256_verified"),
                ),
            ),
        ]
        cache_rows: list[tuple[str, object]] = [
            ("Cache path", cache_path_value),
            (
                "Cache schema",
                _meta_pick(
                    meta.get("cache_schema_version"),
                    cache_meta.get("schema_version"),
                ),
            ),
            (
                "Cache status",
                _meta_pick(meta.get("cache_status"), cache_meta.get("status")),
            ),
            ("Cache used", _meta_pick(meta.get("cache_used"), cache_meta.get("used"))),
        ]
        runtime_rows = [
            row
            for row in (
                ("Scan root absolute", runtime_meta.get("scan_root_absolute")),
                ("Baseline path absolute", runtime_meta.get("baseline_path_absolute")),
                ("Cache path absolute", runtime_meta.get("cache_path_absolute")),
                (
                    "Metrics baseline path absolute",
                    runtime_meta.get("metrics_baseline_path_absolute"),
                ),
            )
            if _meta_pick(row[1]) is not None
        ]
        integrity_rows = [
            row
            for row in (
                ("Canonicalization version", integrity_canonicalization.get("version")),
                ("Canonicalization scope", integrity_canonicalization.get("scope")),
                ("Canonical sections", canonical_sections),
                ("Digest algorithm", integrity_digest.get("algorithm")),
                ("Digest value", integrity_digest.get("value")),
                ("Digest verified", integrity_digest.get("verified")),
            )
            if _meta_pick(row[1]) is not None
        ]

        meta_sections = [
            ("General", general_meta_rows),
            ("Clone Baseline", clone_baseline_rows),
            ("Metrics Baseline", metrics_baseline_rows),
            ("Cache", cache_rows),
            ("Runtime", runtime_rows),
            ("Integrity", integrity_rows),
        ]
        metrics_computed_csv = ",".join(
            str(item) for item in _as_sequence(metrics_computed_value)
        )
        baseline_fingerprint_version = _meta_pick(
            meta.get("baseline_fingerprint_version"),
            baseline_meta.get("fingerprint_version"),
        )
        baseline_schema_version = _meta_pick(
            meta.get("baseline_schema_version"),
            baseline_meta.get("schema_version"),
        )
        baseline_python_tag = _meta_pick(
            meta.get("baseline_python_tag"),
            baseline_meta.get("python_tag"),
        )
        baseline_generator_name = _meta_pick(
            meta.get("baseline_generator_name"),
            baseline_meta.get("generator_name"),
        )
        baseline_generator_version = _meta_pick(
            meta.get("baseline_generator_version"),
            baseline_meta.get("generator_version"),
        )
        baseline_payload_sha256 = _meta_pick(
            meta.get("baseline_payload_sha256"),
            baseline_meta.get("payload_sha256"),
        )
        baseline_payload_verified = _meta_display(
            _meta_pick(
                meta.get("baseline_payload_sha256_verified"),
                baseline_meta.get("payload_sha256_verified"),
            )
        )
        baseline_loaded = _meta_display(
            _meta_pick(meta.get("baseline_loaded"), baseline_meta.get("loaded"))
        )
        baseline_status = _meta_pick(
            meta.get("baseline_status"),
            baseline_meta.get("status"),
        )
        cache_schema_version = _meta_pick(
            meta.get("cache_schema_version"),
            cache_meta.get("schema_version"),
        )
        cache_status = _meta_pick(meta.get("cache_status"), cache_meta.get("status"))
        cache_used = _meta_display(
            _meta_pick(meta.get("cache_used"), cache_meta.get("used"))
        )
        metrics_baseline_loaded = _meta_display(
            _meta_pick(
                meta.get("metrics_baseline_loaded"),
                metrics_baseline_meta.get("loaded"),
            )
        )
        metrics_baseline_status = _meta_pick(
            meta.get("metrics_baseline_status"),
            metrics_baseline_meta.get("status"),
        )
        metrics_baseline_schema_version = _meta_pick(
            meta.get("metrics_baseline_schema_version"),
            metrics_baseline_meta.get("schema_version"),
        )
        metrics_baseline_payload_sha256 = _meta_pick(
            meta.get("metrics_baseline_payload_sha256"),
            metrics_baseline_meta.get("payload_sha256"),
        )
        metrics_baseline_payload_verified = _meta_display(
            _meta_pick(
                meta.get("metrics_baseline_payload_sha256_verified"),
                metrics_baseline_meta.get("payload_sha256_verified"),
            )
        )

        meta_attrs = " ".join(
            [
                (f'data-report-schema-version="{_escape_attr(report_schema_version)}"'),
                (
                    'data-codeclone-version="'
                    f'{_escape_attr(meta.get("codeclone_version", __version__))}"'
                ),
                f'data-project-name="{_escape_attr(meta.get("project_name"))}"',
                f'data-scan-root="{_escape_attr(scan_root_value)}"',
                f'data-python-version="{_escape_attr(meta.get("python_version"))}"',
                f'data-python-tag="{_escape_attr(python_tag_value)}"',
                f'data-analysis-mode="{_escape_attr(meta.get("analysis_mode"))}"',
                f'data-report-mode="{_escape_attr(report_mode_value)}"',
                (f'data-report-generated-at-utc="{_escape_attr(report_generated_at)}"'),
                (f'data-metrics-computed="{_escape_attr(metrics_computed_csv)}"'),
                f'data-health-score="{_escape_attr(meta.get("health_score"))}"',
                f'data-health-grade="{_escape_attr(meta.get("health_grade"))}"',
                f'data-baseline-file="{_escape_attr(_path_basename(baseline_path_value))}"',
                f'data-baseline-path="{_escape_attr(baseline_path_value)}"',
                (
                    'data-baseline-fingerprint-version="'
                    f'{_escape_attr(baseline_fingerprint_version)}"'
                ),
                (
                    'data-baseline-schema-version="'
                    f'{_escape_attr(baseline_schema_version)}"'
                ),
                (f'data-baseline-python-tag="{_escape_attr(baseline_python_tag)}"'),
                (
                    'data-baseline-generator-name="'
                    f'{_escape_attr(baseline_generator_name)}"'
                ),
                (
                    'data-baseline-generator-version="'
                    f'{_escape_attr(baseline_generator_version)}"'
                ),
                (
                    'data-baseline-payload-sha256="'
                    f'{_escape_attr(baseline_payload_sha256)}"'
                ),
                (
                    'data-baseline-payload-verified="'
                    f'{_escape_attr(baseline_payload_verified)}"'
                ),
                f'data-baseline-loaded="{_escape_attr(baseline_loaded)}"',
                f'data-baseline-status="{_escape_attr(baseline_status)}"',
                f'data-cache-path="{_escape_attr(cache_path_value)}"',
                (f'data-cache-schema-version="{_escape_attr(cache_schema_version)}"'),
                f'data-cache-status="{_escape_attr(cache_status)}"',
                f'data-cache-used="{_escape_attr(cache_used)}"',
                (
                    'data-files-skipped-source-io="'
                    f'{_escape_attr(meta.get("files_skipped_source_io"))}"'
                ),
                (
                    'data-metrics-baseline-path="'
                    f'{_escape_attr(metrics_baseline_path_value)}"'
                ),
                (
                    'data-metrics-baseline-loaded="'
                    f'{_escape_attr(metrics_baseline_loaded)}"'
                ),
                (
                    'data-metrics-baseline-status="'
                    f'{_escape_attr(metrics_baseline_status)}"'
                ),
                (
                    'data-metrics-baseline-schema-version="'
                    f'{_escape_attr(metrics_baseline_schema_version)}"'
                ),
                (
                    'data-metrics-baseline-payload-sha256="'
                    f'{_escape_attr(metrics_baseline_payload_sha256)}"'
                ),
                (
                    'data-metrics-baseline-payload-verified="'
                    f'{_escape_attr(metrics_baseline_payload_verified)}"'
                ),
                (
                    'data-runtime-scan-root-absolute="'
                    f'{_escape_attr(runtime_meta.get("scan_root_absolute"))}"'
                ),
                (
                    'data-runtime-baseline-path-absolute="'
                    f'{_escape_attr(runtime_meta.get("baseline_path_absolute"))}"'
                ),
                (
                    'data-runtime-cache-path-absolute="'
                    f'{_escape_attr(runtime_meta.get("cache_path_absolute"))}"'
                ),
                (
                    'data-runtime-metrics-baseline-path-absolute="'
                    f'{_escape_attr(runtime_meta.get("metrics_baseline_path_absolute"))}"'
                ),
                (
                    'data-canonicalization-version="'
                    f'{_escape_attr(integrity_canonicalization.get("version"))}"'
                ),
                (
                    'data-canonicalization-scope="'
                    f'{_escape_attr(integrity_canonicalization.get("scope"))}"'
                ),
                (f'data-canonical-sections="{_escape_attr(canonical_sections)}"'),
                (
                    'data-digest-algorithm="'
                    f'{_escape_attr(integrity_digest.get("algorithm"))}"'
                ),
                (f'data-digest-value="{_escape_attr(integrity_digest.get("value"))}"'),
                (
                    'data-digest-verified="'
                    f'{_escape_attr(_meta_display(integrity_digest.get("verified")))}"'
                ),
            ]
        )

        def _meta_item_class(label: str) -> str:
            cls = ["meta-item"]
            if label in {
                "Baseline path",
                "Cache path",
                "Baseline payload sha256",
                "Metrics baseline payload sha256",
                "Metrics baseline path",
                "Scan root absolute",
                "Baseline path absolute",
                "Cache path absolute",
                "Metrics baseline path absolute",
                "Canonical sections",
                "Digest value",
            }:
                cls.append("meta-item-wide")
            if label in {
                "Baseline payload verified",
                "Baseline loaded",
                "Cache used",
                "Metrics baseline loaded",
                "Metrics baseline payload verified",
                "Digest verified",
            }:
                cls.append("meta-item-boolean")
            return " ".join(cls)

        def _meta_value_html(label: str, value: object) -> str:
            if label in {
                "Baseline payload verified",
                "Baseline loaded",
                "Cache used",
                "Metrics baseline loaded",
                "Metrics baseline payload verified",
                "Digest verified",
            } and isinstance(value, bool):
                badge_cls = "meta-bool-true" if value else "meta-bool-false"
                text = "true" if value else "false"
                return f'<span class="meta-bool {badge_cls}">{text}</span>'
            return _escape_html(_meta_display(value))

        meta_rows_html = "".join(
            (
                '<section class="meta-section">'
                f'<h3 class="meta-section-title">{_escape_html(section_title)}</h3>'
                '<div class="meta-grid">'
                + "".join(
                    (
                        f'<div class="{_meta_item_class(label)}">'
                        f'<div class="meta-label">{_escape_html(label)}'
                        f"{_glossary_tip(label)}</div>"
                        '<div class="meta-value">'
                        f"{_meta_value_html(label, value)}"
                        "</div>"
                        "</div>"
                    )
                    for label, value in section_rows
                )
                + "</div>"
                "</section>"
            )
            for section_title, section_rows in meta_sections
            if section_rows
        )

        chevron_icon = (
            '<svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M19 9l-7 7-7-7"/>'
            "</svg>"
        )

        def _prov_badge(label: str, color: str) -> str:
            return f'<span class="prov-badge {color}">{_escape_html(label)}</span>'

        prov_badges: list[str] = []
        bl_verified = _meta_pick(
            meta.get("baseline_payload_sha256_verified"),
            baseline_meta.get("payload_sha256_verified"),
        )
        bl_loaded = _meta_pick(meta.get("baseline_loaded"), baseline_meta.get("loaded"))
        if bl_verified is True:
            prov_badges.append(_prov_badge("Baseline verified", "green"))
        elif bl_loaded is True and bl_verified is not True:
            prov_badges.append(_prov_badge("Baseline untrusted", "red"))
        elif bl_loaded is False or bl_loaded is None:
            prov_badges.append(_prov_badge("Baseline missing", "amber"))

        schema_ver = report_schema_version
        if schema_ver:
            prov_badges.append(_prov_badge(f"Schema {schema_ver}", "neutral"))

        fp_ver = _meta_pick(
            meta.get("baseline_fingerprint_version"),
            baseline_meta.get("fingerprint_version"),
        )
        if fp_ver is not None:
            prov_badges.append(_prov_badge(f"Fingerprint {fp_ver}", "neutral"))

        gen_name = str(
            _meta_pick(
                meta.get("baseline_generator_name"),
                baseline_meta.get("generator_name"),
            )
            or ""
        )
        if gen_name and gen_name != "codeclone":
            prov_badges.append(_prov_badge(f"Generator mismatch: {gen_name}", "red"))

        cache_used_value = _meta_pick(meta.get("cache_used"), cache_meta.get("used"))
        if cache_used_value is True:
            prov_badges.append(_prov_badge("Cache hit", "green"))
        elif cache_used_value is False:
            prov_badges.append(_prov_badge("Cache miss", "amber"))
        else:
            prov_badges.append(_prov_badge("Cache N/A", "neutral"))

        analysis_mode = str(_meta_pick(meta.get("analysis_mode")) or "")
        if analysis_mode:
            prov_badges.append(_prov_badge(f"Mode: {analysis_mode}", "neutral"))

        mbl_loaded = _meta_pick(
            meta.get("metrics_baseline_loaded"),
            metrics_baseline_meta.get("loaded"),
        )
        mbl_verified = _meta_pick(
            meta.get("metrics_baseline_payload_sha256_verified"),
            metrics_baseline_meta.get("payload_sha256_verified"),
        )
        if mbl_verified is True:
            prov_badges.append(_prov_badge("Metrics baseline verified", "green"))
        elif mbl_loaded is True and mbl_verified is not True:
            prov_badges.append(_prov_badge("Metrics baseline untrusted", "red"))

        sep = '<span class="prov-sep">·</span>'
        prov_summary_html = (
            '<div class="prov-summary">'
            + sep.join(prov_badges)
            + '<span class="prov-explain">'
            "Baseline-aware · contract-verified"
            "</span>"
            "</div>"
            if prov_badges
            else ""
        )

        return (
            f'<div class="meta-panel" id="report-meta" {meta_attrs}>'
            '<div class="meta-header">'
            '<div class="meta-title">'
            "Report Provenance"
            '<span class="meta-hint">expand for details</span>'
            "</div>"
            f'<div class="meta-toggle collapsed">{chevron_icon}</div>'
            "</div>"
            f"{prov_summary_html}"
            '<div class="meta-content collapsed">'
            f'<div class="meta-sections">{meta_rows_html}</div>'
            "</div>"
            "</div>"
        )

    report_meta_html = _build_report_meta_panel()

    return REPORT_TEMPLATE.substitute(
        title=_escape_html(title),
        version=__version__,
        brand_project_html=brand_project_html,
        brand_meta=_escape_html(brand_meta),
        pyg_dark=pyg_dark,
        pyg_light=pyg_light,
        global_novelty_html=global_novelty_html,
        report_meta_html=report_meta_html,
        empty_state_html=empty_state_html,
        func_section=func_section,
        block_section=block_section,
        segment_section=segment_section,
        analysis_tabs_html=analysis_tabs_html,
        icon_theme=ICONS["theme"],
        font_css_url=FONT_CSS_URL,
        repository_url=_escape_attr(REPOSITORY_URL),
        issues_url=_escape_attr(ISSUES_URL),
        docs_url=_escape_attr(DOCS_URL),
    )
