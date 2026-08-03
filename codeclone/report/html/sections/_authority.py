# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Semantic-authority panel projected from canonical metric facts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from codeclone.utils.coerce import as_int as _as_int
from codeclone.utils.coerce import as_mapping as _as_mapping
from codeclone.utils.coerce import as_sequence as _as_sequence

from ..primitives.escape import _escape_html
from ..widgets.badges import _micro_badges, _stat_card
from ..widgets.components import Tone, insight_block
from ..widgets.glossary import glossary_tip
from ..widgets.tables import render_rows_table
from ..widgets.tabs import render_split_tabs

if TYPE_CHECKING:
    from .._context import ReportContext


#: Contract IR failure kinds, in the words a reader can act on.
_UNRESOLVED_REASON_LABELS = {
    "unresolved_call": "unresolved call",
    "unresolved_flow": "unresolved flow",
}


def _unresolved_reason_text(item: Mapping[str, object]) -> str:
    """Say why a sink abstained; an abstention without a reason is not a fact."""

    reasons = [
        _UNRESOLVED_REASON_LABELS.get(text, text)
        for value in _as_sequence(item.get("unresolved_reasons"))
        for text in (str(value).strip(),)
        if text
    ]
    return ", ".join(reasons) if reasons else "-"


#: Candidate rows rendered before the tail is summarised. Discovery proposes on
#: the scale of the whole tree, so the panel shows the strongest evidence and
#: says how much it is not showing.
_CANDIDATE_ROW_LIMIT = 50

#: Only these levels earn a row. The weaker two are real findings but arrive in
#: the thousands, so they are counted in the caption histogram instead of
#: turning the panel into an unreadable wall. The cut is stated, never silent.
_LEVEL_RANK: Final = {
    "exact_contract_ir": 5,
    "same_effect_signature": 4,
    "same_output_fact_and_input_family": 3,
    "overlapping_transform_chain": 2,
    "divergent_projection": 1,
}

_STRONG_CANDIDATE_LEVELS: Final = (
    "exact_contract_ir",
    "same_effect_signature",
    "same_output_fact_and_input_family",
)

#: Discovery proposes; a human decides. Promotion is a copy-paste into
#: pyproject, never a write by this tool.
_CANDIDATE_CAPTION = (
    "Discovered owners, ranked by evidence strength. Authority is a governance "
    "act: tools propose, humans own. Copy a proposal into "
    "[[tool.codeclone.authority]] to govern it; nothing here changes your "
    "configuration."
)


def _level_histogram_text(candidates: Sequence[Mapping[str, object]]) -> str:
    """Count every level, so the levels held back from the table stay visible."""

    if not candidates:
        return ""
    counts: Counter[str] = Counter(
        str(item.get("level", "")).strip() for item in candidates
    )
    ordered = sorted(
        counts.items(),
        key=lambda row: (-_LEVEL_RANK.get(row[0], 0), row[0]),
    )
    parts = ", ".join(f"{level.replace('_', ' ')} {count}" for level, count in ordered)
    weak = ", ".join(
        level.replace("_", " ")
        for level in sorted(counts)
        if level not in _STRONG_CANDIDATE_LEVELS
    )
    cut = (
        f" Levels below the cut ({weak}) are counted here only; "
        'drill into them with check_authority(section="candidates") over MCP.'
        if weak
        else ""
    )
    return f" By level: {parts}.{cut}"


def _sink_population_note(sink_total: int) -> str:
    """Account for the discovery population instead of dropping it silently."""

    if sink_total <= 0:
        return ""
    return (
        f" Discovery examined {sink_total} semantic sinks; the candidates below "
        "are the subset carrying shared-fact evidence."
    )


def _candidate_producers_html(producers: Sequence[str]) -> str:
    """Disclose the co-producers instead of pasting them into the cell.

    The owner leads the row on its own; everyone else sharing the fact is one
    click away. Joining them into the cell produced forty thousand characters
    of unscannable, unclickable text on this repository.
    """

    if len(producers) <= 1:
        return "-"
    rest = producers[1:]
    items = "".join(f"<li><code>{_escape_html(name)}</code></li>" for name in rest)
    return (
        '<details class="authority-producers">'
        f"<summary>+{len(rest)} more</summary>"
        f'<ul class="detail-panel authority-producer-list">{items}</ul>'
        "</details>"
    )


def _candidate_owner_html(owner: str) -> str:
    """Render the proposed owner as the row's primary, copyable fact."""

    if not owner:
        return "-"
    return (
        '<div class="authority-owner authority-copy-host">'
        f"<code>{_escape_html(owner)}</code>"
        '<button class="btn authority-copy-btn" type="button" '
        'data-authority-copy title="Copy qualname">Copy</button>'
        "</div>"
    )


