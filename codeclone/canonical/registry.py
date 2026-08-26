# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical field declaration registry — the structural pin chosen by the
maintainer (2026-08-13): every canonical field is declared with its
epistemic class, owner, and wire obligation, and the projector emits only
declared fields.  An undeclared derived field is not something a test
catches — it is something that cannot be written.

Field classes follow the ratified three-class epistemics:

* ``analysis_fact`` — a producer established it; stored in the run snapshot.
* ``contract_derived_semantic`` — purely derivable from canonical facts plus
  a versioned contract, but participates in identity, ordering, selection,
  compatibility, or public addressing; its formula has exactly one versioned
  authority even when the value is not stored.
* ``representation_projection`` — derivable and semantically inert; never
  stored, only a representation convenience.

The wire order of fact families is born mechanically from this registry —
sorted family names, no manual tail (facts-order sanction, 2026-08-13):
declared field order exists only where earlier bytes are required to
interpret later bytes, and fact families have no such dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

ANALYSIS_FACT: Final = "analysis_fact"
CONTRACT_DERIVED: Final = "contract_derived_semantic"
REPRESENTATION: Final = "representation_projection"


@dataclass(frozen=True, slots=True)
class FieldDeclaration:
    """One canonical field: who owns it, what it is, and where it may appear.

    ``wire_shape`` names the column's wire form: ``"column"`` is a plain
    equal-length column; ``"sparse_bool_positions"`` is a boolean written as
    a strictly increasing list of true row positions, omitted when no row is
    true (F-3 §7.6 rule 3 — omitted list means no trues, so absence and
    emptiness mean the same thing and rule 1 omits the default).
    """

    field: str
    category: str
    owner: str
    derivation: str
    stored: bool
    wire: bool
    public_handle: bool = False
    wire_shape: str = "column"


