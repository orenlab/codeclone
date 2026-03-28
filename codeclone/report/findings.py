# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""CodeClone — structural code quality analysis for Python.

Serialization and rendering helpers for structural findings (report-only layer).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._html_badges import _source_kind_badge_html, _tab_empty
from .._html_escape import _escape_attr, _escape_html
from .._html_snippets import _FileCache, _render_code_block
from ..domain.findings import (
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
    STRUCTURAL_KIND_DUPLICATED_BRANCHES,
)
from ..domain.quality import RISK_HIGH, RISK_LOW
from ..structural_findings import normalize_structural_findings
from ._source_kinds import SOURCE_KIND_FILTER_VALUES, source_kind_label
from .derived import (
    combine_source_kinds,
    group_spread,
    relative_report_path,
    report_location_from_structural_occurrence,
)
from .json_contract import structural_group_id

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models import StructuralFindingGroup, StructuralFindingOccurrence

__all__ = [
    "build_structural_findings_html_panel",
]

# Human-readable label per finding kind
_KIND_LABEL: dict[str, str] = {
    STRUCTURAL_KIND_DUPLICATED_BRANCHES: "Duplicated branches",
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE: "Clone guard/exit divergence",
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT: "Clone cohort drift",
}


def _spread(items: Sequence[StructuralFindingOccurrence]) -> dict[str, int]:
    """Compute spread metadata: unique files and functions in a finding group."""
    files: set[str] = set()
    functions: set[str] = set()
    for item in items:
        files.add(item.file_path)
        functions.add(item.qualname)
    return {"files": len(files), "functions": len(functions)}


def _sort_key_group(g: StructuralFindingGroup) -> tuple[str, int, str]:
    unique_count = len(
        {(item.file_path, item.qualname, item.start, item.end) for item in g.items}
    )
    return g.finding_kind, -unique_count, g.finding_key


def _sort_key_item(o: StructuralFindingOccurrence) -> tuple[str, str, int, int]:
    return o.file_path, o.qualname, o.start, o.end


def _dedupe_items(
    items: Sequence[StructuralFindingOccurrence],
) -> tuple[StructuralFindingOccurrence, ...]:
    unique: dict[tuple[str, str, int, int], StructuralFindingOccurrence] = {}
    for item in sorted(items, key=_sort_key_item):
        key = (item.file_path, item.qualname, item.start, item.end)
        if key not in unique:
            unique[key] = item
    return tuple(unique.values())


# ---------------------------------------------------------------------------
# HTML panel rendering
# ---------------------------------------------------------------------------


def _signature_chips_html(sig: dict[str, str]) -> str:
    """Render signature key=value pairs as category-badge chips."""
    chips: list[str] = []
    for k, v in sorted(sig.items()):
        key = k.replace("_", " ")
        chips.append(
            f'<span class="category-badge">'
            f'<span class="category-badge-key">{_escape_html(key)}</span>'
            f'<span class="category-badge-val">{_escape_html(v)}</span></span>'
        )
    return " ".join(chips)