def _candidate_promotion_html(item: Mapping[str, object]) -> str:
    """Render the paste-ready registry entry for one discovery candidate.

    Promotion is a governance act. This writes nothing: it renders the TOML a
    human copies into pyproject, with the contract id left as a placeholder
    because only a human can name the contract a producer is meant to own.
    """

    producers = [
        text
        for value in _as_sequence(item.get("producers"))
        for text in (str(value).strip(),)
        if text
    ]
    if not producers:
        return "-"
    owner, *alternatives = producers
    lines = [
        "[[tool.codeclone.authority]]",
        'contract_id = "<name.this.contract/v1>"',
        f'canonical_owner = "{owner}"',
        "allowed_adapters = []",
        "forbidden_raw_inputs = []",
        f'required_provenance = ["{owner}"]',
    ]
    if alternatives:
        lines.append("# other producers sharing this fact: " + ", ".join(alternatives))
    snippet = _escape_html("\n".join(lines))
    # Collapsed by construction: fifty open TOML blocks cannot happen, because
    # a proposal only expands when a human asks for that one.
    return (
        '<details class="authority-promotion">'
        '<summary class="authority-promotion-summary">Propose</summary>'
        '<div class="authority-promotion-body authority-copy-host">'
        '<button class="btn authority-copy-btn" type="button" '
        "data-authority-copy>Copy</button>"
        f'<pre class="codebox"><code>{snippet}</code></pre>'
        "</div>"
        "</details>"
    )


def _authority_answer(
    *,
    enabled: bool,
    active: int,
    suppressed: int,
    registry_contracts: int,
    governed_total: int,
    unresolved_total: int,
    candidate_total: int = 0,
) -> tuple[str, Tone]:
    """Decide what the panel claims, worst-known first.

    An empty violation list over an unresolved population is not a clean
    result: nothing could have been found there. Abstention is reported as
    abstention rather than counted as zero.
    """

    if not enabled:
        if candidate_total:
            return (
                "Semantic-authority discovery is report-only; "
                f"{candidate_total} discovery candidates found.",
                "info",
            )
        return (
            "Semantic-authority discovery is report-only; no registry is configured.",
            "info",
        )
    if active:
        return (
            f"{active} active violations across {registry_contracts} governed "
            f"contracts; {suppressed} findings suppressed.",
            "risk",
        )
    if unresolved_total:
        return (
            f"Authority cannot be asserted: {unresolved_total} of {governed_total} "
            "governed owners are unresolved.",
            "info",
        )
    return (
        f"{active} active violations across {registry_contracts} governed "
        f"contracts; {suppressed} findings suppressed.",
        "ok",
    )


