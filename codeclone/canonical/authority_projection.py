# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The candidate row projection: canonical facts → the public row shape.

Backend P0 step 8.  ``surfaces/mcp/_authority_candidates`` hands the report's
candidate row to its client WHOLE, so a consumer that moves onto the run
store must be able to produce every published column, not only the two its
own logic reads.  This module is the one owner of that reconstruction.

Seven columns of the published row are not stored on
:class:`~codeclone.canonical.model.CandidateRow`, and each is absent for a
different measured reason.  Three are analysis conclusions about the group
that the model already proves from other stored families; four are not
semantic values of the candidate at all:

``independence`` · ``semantic_divergence`` · ``sink_statuses``
    Conclusions of the authority producer about one candidate group, and
    strictly derivable from facts the wave-1 subset already carries:
    ``semantic_edges`` (the authority graph), ``graph_nodes.effect_signature``
    and ``graph_nodes.resolution_state``.  §8.V.3's test — derivability is a
    property of the ``(value, place)`` pair, and ``ContractRow`` carries
    ``effect_signature`` precisely BECAUSE its basis is outside the subset —
    lands the other way here: the basis is inside the subset, measured on the
    self-repo corpus at 7 317/7 317 candidate rows and 165 438 status
    entries covering all four reachable statuses, 0 disagreements.  Storing
    them would be the same fact in two places.

``score``
    A strict function of ``level`` through the closed table of
    ``candidate_identity_contract.v1``.  The registry already declares it
    CONTRACT_DERIVED with ``stored=False``; this module only reads its owner.

``source_kind``
    Born in the report document layer, never in the producer: a ranking term
    classified from ``producers`` so the order it yields can be read back
    instead of inferred.  Derived formatting of a stored column.

``algorithm_revision``
    Run-level provenance — ``AUTHORITY_ANALYSIS_REVISION``, identical on
    every authority row of a run and already inside the candidate handle's
    preimage.  A duplicated label, not a column.

``suppressed``
    The union container's boolean placeholder.  The authority producer emits
    no ``suppressed`` key on a candidate item at all; the document builder's
    ``bool(item.get("suppressed"))`` therefore yields ``False`` for every
    candidate in every configuration.  Suppression is a violation concept.

The projection reproduces the FULL published row, union placeholders
included, in the document builder's own key order and the document
builder's own candidate order — so equivalence against the report path is
decidable byte for byte rather than field by field.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from codeclone.canonical.authority_identity import (
    candidate_handle,
    candidate_level_score,
    candidate_total_order_key,
)
from codeclone.canonical.codec import legacy_symbol_keys
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import SymbolId
from codeclone.canonical.model import CandidateRow, CanonicalModel
from codeclone.contracts import AUTHORITY_ANALYSIS_REVISION
from codeclone.domain.source_scope import SOURCE_KIND_ORDER, SOURCE_KIND_OTHER
from codeclone.paths import classify_source_kind
from codeclone.utils.coerce import as_int, as_sequence

CANDIDATE_ROW_PROJECTION_CONTRACT: Final = "candidate_row_projection.v1"

#: The closed status vocabulary a candidate group assigns its producers.
#: ``authoritative`` is a sink-level verdict and is unreachable per producer
#: inside a group, so it is deliberately absent: this tuple is what the
#: projection may emit, not what a sink may hold.
CANDIDATE_PRODUCER_STATUSES: Final = ("adapter", "mixed", "shadow", "unavailable")


def producer_source_kind(producers: Sequence[str]) -> str:
    """Classify a candidate group by its most production-facing producer.

    Producers are qualnames whose module prefix is a dotted path or a file
    path, so the prefix classifies exactly like the file it names, and the
    group is ranked by its strongest member.
    """

    kinds = {
        classify_source_kind(module.replace(".", "/"))
        for producer in producers
        for module in (str(producer).partition(":")[0],)
        if module.strip()
    }
    if not kinds:
        return SOURCE_KIND_OTHER
    return min(
        kinds, key=lambda kind: SOURCE_KIND_ORDER.get(kind, len(SOURCE_KIND_ORDER))
    )