def _occurrences_table_html(
    items: Sequence[StructuralFindingOccurrence],
    *,
    scan_root: str,
    already_deduped: bool = False,
    visible_limit: int = 4,
) -> str:
    """Render occurrences as a styled table using the existing table CSS."""
    deduped_items = tuple(items) if already_deduped else _dedupe_items(items)
    visible_items = deduped_items[:visible_limit]
    hidden_items = deduped_items[visible_limit:]

    def _rows_for(entries: Sequence[StructuralFindingOccurrence]) -> str:
        rows: list[str] = []
        for item in entries:
            location = report_location_from_structural_occurrence(
                item,
                scan_root=scan_root,
            )
            short_path = relative_report_path(item.file_path, scan_root=scan_root)
            rows.append(
                "<tr>"
                f'<td class="col-path" title="{_escape_attr(item.file_path)}">'
                f'<a class="ide-link" data-file="{_escape_attr(item.file_path)}" '
                f'data-line="{item.start}">'
                f"{_escape_html(short_path)}</a></td>"
                f'<td class="col-name">{_source_kind_badge_html(location.source_kind)} '
                f"{_escape_html(item.qualname)}</td>"
                f'<td class="col-num">{item.start}-{item.end}</td>'
                "</tr>"
            )
        return "".join(rows)

    colgroup = (
        "<colgroup>"
        '<col style="width:35%">'
        '<col style="width:55%">'
        '<col style="width:10%">'
        "</colgroup>"
    )
    thead = "<thead><tr><th>File</th><th>Location</th><th>Lines</th></tr></thead>"

    hidden_details = ""
    if hidden_items:
        hidden_details = (
            '<details class="finding-occurrences-more">'
            f"<summary>Show {len(hidden_items)} more occurrences</summary>"
            f'<div class="table-wrap"><table class="table sf-table">'
            f"{colgroup}{thead}"
            f"<tbody>{_rows_for(hidden_items)}</tbody>"
            "</table></div></details>"
        )
    return (
        f'<div class="table-wrap"><table class="table sf-table">'
        f"{colgroup}{thead}"
        f"<tbody>{_rows_for(visible_items)}</tbody>"
        "</table></div>"
        f"{hidden_details}"
    )


def _short_path(file_path: str) -> str:
    parts = file_path.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 1 else file_path


def _finding_scope_text(items: Sequence[StructuralFindingOccurrence]) -> str:
    spread = _spread(items)
    if spread["functions"] == 1:
        return f"inside {items[0].qualname}"
    return (
        f"across {spread['functions']} functions in {spread['files']} "
        f"{'file' if spread['files'] == 1 else 'files'}"
    )


def _render_reason_list_html(reasons: Sequence[str]) -> str:
    return (
        '<ul class="finding-why-list">'
        + "".join(f"<li>{_escape_html(reason)}</li>" for reason in reasons)
        + "</ul>"
    )


def _finding_reason_list_html(
    group: StructuralFindingGroup,
    items: Sequence[StructuralFindingOccurrence],
) -> str:
    spread = _spread(items)
    if group.finding_kind == STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE:
        reasons = [
            (
                f"{len(items)} divergent clone members were detected after "
                "stable sorting and deduplication."
            ),
            (
                "Members were compared by entry-guard count/profile, terminal "
                "kind, and side-effect-before-guard marker."
            ),
            (
                f"Cohort id: {group.signature.get('cohort_id', 'unknown')}; "
                "majority guard count: "
                f"{group.signature.get('majority_guard_count', '0')}."
            ),
            (
                f"Spread includes {spread['functions']} "
                f"{'function' if spread['functions'] == 1 else 'functions'} in "
                f"{spread['files']} {'file' if spread['files'] == 1 else 'files'}."
            ),
            "This is a report-only finding and does not affect clone gating.",
        ]
        return _render_reason_list_html(reasons)
    if group.finding_kind == STRUCTURAL_KIND_CLONE_COHORT_DRIFT:
        reasons = [
            f"{len(items)} clone members diverge from the cohort majority profile.",
            f"Drift fields: {group.signature.get('drift_fields', 'n/a')}.",
            (
                f"Cohort id: {group.signature.get('cohort_id', 'unknown')} with "
                f"arity {group.signature.get('cohort_arity', 'n/a')}."
            ),
            ("Majority profile is compared deterministically with lexical tie-breaks."),
            "This is a report-only finding and does not affect clone gating.",
        ]
        return _render_reason_list_html(reasons)

    stmt_seq = group.signature.get("stmt_seq", "n/a")
    terminal = group.signature.get("terminal", "n/a")
    reasons = [
        (
            f"{len(items)} non-overlapping branch bodies remained after "
            "deduplication and overlap pruning."
        ),
        (
            f"All occurrences belong to {spread['functions']} "
            f"{'function' if spread['functions'] == 1 else 'functions'} in "
            f"{spread['files']} {'file' if spread['files'] == 1 else 'files'}."
        ),
        (
            f"The detector grouped them by structural signature: "
            f"stmt seq: {stmt_seq}, terminal: {terminal}."
        ),
        (
            "Call/raise buckets and nested control-flow flags must also match "
            "for branches to land in the same finding group."
        ),
        (
            "This is a local, report-only hint. It does not change clone groups "
            "or CI verdicts."
        ),
    ]
    return _render_reason_list_html(reasons)


