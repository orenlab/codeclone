# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""R3 door: the typed records a presentation ring holds per report document.

The HTML report context used to project two of its fields into
``types.SimpleNamespace``. That is a type eraser: every attribute read off one
is ``Any``, so the thirteen ``Any`` parameters in the structural panel and the
two in the suggestions panel were consequences of the choice rather than
decisions of their own -- writing ``SimpleNamespace`` there would have said
exactly as little. Thirty-eight fields reached the renderers unchecked, and an
inventory that greps for ``Any`` cannot see any of it, because the widest
``Any`` in the package contains no ``Any`` token.

The records live here rather than beside their projection because the frozen
import graph decides placement, not readability preference. ``codeclone.report``
is ``r2`` and ``codeclone.report.html`` is ``r4``; ``r4`` may reach ``r0``,
``r1``, ``r3`` and ``r4`` and nothing else, and the boundary ratchet also counts
every typed record declared outside the model store. Declaring these four in the
presentation ring would have grown that ratchet by four entries, and importing
the two structural records straight from ``codeclone.models`` would have grown
it by an ``r4 -> r2`` edge. This module is the ``r3`` door both constraints
leave: it may read the model store, and the presentation ring may read it.

Two of the four records already existed. ``StructuralFindingGroup`` and
``StructuralFindingOccurrence`` are the shape the structural detector produces
*and* the shape the report helpers outside the presentation ring already
declare in their signatures -- ``report/findings.py``, ``report/derived.py`` and
``report/suggestions.py`` all say so. While the panel handed them a namespace
those declarations were unenforced by construction: the argument was ``Any``, so
no checker compared it against anything. Re-exporting the records here makes
them enforced for the first time, and a second parallel record would have made
the same claim twice instead.

The two suggestion records are new because no existing one is true of them.
``models.Suggestion`` narrows severity, category, effort, confidence, family and
source kind to ``Literal`` alternatives; the projection carries whatever string
the document holds, and narrowing it would turn an unknown value into either a
crash or a silently different verdict -- a presentation projection is not the
place to decide that. These records state what the projection actually carries.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import StructuralFindingGroup, StructuralFindingOccurrence


@dataclass(frozen=True, kw_only=True, slots=True)
class SuggestionLocationView:
    """One representative location of a suggestion, as its panel reads it.

    The document publishes exactly five keys per location
    (``report/document/derived.py::_representative_location_rows``); the sixth
    field is the absolute path the projection derives for the IDE link.
    """

    relative_path: str
    start_line: int
    end_line: int
    qualname: str
    source_kind: str
    filepath: str


@dataclass(frozen=True, kw_only=True, slots=True)
class SuggestionView:
    """One suggestion of a report document, as its panel reads it."""

    severity: str
    category: str
    title: str
    location: str
    steps: tuple[str, ...]
    effort: str
    priority: float
    finding_family: str
    finding_kind: str
    subject_key: str
    fact_kind: str
    fact_summary: str
    fact_count: int
    spread_files: int
    spread_functions: int
    clone_type: str
    confidence: str
    source_kind: str
    #: Pairs as the document holds them. The panel reads element ``0`` as a
    #: source-kind label and element ``1`` as a count, and coercing either here
    #: would change what the panel prints for a value the producer never emits.
    source_breakdown: tuple[tuple[object, ...], ...]
    representative_locations: tuple[SuggestionLocationView, ...]
    location_label: str


__all__ = [
    "StructuralFindingGroup",
    "StructuralFindingOccurrence",
    "SuggestionLocationView",
    "SuggestionView",
]
