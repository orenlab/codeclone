# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The authority row projections: canonical facts → the public row shape.

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

The sink and violation rows follow, under the same law and with the same
obligation to be measured rather than declared.  The nine unrepresented
SINK columns all close: three are the function contract's, read off the
stored graph node the producer built from the same entry (14 837/14 837
self-repo rows and 292/292 corpus rows byte-identical, 0 disagreements);
the rest are a ranking term, a provenance label and four union
placeholders.  The seven VIOLATION columns close too, but not all the
same way: six were derivable and one, ``locations``, was measured NOT
derivable — so it was CANONICALIZED rather than projected, and the row
stores it now (:data:`VIOLATION_UNPROJECTED_COLUMNS` records what that
changed here).  This module renders the stored witness back into the
published struct: the path from the site's own variant, ``start_line``
from its line, ``end_line`` from the same line (a semantic event carries
one line, never a span) and ``qualname`` from the violation's own
``sink_identity``, the string the producer stamps on every row of its
per-function location table.  With that, ``authority.violations`` joins
``authority.sinks`` at ``equivalent``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from codeclone.canonical.authority_identity import (
    candidate_handle,
    candidate_level_score,
    candidate_total_order_key,
    violation_handle,
)
from codeclone.canonical.codec import legacy_symbol_keys
from codeclone.canonical.errors import CanonicalModelError
from codeclone.canonical.identity import ProducerRoot, SourceLocation, SymbolId
from codeclone.canonical.model import (
    CandidateRow,
    CanonicalModel,
    SinkRoleRow,
    ViolationRow,
)
from codeclone.canonical.semantic_grammar import (
    format_root_set,
    format_source_location,
)
from codeclone.contracts import AUTHORITY_ANALYSIS_REVISION
from codeclone.domain.source_scope import SOURCE_KIND_ORDER, SOURCE_KIND_OTHER
from codeclone.paths import classify_source_kind
from codeclone.utils.coerce import as_int, as_sequence

CANDIDATE_ROW_PROJECTION_CONTRACT: Final = "candidate_row_projection.v1"
SINK_ROW_PROJECTION_CONTRACT: Final = "sink_row_projection.v1"
VIOLATION_ROW_PROJECTION_CONTRACT: Final = "violation_row_projection.v1"

#: The published violation columns this projection does NOT emit -- EMPTY.
#: ``locations`` was the one entry, and the reason it stood here is the
#: reason it is gone: under S8.V.3 a value whose derivation basis lies
#: outside the stored subset is a CANONICALIZATION decision, not a
#: projection gap.  The producer distils it from
#: ``FunctionContractSummary.events`` -- the first three source sites of the
#: sink's own events -- and that event stream is no family of the wave-1..4
#: model, so the column is STORED now (``ViolationRow.locations``, a tuple
#: of tagged ``SourceLocation`` witnesses) and this projection renders it
#: from the model like every other column.  The tuple stays declared and
#: empty rather than deleted: it is what the equivalence lane reads to say
#: the gap is zero, and a future column with no stored basis lands here
#: instead of being silently absent.
VIOLATION_UNPROJECTED_COLUMNS: Final[tuple[str, ...]] = ()

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

    __slots__ = ("_edges", "_resolution", "_roots", "_signature", "_unresolved")

    def __init__(self, model: CanonicalModel) -> None:
        facts = model.facts.analysis
        self._signature = {
            node.function: node.effect_signature for node in facts.graph_nodes
        }
        self._resolution = {
            node.function: node.resolution_state for node in facts.graph_nodes
        }
        self._roots = {node.function: node.root_set for node in facts.graph_nodes}
        self._unresolved = {
            node.function: node.resolution_state == "unavailable"
            for node in facts.graph_nodes
        }
        edges: dict[SymbolId, list[SymbolId]] = {}
        for edge in facts.semantic_edges:
            edges.setdefault(edge.source, []).append(edge.target)
        self._edges = edges

    def sink_columns(
        self, symbol: SymbolId, legacy: Mapping[SymbolId, str]
    ) -> tuple[list[str], str, str]:
        """The three published sink columns the SINK role does not own.

        ``SinkRoleRow`` carries only what the role itself owns -- the symbol
        and the status weakest over its groups.  The other three are the
        contract's, and the producer reads them off exactly the same
        ``by_function[...]`` entry it built the graph node from
        (``semantics/authority.py``: ``provenance_roots``,
        ``effect_signatures[function]``, and the same ``unresolved``
        ternary).  Same expression, same place -- so the basis is INSIDE
        the subset and the value is derived, not stored twice.
        """

        self.require_known(frozenset({symbol}))
        return (
            format_root_set(self._roots[symbol], legacy),
            self._signature[symbol],
            self._resolution[symbol],
        )

    def producer_root_targets(self) -> set[SymbolId]:
        """Every SYMBOL a stored root set names, so its legacy key exists.

        A ``ProducerRoot`` names a symbol that need not be a sink, a
        candidate producer or a violation party; rendering its row without
        that key would raise ``KeyError`` deep inside the formatter instead
        of failing where the population is decided.
        """

        return {
            root.target
            for root_set in self._roots.values()
            for root in root_set
            if isinstance(root, ProducerRoot)
        }

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


