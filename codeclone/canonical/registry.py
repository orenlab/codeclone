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
    """One canonical field: who owns it, what it is, and where it may appear."""

    field: str
    category: str
    owner: str
    derivation: str
    stored: bool
    wire: bool
    public_handle: bool = False


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
}


def wire_fact_family_order() -> tuple[str, ...]:
    """Wire order of fact families: mechanical, total, no manual tail."""
    return tuple(sorted(FACT_FAMILY_FIELDS))


def wire_columns(family: str) -> tuple[str, ...]:
    """Wire columns of one family, in canonical (sorted) column order."""
    return tuple(
        sorted(
            declaration.field
            for declaration in FACT_FAMILY_FIELDS[family]
            if declaration.wire and declaration.stored
        )
    )
