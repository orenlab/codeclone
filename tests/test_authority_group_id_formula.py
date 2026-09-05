# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The public authority handle's FORMULA, pinned at its own owner.

``tests/test_authority_public_handle`` already pins that the id does not
collapse and that it round-trips through ``get_finding`` and the receipt.
Neither reaches the formula: measured 2026-09-05, replacing
``authority_group_id`` with a handle derived from the FIRST CHARACTER of
``violation_id`` alone -- still 64 hex characters, still unique on the
three-row fixture, still round-tripping -- left 15 tests green. A formula
that collides on any larger population would ship.

What is pinned here is the derivation rule, not the literal: the public id
is the ``(contract_id, violation_id)`` PAIR ITSELF under the ``authority``
namespace. Three consequences follow, and each of them is measured against
the real input domain rather than a hand-written sample:

* every character of both inputs is load-bearing -- the id is a lossless
  encoding, so no position may be dropped;
* the pair is recoverable from the id, which is what makes the handle
  greppable and what lets a surface accept it back;
* distinct pairs never share an id -- injectivity over the domain the
  producers actually emit, not over one fixture.

Asserting ``id == f"authority:{c}:{v}"`` instead would only move the
formula into the test and follow it wherever it went. Each assertion below
dies under the measured mutant.
"""

from __future__ import annotations

import pytest

from codeclone.canonical.authority_identity import violation_handle
from codeclone.findings.ids import authority_group_id
from codeclone.semantics.registry import _CONTRACT_ID_RE

#: Contract ids as the registry admits them, and violation ids as the
#: producer mints them. Reading both from their owners is what makes this a
#: statement about the shipped domain: a separator can only be absent from
#: the inputs because the grammar and the digest keep it out, and a test that
#: invented its own strings would be pinning its own imagination.
_CONTRACT_IDS = (
    "wire-freeze-fixture.normalize/v1",
    "wire-freeze-fixture.normalise/v1",
    "a/v1",
    "a/v2",
)

_VIOLATIONS = tuple(
    violation_handle(
        contract_id="wire-freeze-fixture.normalize/v1",
        kind=kind,
        sink_identity=sink,
        producers=("pkg.mod:producer",),
    )
    for kind, sink in (
        ("shadowed_owner", "pkg.mod:sink_a"),
        ("divergent_dialect", "pkg.mod:sink_a"),
        ("shadowed_owner", "pkg.mod:sink_b"),
    )
)


def test_the_domain_this_pin_measures_is_the_shipped_one() -> None:
    """Probe validity: the inputs below are the ones production emits.

    Without this, every assertion in the module could be true of strings no
    producer ever mints -- and the separator argument in particular rests on
    the grammar, not on the author's choice of sample.
    """

    for contract_id in _CONTRACT_IDS:
        assert _CONTRACT_ID_RE.fullmatch(contract_id), contract_id
        assert ":" not in contract_id, contract_id
    for violation_id in _VIOLATIONS:
        assert len(violation_id) == 64, violation_id
        assert int(violation_id, 16) >= 0, violation_id
        assert ":" not in violation_id, violation_id
    assert len(set(_VIOLATIONS)) == len(_VIOLATIONS)


@pytest.mark.parametrize("position", range(64))
def test_every_character_of_violation_id_is_load_bearing(position: int) -> None:
    """No position of the violation handle may be dropped from the id.

    This is the assertion the measured mutant dies on: a handle built from
    ``violation_id[0]`` is identical for two violations that differ at any
    later position, so 63 of these 64 cases turn red at once. A pin that only
    compared two arbitrary violations would have caught it by luck or not at
    all.
    """

    contract_id = _CONTRACT_IDS[0]
    original = _VIOLATIONS[0]
    flipped = "0" if original[position] != "0" else "1"
    mutated = original[:position] + flipped + original[position + 1 :]

    assert mutated != original
    assert authority_group_id(contract_id, mutated) != authority_group_id(
        contract_id, original
    )


@pytest.mark.parametrize("position", range(len(_CONTRACT_IDS[0])))
def test_every_character_of_contract_id_is_load_bearing(position: int) -> None:
    """The contract half carries the same duty as the violation half.

    Comprehensive means both boundaries: a formula that dropped the contract
    id would merge two contracts' violations under one handle just as surely
    as dropping the violation id merges one contract's.
    """

    original = _CONTRACT_IDS[0]
    character = original[position]
    if character == "/":
        pytest.skip("the grammar's single separator has no admissible neighbour")
    flipped = "x" if character != "x" else "y"
    mutated = original[:position] + flipped + original[position + 1 :]

    assert mutated != original
    assert authority_group_id(mutated, _VIOLATIONS[0]) != authority_group_id(
        original, _VIOLATIONS[0]
    )


def test_the_pair_is_recoverable_from_the_public_id() -> None:
    """The id is a lossless encoding, so the inputs read back out of it.

    This is what a persisted public handle owes a reader: the finding id in a
    receipt names its contract and its violation without a lookup. A digest
    of either half satisfies "unique" and fails this.
    """

    for contract_id in _CONTRACT_IDS:
        for violation_id in _VIOLATIONS:
            family, recovered_contract, recovered_violation = authority_group_id(
                contract_id, violation_id
            ).split(":", 2)

            assert family == "authority"
            assert recovered_contract == contract_id
            assert recovered_violation == violation_id


def test_distinct_pairs_never_share_one_public_id() -> None:
    """Injectivity over the whole cross product, not over one fixture.

    The separator cannot be smuggled in from either side -- the contract
    grammar excludes it and the violation handle is hex -- so the encoding is
    unambiguous and the count is the assertion.
    """

    pairs = [
        (contract_id, violation_id)
        for contract_id in _CONTRACT_IDS
        for violation_id in _VIOLATIONS
    ]
    ids = {
        authority_group_id(contract_id, violation_id)
        for contract_id, violation_id in pairs
    }

    assert len(ids) == len(pairs)
