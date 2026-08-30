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

from ...messages.glossary import GLOSSARY_FAMILY_AUTHORITY
from ..primitives.escape import _escape_html
from ..widgets.badges import _micro_badges, _stat_card
from ..widgets.components import Tone, insight_block
from ..widgets.glossary import family_glossary_tip
from ..widgets.highlight import highlight_block
from ..widgets.tables import (
    render_rows_table,
    row_cut_note_html,
    table_meta_band_html,
)
from ..widgets.tabs import render_split_tabs

if TYPE_CHECKING:
    from .._context import ReportContext


#: Contract IR failure kinds, in the words a reader can act on.
# The family this panel speaks for. Bound once so every card, table
# and tab in this module asks the glossary as the same family.
_TIP = family_glossary_tip(GLOSSARY_FAMILY_AUTHORITY)


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

#: Discovery proposes; a human decides. The short line rides the table's meta
#: band; the full governance rule is a tooltip on the Propose column, because
#: a reader who already knows it should not read it on every visit.
_CANDIDATE_LEAD = "Discovered owners, ranked by evidence strength."
_CANDIDATE_DOCTRINE = "Tools propose, humans own."

#: How the document ordered the candidates, in the band's own words. The total
#: this band counts against is every candidate the run proposed, including the
#: levels below the row cut; the footnote under the table names those levels,
#: so the two statements together account for the whole population.
_CANDIDATE_ORDER = "strongest evidence first"


def _candidate_meta_html(shown: int, total: int) -> str:
    """State the lead and the shown-of-total count on the table's own band.

    A count belongs beside the table it counts, not inside a sentence: the
    reader who wants to know how much is hidden looks to the table's edge.

    This panel declared its cut before any other did; the count is now built
    by the same renderer every other table uses, so there is one sentence for
    "you are looking at part of this" in the whole report rather than one per
    panel that happened to be honest.
    """

    return table_meta_band_html(
        (
            '<span class="table-meta-lead">'
            f"{_escape_html(_CANDIDATE_LEAD)} {_escape_html(_CANDIDATE_DOCTRINE)}"
            "</span>"
        ),
        row_cut_note_html(total=total, shown=shown, ordering=_CANDIDATE_ORDER),
    )


def _level_strip_html(candidates: Sequence[Mapping[str, object]]) -> str:
    """Count every level as chips, so the held-back levels stay visible.

    This was a prose histogram inside a ten-line caption. It is a distribution:
    it is read by scanning, never by reading, so it renders as counts.
    """

    if not candidates:
        return ""
    counts: Counter[str] = Counter(
        str(item.get("level", "")).strip() for item in candidates
    )
    ordered = sorted(
        counts.items(),
        key=lambda row: (-_LEVEL_RANK.get(row[0], 0), row[0]),
    )
    pairs = tuple((level.replace("_", " "), count) for level, count in ordered)
    return f'<div class="level-strip">{_micro_badges(*pairs)}</div>'


