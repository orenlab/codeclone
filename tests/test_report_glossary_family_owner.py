# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A glossary term answers for the family that asked, or stays silent.

Measured on the flat namespace these pins replace: ``suppressed``, ``kind``
and ``modules`` each reached two or three report families through one
definition, so the clone tab and the semantic-authority tab both explained
themselves as dead code.

Every expectation here is a literal written in this file. None of them reads
the definition back out of ``FAMILY_TERMS`` or ``SHARED_TERMS``: a pin that
takes its expectation from the table it is checking survives any swap of that
table and proves nothing.
"""

from __future__ import annotations

import pytest

from codeclone.report.html.widgets.glossary import glossary_tip
from codeclone.report.html.widgets.tables import render_rows_table
from codeclone.report.html.widgets.tabs import render_split_tabs
from codeclone.report.messages.glossary import (
    FAMILY_TERMS,
    GLOSSARY_FAMILIES,
    GLOSSARY_FAMILY_AUTHORITY,
    GLOSSARY_FAMILY_CLONES,
    GLOSSARY_FAMILY_COUPLING,
    GLOSSARY_FAMILY_DEAD_CODE,
    GLOSSARY_FAMILY_DEPENDENCIES,
    GLOSSARY_FAMILY_MODULE_MAP,
    SHARED_TERMS,
    glossary_term,
)


def _tab_title(label: str, *, family: str) -> str:
    """The tooltip a tab button actually carries, as the reader gets it."""
    html = render_split_tabs(
        group_id="probe",
        tabs=((label.lower(), label, 3, "<p>panel</p>"),),
        family=family,
    )
    if ' title="' not in html:
        return ""
    return html.split(' title="', 1)[1].split('"', 1)[0]


def _header_tip(header: str, *, family: str) -> str:
    """The tooltip a table column header actually carries."""
    html = render_rows_table(
        headers=(header,),
        rows=[("value",)],
        empty_message="none",
        family=family,
    )
    if 'data-tip="' not in html:
        return ""
    return html.split('data-tip="', 1)[1].split('"', 1)[0]


# --- Tab consumer: both boundaries of the suppressed collision ------------


def test_clone_suppressed_tab_speaks_of_clone_groups_not_dead_code() -> None:
    title = _tab_title("Suppressed", family=GLOSSARY_FAMILY_CLONES).lower()
    assert "clone group" in title
    assert "dead code" not in title


def test_dead_code_suppressed_tab_speaks_of_dead_code_not_clone_groups() -> None:
    title = _tab_title("Suppressed", family=GLOSSARY_FAMILY_DEAD_CODE).lower()
    assert "dead code" in title
    assert "clone group" not in title


def test_authority_suppressed_tab_speaks_of_authority_findings() -> None:
    title = _tab_title("Suppressed", family=GLOSSARY_FAMILY_AUTHORITY).lower()
    assert "authority" in title
    assert "dead code" not in title
    assert "clone group" not in title


def test_each_family_gives_suppressed_its_own_wording() -> None:
    titles = [
        _tab_title("Suppressed", family=family)
        for family in (
            GLOSSARY_FAMILY_AUTHORITY,
            GLOSSARY_FAMILY_CLONES,
            GLOSSARY_FAMILY_DEAD_CODE,
        )
    ]
    assert all(titles), "every one of the three families must answer"
    assert len(set(titles)) == 3


# --- Table-header consumer: a different consumer, its own pins ------------


def test_clone_kind_column_explains_clone_kinds_not_symbol_types() -> None:
    tip = _header_tip("Kind", family=GLOSSARY_FAMILY_CLONES).lower()
    assert "clone kind" in tip
    assert "symbol type" not in tip


def test_dead_code_kind_column_explains_symbol_types_not_clone_kinds() -> None:
    tip = _header_tip("Kind", family=GLOSSARY_FAMILY_DEAD_CODE).lower()
    assert "symbol type" in tip
    assert "clone kind" not in tip


def test_authority_kind_column_explains_violation_kinds() -> None:
    tip = _header_tip("Kind", family=GLOSSARY_FAMILY_AUTHORITY).lower()
    assert "violation kind" in tip
    assert "symbol type" not in tip


def test_stat_card_tooltip_is_keyed_by_family_too() -> None:
    clones = glossary_tip("Suppressed", family=GLOSSARY_FAMILY_CLONES).lower()
    dead = glossary_tip("Suppressed", family=GLOSSARY_FAMILY_DEAD_CODE).lower()
    assert "clone group" in clones
    assert "dead code" in dead
    assert clones != dead


# --- The counted-vs-navigated split of "modules" --------------------------


def test_dependencies_counts_modules_while_the_map_zooms_to_them() -> None:
    counted = glossary_term("Modules", family=GLOSSARY_FAMILY_DEPENDENCIES).lower()
    zoomed = glossary_term("Modules", family=GLOSSARY_FAMILY_MODULE_MAP).lower()
    assert "total number" in counted
    assert "zoom" in zoomed
    assert counted != zoomed


# --- The fallback, and the silence that guards it -------------------------


def test_a_family_that_claims_nothing_still_reads_the_shared_term() -> None:
    """The fallback is reachable: a real input arrives and is answered."""
    assert "cbo" not in FAMILY_TERMS.get(GLOSSARY_FAMILY_CLONES, {})
    term = glossary_term("CBO", family=GLOSSARY_FAMILY_CLONES)
    assert "Coupling Between Objects" in term
    assert term == glossary_term("CBO", family=GLOSSARY_FAMILY_COUPLING)


def test_the_fallback_is_reached_through_a_real_consumer() -> None:
    tip = _header_tip("CBO", family=GLOSSARY_FAMILY_CLONES)
    assert "Coupling Between Objects" in tip


def test_an_unknown_family_gets_silence_not_a_neighbours_meaning() -> None:
    assert glossary_term("Suppressed", family="no_such_family") == ""
    assert glossary_term("Kind", family="no_such_family") == ""
    assert _tab_title("Suppressed", family="no_such_family") == ""


def test_an_owned_word_is_never_also_a_shared_word() -> None:
    """What makes the silence above possible, stated as the invariant."""
    for family, terms in FAMILY_TERMS.items():
        overlap = sorted(set(terms) & set(SHARED_TERMS))
        assert not overlap, f"{family} owns {overlap}, which SHARED_TERMS also defines"


def test_every_owning_family_is_a_declared_family() -> None:
    assert set(FAMILY_TERMS) <= GLOSSARY_FAMILIES


# --- The addressing is enforced, not merely available ---------------------


def test_a_consumer_cannot_key_the_glossary_by_a_bare_label() -> None:
    with pytest.raises(TypeError):
        glossary_tip("Suppressed")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        render_split_tabs(  # type: ignore[call-arg]
            group_id="probe", tabs=(("suppressed", "Suppressed", 1, ""),)
        )
    with pytest.raises(TypeError):
        render_rows_table(  # type: ignore[call-arg]
            headers=("Kind",), rows=[("v",)], empty_message="none"
        )
