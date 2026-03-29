# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Clones panel renderer — function/block/segment sections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Literal

from ... import _coerce
from ..._html_badges import _source_kind_badge_html
from ..._html_data_attrs import _build_data_attrs
from ..._html_escape import _escape_attr, _escape_html
from ..._html_filters import CLONE_TYPE_OPTIONS, SPREAD_OPTIONS, _render_select
from ..._html_snippets import _render_code_block
from ...report._source_kinds import SOURCE_KIND_FILTER_VALUES
from ...report.derived import (
    combine_source_kinds,
    group_spread,
    report_location_from_group_item,
)
from ...report.explain_contract import format_group_instance_compare_meta
from ...report.json_contract import clone_group_id
from ...report.suggestions import classify_clone_type
from .._components import Tone, insight_block
from .._icons import ICONS
from .._tabs import render_split_tabs

if TYPE_CHECKING:
    from ...models import GroupItemLike
    from .._context import ReportContext

_as_int = _coerce.as_int

_HEX_SET = frozenset("0123456789abcdefABCDEF")


def _looks_like_hash(text: str) -> bool:
    """Return True if text starts with a long hex string (likely a hash key)."""
    bare = text.split("|")[0].strip()
    return len(bare) >= 16 and all(c in _HEX_SET for c in bare)


def _derive_group_display_name(
    gkey: str,
    items: Sequence[Mapping[str, object]],
    section_id: str,
    block_meta: Mapping[str, str],
    ctx: ReportContext,
) -> str:
    """Build a human-friendly group display name from items, never raw hashes."""
    # Explicit overrides from block_group_facts
    if section_id == "blocks":
        if block_meta.get("group_display_name"):
            return str(block_meta["group_display_name"])
        if block_meta.get("pattern_display"):
            return str(block_meta["pattern_display"])

    # For function clones — gkey is already qualname, use it directly
    if section_id == "functions" and not _looks_like_hash(gkey):
        return gkey

    # For any section with hash-like keys — derive from items
    if items:
        # Collect short paths from items
        short_names: list[str] = []
        for it in items[:3]:
            qn = str(it.get("qualname", ""))
            fp = str(it.get("filepath", ""))
            name = ctx.bare_qualname(qn, fp)
            if name:
                short_names.append(name)
            else:
                rel = ctx.relative_path(fp)
                if rel:
                    short_names.append(rel)
        if short_names:
            label = " \u2022 ".join(dict.fromkeys(short_names))
            if len(label) > 72:
                label = label[:68] + "\u2026"
            return label

    # Fallback: truncate key
    if len(gkey) > 56:
        return f"{gkey[:24]}\u2026{gkey[-16:]}"
    return gkey


def _render_group_explanation(meta: Mapping[str, object]) -> str:
    if not meta:
        return ""
    items: list[tuple[str, str]] = []
    if meta.get("match_rule"):
        items.append((f"match_rule: {meta['match_rule']}", "group-explain-item"))
    if meta.get("block_size"):
        items.append((f"block_size: {meta['block_size']}", "group-explain-item"))
    if meta.get("signature_kind"):
        items.append(
            (f"signature_kind: {meta['signature_kind']}", "group-explain-item")
        )
    if meta.get("merged_regions"):
        items.append(
            (f"merged_regions: {meta['merged_regions']}", "group-explain-item")
        )
    pattern_value = str(meta.get("pattern", "")).strip()
    if pattern_value:
        pattern_label = str(meta.get("pattern_label", pattern_value)).strip()
        pattern_display = str(meta.get("pattern_display", "")).strip()
        if pattern_display:
            items.append(
                (f"pattern: {pattern_label} ({pattern_display})", "group-explain-item")
            )
        else:
            items.append((f"pattern: {pattern_label}", "group-explain-item"))
    hint_id = str(meta.get("hint", "")).strip()
    if hint_id:
        hint_label = str(meta.get("hint_label", hint_id)).strip()
        items.append((f"hint: {hint_label}", "group-explain-item group-explain-warn"))
        if meta.get("hint_confidence"):
            items.append(
                (
                    f"hint_confidence: {meta['hint_confidence']}",
                    "group-explain-item group-explain-muted",
                )
            )
        if meta.get("assert_ratio"):
            items.append(
                (
                    f"assert_ratio: {meta['assert_ratio']}",
                    "group-explain-item group-explain-muted",
                )
            )
        if meta.get("consecutive_asserts"):
            items.append(
                (
                    f"consecutive_asserts: {meta['consecutive_asserts']}",
                    "group-explain-item group-explain-muted",
                )
            )
        hint_context = str(meta.get("hint_context_label", "")).strip()
        if hint_context:
            items.append((hint_context, "group-explain-item group-explain-muted"))

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
    attr_html = " ".join(f'{k}="{_escape_attr(v)}"' for k, v in attrs.items() if v)
    parts = [f'<span class="{css}">{_escape_html(text)}</span>' for text, css in items]
    note = ""
    if isinstance(meta.get("hint_note"), str):
        note = (
            f'<p class="group-explain-note">{_escape_html(str(meta["hint_note"]))}</p>'
        )
    return f'<div class="group-explain" {attr_html}>{"".join(parts)}{note}</div>'