def _candidate_cut_note_html(candidates: Sequence[Mapping[str, object]]) -> str:
    """Name the levels that earn no row, and the route to them."""

    weak = sorted(
        {
            str(item.get("level", "")).strip().replace("_", " ")
            for item in candidates
            if str(item.get("level", "")).strip() not in _STRONG_CANDIDATE_LEVELS
            and str(item.get("level", "")).strip()
        }
    )
    if not weak:
        return ""
    return (
        '<div class="table-footnote">'
        f"Levels below the cut ({_escape_html(', '.join(weak))}) are counted "
        "above only; drill into them with "
        '<code>check_authority(section="candidates")</code> over MCP.'
        "</div>"
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


def _candidate_promotion_html(item: Mapping[str, object]) -> tuple[str, str]:
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
        return "-", ""
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
        # The co-producers are a list, so the comment states its policy rather
        # than pasting it: on this repository the joined form reached hundreds
        # of thousands of characters on one line, and a TOML line that long
        # drove the whole table's intrinsic width. The full set is one click
        # away in the Producers column of the same row.
        shown = ", ".join(alternatives[:3])
        rest = len(alternatives) - 3
        tail = f" (+{rest} more, see Producers)" if rest > 0 else ""
        lines.append(f"# other producers sharing this fact: {shown}{tail}")
    # Highlighted as TOML at build time: this is the one real configuration
    # block in the report, and a reader must be able to tell the placeholder
    # contract id from the key that names it. The text copied is unchanged.
    snippet = highlight_block("\n".join(lines), language="toml")
    # Collapsed by construction: fifty open TOML blocks cannot happen, because
    # a proposal only expands when a human asks for that one. The summary is
    # all that stays in the cell -- the block itself is returned separately and
    # rendered as a full-width row, because six lines of TOML in the narrowest
    # column of the table were cut mid-word at the cell edge.
    summary = (
        '<details class="authority-promotion">'
        '<summary class="authority-promotion-summary">Propose</summary>'
        "</details>"
    )
    body = (
        '<div class="authority-promotion-body authority-copy-host">'
        '<button class="btn authority-copy-btn" type="button" '
        "data-authority-copy>Copy</button>"
        f'<pre class="codebox"><code>{snippet}</code></pre>'
        "</div>"
    )
    return summary, body


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
    #
    # Every count on this panel is read from the summary the document carries,
    # never recounted from the rows. The rows above are filtered because the
    # panel renders them; the numbers are a separate question and the document
    # already answers it. The sink count in particular used to be
    # ``sum(1 for ... ) or summary["sinks"]``, which is worse than a plain
    # recount: the ``or`` silently substituted one answer for the other, so a
    # document whose rows and summary disagreed rendered whichever the rows
    # happened to say, and a projection that stopped emitting sink rows would
    # have swapped the source with nothing to show for it.
    sink_total = _as_int(summary.get("sinks"))
    governed_total = _as_int(summary.get("governed_sinks"))
    active_total = _as_int(summary.get("active_violations"))
    suppressed_total = _as_int(summary.get("suppressed_violations"))
    candidate_total = _as_int(summary.get("candidates"))

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
    candidate_details: list[str] = []
    for item in strong_candidates[:_CANDIDATE_ROW_LIMIT]:
        producers = [
            text
            for value in _as_sequence(item.get("producers"))
            for text in (str(value).strip(),)
            if text
        ]
        propose_summary, propose_body = _candidate_promotion_html(item)
        candidate_rows.append(
            (
                _candidate_owner_html(producers[0] if producers else ""),
                str(item.get("level", "")).replace("_", " "),
                str(_as_int(item.get("score"))),
                _candidate_producers_html(producers),
                propose_summary,
            )
        )
        candidate_details.append(propose_body)

    enabled = bool(summary.get("enforcement_enabled"))
    unresolved_governed = sum(
        1
        for item in governed
        if str(item.get("authority_status", "")).strip() == "unavailable"
    )
    answer, tone = _authority_answer(
        enabled=enabled,
        active=active_total,
        suppressed=suppressed_total,
        registry_contracts=_as_int(summary.get("registry_contracts")),
        governed_total=governed_total,
        unresolved_total=unresolved_governed,
        candidate_total=candidate_total,
    )
    governed_panel = render_rows_table(
        family=GLOSSARY_FAMILY_AUTHORITY,
        headers=("Contract", "Sink", "Status", "Resolution", "Why"),
        rows=governed_rows,
        empty_message="No governed semantic sinks.",
        column_types={"Status": "status"},
        ctx=ctx,
    )
    active_panel = render_rows_table(
        family=GLOSSARY_FAMILY_AUTHORITY,
        headers=("Contract", "Kind", "Sink", "Canonical owner"),
        rows=violation_rows,
        empty_message="No semantic-authority violations.",
        ctx=ctx,
    )
    suppressed_panel = render_rows_table(
        family=GLOSSARY_FAMILY_AUTHORITY,
        headers=("Contract", "Kind", "Sink", "Rule"),
        rows=suppressed_rows,
        empty_message="No suppressed semantic-authority findings.",
        ctx=ctx,
    )
    # The caption was five facts in one paragraph, in a reading measure that
    # left a ragged half-width column floating over a full-width table. Each
    # fact now sits where it is actually read: the lead and the shown-of-total
    # count on the table's own meta band, the level distribution as a count
    # strip, the governance rule as a tooltip on Propose, and the route to the
    # held-back levels as a footnote under the table. Nothing was dropped, and
    # the sink population is no longer said twice -- the Discovery stat card
    # already carries it.
    shown = len(candidate_rows)
    candidate_panel = (
        _candidate_meta_html(shown, candidate_total)
        + _level_strip_html(candidates)
        + render_rows_table(
            family=GLOSSARY_FAMILY_AUTHORITY,
            headers=("Owner", "Level", "Score", "Producers", "Propose"),
            rows=candidate_rows,
            empty_message="No semantic-authority discovery candidates.",
            raw_html_headers=("Owner", "Producers", "Propose"),
            column_types={"Score": "meter_neutral", "Level": "chips"},
            row_details=candidate_details,
            ctx=ctx,
        )
        + _candidate_cut_note_html(candidates)
    )
    # The narrative contract: the answer first, then the numbers a reader acts
    # on, then the evidence. Until now this panel jumped from the answer
    # straight into four tabs, so the counts lived only as tab badges.
    cards = [
        _stat_card(
            "Violations",
            active_total,
            detail=_micro_badges(("suppressed", suppressed_total)),
            value_tone="bad" if active_total else "good",
            glossary_tip_fn=_TIP,
        ),
        _stat_card(
            "Governed contracts",
            _as_int(summary.get("registry_contracts")),
            detail=_micro_badges(("owners", governed_total)),
            value_tone="muted" if not enabled else "",
            glossary_tip_fn=_TIP,
        ),
        _stat_card(
            "Discovery",
            candidate_total,
            detail=_micro_badges(("sinks examined", sink_total or "n/a")),
            value_tone="muted",
            glossary_tip_fn=_TIP,
        ),
        _stat_card(
            "Unresolved owners",
            unresolved_governed,
            secondary=f"of {governed_total}" if governed_total else "",
            value_tone="warn" if unresolved_governed else "good",
            glossary_tip_fn=_TIP,
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
            family=GLOSSARY_FAMILY_AUTHORITY,
            group_id="semantic-authority",
            tabs=(
                ("violations", "Violations", active_total, active_panel),
                ("governed", "Contracts", governed_total, governed_panel),
                ("candidates", "Discovery", candidate_total, candidate_panel),
                ("suppressed", "Suppressed", suppressed_total, suppressed_panel),
            ),
        )
    )


__all__ = ["render_authority_panel"]
