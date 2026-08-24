# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Candidate ordering tails come from ``candidate_identity_contract.v1``.

Backend wave 4, element (b): the three legacy ordering sites — the sink
selection tie-break in ``semantics/authority.py``, the items sort of the
semantic-authority metrics payload, and the items sort of the metrics
document — obtain their totality tail from the one formula owner
(``candidate_total_order_key``), never from the ``candidate_id`` string
stored on the row.  A stored string can drift from the owner (tampered
artifact, stale document, future formula revision); the owner cannot.

Fixture law (F-3 §6.2): every fixture makes the correct and the
substituted answer incapable of coinciding.  The tampered ``candidate_id``
strings are constructed *opposite* to the owner-key order, so a site that
still reads the stored string gives the reversed order, verbatim.
"""

from __future__ import annotations

import pytest

from codeclone.canonical.authority_identity import candidate_total_order_key
from codeclone.core.metrics_payload import _semantic_authority_payload
from codeclone.models import (
    AuthorityCandidate,
    AuthorityGraph,
    ContractIRBuildResult,
    SemanticAuthorityResult,
)
from codeclone.report.document.metrics import _normalize_metrics_families
from codeclone.semantics.authority import _candidate_for_sink

_SHARED_FUNCTION = "codeclone.pkg:shared_producer"

#: Tampered handles: lexical order is fixed and extreme, so whichever owner
#: order the natural keys produce, assigning ``_TAMPER_LOW`` to the
#: owner-larger row makes the stored-string order the exact reverse.
_TAMPER_LOW = "0" * 64
_TAMPER_HIGH = "f" * 64


def _owner_key(*, level: str, shared_fact: str, producers: tuple[str, ...]) -> str:
    return candidate_total_order_key(
        level=level, shared_fact=shared_fact, producers=producers
    )


def _tampered_pair(
    *,
    level: str = "same_effect_signature",
    score: int = 4,
    shared_facts: tuple[str, str] = ("fact:alpha", "fact:beta"),
    producers: tuple[str, ...] = (_SHARED_FUNCTION, "codeclone.pkg:other"),
) -> tuple[AuthorityCandidate, AuthorityCandidate]:
    """Two candidates whose stored ids order opposite to their owner keys.

    Returns ``(owner_min, owner_max)``: the candidate whose *owner* key
    sorts first carries the lexically largest tampered id, and vice versa.
    """

    key_a = _owner_key(level=level, shared_fact=shared_facts[0], producers=producers)
    key_b = _owner_key(level=level, shared_fact=shared_facts[1], producers=producers)
    assert key_a != key_b, "distinguishing fixture requires distinct owner keys"
    first_fact, second_fact = (
        (shared_facts[0], shared_facts[1])
        if key_a < key_b
        else (shared_facts[1], shared_facts[0])
    )
    owner_min = AuthorityCandidate(
        candidate_id=_TAMPER_HIGH,
        level=level,  # type: ignore[arg-type]
        score=score,
        producers=producers,
        shared_fact=first_fact,
        independence=True,
        semantic_divergence=False,
        sink_statuses=("shadow",) * len(producers),  # type: ignore[arg-type]
    )
    owner_max = AuthorityCandidate(
        candidate_id=_TAMPER_LOW,
        level=level,  # type: ignore[arg-type]
        score=score,
        producers=producers,
        shared_fact=second_fact,
        independence=True,
        semantic_divergence=False,
        sink_statuses=("shadow",) * len(producers),  # type: ignore[arg-type]
    )
    return owner_min, owner_max


def _payload_items(
    payload: dict[str, object], *, item_kind: str
) -> list[dict[str, object]]:
    items = payload["items"]
    assert isinstance(items, list)
    return [item for item in items if item["item_kind"] == item_kind]


def _payload_result(
    candidates: tuple[AuthorityCandidate, ...],
) -> SemanticAuthorityResult:
    return SemanticAuthorityResult(
        algorithm_revision="test-rev",
        contract_ir=ContractIRBuildResult(contracts=(), sccs=(), fixpoint_iterations=0),
        graph=AuthorityGraph(nodes=(), edges=()),
        sinks=(),
        candidates=candidates,
    )


# ── site 1: sink selection tie-break (semantics/authority.py) ─────────


def test_sink_selection_tie_break_uses_owner_key_not_stored_id() -> None:
    owner_min, owner_max = _tampered_pair()
    selected = _candidate_for_sink(_SHARED_FUNCTION, candidates=(owner_max, owner_min))
    assert selected is not None
    # The stored strings order the other way round by construction; only
    # the owner key selects this row.
    assert selected.shared_fact == owner_min.shared_fact
    assert selected.candidate_id == _TAMPER_HIGH


@pytest.mark.parametrize("high_first", [True, False])
def test_sink_selection_score_dominates_owner_tail(high_first: bool) -> None:
    """Both boundaries of the primary term: the higher score wins whichever
    side of the owner-key order it sits on."""

    owner_min, owner_max = _tampered_pair()
    low, high = (owner_min, owner_max) if high_first else (owner_max, owner_min)
    import dataclasses

    high = dataclasses.replace(high, score=5, level="exact_contract_ir")
    selected = _candidate_for_sink(_SHARED_FUNCTION, candidates=(low, high))
    assert selected is not None
    assert selected.shared_fact == high.shared_fact


# ── site 2: metrics payload items sort (core/metrics_payload.py) ──────


def test_payload_items_order_by_owner_key_not_stored_id() -> None:
    owner_min, owner_max = _tampered_pair()
    payload = _semantic_authority_payload(_payload_result((owner_max, owner_min)))
    items = _payload_items(payload, item_kind="candidate")
    assert [item["shared_fact"] for item in items] == [
        owner_min.shared_fact,
        owner_max.shared_fact,
    ]


def test_payload_tail_is_total_without_the_stored_id() -> None:
    """Untampered rows differing only in the natural key still order by the
    owner key — a site that drops the tail keeps insertion order instead."""

    owner_min, owner_max = _tampered_pair()
    import dataclasses

    honest_min = dataclasses.replace(
        owner_min,
        candidate_id=_owner_key(
            level=owner_min.level,
            shared_fact=owner_min.shared_fact,
            producers=owner_min.producers,
        ),
    )
    honest_max = dataclasses.replace(
        owner_max,
        candidate_id=_owner_key(
            level=owner_max.level,
            shared_fact=owner_max.shared_fact,
            producers=owner_max.producers,
        ),
    )
    payload = _semantic_authority_payload(_payload_result((honest_max, honest_min)))
    items = _payload_items(payload, item_kind="candidate")
    assert [item["shared_fact"] for item in items] == [
        honest_min.shared_fact,
        honest_max.shared_fact,
    ]


# ── site 3: metrics document items sort (report/document/metrics.py) ──


def _document_candidate_item(candidate: AuthorityCandidate) -> dict[str, object]:
    return {
        "item_kind": "candidate",
        "candidate_id": candidate.candidate_id,
        "level": candidate.level,
        "score": candidate.score,
        "producers": list(candidate.producers),
        "shared_fact": candidate.shared_fact,
        "independence": candidate.independence,
        "semantic_divergence": candidate.semantic_divergence,
        "sink_statuses": list(candidate.sink_statuses),
        "algorithm_revision": "test-rev",
    }


def _document_items(
    items: list[dict[str, object]],
) -> list[dict[str, object]]:
    families = _normalize_metrics_families(
        {
            "semantic_authority": {
                "summary": {"enabled": True},
                "items": items,
                "registry": [],
                "contract_ir": [],
            }
        },
        scan_root="/repo",
    )
    section = families["semantic_authority"]
    assert isinstance(section, dict)
    return list(section["items"])


def test_document_items_order_by_owner_key_not_stored_id() -> None:
    owner_min, owner_max = _tampered_pair()
    ordered = _document_items(
        [_document_candidate_item(owner_max), _document_candidate_item(owner_min)]
    )
    assert [item["shared_fact"] for item in ordered] == [
        owner_min.shared_fact,
        owner_max.shared_fact,
    ]


def test_document_non_candidate_rows_keep_the_empty_tail() -> None:
    """Non-candidate rows carry no candidate natural key; their tail stays
    empty and equal rows keep insertion order (stable sort).  A site that
    hashes every row would reorder — or refuse — these two."""

    base = {
        "item_kind": "violation",
        "violation_id": "v-1",
        "contract_id": "contract-a",
        "kind": "owner_bypass",
        "sink_identity": "codeclone.pkg:sink",
        "canonical_owner": "codeclone.pkg:owner",
        "authority_status": "shadow",
        "producer_root_ids": [],
        "effect_signature": "sig",
        "resolution_state": "resolved",
        "suppressed": False,
        "locations": [],
        "sink_statuses": [],
        "algorithm_revision": "test-rev",
    }
    first = dict(base, producers=["codeclone.pkg:p1"])
    second = dict(base, producers=["codeclone.pkg:p2"])
    # Same length producer lists, so every declared key term is equal and
    # only a fabricated tail could tell them apart.
    tail_first = _owner_key(level="", shared_fact="", producers=("codeclone.pkg:p1",))
    tail_second = _owner_key(level="", shared_fact="", producers=("codeclone.pkg:p2",))
    assert tail_first != tail_second
    if tail_first < tail_second:
        first, second = second, first
    # Insertion order deliberately puts the row with the *larger* fabricated
    # tail first: a mutant that hashes non-candidate rows must swap them.
    ordered = _document_items([first, second])
    assert [item["producers"] for item in ordered] == [
        first["producers"],
        second["producers"],
    ]


def test_payload_non_candidate_rows_keep_the_empty_tail() -> None:
    """Payload twin of the document pin: two violations on one sink are
    tie-broken by nothing, so insertion order survives — unless a mutant
    fabricates a tail for rows that own none."""

    from codeclone.models import AuthorityViolation

    def violation(producers: tuple[str, ...]) -> AuthorityViolation:
        return AuthorityViolation(
            violation_id="v-" + producers[0],
            contract_id="contract-a",
            kind="owner_bypass",
            sink_identity="codeclone.pkg:sink",
            canonical_owner="codeclone.pkg:owner",
            authority_status="shadow",
            producer_root_ids=(),
            effect_signature="sig",
            resolution_state="resolved",
            producers=producers,
            suppressed=False,
            locations=(),
        )

    tail_p1 = _owner_key(level="", shared_fact="", producers=("codeclone.pkg:p1",))
    tail_p2 = _owner_key(level="", shared_fact="", producers=("codeclone.pkg:p2",))
    assert tail_p1 != tail_p2
    ordered_producers = (
        (("codeclone.pkg:p2",), ("codeclone.pkg:p1",))
        if tail_p1 < tail_p2
        else (("codeclone.pkg:p1",), ("codeclone.pkg:p2",))
    )
    result = SemanticAuthorityResult(
        algorithm_revision="test-rev",
        contract_ir=ContractIRBuildResult(contracts=(), sccs=(), fixpoint_iterations=0),
        graph=AuthorityGraph(nodes=(), edges=()),
        sinks=(),
        candidates=(),
        violations=tuple(violation(p) for p in ordered_producers),
    )
    payload = _semantic_authority_payload(result)
    items = _payload_items(payload, item_kind="violation")
    observed: list[tuple[str, ...]] = []
    for item in items:
        producers_value = item["producers"]
        assert isinstance(producers_value, list)
        observed.append(tuple(producers_value))
    assert observed == list(ordered_producers)
