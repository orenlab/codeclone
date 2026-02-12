"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from . import __version__
from ._html_escape import _escape_attr, _escape_html, _meta_display
from ._html_snippets import (
    _FileCache,
    _prefix_css,
    _pygments_css,
    _render_code_block,
    _try_pygments,
    pairwise,
)
from ._report_explain_contract import format_group_instance_compare_meta
from ._report_types import GroupItem, GroupMap
from .contracts import DOCS_URL, ISSUES_URL, REPOSITORY_URL
from .templates import FONT_CSS_URL, REPORT_TEMPLATE

__all__ = [
    "_FileCache",
    "_prefix_css",
    "_pygments_css",
    "_render_code_block",
    "_try_pygments",
    "build_html_report",
    "pairwise",
]

# ============================
# HTML report builder
# ============================


def _group_sort_key(items: list[GroupItem]) -> tuple[int]:
    return (-len(items),)


def build_html_report(
    *,
    func_groups: GroupMap,
    block_groups: GroupMap,
    segment_groups: GroupMap,
    block_group_facts: dict[str, dict[str, str]],
    new_function_group_keys: Collection[str] | None = None,
    new_block_group_keys: Collection[str] | None = None,
    report_meta: Mapping[str, object] | None = None,
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
        groups: list[tuple[str, list[GroupItem]]],
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

        def _item_span_size(item: GroupItem) -> int:
            start_line = int(item.get("start_line", 0))
            end_line = int(item.get("end_line", 0))
            return max(0, end_line - start_line + 1)

        def _group_span_size(items: list[GroupItem]) -> int:
            return max((_item_span_size(item) for item in items), default=0)

        section_novelty = novelty_by_group or {}
        has_novelty_filter = bool(section_novelty)

        out: list[str] = [
            f'<section id="{section_id}" class="section" data-section="{section_id}" '
            f'data-has-novelty-filter="{"true" if has_novelty_filter else "false"}">',
            '<div class="section-title">',
            f"<h2>{_escape_html(section_title)} "
            f'<span class="count-pill" data-count-pill="{section_id}">'
            f"{len(groups)} groups</span></h2>",
            "</div>",
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
                snippet = _render_code_block(
                    filepath=item["filepath"],
                    start_line=int(item["start_line"]),
                    end_line=int(item["end_line"]),
                    file_cache=file_cache,
                    context=context_lines,
                    max_lines=max_snippet_lines,
                )
                qualname = _escape_html(item["qualname"])
                qualname_attr = _escape_attr(item["qualname"])
                filepath = _escape_html(item["filepath"])
                filepath_attr = _escape_attr(item["filepath"])
                start_line = int(item["start_line"])
                end_line = int(item["end_line"])
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

    empty_state_html = ""
    if not has_any:
        empty_state_html = f"""
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
    function_novelty = {
        group_key: ("new" if group_key in new_function_key_set else "known")
        for group_key, _ in func_sorted
    }
    block_novelty = {
        group_key: ("new" if group_key in new_block_key_set else "known")
        for group_key, _ in block_sorted
    }
    novelty_enabled = bool(function_novelty) or bool(block_novelty)
    total_new_groups = sum(1 for value in function_novelty.values() if value == "new")
    total_new_groups += sum(1 for value in block_novelty.values() if value == "new")
    total_known_groups = sum(
        1 for value in function_novelty.values() if value == "known"
    )
    total_known_groups += sum(1 for value in block_novelty.values() if value == "known")
    default_novelty = "new" if total_new_groups > 0 else "known"
    global_novelty_html = ""
    if novelty_enabled:
        global_novelty_html = (
            '<section class="global-novelty" id="global-novelty-controls" '
            f'data-default-novelty="{default_novelty}">'
            '<div class="global-novelty-head">'
            "<h2>Duplicate Scope</h2>"
            '<div class="novelty-tabs" role="tablist" '
            'aria-label="Baseline split filter">'
            '<button class="btn novelty-tab" type="button" '
            'data-global-novelty="new">'
            "New duplicates "
            f'<span class="novelty-count">{total_new_groups}</span>'
            "</button>"
            '<button class="btn novelty-tab" type="button" '
            'data-global-novelty="known">'
            "Known duplicates "
            f'<span class="novelty-count">{total_known_groups}</span>'
            "</button>"
            "</div>"
            "</div>"
            f'<p class="novelty-note">{_escape_html(baseline_split_note)}</p>'
            "</section>"
        )

    func_section = render_section(
        "functions",
        "Function clones",
        func_sorted,
        "pill-func",
        novelty_by_group=function_novelty,
    )
    block_section = render_section(
        "blocks",
        "Block clones",
        block_sorted,
        "pill-block",
        novelty_by_group=block_novelty,
    )
    segment_section = render_section(
        "segments", "Segment clones", segment_sorted, "pill-segment"
    )
    baseline_path_value = meta.get("baseline_path")
    meta_rows: list[tuple[str, object]] = [
        ("Report schema", meta.get("report_schema_version")),
        ("CodeClone", meta.get("codeclone_version", __version__)),
        ("Python", meta.get("python_version")),
        ("Baseline file", _path_basename(baseline_path_value)),
        ("Baseline fingerprint", meta.get("baseline_fingerprint_version")),
        ("Baseline schema", meta.get("baseline_schema_version")),
        ("Baseline Python tag", meta.get("baseline_python_tag")),
        ("Baseline generator name", meta.get("baseline_generator_name")),
        ("Baseline generator version", meta.get("baseline_generator_version")),
        ("Baseline payload sha256", meta.get("baseline_payload_sha256")),
        (
            "Baseline payload verified",
            meta.get("baseline_payload_sha256_verified"),
        ),
        ("Baseline loaded", meta.get("baseline_loaded")),
        ("Baseline status", meta.get("baseline_status")),
        ("Source IO skipped", meta.get("files_skipped_source_io")),
        ("Baseline path", baseline_path_value),
    ]
    if "cache_path" in meta:
        meta_rows.append(("Cache path", meta.get("cache_path")))
    if "cache_schema_version" in meta:
        meta_rows.append(("Cache schema", meta.get("cache_schema_version")))
    if "cache_status" in meta:
        meta_rows.append(("Cache status", meta.get("cache_status")))
    if "cache_used" in meta:
        meta_rows.append(("Cache used", meta.get("cache_used")))

    meta_attrs = " ".join(
        [
            (
                'data-report-schema-version="'
                f'{_escape_attr(meta.get("report_schema_version"))}"'
            ),
            (
                'data-codeclone-version="'
                f'{_escape_attr(meta.get("codeclone_version", __version__))}"'
            ),
            f'data-python-version="{_escape_attr(meta.get("python_version"))}"',
            f'data-baseline-file="{_escape_attr(_path_basename(baseline_path_value))}"',
            f'data-baseline-path="{_escape_attr(baseline_path_value)}"',
            (
                'data-baseline-fingerprint-version="'
                f'{_escape_attr(meta.get("baseline_fingerprint_version"))}"'
            ),
            f'data-baseline-schema-version="{_escape_attr(meta.get("baseline_schema_version"))}"',
            (
                'data-baseline-python-tag="'
                f'{_escape_attr(meta.get("baseline_python_tag"))}"'
            ),
            (
                'data-baseline-generator-name="'
                f'{_escape_attr(meta.get("baseline_generator_name"))}"'
            ),
            (
                'data-baseline-generator-version="'
                f'{_escape_attr(meta.get("baseline_generator_version"))}"'
            ),
            (
                'data-baseline-payload-sha256="'
                f'{_escape_attr(meta.get("baseline_payload_sha256"))}"'
            ),
            (
                'data-baseline-payload-verified="'
                f'{_escape_attr(_meta_display(meta.get("baseline_payload_sha256_verified")))}"'
            ),
            f'data-baseline-loaded="{_escape_attr(_meta_display(meta.get("baseline_loaded")))}"',
            f'data-baseline-status="{_escape_attr(meta.get("baseline_status"))}"',
            f'data-cache-path="{_escape_attr(meta.get("cache_path"))}"',
            (
                'data-cache-schema-version="'
                f'{_escape_attr(meta.get("cache_schema_version"))}"'
            ),
            f'data-cache-status="{_escape_attr(meta.get("cache_status"))}"',
            f'data-cache-used="{_escape_attr(_meta_display(meta.get("cache_used")))}"',
            (
                'data-files-skipped-source-io="'
                f'{_escape_attr(meta.get("files_skipped_source_io"))}"'
            ),
        ]
    )

    def _meta_item_class(label: str) -> str:
        cls = ["meta-item"]
        if label in {"Baseline path", "Cache path", "Baseline payload sha256"}:
            cls.append("meta-item-wide")
        if label in {
            "Baseline payload verified",
            "Baseline loaded",
            "Cache used",
        }:
            cls.append("meta-item-boolean")
        return " ".join(cls)

    def _meta_value_html(label: str, value: object) -> str:
        if label in {
            "Baseline payload verified",
            "Baseline loaded",
            "Cache used",
        } and isinstance(value, bool):
            badge_cls = "meta-bool-true" if value else "meta-bool-false"
            text = "true" if value else "false"
            return f'<span class="meta-bool {badge_cls}">{text}</span>'
        return _escape_html(_meta_display(value))

    meta_rows_html = "".join(
        (
            f'<div class="{_meta_item_class(label)}">'
            f'<div class="meta-label">{_escape_html(label)}</div>'
            f'<div class="meta-value">{_meta_value_html(label, value)}</div>'
            "</div>"
        )
        for label, value in meta_rows
    )

    # Chevron icon for toggle
    chevron_icon = (
        '<svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        'd="M19 9l-7 7-7-7"/>'
        "</svg>"
    )

    report_meta_html = (
        f'<div class="meta-panel" id="report-meta" {meta_attrs}>'
        '<div class="meta-header">'
        '<div class="meta-title">'
        f"{chevron_icon}"
        "Report Provenance"
        "</div>"
        '<div class="meta-toggle collapsed">▸</div>'
        "</div>"
        '<div class="meta-content collapsed">'
        f'<div class="meta-grid">{meta_rows_html}</div>'
        "</div>"
        "</div>"
    )

    return REPORT_TEMPLATE.substitute(
        title=_escape_html(title),
        version=__version__,
        pyg_dark=pyg_dark,
        pyg_light=pyg_light,
        global_novelty_html=global_novelty_html,
        report_meta_html=report_meta_html,
        empty_state_html=empty_state_html,
        func_section=func_section,
        block_section=block_section,
        segment_section=segment_section,
        icon_theme=ICONS["theme"],
        font_css_url=FONT_CSS_URL,
        repository_url=_escape_attr(REPOSITORY_URL),
        issues_url=_escape_attr(ISSUES_URL),
        docs_url=_escape_attr(DOCS_URL),
    )