def _finding_matters_paragraph(message: str) -> str:
    return f'<p class="finding-why-text">{_escape_html(message)}</p>'


def _finding_matters_html(
    group: StructuralFindingGroup,
    items: Sequence[StructuralFindingOccurrence],
) -> str:
    spread = _spread(items)
    count = len(items)
    if group.finding_kind == STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE:
        message = (
            "Members of one function-clone cohort diverged in guard/exit behavior. "
            "This often points to a partial fix where one path was updated and "
            "other siblings were left unchanged."
        )
        return _finding_matters_paragraph(message)
    if group.finding_kind == STRUCTURAL_KIND_CLONE_COHORT_DRIFT:
        message = (
            "Members of one function-clone cohort drifted from a stable majority "
            "profile (terminal, guard, try/finally, side-effect order). Review "
            "whether divergence is intentional."
        )
        return _finding_matters_paragraph(message)

    terminal = str(group.signature.get("terminal", "")).strip()
    stmt_seq = str(group.signature.get("stmt_seq", "")).strip()
    if spread["functions"] > 1 or spread["files"] > 1:
        message = (
            f"This pattern repeats across {spread['functions']} functions and "
            f"{spread['files']} files, so the same branch policy may be copied "
            "between multiple code paths."
        )
    elif terminal == "raise":
        message = (
            "This group points to repeated guard or validation exits inside one "
            "function. Consolidating the shared exit policy usually reduces "
            "branch noise."
        )
    elif terminal == "return":
        message = (
            "This group points to repeated return-path logic inside one function. "
            "A helper can often keep the branch predicate local while sharing "
            "the emitted behavior."
        )
    else:
        message = (
            f"This group reports {count} branches with the same local shape "
            f"({stmt_seq or 'unknown signature'}). Review whether the shared "
            "branch body should stay duplicated or become a helper."
        )
    return _finding_matters_paragraph(message)


def _finding_example_card_html(
    item: StructuralFindingOccurrence,
    *,
    label: str,
    file_cache: _FileCache,
    context_lines: int,
    max_snippet_lines: int,
) -> str:
    snippet = _render_code_block(
        filepath=item.file_path,
        start_line=item.start,
        end_line=item.end,
        file_cache=file_cache,
        context=context_lines,
        max_lines=max_snippet_lines,
    )
    return (
        '<div class="finding-why-example">'
        '<div class="finding-why-example-head">'
        f'<span class="finding-why-example-label">{_escape_html(label)}</span>'
        f'<span class="finding-why-example-meta">{_escape_html(item.qualname)}</span>'
        f'<span class="finding-why-example-loc">'
        f"{_escape_html(_short_path(item.file_path))}:{item.start}\u2013{item.end}</span>"
        "</div>"
        f"{snippet.code_html}"
        "</div>"
    )