def render_authority_panel(ctx: ReportContext) -> str:
    authority = _as_mapping(ctx.metrics_map.get("semantic_authority"))
    summary = _as_mapping(authority.get("summary"))
    items = tuple(_as_mapping(item) for item in _as_sequence(authority.get("items")))
    governed = tuple(
        item for item in items if str(item.get("item_kind", "")) == "governed_sink"
    )
    violations = tuple(
        item for item in items if str(item.get("item_kind", "")) == "violation"
    )
    active = tuple(item for item in violations if not bool(item.get("suppressed")))
    suppressed = tuple(item for item in violations if bool(item.get("suppressed")))
    candidates = tuple(
        item for item in items if str(item.get("item_kind", "")) == "candidate"
    )
    strong_candidates = tuple(
        item
        for item in candidates
        if str(item.get("level", "")).strip() in _STRONG_CANDIDATE_LEVELS
    )
    # The "sink" item kind is deliberately not rendered as rows: it is the raw
    # discovery population, one entry per semantic sink in the tree, and it is
    # evidence for the candidates rather than a list anybody acts on. Its size
    # is stated below so the kind is accounted for instead of dropped.
    sink_total = sum(
        1 for item in items if str(item.get("item_kind", "")) == "sink"
    ) or _as_int(summary.get("sinks"))

    governed_rows = [
        (
            str(item.get("contract_id", "")),
            str(item.get("sink_identity", "")),
            str(item.get("authority_status", "")),
            str(item.get("resolution_state", "")),
            _unresolved_reason_text(item),
        )
        for item in governed
    ]
    violation_rows = [
        (
            str(item.get("contract_id", "")),
            str(item.get("kind", "")),
            str(item.get("sink_identity", "")),
            str(item.get("canonical_owner", "")),
        )
        for item in active
    ]
    suppressed_rows = [
        (
            str(item.get("contract_id", "")),
            str(item.get("kind", "")),
            str(item.get("sink_identity", "")),
            "duplicate-responsibility",
        )
        for item in suppressed
    ]
    candidate_rows = []
    for item in strong_candidates[:_CANDIDATE_ROW_LIMIT]:
        producers = [
            text
            for value in _as_sequence(item.get("producers"))
            for text in (str(value).strip(),)
            if text
        ]
        candidate_rows.append(
            (
                _candidate_owner_html(producers[0] if producers else ""),
                str(item.get("level", "")).replace("_", " "),
                str(_as_int(item.get("score"))),
                _candidate_producers_html(producers),
                _candidate_promotion_html(item),
            )
        )

    enabled = bool(summary.get("enforcement_enabled"))
    unresolved_governed = sum(
        1
        for item in governed
        if str(item.get("authority_status", "")).strip() == "unavailable"
    )
    answer, tone = _authority_answer(
        enabled=enabled,
        active=len(active),
        suppressed=len(suppressed),
        registry_contracts=_as_int(summary.get("registry_contracts")),
        governed_total=len(governed),
        unresolved_total=unresolved_governed,
        candidate_total=len(candidates),
    )
    governed_panel = render_rows_table(
        headers=("Contract", "Sink", "Status", "Resolution", "Why"),
        rows=governed_rows,
        empty_message="No governed semantic sinks.",
        column_types={"Status": "status"},
        ctx=ctx,
    )
    active_panel = render_rows_table(
        headers=("Contract", "Kind", "Sink", "Canonical owner"),
        rows=violation_rows,
        empty_message="No semantic-authority violations.",
        ctx=ctx,
    )
    suppressed_panel = render_rows_table(
        headers=("Contract", "Kind", "Sink", "Rule"),
        rows=suppressed_rows,
        empty_message="No suppressed semantic-authority findings.",
        ctx=ctx,
    )
    shown = len(candidate_rows)
    tail_note = (
        f" Showing the {shown} strongest of {len(candidates)} candidates."
        if len(candidates) > shown
        else ""
    )
    histogram = _level_histogram_text(candidates)
    candidate_caption = (
        '<p class="muted authority-candidate-note">'
        f"{_escape_html(_CANDIDATE_CAPTION)}"
        f"{_escape_html(_sink_population_note(sink_total))}"
        f"{_escape_html(tail_note)}"
        f"{_escape_html(histogram)}"
        "</p>"
    )
    candidate_panel = candidate_caption + render_rows_table(
        headers=("Owner", "Level", "Score", "Producers", "Propose"),
        rows=candidate_rows,
        empty_message="No semantic-authority discovery candidates.",
        raw_html_headers=("Owner", "Producers", "Propose"),
        column_types={"Score": "meter_neutral", "Level": "chips"},
        ctx=ctx,
    )
    # The narrative contract: the answer first, then the numbers a reader acts
    # on, then the evidence. Until now this panel jumped from the answer
    # straight into four tabs, so the counts lived only as tab badges.
    cards = [
        _stat_card(
            "Violations",
            len(active),
            detail=_micro_badges(("suppressed", len(suppressed))),
            value_tone="bad" if active else "good",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Governed contracts",
            _as_int(summary.get("registry_contracts")),
            detail=_micro_badges(("owners", len(governed))),
            value_tone="muted" if not enabled else "",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Discovery",
            len(candidates),
            detail=_micro_badges(("sinks examined", sink_total or "n/a")),
            value_tone="muted",
            glossary_tip_fn=glossary_tip,
        ),
        _stat_card(
            "Unresolved owners",
            unresolved_governed,
            secondary=f"of {len(governed)}" if governed else "",
            value_tone="warn" if unresolved_governed else "good",
            glossary_tip_fn=glossary_tip,
        ),
    ]
    return (
        insight_block(
            question="Is each governed semantic contract owned by one authority?",
            answer=answer,
            tone=tone,
        )
        + f'<div class="stat-cards">{"".join(cards)}</div>'
        + render_split_tabs(
            group_id="semantic-authority",
            tabs=(
                ("violations", "Violations", len(active), active_panel),
                ("governed", "Contracts", len(governed), governed_panel),
                ("candidates", "Discovery", len(candidates), candidate_panel),
                ("suppressed", "Suppressed", len(suppressed), suppressed_panel),
            ),
        )
    )


__all__ = ["render_authority_panel"]