def _render_section_toolbar(
    section_id: str,
    section_title: str,
    group_count: int,
) -> str:
    return (
        f'<div class="toolbar" role="toolbar" aria-label="{_escape_attr(section_title)} controls">'
        '<div class="toolbar-left">'
        '<div class="search-box">'
        f'<span class="search-ico">{ICONS["search"]}</span>'
        f'<input type="text" id="search-{section_id}" placeholder="Search..." autocomplete="off"/>'
        f'<button class="clear-btn" type="button" data-clear="{section_id}" title="Clear search">'
        f"{ICONS['clear']}</button></div>"
        f'<button class="btn" type="button" data-collapse-all="{section_id}">Collapse</button>'
        f'<button class="btn" type="button" data-expand-all="{section_id}">Expand</button>'
        f'<label class="muted" for="source-kind-{section_id}">Context:</label>'
        + _render_select(
            element_id=f"source-kind-{section_id}",
            data_attr=f'data-source-kind-filter="{section_id}"',
            options=tuple((k, k) for k in SOURCE_KIND_FILTER_VALUES),
        )
        + f'<label class="muted" for="clone-type-{section_id}">Type:</label>'
        + _render_select(
            element_id=f"clone-type-{section_id}",
            data_attr=f'data-clone-type-filter="{section_id}"',
            options=CLONE_TYPE_OPTIONS,
        )
        + f'<label class="muted" for="spread-{section_id}">Spread:</label>'
        + _render_select(
            element_id=f"spread-{section_id}",
            data_attr=f'data-spread-filter="{section_id}"',
            options=SPREAD_OPTIONS,
        )
        + f'<label class="inline-check">'
        f'<input type="checkbox" data-min-occurrences-filter="{section_id}"/>'
        "<span>4+ occurrences</span></label>"
        "</div>"
        '<div class="toolbar-right">'
        '<div class="pagination">'
        f'<button class="btn" type="button" data-prev="{section_id}">{ICONS["prev"]}</button>'
        f'<span class="page-meta" data-page-meta="{section_id}">'
        f"Page 1 / 1 \u2022 {group_count} groups</span>"
        f'<button class="btn" type="button" data-next="{section_id}">{ICONS["next"]}</button>'
        "</div>"
        f'<select class="select" data-pagesize="{section_id}" aria-label="Items per page" '
        'title="Groups per page">'
        '<option value="5">5 / page</option>'
        '<option value="10" selected>10 / page</option>'
        '<option value="20">20 / page</option>'
        '<option value="50">50 / page</option>'
        "</select></div></div>"
    )


def _group_block_meta(
    section_id: str,
    group_key: str,
    block_group_facts: Mapping[str, Mapping[str, object]],
) -> dict[str, str]:
    if section_id != "blocks":
        return {}
    return {
        str(k): str(v)
        for k, v in block_group_facts.get(group_key, {}).items()
        if v is not None
    }


def _group_item_span(item: Mapping[str, object]) -> int:
    return max(
        0,
        _as_int(item.get("end_line", 0)) - _as_int(item.get("start_line", 0)) + 1,
    )


def _resolve_group_span_and_arity(
    section_id: str,
    items: Sequence[Mapping[str, object]],
    block_meta: Mapping[str, str],
) -> tuple[int, int]:
    group_span = max((_group_item_span(item) for item in items), default=0)
    group_arity = len(items)
    if section_id != "blocks":
        return group_span, group_arity

    block_size_raw = block_meta.get("block_size", "").strip()
    if block_size_raw.isdigit():
        group_span = int(block_size_raw)

    group_arity_raw = block_meta.get("group_arity", "").strip()
    if group_arity_raw.isdigit() and int(group_arity_raw) > 0:
        group_arity = int(group_arity_raw)
    return group_span, group_arity