def _finding_why_template_html(
    group: StructuralFindingGroup,
    items: Sequence[StructuralFindingOccurrence],
    *,
    file_cache: _FileCache,
    context_lines: int,
    max_snippet_lines: int,
) -> str:
    preview_items = list(items[:2])
    examples_html = "".join(
        _finding_example_card_html(
            item,
            label=f"Example {'AB'[idx] if idx < 2 else idx + 1}",
            file_cache=file_cache,
            context_lines=context_lines,
            max_snippet_lines=max_snippet_lines,
        )
        for idx, item in enumerate(preview_items)
    )
    if group.finding_kind == STRUCTURAL_KIND_DUPLICATED_BRANCHES:
        showing_note = (
            f"Showing the first {len(preview_items)} matching branches from "
            f"{len(items)} total occurrences."
        )
        reported_subject = "structurally matching branch bodies"
    elif group.finding_kind == STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE:
        showing_note = (
            f"Showing the first {len(preview_items)} cohort members from "
            f"{len(items)} divergent occurrences."
        )
        reported_subject = "clone cohort members with guard/exit divergence"
    elif group.finding_kind == STRUCTURAL_KIND_CLONE_COHORT_DRIFT:
        showing_note = (
            f"Showing the first {len(preview_items)} cohort members from "
            f"{len(items)} divergent occurrences."
        )
        reported_subject = "clone cohort members that drift from majority profile"
    else:
        showing_note = (
            f"Showing the first {len(preview_items)} matching branches from "
            f"{len(items)} total occurrences."
        )
        reported_subject = "structurally matching branch bodies"
    return (
        '<div class="metrics-section">'
        '<div class="metrics-section-title">Impact</div>'
        f"{_finding_matters_html(group, items)}"
        "</div>"
        '<div class="metrics-section">'
        '<div class="metrics-section-title">Detection Rationale</div>'
        f'<p class="finding-why-text">CodeClone reported this group because it found '
        f"{len(items)} {reported_subject} "
        f"{_escape_html(_finding_scope_text(items))}.</p>"
        f"{_finding_reason_list_html(group, items)}"
        "</div>"
        '<div class="metrics-section">'
        '<div class="metrics-section-title">Signature</div>'
        f'<div class="finding-why-chips">{_signature_chips_html(group.signature)}</div>'
        "</div>"
        '<div class="metrics-section">'
        '<div class="metrics-section-title">Examples</div>'
        f'<div class="finding-why-note">{_escape_html(showing_note)}</div>'
        f'<div class="finding-why-examples">{examples_html}</div>'
        "</div>"
    )


def _render_finding_card(
    g: StructuralFindingGroup,
    *,
    scan_root: str,
    file_cache: _FileCache,
    context_lines: int,
    max_snippet_lines: int,
    why_templates: list[str],
) -> tuple[str, str]:
    """Render a single finding group as a compact card. Returns (html, source_kind)."""
    deduped_items = _dedupe_items(g.items)
    spread = _spread(deduped_items)
    chips_html = _signature_chips_html(g.signature)
    report_locations = tuple(
        report_location_from_structural_occurrence(item, scan_root=scan_root)
        for item in deduped_items
    )
    source_kind = combine_source_kinds(
        location.source_kind for location in report_locations
    )
    spread_files, spread_functions = group_spread(report_locations)
    spread_bucket = RISK_HIGH if spread_files > 1 or spread_functions > 1 else RISK_LOW
    table_html = _occurrences_table_html(
        deduped_items, scan_root=scan_root, already_deduped=True
    )
    count = len(deduped_items)

    why_template_id = f"finding-why-template-{g.finding_key}"
    why_template_html = _finding_why_template_html(
        g,
        deduped_items,
        file_cache=file_cache,
        context_lines=context_lines,
        max_snippet_lines=max_snippet_lines,
    )
    why_templates.append(
        f'<template id="{_escape_attr(why_template_id)}">{why_template_html}</template>'
    )

    func_word = "function" if spread["functions"] == 1 else "functions"
    file_word = "file" if spread["files"] == 1 else "files"
    kind_label = _KIND_LABEL.get(g.finding_kind, g.finding_kind)

    # Context chips — source kind + finding kind
    source_chip = _escape_html(source_kind_label(source_kind))
    finding_kind_chip = _escape_html(g.finding_kind.replace("_", " "))
    ctx_chips = (
        f'<span class="suggestion-chip">{source_chip}</span>'
        f'<span class="suggestion-chip">{finding_kind_chip}</span>'
    )

    # Scope text — concise spread summary
    scope_text = _finding_scope_text(deduped_items)
    finding_id = structural_group_id(g.finding_kind, g.finding_key)

    return (
        f'<article class="sf-card"'
        f' id="finding-{_escape_attr(finding_id)}"'
        f' data-finding-id="{_escape_attr(finding_id)}"'
        f' data-sf-group="true"'
        f' data-source-kind="{_escape_attr(source_kind)}"'
        f' data-spread-bucket="{_escape_attr(spread_bucket)}">'
        # -- header --
        '<div class="sf-head">'
        '<span class="sf-kind-badge">info</span>'
        f'<span class="sf-title">{_escape_html(kind_label)}</span>'
        '<span class="sf-meta">'
        f'<span class="suggestion-meta-badge">'
        f"{spread['functions']} {func_word} \u00b7 {spread['files']} {file_word}</span>"
        f'<button class="btn ghost sf-why-btn" type="button" '
        f'data-finding-why-btn="{_escape_attr(why_template_id)}" '
        'aria-haspopup="dialog">Why?</button>'
        "</span></div>"
        # -- body: context + signature chips + scope --
        '<div class="sf-body">'
        f'<div class="suggestion-context">{ctx_chips}</div>'
        f'<div class="sf-chips">{chips_html}</div>'
        f'<div class="sf-scope-text">{_escape_html(scope_text)}</div>'
        "</div>"
        # -- expandable occurrences --
        '<details class="sf-details">'
        f"<summary>Occurrences ({count})</summary>"
        f'<div class="sf-details-body">{table_html}</div>'
        "</details>"
        "</article>",
        source_kind,
    )


