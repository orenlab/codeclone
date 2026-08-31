# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The one versioned owner of the class-B authority identity formulas.

``candidate_identity_contract.v1`` and ``violation_identity_contract.v1``
(F-3 SS5.1, SS8.0): a derived value that affects selection, identity,
ordering, compatibility, or an externally persistent reference is
contract-derived semantic state — its formula has exactly one versioned
authority even when the value is never stored.  The authority producer
(``codeclone.semantics.authority``) and the canonical wire projector both
call this module; neither carries a second spelling of the SHA.

Inputs are the producer's own key strings: a producer or sink is named by
its legacy ModuleKey-headed key ``{head}:{qualname}`` where the head is the
registry module name of the symbol's file, or the analysis path for the
measured module-less files (``lossless_normalization=YES`` on the frozen
corpus, F-3 SS2.1.8).  Producer order is canonicalized here — the natural
key contains a producer *set*, so the handle sorts before hashing; the
authority producer already emits sorted tuples, byte-identically.

The candidate namespace fact (F-3 SS5.1): ``AUTHORITY_ANALYSIS_REVISION``
is part of both preimages, so candidates and violations of different
analysis revisions never share an identity.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Final

from codeclone.contracts import AUTHORITY_ANALYSIS_REVISION

CANDIDATE_IDENTITY_CONTRACT: Final = "candidate_identity_contract.v1"
VIOLATION_IDENTITY_CONTRACT: Final = "violation_identity_contract.v1"

# Domain-separation prefixes of the two preimages. Moved verbatim from the
# authority producer; changing a byte here is a breaking identity-contract
# change (violation ids persist in review receipts).
_AUTHORITY_DOMAIN: Final = b"ccsem1:authority\x00"
_AUTHORITY_VIOLATION_DOMAIN: Final = b"ccsem1:authority-violation\x00"


#: The closed level score table of ``candidate_identity_contract.v1``.
#: The registry already declares ``score`` CONTRACT_DERIVED under this
#: contract with ``stored=False`` — a strict function of ``level``, so the
#: rank lives with the contract and never becomes a stored column.
_CANDIDATE_LEVEL_SCORES: Final[dict[str, int]] = {
    "exact_contract_ir": 5,
    "same_effect_signature": 4,
    "same_output_fact_and_input_family": 3,
    "overlapping_transform_chain": 2,
    "divergent_projection": 1,
}


def candidate_level_score(level: str) -> int:
    """The contract's rank of one discovery-candidate level."""
    return _CANDIDATE_LEVEL_SCORES[level]


def legacy_symbol_key(head: str, qualname: str) -> str:
    """The producer's symbol key grammar: ``{head}:{qualname}``.

    The head slot is one string with a fallback, never two schemes: the
    registry module name when the file has one, the analysis path for the
    measured module-less files (F-3 SS2.1.2).
    """
    return f"{head}:{qualname}"


def _handle(domain: bytes, parts: tuple[str, ...], producers: Iterable[str]) -> str:
    wire = "\x00".join((AUTHORITY_ANALYSIS_REVISION, *parts, *sorted(producers)))
    return hashlib.sha256(domain + wire.encode("utf-8")).hexdigest()


def candidate_handle(*, level: str, shared_fact: str, producers: Iterable[str]) -> str:
    """Public wire handle of one authority candidate.

    ``sha256`` over ``(revision, level, shared_fact, *sorted(producers))``
    with the candidate domain prefix — the natural key
    ``(level, shared_fact, PRODUCER_SET)`` under the analysis-revision
    namespace.  Never stored; emitted on the wire and recomputed only here.
    """
    return _handle(_AUTHORITY_DOMAIN, (level, shared_fact), producers)


def candidate_total_order_key(
    *, level: str, shared_fact: str, producers: Iterable[str]
) -> str:
    """The totality tail of candidate orderings.

    Today the tail IS the public handle — the producer's sink selection and
    both metrics orderings sort by the same digest, and owning the tail and
    the handle in one place is what keeps them incapable of drifting apart
    (F-3 SS5.1: the tail belongs to the same contract as the handle).
    """
    return candidate_handle(level=level, shared_fact=shared_fact, producers=producers)


def violation_handle(
    *, contract_id: str, kind: str, sink_identity: str, producers: Iterable[str]
) -> str:
    """Public finding-facing handle of one authority violation.

    ``sha256`` over ``(revision, contract_id, kind, sink_identity,
    *sorted(producers))`` with the violation domain prefix.  This handle has
    persistent external obligations: it rides ``authority_group_id`` into
    the public finding id, is accepted back by MCP, and settles in review
    receipts — changing the formula is a breaking change of audit artifacts.
    """
    return _handle(
        _AUTHORITY_VIOLATION_DOMAIN, (contract_id, kind, sink_identity), producers
    )