class _AuthorityGraphView:
    """The stored authority graph, read for the conclusions it settles."""

    __slots__ = ("_edges", "_signature", "_unresolved")

    def __init__(self, model: CanonicalModel) -> None:
        facts = model.facts.analysis
        self._signature = {
            node.function: node.effect_signature for node in facts.graph_nodes
        }
        self._unresolved = {
            node.function: node.resolution_state == "unavailable"
            for node in facts.graph_nodes
        }
        edges: dict[SymbolId, list[SymbolId]] = {}
        for edge in facts.semantic_edges:
            edges.setdefault(edge.source, []).append(edge.target)
        self._edges = edges

    def reaches_member(self, source: SymbolId, members: frozenset[SymbolId]) -> bool:
        """Does ``source`` reach another member of its own group?"""

        seen = {source}
        pending = list(self._edges.get(source, ()))
        while pending:
            node = pending.pop()
            if node in members and node != source:
                return True
            if node in seen:
                continue
            seen.add(node)
            pending.extend(self._edges.get(node, ()))
        return False

    def diverges(self, members: frozenset[SymbolId]) -> bool:
        """Do the group's producers disagree on their effect signature?"""

        return len({self._signature[member] for member in members}) > 1

    def status(
        self, producer: SymbolId, *, members: frozenset[SymbolId], diverges: bool
    ) -> str:
        """The producer's authority status INSIDE this candidate group.

        Group-relative, and deliberately not the sink's published status:
        a sink's is the weakest verdict over every group it belongs to.
        """

        if self.reaches_member(producer, members):
            return "mixed" if diverges else "adapter"
        if self._unresolved[producer]:
            return "unavailable"
        return "shadow"

    def require_known(self, members: frozenset[SymbolId]) -> None:
        """Refuse a group whose producers the stored graph does not name."""

        missing = sorted(
            f"{member.file.path}:{member.qualname}"
            for member in members
            if member not in self._signature
        )
        if missing:
            raise CanonicalModelError(
                "candidate projection needs a graph node for every producer; "
                f"the stored graph does not name {', '.join(missing)}"
            )


def _candidate_row(
    row: CandidateRow,
    *,
    graph: _AuthorityGraphView,
    legacy: Mapping[SymbolId, str],
) -> dict[str, object]:
    members = row.producer_set
    graph.require_known(members)
    ordered = sorted(members, key=lambda symbol: legacy[symbol])
    producers = [legacy[symbol] for symbol in ordered]
    diverges = graph.diverges(members)
    # The union container's placeholders ride in the document builder's own
    # key order: a candidate row literally carries ``violation_id: ""``
    # because the family is one union of four item kinds.
    return {
        "item_kind": "candidate",
        "sink_identity": "",
        "violation_id": "",
        "contract_id": "",
        "kind": "",
        "canonical_owner": "",
        "authority_status": "",
        "producer_root_ids": [],
        "effect_signature": "",
        "resolution_state": "",
        "unresolved_reasons": [],
        "candidate_id": candidate_handle(
            level=row.level, shared_fact=row.shared_fact, producers=producers
        ),
        "level": row.level,
        "score": candidate_level_score(row.level),
        "producers": producers,
        "shared_fact": row.shared_fact,
        "source_kind": producer_source_kind(producers),
        "independence": not any(
            graph.reaches_member(member, members) for member in members
        ),
        "semantic_divergence": diverges,
        "suppressed": False,
        "locations": [],
        "sink_statuses": [
            graph.status(member, members=members, diverges=diverges)
            for member in ordered
        ],
        "algorithm_revision": AUTHORITY_ANALYSIS_REVISION,
    }


def _document_order(row: Mapping[str, object]) -> tuple[object, ...]:
    """The document builder's candidate ordering, restricted to candidates.

    The builder sorts the whole union by ``(item_kind, contract_id,
    sink_identity, kind, ...)`` before the candidate terms; all four are
    constant across candidate rows, so the relative order of candidates is
    settled by the terms below alone.
    """

    producers = [str(value) for value in as_sequence(row["producers"])]
    return (
        -as_int(row["score"]),
        SOURCE_KIND_ORDER.get(str(row["source_kind"]), len(SOURCE_KIND_ORDER)),
        -len(producers),
        candidate_total_order_key(
            level=str(row["level"]),
            shared_fact=str(row["shared_fact"]),
            producers=producers,
        ),
    )


def candidate_projection_rows(
    model: CanonicalModel,
) -> tuple[dict[str, object], ...]:
    """Rebuild the published candidate rows from canonical facts alone."""

    facts = model.facts.analysis
    graph = _AuthorityGraphView(model)
    legacy = legacy_symbol_keys(
        {producer for row in facts.candidates for producer in row.producer_set},
        model.file_modules,
    )
    return tuple(
        sorted(
            (
                _candidate_row(row, graph=graph, legacy=legacy)
                for row in facts.candidates
            ),
            key=_document_order,
        )
    )


__all__ = [
    "CANDIDATE_PRODUCER_STATUSES",
    "CANDIDATE_ROW_PROJECTION_CONTRACT",
    "candidate_projection_rows",
    "producer_source_kind",
]
