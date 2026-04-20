# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Structural Findings panel — HTML rendering only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeclone.domain.findings import (
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT,
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE,
    STRUCTURAL_KIND_DUPLICATED_BRANCHES,
)
from codeclone.domain.quality import RISK_HIGH, RISK_LOW
from codeclone.findings.ids import structural_group_id
from codeclone.findings.structural import normalize_structural_findings

from ..._source_kinds import SOURCE_KIND_FILTER_VALUES, source_kind_label
from ...derived import (
    combine_source_kinds,
    group_spread,
    relative_report_path,
    report_location_from_structural_occurrence,
)
from ...findings import _dedupe_items, _finding_scope_text, _spread
from ...suggestions import (
    structural_action_steps,
    structural_has_separate_suggestion,
)
from ..primitives.escape import _escape_html
from ..widgets.badges import _source_kind_badge_html, _tab_empty
from ..widgets.snippets import _FileCache, _render_code_block
from ..widgets.tabs import render_split_tabs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from codeclone.models import StructuralFindingGroup, StructuralFindingOccurrence

    from .._context import ReportContext

__all__ = [
    "build_structural_findings_html_panel",
    "render_structural_panel",
]

_KIND_LABEL: dict[str, str] = {
    STRUCTURAL_KIND_DUPLICATED_BRANCHES: "Duplicated branches",
    STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE: "Clone guard/exit divergence",
    STRUCTURAL_KIND_CLONE_COHORT_DRIFT: "Clone cohort drift",
}


def _sort_key_group(g: StructuralFindingGroup) -> tuple[str, int, str]:
    unique_count = len(
        {(item.file_path, item.qualname, item.start, item.end) for item in g.items}
    )
    return g.finding_kind, -unique_count, g.finding_key


def _short_path(file_path: str) -> str:
    parts = file_path.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 1 else file_path


def _signature_chips_html(sig: dict[str, str]) -> str:
    chips: list[str] = []
    for key, value in sorted(sig.items()):
        label = key.replace("_", " ")
        chips.append(
            f'<span class="category-badge">'
            f'<span class="category-badge-key">{_escape_html(label)}</span>'
            f'<span class="category-badge-val">{_escape_html(value)}</span></span>'
        )
    return " ".join(chips)