# Fact families of the wave-1 canonical subset.  Keys are the wire table
# names; the wire emits them in sorted(key) order — mechanically, from this
# mapping, never from a hand-written list.
FACT_FAMILY_FIELDS: Final[dict[str, tuple[FieldDeclaration, ...]]] = {
    "candidates": (
        FieldDeclaration(
            "level",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "producer_set",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "shared_fact",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "candidate_id",
            CONTRACT_DERIVED,
            "candidate_identity_contract.v1",
            "sha256 over (revision, level, shared_fact, producers)",
            stored=False,
            wire=True,
            public_handle=True,
        ),
        FieldDeclaration(
            "score",
            CONTRACT_DERIVED,
            "candidate_identity_contract.v1",
            "closed level score table",
            stored=False,
            wire=False,
        ),
    ),
    "contracts": (
        FieldDeclaration(
            "effect_signature",
            ANALYSIS_FACT,
            "contract_ir_producer",
            "carried fact in the wave-1 subset (wire basis not carried)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "function",
            ANALYSIS_FACT,
            "contract_ir_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "root_set",
            ANALYSIS_FACT,
            "contract_ir_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "coupling_cohesion_observations": (
        FieldDeclaration(
            "dimension",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "closed vocabulary (COUPLING_COHESION_DIMENSIONS); key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "numerator",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "observed positive count; payload, never key (zero rows dropped "
            "by the producer — absence means zero)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "design_metrics_producer",
            "SYMBOL key component (measured 2091/2091 with dimension)",
            stored=True,
            wire=True,
        ),
    ),
    # The ratified dependency split (ruling 2026-08-24 §2): the relation is
    # the entity gate/SCC read; the occurrence is location evidence bound to
    # it.  ``line`` never enters the relation — location is evidence, not
    # identity.
    "dependency_occurrences": (
        FieldDeclaration(
            "binding",
            ANALYSIS_FACT,
            "dependency_producer",
            "classified binding time; occurrence payload, never key",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "dependency_type",
            ANALYSIS_FACT,
            "dependency_producer",
            "relation-triple component binding this evidence to its entity",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "is_lazy",
            ANALYSIS_FACT,
            "dependency_producer",
            "raw PEP 810 marker; occurrence payload boolean",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "line",
            ANALYSIS_FACT,
            "dependency_producer",
            "evidence location; occurrence row-key component (926 corpus "
            "collisions without it), never relation identity",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "dependency_producer",
            "relation-triple component; DependencyEndpoint MODULE | FILE",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "dependency_producer",
            "relation-triple component; DependencyEndpoint MODULE | FILE",
            stored=True,
            wire=True,
        ),
    ),
    "dependency_relations": (
        FieldDeclaration(
            "dependency_type",
            ANALYSIS_FACT,
            "dependency_producer",
            "entity-key component; closed vocabulary (IMPORT_TYPES)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "dependency_producer",
            "entity-key component; DependencyEndpoint MODULE | FILE (measured 860/1)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "dependency_producer",
            "entity-key component; DependencyEndpoint MODULE | FILE",
            stored=True,
            wire=True,
        ),
    ),
    "file_modules": (
        FieldDeclaration(
            "file",
            ANALYSIS_FACT,
            "module_registry",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "module",
            ANALYSIS_FACT,
            "module_registry",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "graph_nodes": (
        FieldDeclaration(
            "effect_signature",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "not derivable here: no wire stored beside (S8.V.3)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "function",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "output_facts",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "ordered producer emission; NOT a set (1 157/12 244 unsorted)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "resolution_state",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "root_set",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "semantic_edges": (
        FieldDeclaration(
            "source",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "target",
            ANALYSIS_FACT,
            "semantic_graph_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "sink_roles": (
        FieldDeclaration(
            "authority_status",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "not derivable: unique role fact (§8.1)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "symbol",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
    ),
    "violations": (
        FieldDeclaration(
            "authority_status",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "canonical_owner",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "governance registry declaration; no role requirement",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "contract_id",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "governance registry declaration; natural-key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "effect_signature",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "authority-effect domain digest; not derivable (S8.V.3)",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "kind",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "closed vocabulary; natural-key component",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "producer_set",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "natural-key component; FUNCTION role required",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "resolution_state",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "root_set",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "observed",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "sink_identity",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "natural-key component; FUNCTION role required",
            stored=True,
            wire=True,
        ),
        FieldDeclaration(
            "suppressed",
            ANALYSIS_FACT,
            "semantic_authority_producer",
            "inline suppression flag; payload boolean",
            stored=True,
            wire=True,
            wire_shape="sparse_bool_positions",
        ),
        FieldDeclaration(
            "violation_id",
            CONTRACT_DERIVED,
            "violation_identity_contract.v1",
            "sha256 over (revision, contract_id, kind, sink_identity, producers)",
            stored=False,
            wire=True,
            public_handle=True,
        ),
    ),
}


# ---------------------------------------------------------------------------
# Ratified future-family keys (wave-4 form) — declarations, not wire families
# ---------------------------------------------------------------------------

# F1 ``risk_observations`` — logical key of the FUTURE analysis-fact family,
# resolved by the 2026-08-24 night preflight trace (ruling 2026-08-24 §1).
#
# The measured defect: the bare ``(FILE, qualname, dimension)`` key is blind
# to 4 real entity groups (three ``@overload`` triples and one
# property/setter pair — 9 of 17 561 corpus rows lost), and every one of
# them is *different declarations sharing one name*, so deduplication is
# indefensible: a producer-native discriminator is required.
#
# The ratified discriminator is the declaration-site ``start_line``, by the
# product's own precedent: ``complexity.items`` already keys
# ``(path, qualname, start_line)`` and is 12 285/12 285 unique on the frozen
# corpus.  SOURCE OF THE FACT: ``codeclone.models.Unit`` carries
# ``start_line`` on the producer's own input; the projection
# (``observations/projection.py`` → ``IntegerObservation``) is the lossy
# step that drops it.  Wiring it through is producer work for the wave that
# introduces the family — the production projector is deliberately not
# touched by this declaration.
#
# FLAG (named fork for the maintainer, morning override): this admits the
# declaration site into an *identity* — unlike dependency occurrences,
# where location is evidence and never key (ruling §2).
RISK_OBSERVATIONS_FAMILY: Final = "risk_observations"
RISK_OBSERVATIONS_KEY: Final[tuple[str, ...]] = (
    "file",
    "qualname",
    "dimension",
    "start_line",
)


def wire_fact_family_order() -> tuple[str, ...]:
    """Wire order of fact families: mechanical, total, no manual tail."""
    return tuple(sorted(FACT_FAMILY_FIELDS))


def wire_columns(family: str) -> tuple[str, ...]:
    """Wire columns of one family, in canonical (sorted) column order.

    Every ``wire=True`` field is a wire column: stored facts are emitted
    from the model, and contract-derived handles (``stored=False``) are
    computed by the projector through the field's one formula owner —
    never by a consumer, never by a second spelling of the formula.
    """
    return tuple(
        sorted(
            declaration.field
            for declaration in FACT_FAMILY_FIELDS[family]
            if declaration.wire
        )
    )


def derived_wire_columns(family: str) -> tuple[str, ...]:
    """The family's contract-derived wire columns (emitted, never stored)."""
    return tuple(
        sorted(
            declaration.field
            for declaration in FACT_FAMILY_FIELDS[family]
            if declaration.wire and not declaration.stored
        )
    )


def sparse_bool_wire_columns(family: str) -> tuple[str, ...]:
    """The family's sparse-boolean wire columns (position lists, omitted
    when no row is true — F-3 §7.6 rules 1 and 3)."""
    return tuple(
        sorted(
            declaration.field
            for declaration in FACT_FAMILY_FIELDS[family]
            if declaration.wire and declaration.wire_shape == "sparse_bool_positions"
        )
    )