def _sink_row(
    row: SinkRoleRow,
    *,
    graph: _AuthorityGraphView,
    legacy: Mapping[SymbolId, str],
) -> dict[str, object]:
    """One published sink row, union placeholders included.

    Nine columns of this row are not on ``SinkRoleRow``.  Three are the
    contract's, read off the graph node the producer built from the same
    entry (:meth:`_AuthorityGraphView.sink_columns`).  ``source_kind`` is
    the document layer's ranking term over ``producers`` -- and a sink row
    carries none, so the owner is asked with an empty group rather than
    told the answer.  ``algorithm_revision`` is run provenance.  The
    remaining four are the union container's placeholders: the authority
    producer emits no ``score``, ``independence``, ``semantic_divergence``
    or ``suppressed`` key on a sink item at all, so the document builder's
    ``_as_int(None)`` / ``bool(None)`` settle them for every sink in every
    configuration.
    """

    producer_root_ids, effect_signature, resolution_state = graph.sink_columns(
        row.symbol, legacy
    )
    return {
        "item_kind": "sink",
        "sink_identity": legacy[row.symbol],
        "violation_id": "",
        "contract_id": "",
        "kind": "",
        "canonical_owner": "",
        "authority_status": row.authority_status,
        "producer_root_ids": producer_root_ids,
        "effect_signature": effect_signature,
        "resolution_state": resolution_state,
        "unresolved_reasons": [],
        "candidate_id": "",
        "level": "",
        "score": 0,
        "producers": [],
        "shared_fact": "",
        "source_kind": producer_source_kind(()),
        "independence": False,
        "semantic_divergence": False,
        "suppressed": False,
        "locations": [],
        "sink_statuses": [],
        "algorithm_revision": AUTHORITY_ANALYSIS_REVISION,
    }


def sink_projection_rows(model: CanonicalModel) -> tuple[dict[str, object], ...]:
    """Rebuild the published sink rows from canonical facts alone.

    The document builder sorts the whole union by ``(item_kind,
    contract_id, sink_identity, kind, -score, source_kind, -len(producers),
    candidate tail)``.  Every one of those terms except ``sink_identity``
    is constant across sink rows, and ``sink_identity`` is unique per sink
    (the producer keys its sinks by function), so the order is total and
    settled by that single term.
    """

    facts = model.facts.analysis
    graph = _AuthorityGraphView(model)
    legacy = legacy_symbol_keys(
        {row.symbol for row in facts.sink_roles} | graph.producer_root_targets(),
        model.file_modules,
    )
    return tuple(
        sorted(
            (_sink_row(row, graph=graph, legacy=legacy) for row in facts.sink_roles),
            key=lambda row: str(row["sink_identity"]),
        )
    )


def _violation_location(
    location: SourceLocation, *, qualname: str
) -> dict[str, object]:
    """One stored evidence site as the published location struct.

    Two of the four slots are derived rather than read, and each has its
    owner cited rather than assumed.  ``end_line`` repeats ``start_line``
    because the producer builds both from ``event.location[1]`` and
    ``SemanticEvent.location`` is ``(path, int)`` -- one line, no span.
    ``qualname`` is the violation's own sink: the producer keys its
    location table by ``summary.function``, stamps that same string on every
    row of the entry, then hands the SINK's entry to the violation.
    Neither derivation is left to rot -- the projection equivalence compares
    this struct against the report's own byte for byte, so a producer that
    grew a real span, or a second qualname, turns that comparison red
    instead of drifting quietly.
    """

    return {
        "relative_path": format_source_location(location),
        "start_line": location.line,
        "end_line": location.line,
        "qualname": qualname,
    }