def _clone_kind_for_section(
    section_id: str,
) -> Literal["function", "block", "segment"]:
    if section_id == "functions":
        return "function"
    if section_id == "blocks":
        return "block"
    return "segment"


def _build_group_data_attrs(
    *,
    group_id: str,
    group_span: int,
    group_arity: int,
    clone_type: str,
    group_source_kind: str,
    spread_bucket: str,
    spread_files: int,
    spread_functions: int,
    block_meta: Mapping[str, str],
) -> dict[str, object | None]:
    attrs: dict[str, object | None] = {
        "data-group-id": group_id,
        "data-clone-size": str(group_span),
        "data-items-count": str(group_arity),
        "data-group-arity": str(group_arity),
        "data-clone-type": clone_type,
        "data-source-kind": group_source_kind,
        "data-spread-bucket": spread_bucket,
        "data-spread-files": str(spread_files),
        "data-spread-functions": str(spread_functions),
    }
    if not block_meta:
        return attrs
    attrs.update(
        {
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
    )
    return attrs


def _metrics_button_html(section_id: str, group_id: str) -> str:
    if section_id != "blocks":
        return ""
    return (
        f'<button class="btn ghost" type="button" '
        f'data-metrics-btn="{_escape_attr(group_id)}">Info</button>'
    )


def _compare_note_html(
    section_id: str,
    group_arity: int,
    block_meta: Mapping[str, str],
) -> str:
    if section_id != "blocks" or group_arity <= 2:
        return ""
    compare_note = block_meta.get("group_compare_note", "").strip()
    if not compare_note:
        return ""
    return f'<div class="group-compare-note">{_escape_html(compare_note)}</div>'


def _resolve_peer_count(section_id: str, block_meta: Mapping[str, str]) -> int:
    if section_id != "blocks":
        return 0
    peer_count_raw = block_meta.get("instance_peer_count", "").strip()
    if peer_count_raw.isdigit() and int(peer_count_raw) >= 0:
        return int(peer_count_raw)
    return 0


def _render_group_items_html(
    *,
    ctx: ReportContext,
    section_id: str,
    items: Sequence[GroupItemLike],
    group_id: str,
    group_arity: int,
    peer_count: int,
    block_meta: Mapping[str, str],
) -> str:
    rendered: list[str] = [f'<div class="group-body items" id="group-body-{group_id}">']
    include_compare_meta = section_id == "blocks" and "group_arity" in block_meta

    for item_index, item in enumerate(items, start=1):
        filepath = str(item.get("filepath", ""))
        qualname = str(item.get("qualname", ""))
        start_line = _as_int(item.get("start_line", 0))
        end_line = _as_int(item.get("end_line", 0))
        snippet = _render_code_block(
            filepath=filepath,
            start_line=start_line,
            end_line=end_line,
            file_cache=ctx.file_cache,
            context=ctx.context_lines,
            max_lines=ctx.max_snippet_lines,
        )
        display_qualname = ctx.bare_qualname(qualname, filepath)
        display_filepath = ctx.relative_path(filepath)
        compare_html = ""
        if include_compare_meta:
            compare_text = format_group_instance_compare_meta(
                instance_index=item_index,
                group_arity=group_arity,
                peer_count=peer_count,
            )
            compare_html = (
                f'<div class="item-compare-meta">{_escape_html(compare_text)}</div>'
            )
        rendered.append(
            f'<div class="item" data-qualname="{_escape_attr(qualname)}" '
            f'data-filepath="{_escape_attr(filepath)}" '
            f'data-start-line="{start_line}" data-end-line="{end_line}" '
            f'data-peer-count="{peer_count}" data-instance-index="{item_index}">'
            '<div class="item-header">'
            f'<div class="item-title" title="{_escape_attr(qualname)}">'
            f"{_escape_html(display_qualname)}</div>"
            f'<div class="item-loc">'
            f'<a class="ide-link" data-file="{_escape_attr(filepath)}" data-line="{start_line}" '
            f'title="{_escape_attr(filepath)}:{start_line}-{end_line}">'
            f"{_escape_html(display_filepath)}:{start_line}-{end_line}</a></div></div>"
            f"{compare_html}"
            f"{snippet.code_html}"
            "</div>"
        )
    rendered.append("</div>")
    return "".join(rendered)


def _render_group_html(
    *,
    ctx: ReportContext,
    section_id: str,
    group_index: int,
    group_key: str,
    items: Sequence[GroupItemLike],
    block_group_facts: Mapping[str, Mapping[str, object]],
    section_novelty: Mapping[str, str],
) -> str:
    group_id = f"{section_id}-{group_index}"
    finding_id = clone_group_id(_clone_kind_for_section(section_id), group_key)
    search_parts: list[str] = [str(group_key)]
    for item in items:
        search_parts.append(str(item.get("qualname", "")))
        search_parts.append(str(item.get("filepath", "")))
    search_blob = _escape_attr(" ".join(search_parts).lower())

    block_meta = _group_block_meta(section_id, group_key, block_group_facts)
    group_name = _derive_group_display_name(
        group_key,
        items,
        section_id,
        block_meta,
        ctx,
    )
    group_span, group_arity = _resolve_group_span_and_arity(
        section_id,
        items,
        block_meta,
    )
    group_summary = (
        f"{group_arity} instances \u2022 block size {group_span}"
        if group_span > 0
        else f"{group_arity} instances"
    )
    clone_type = classify_clone_type(
        items=items,
        kind=_clone_kind_for_section(section_id),
    )
    group_locations = tuple(
        report_location_from_group_item(item, scan_root=ctx.scan_root) for item in items
    )
    group_source_kind = combine_source_kinds(
        location.source_kind for location in group_locations
    )
    spread_files, spread_functions = group_spread(group_locations)
    spread_bucket = "high" if spread_files > 1 or spread_functions > 1 else "low"
    group_summary += f" \u2022 spread {spread_functions} fn / {spread_files} files"
    group_attrs = _build_group_data_attrs(
        group_id=group_id,
        group_span=group_span,
        group_arity=group_arity,
        clone_type=clone_type,
        group_source_kind=group_source_kind,
        spread_bucket=spread_bucket,
        spread_files=spread_files,
        spread_functions=spread_functions,
        block_meta=block_meta,
    )
    peer_count = _resolve_peer_count(section_id, block_meta)
    explanation_html = _render_group_explanation(block_meta) if block_meta else ""

    return (
        f'<div class="group" id="finding-{_escape_attr(finding_id)}" '
        f'data-group="{section_id}" '
        f'data-group-index="{group_index}" '
        f'data-finding-id="{_escape_attr(finding_id)}" '
        f'data-group-key="{_escape_attr(group_key)}" '
        f'data-novelty="{_escape_attr(section_novelty.get(group_key, "all"))}" '
        f'data-search="{search_blob}"{_build_data_attrs(group_attrs)}>'
        '<div class="group-head">'
        '<div class="group-head-left">'
        f'<button class="group-toggle" type="button" aria-label="Toggle group" '
        f'data-toggle-group="{group_id}">{ICONS["chev_down"]}</button>'
        '<div class="group-info">'
        f'<div class="group-name">{_escape_html(group_name)}</div>'
        f'<div class="group-summary">{_escape_html(group_summary)}</div>'
        "</div></div>"
        '<div class="group-head-right">'
        f"{_source_kind_badge_html(group_source_kind)}"
        f'<span class="clone-type-badge">{_escape_html(clone_type)}</span>'
        f'<span class="clone-count-badge">{group_arity}</span>'
        f"{_metrics_button_html(section_id, group_id)}"
        "</div></div>"
        f"{_compare_note_html(section_id, group_arity, block_meta)}"
        f"{explanation_html}"
        + _render_group_items_html(
            ctx=ctx,
            section_id=section_id,
            items=items,
            group_id=group_id,
            group_arity=group_arity,
            peer_count=peer_count,
            block_meta=block_meta,
        )
        + "</div>"
    )


def _render_section(
    ctx: ReportContext,
    section_id: str,
    section_title: str,
    groups: Sequence[tuple[str, Sequence[GroupItemLike]]],
    *,
    novelty_by_group: Mapping[str, str] | None = None,
) -> str:
    if not groups:
        return ""

    block_group_facts = ctx.block_group_facts
    section_novelty = novelty_by_group or {}
    has_novelty_filter = bool(section_novelty)

    out: list[str] = [
        f'<section id="{section_id}" class="section" data-section="{section_id}" '
        f'data-has-novelty-filter="{"true" if has_novelty_filter else "false"}" '
        f'data-total-groups="{len(groups)}">',
        _render_section_toolbar(section_id, section_title, len(groups)),
        '<div class="section-body">',
    ]

    for idx, (gkey, items) in enumerate(groups, start=1):
        out.append(
            _render_group_html(
                ctx=ctx,
                section_id=section_id,
                group_index=idx,
                group_key=gkey,
                items=items,
                block_group_facts=block_group_facts,
                section_novelty=section_novelty,
            )
        )

    out.append("</div>")  # section-body
    out.append("</section>")
    return "\n".join(out)


def render_clones_panel(ctx: ReportContext) -> tuple[str, bool, int, int]:
    """Build the Clones tab panel HTML.

    Returns ``(panel_html, novelty_enabled, total_new, total_known)``.
    """
    # Empty state
    if not ctx.has_any_clones:
        empty = (
            '<div class="empty"><div class="empty-card">'
            f'<div class="empty-icon">{ICONS["check"]}</div>'
            "<h2>No code clones detected</h2>"
            "<p>No structural, block-level, or segment-level duplication was found "
            "above configured thresholds.</p>"
            '<p class="muted">This usually indicates healthy abstraction boundaries.</p>'
            "</div></div>"
        )
        return empty, False, 0, 0

    # Novelty maps
    func_novelty = {
        gk: ("new" if gk in ctx.new_func_keys else "known") for gk, _ in ctx.func_sorted
    }
    block_novelty = {
        gk: ("new" if gk in ctx.new_block_keys else "known")
        for gk, _ in ctx.block_sorted
    }
    novelty_enabled = bool(func_novelty) or bool(block_novelty)
    total_new = sum(1 for v in func_novelty.values() if v == "new")
    total_new += sum(1 for v in block_novelty.values() if v == "new")
    total_known = sum(1 for v in func_novelty.values() if v == "known")
    total_known += sum(1 for v in block_novelty.values() if v == "known")
    default_novelty = "new" if total_new > 0 else "known"

    global_novelty_html = ""
    if novelty_enabled:
        global_novelty_html = (
            '<section class="global-novelty" id="global-novelty-controls" '
            f'data-default-novelty="{default_novelty}">'
            '<div class="global-novelty-head">'
            "<h2>Duplicate Scope</h2>"
            '<div class="novelty-tabs" role="tablist" aria-label="Baseline split filter">'
            '<button class="btn novelty-tab" type="button" data-global-novelty="new" '
            f'data-novelty-state="{"good" if total_new == 0 else "bad"}">'
            f'New duplicates <span class="novelty-count">{total_new}</span></button>'
            '<button class="btn novelty-tab" type="button" data-global-novelty="known">'
            f'Known duplicates <span class="novelty-count">{total_known}</span></button>'
            "</div></div>"
            f'<p class="novelty-note">{_escape_html(ctx.baseline_split_note)}</p>'
            "</section>"
        )

    func_section = _render_section(
        ctx,
        "functions",
        "Function clones",
        list(ctx.func_sorted),
        novelty_by_group=func_novelty,
    )
    block_section = _render_section(
        ctx,
        "blocks",
        "Block clones",
        list(ctx.block_sorted),
        novelty_by_group=block_novelty,
    )
    segment_section = _render_section(
        ctx,
        "segments",
        "Segment clones",
        list(ctx.segment_sorted),
    )

    sub_tabs: list[tuple[str, str, int, str]] = []
    if ctx.func_sorted:
        sub_tabs.append(("functions", "Functions", len(ctx.func_sorted), func_section))
    if ctx.block_sorted:
        sub_tabs.append(("blocks", "Blocks", len(ctx.block_sorted), block_section))
    if ctx.segment_sorted:
        sub_tabs.append(
            ("segments", "Segments", len(ctx.segment_sorted), segment_section)
        )

    panel = global_novelty_html + render_split_tabs(
        group_id="clones", tabs=sub_tabs, emit_clone_counters=True
    )

    # Insight block
    if novelty_enabled:
        clones_answer = (
            f"{ctx.clone_groups_total} groups total; "
            f"{total_new} new vs {total_known} known."
        )
    else:
        clones_answer = f"{ctx.clone_groups_total} groups and {ctx.clone_instances_total} instances."
    clones_tone: Tone = "warn" if ctx.clone_groups_total > 0 else "ok"
    panel = (
        insight_block(
            question="Where is duplication concentrated right now?",
            answer=clones_answer,
            tone=clones_tone,
        )
        + panel
    )

    return panel, novelty_enabled, total_new, total_known