def _occurrences_table_html(
    items: Sequence[StructuralFindingOccurrence],
    *,
    scan_root: str,
    already_deduped: bool = False,
    visible_limit: int = 4,
) -> str:
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
                f'<td class="col-path" title="{_escape_html(item.file_path)}">'
                f'<a class="ide-link" data-file="{_escape_html(item.file_path)}" '
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
    clone_cohort_reasons = {
        STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE: [
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
        ],
        STRUCTURAL_KIND_CLONE_COHORT_DRIFT: [
            f"{len(items)} clone members diverge from the cohort majority profile.",
            f"Drift fields: {group.signature.get('drift_fields', 'n/a')}.",
            (
                f"Cohort id: {group.signature.get('cohort_id', 'unknown')} with "
                f"arity {group.signature.get('cohort_arity', 'n/a')}."
            ),
            "Majority profile is compared deterministically with lexical tie-breaks.",
            "This is a report-only finding and does not affect clone gating.",
        ],
    }
    if group.finding_kind in clone_cohort_reasons:
        return _render_reason_list_html(clone_cohort_reasons[group.finding_kind])

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
    special_messages = {
        STRUCTURAL_KIND_CLONE_GUARD_EXIT_DIVERGENCE: (
            "Members of one function-clone cohort diverged in guard/exit behavior. "
            "This often points to a partial fix where one path was updated and "
            "other siblings were left unchanged."
        ),
        STRUCTURAL_KIND_CLONE_COHORT_DRIFT: (
            "Members of one function-clone cohort drifted from a stable majority "
            "profile (terminal, guard, try/finally, side-effect order). Review "
            "whether divergence is intentional."
        ),
    }
    if group.finding_kind in special_messages:
        return _finding_matters_paragraph(special_messages[group.finding_kind])

    terminal = str(group.signature.get("terminal", "")).strip()
    stmt_seq = str(group.signature.get("stmt_seq", "")).strip()
    if spread["functions"] > 1 or spread["files"] > 1:
        message = (
            f"This pattern repeats across {spread['functions']} functions and "
            f"{spread['files']} files, so the same branch policy may be copied "
            "between multiple code paths."
        )
    else:
        terminal_messages = {
            "raise": (
                "This group points to repeated guard or validation exits inside one "
                "function. Consolidating the shared exit policy usually reduces "
                "branch noise."
            ),
            "return": (
                "This group points to repeated return-path logic inside one function. "
                "A helper can often keep the branch predicate local while sharing "
                "the emitted behavior."
            ),
        }
        message = terminal_messages.get(
            terminal,
            (
                f"This group reports {count} branches with the same local shape "
                f"({stmt_seq or 'unknown signature'}). Review whether the local "
                "branch logic should stay duplicated or be simplified in place."
            ),
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


def _finding_inline_action_html(
    group: StructuralFindingGroup,
    *,
    occurrence_count: int,
    spread_functions: int,
) -> str:
    if structural_has_separate_suggestion(
        group,
        occurrence_count=occurrence_count,
        spread_functions=spread_functions,
    ):
        return ""
    action_steps = structural_action_steps(group)
    if not action_steps:
        return ""
    primary_action = action_steps[0]
    return (
        '<div class="sf-inline-action">'
        '<span class="sf-inline-action-label">Suggested action</span>'
        f'<span class="sf-inline-action-text">{_escape_html(primary_action)}</span>'
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
    group: StructuralFindingGroup,
    *,
    scan_root: str,
    file_cache: _FileCache,
    context_lines: int,
    max_snippet_lines: int,
    why_templates: list[str],
) -> tuple[str, str]:
    deduped_items = _dedupe_items(group.items)
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
    inline_action_html = _finding_inline_action_html(
        group,
        occurrence_count=count,
        spread_functions=spread_functions,
    )

    why_template_id = f"finding-why-template-{group.finding_key}"
    why_template_html = _finding_why_template_html(
        group,
        deduped_items,
        file_cache=file_cache,
        context_lines=context_lines,
        max_snippet_lines=max_snippet_lines,
    )
    why_templates.append(
        f'<template id="{_escape_html(why_template_id)}">{why_template_html}</template>'
    )

    spread = _spread(deduped_items)
    func_word = "function" if spread["functions"] == 1 else "functions"
    file_word = "file" if spread["files"] == 1 else "files"
    kind_label = _KIND_LABEL.get(group.finding_kind, group.finding_kind)
    source_chip = _escape_html(source_kind_label(source_kind))
    finding_kind_chip = _escape_html(group.finding_kind.replace("_", " "))
    context_chips = (
        f'<span class="suggestion-chip">{source_chip}</span>'
        f'<span class="suggestion-chip">{finding_kind_chip}</span>'
    )
    scope_text = _finding_scope_text(deduped_items)
    finding_id = structural_group_id(group.finding_kind, group.finding_key)
    chips_html = _signature_chips_html(group.signature)

    return (
        f'<article class="sf-card"'
        f' id="finding-{_escape_html(finding_id)}"'
        f' data-finding-id="{_escape_html(finding_id)}"'
        f' data-sf-group="true"'
        f' data-source-kind="{_escape_html(source_kind)}"'
        f' data-spread-bucket="{_escape_html(spread_bucket)}">'
        '<div class="sf-head">'
        '<span class="sf-kind-badge">info</span>'
        f'<span class="sf-title">{_escape_html(kind_label)}</span>'
        '<span class="sf-meta">'
        f'<span class="suggestion-meta-badge">'
        f"{spread['functions']} {func_word} \u00b7 {spread['files']} {file_word}</span>"
        f'<button class="btn ghost sf-why-btn" type="button" '
        f'data-finding-why-btn="{_escape_html(why_template_id)}" '
        'aria-haspopup="dialog">Why?</button>'
        "</span></div>"
        '<div class="sf-body">'
        f'<div class="suggestion-context">{context_chips}</div>'
        f'<div class="sf-chips">{chips_html}</div>'
        f'<div class="sf-scope-text">{_escape_html(scope_text)}</div>'
        f"{inline_action_html}"
        "</div>"
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
    intro = (
        '<div class="insight-banner insight-info">'
        '<div class="insight-question">What are structural findings?</div>'
        '<div class="insight-answer">Repeated non-overlapping branch-body shapes '
        "detected inside individual functions. These are local, report-only "
        "refactoring hints and do not affect clone detection or CI verdicts.</div>"
        "</div>"
    )
    normalized_groups = normalize_structural_findings(groups)
    if not normalized_groups:
        return intro + _tab_empty("No structural findings detected.")

    resolved_file_cache = file_cache if file_cache is not None else _FileCache()
    why_templates: list[str] = []
    by_source: dict[str, list[str]] = {}
    for group in sorted(normalized_groups, key=_sort_key_group):
        card_html, source_kind = _render_finding_card(
            group,
            scan_root=scan_root,
            file_cache=resolved_file_cache,
            context_lines=context_lines,
            max_snippet_lines=max_snippet_lines,
            why_templates=why_templates,
        )
        by_source.setdefault(source_kind, []).append(card_html)

    all_cards: list[str] = []
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


def render_structural_panel(ctx: ReportContext) -> str:
    structural_groups = list(normalize_structural_findings(ctx.structural_findings))
    structural_files: list[str] = sorted(
        {occ.file_path for group in structural_groups for occ in group.items}
    )
    return build_structural_findings_html_panel(
        structural_groups,
        structural_files,
        scan_root=ctx.scan_root,
        file_cache=ctx.file_cache,
        context_lines=ctx.context_lines,
        max_snippet_lines=ctx.max_snippet_lines,
    )