def _violation_row(
    row: ViolationRow,
    *,
    legacy: Mapping[SymbolId, str],
) -> dict[str, object]:
    """One published violation row -- every column, none exempt.

    ``producer_root_ids`` is stored outright (``root_set``); ``locations``
    is stored outright too -- the canonicalized evidence witness, rendered
    by :func:`_violation_location`.  ``source_kind`` is the document
    layer's ranking term over the stored producer set,
    ``algorithm_revision`` is run provenance, and ``score``,
    ``independence`` and ``semantic_divergence`` are union placeholders the
    producer emits no key for on a violation item.
    """

    sink_identity = legacy[row.sink_identity]
    producers = sorted(legacy[producer] for producer in row.producer_set)
    return {
        "item_kind": "violation",
        "sink_identity": sink_identity,
        "violation_id": violation_handle(
            contract_id=row.contract_id,
            kind=row.kind,
            sink_identity=sink_identity,
            producers=producers,
        ),
        "contract_id": row.contract_id,
        "kind": row.kind,
        "canonical_owner": legacy[row.canonical_owner],
        "authority_status": row.authority_status,
        "producer_root_ids": format_root_set(row.root_set, legacy),
        "effect_signature": row.effect_signature,
        "resolution_state": row.resolution_state,
        "unresolved_reasons": [],
        "candidate_id": "",
        "level": "",
        "score": 0,
        "producers": producers,
        "shared_fact": "",
        "source_kind": producer_source_kind(producers),
        "independence": False,
        "semantic_divergence": False,
        "suppressed": row.suppressed,
        "locations": [
            _violation_location(location, qualname=sink_identity)
            for location in row.locations
        ],
        "sink_statuses": [],
        "algorithm_revision": AUTHORITY_ANALYSIS_REVISION,
    }


def _violation_document_order(row: Mapping[str, object]) -> tuple[object, ...]:
    """The document builder's violation ordering, restricted to violations.

    ``item_kind`` and ``-score`` are constant here, and the candidate tail
    is empty for every non-candidate item, so the builder's key reduces to
    the terms below.  The last term is NOT one of the builder's: the
    builder leans on a stable sort over the producer's own order, which is
    ``(contract_id, kind, sink_identity, violation_id)`` -- so within a
    group that ties on everything above, the surviving discriminator is the
    handle.  Spelling it out makes the order total instead of inherited
    from a list this projection never saw.
    """

    return (
        str(row["contract_id"]),
        str(row["sink_identity"]),
        str(row["kind"]),
        SOURCE_KIND_ORDER.get(str(row["source_kind"]), len(SOURCE_KIND_ORDER)),
        -len(as_sequence(row["producers"])),
        str(row["violation_id"]),
    )


def violation_projection_rows(model: CanonicalModel) -> tuple[dict[str, object], ...]:
    """Rebuild the published violation rows from canonical facts alone."""

    facts = model.facts.analysis
    graph = _AuthorityGraphView(model)
    symbols = {
        symbol
        for row in facts.violations
        for symbol in (row.sink_identity, row.canonical_owner, *row.producer_set)
    }
    roots = {
        root.target
        for row in facts.violations
        for root in row.root_set
        if isinstance(root, ProducerRoot)
    }
    legacy = legacy_symbol_keys(
        symbols | roots | graph.producer_root_targets(), model.file_modules
    )
    return tuple(
        sorted(
            (_violation_row(row, legacy=legacy) for row in facts.violations),
            key=_violation_document_order,
        )
    )


__all__ = [
    "CANDIDATE_PRODUCER_STATUSES",
    "CANDIDATE_ROW_PROJECTION_CONTRACT",
    "SINK_ROW_PROJECTION_CONTRACT",
    "VIOLATION_ROW_PROJECTION_CONTRACT",
    "VIOLATION_UNPROJECTED_COLUMNS",
    "candidate_projection_rows",
    "producer_source_kind",
    "sink_projection_rows",
    "violation_projection_rows",
]