def build_structural_findings_html_panel(
    groups: Sequence[StructuralFindingGroup],
    files: list[str],
    *,
    scan_root: str = "",
    file_cache: _FileCache | None = None,
    context_lines: int = 3,
    max_snippet_lines: int = 220,
) -> str:
    """Build HTML content for the Structural Findings tab panel."""
    from .._html_report._tabs import render_split_tabs

    normalized_groups = normalize_structural_findings(groups)
    if not normalized_groups:
        return _tab_empty("No structural findings detected.")

    intro = (
        '<div class="insight-banner insight-info">'
        '<div class="insight-question">What are structural findings?</div>'
        '<div class="insight-answer">Repeated non-overlapping branch-body shapes '
        "detected inside individual functions. These are local, report-only "
        "refactoring hints and do not affect clone detection or CI verdicts.</div>"
        "</div>"
    )

    resolved_file_cache = file_cache if file_cache is not None else _FileCache()
    why_templates: list[str] = []

    # Render all cards and bucket by source_kind
    by_source: dict[str, list[str]] = {}
    for g in sorted(normalized_groups, key=_sort_key_group):
        card_html, source_kind = _render_finding_card(
            g,
            scan_root=scan_root,
            file_cache=resolved_file_cache,
            context_lines=context_lines,
            max_snippet_lines=max_snippet_lines,
            why_templates=why_templates,
        )
        by_source.setdefault(source_kind, []).append(card_html)

    # Build sub-tabs: "All" + per source_kind
    all_cards = []
    for cards in by_source.values():
        all_cards.extend(cards)

    sub_tabs: list[tuple[str, str, int, str]] = [
        (
            "all",
            "All",
            len(all_cards),
            f'<div class="sf-list">{"".join(all_cards)}</div>',
        ),
    ]
    # Stable order matching SOURCE_KIND_FILTER_VALUES
    for kind in SOURCE_KIND_FILTER_VALUES:
        cards = by_source.get(kind, [])
        if cards:
            sub_tabs.append(
                (
                    kind,
                    source_kind_label(kind),
                    len(cards),
                    f'<div class="sf-list">{"".join(cards)}</div>',
                )
            )

    return (
        intro
        + render_split_tabs(group_id="findings", tabs=sub_tabs)
        + "".join(why_templates)
    )
