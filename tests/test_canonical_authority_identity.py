# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""KAT pins of the class-B authority identity formulas and their one owner.

Every hex literal here is a known answer captured from the pre-extraction
producer (``codeclone.semantics.authority`` at 5b520c08) or from the frozen
corpus (``CORPUS-BEFORE`` @ 1b8dd024, md5 78376f0f6725613df24dbd39a4aa7a5a,
where the formula recomputed 6 266 of 6 266 candidate ids).  Mutating any
formula component — domain prefix, separator, revision namespace, producer
sorting — turns a literal red; refreshing a literal to make a test pass is
an identity-contract break and needs its own review.
"""

from __future__ import annotations

import json

import pytest

from codeclone.canonical import (
    CanonicalModelError,
    WireDecodeError,
    authority_identity,
    candidate_handle,
    candidate_total_order_key,
    decode_canonical_json,
    encode_canonical_json,
    legacy_symbol_key,
    violation_handle,
)
from codeclone.semantics import authority
from tests.test_canonical_roundtrip import fixture_model

# Captured from the pre-extraction producer at 5b520c08.
_CANDIDATE_KAT = "86e20912c73db0d1f9ca4aab3be184ccb575cc99864b70b07a15446757a9216c"
_VIOLATION_KAT_BYPASS = (
    "c438fb943d6dfa6c44d766ec6b3cf1d9decdf8dcc6a3791422bc33a306dc7c7b"
)
_VIOLATION_KAT_SHADOW = (
    "3b7d367be61bb82b71f7fce9c8fc2150d878bf57aa3fbce2066e2ca98b0fb50a"
)
_KAT_PRODUCERS = ("pkg.a:A.run", "tools/b.py:helper")


def test_candidate_handle_kat_pins_the_formula() -> None:
    assert (
        candidate_handle(
            level="exact_contract_ir",
            shared_fact="contract_ir:sig-a",
            producers=_KAT_PRODUCERS,
        )
        == _CANDIDATE_KAT
    )


def test_candidate_handle_reproduces_a_frozen_corpus_row() -> None:
    """Natural key and id copied verbatim from CORPUS-BEFORE, where the
    formula reproduced all 6 266 stored candidate ids."""
    assert (
        candidate_handle(
            level="same_output_fact_and_input_family",
            shared_fact="inputs=;outputs=event:15",
            producers=(
                "benchmarks.run_benchmark:_run_cli_once",
                "codeclone.analysis.blast_radius:compute_blast_radius",
            ),
        )
        == "09435c7a712d32bb78bd97edb702e6f51d1a81fabaa2e1ea19b2f0b9063a5b16"
    )


def test_candidate_handle_canonicalizes_producer_order() -> None:
    """The natural key holds a producer SET: insertion order is not identity."""
    assert candidate_handle(
        level="exact_contract_ir",
        shared_fact="contract_ir:sig-a",
        producers=tuple(reversed(_KAT_PRODUCERS)),
    ) == candidate_handle(
        level="exact_contract_ir",
        shared_fact="contract_ir:sig-a",
        producers=_KAT_PRODUCERS,
    )


def test_violation_handle_kats_pin_the_formula_and_distinguish_kinds() -> None:
    bypass = violation_handle(
        contract_id="governance.report_write",
        kind="owner_bypass",
        sink_identity="pkg.a:A.run",
        producers=_KAT_PRODUCERS,
    )
    shadow = violation_handle(
        contract_id="governance.report_write",
        kind="shadow_projection",
        sink_identity="pkg.a:A.run",
        producers=_KAT_PRODUCERS,
    )
    assert bypass == _VIOLATION_KAT_BYPASS
    assert shadow == _VIOLATION_KAT_SHADOW
    assert bypass != shadow


def test_candidate_and_violation_domains_are_separated() -> None:
    """One preimage under two domain prefixes must never share a digest."""
    assert candidate_handle(
        level="x", shared_fact="y", producers=("z",)
    ) != violation_handle(contract_id="x", kind="y", sink_identity="z", producers=())


def test_total_order_key_is_the_public_handle() -> None:
    assert candidate_total_order_key(
        level="exact_contract_ir",
        shared_fact="contract_ir:sig-a",
        producers=_KAT_PRODUCERS,
    ) == candidate_handle(
        level="exact_contract_ir",
        shared_fact="contract_ir:sig-a",
        producers=_KAT_PRODUCERS,
    )


def test_the_authority_producer_calls_the_owner_not_a_second_spelling() -> None:
    """One formula owner (F-3 §5.1, §8.0): the producer module binds the
    owner's functions and defines no local SHA over the same preimage."""
    bindings = vars(authority)
    assert bindings["candidate_handle"] is authority_identity.candidate_handle
    assert bindings["violation_handle"] is authority_identity.violation_handle
    assert (
        authority._candidate_id(
            level="exact_contract_ir",
            producers=_KAT_PRODUCERS,
            shared_fact="contract_ir:sig-a",
        )
        == _CANDIDATE_KAT
    )
    assert (
        authority._violation_id(
            contract_id="governance.report_write",
            kind="owner_bypass",
            sink_identity="pkg.a:A.run",
            producers=_KAT_PRODUCERS,
        )
        == _VIOLATION_KAT_BYPASS
    )


def test_legacy_symbol_key_is_a_tuple_join_owned_here() -> None:
    assert legacy_symbol_key("pkg.a", "A.run") == "pkg.a:A.run"
    assert legacy_symbol_key("tools/b.py", "helper") == "tools/b.py:helper"


def test_wire_emits_the_violation_kats_from_the_fixture() -> None:
    """The fixture violations carry exactly the KAT natural keys, so the
    wire column must carry exactly the KAT hex literals — producer,
    projector and this pin cannot drift apart independently."""
    document = json.loads(encode_canonical_json(fixture_model()))
    assert document["facts"]["violations"]["violation_id"] == [
        _VIOLATION_KAT_BYPASS,
        _VIOLATION_KAT_SHADOW,
    ]


def test_wire_candidate_ids_verify_against_the_owner() -> None:
    document = json.loads(encode_canonical_json(fixture_model()))
    ids = document["facts"]["candidates"]["candidate_id"]
    assert len(ids) == 2
    assert len(set(ids)) == 2
    assert ids == [
        candidate_handle(
            level="exact",
            shared_fact="shared",
            producers=("pkg.a:A.run", "pkg.a:A.stop"),
        ),
        candidate_handle(
            level="exact",
            shared_fact="shared",
            producers=("pkg.a:A.run", "tools/b.py:helper"),
        ),
    ]


def _tampered_handle(data: bytes, handle: str) -> bytes:
    text = data.decode("utf-8")
    assert text.count(handle) == 1
    flipped = ("0" if handle[0] != "0" else "1") + handle[1:]
    return text.replace(handle, flipped).encode("utf-8")


def test_decoder_refuses_a_tampered_violation_handle_with_w25() -> None:
    payload = encode_canonical_json(fixture_model())
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(_tampered_handle(payload, _VIOLATION_KAT_BYPASS))
    assert caught.value.code == "W25"


def test_decoder_refuses_a_tampered_candidate_handle_with_w25() -> None:
    payload = encode_canonical_json(fixture_model())
    document = json.loads(payload)
    handle = document["facts"]["candidates"]["candidate_id"][0]
    with pytest.raises(WireDecodeError) as caught:
        decode_canonical_json(_tampered_handle(payload, handle))
    assert caught.value.code == "W25"


def test_projection_refuses_an_ambiguous_file_module_relation() -> None:
    """A file with two modules has no deterministic legacy head; the handle
    projection fails closed instead of guessing an identity."""
    from codeclone.canonical import FileId, FileModuleRelation, ModuleId, SymbolId
    from codeclone.canonical.codec import legacy_symbol_keys

    fa = FileId("pkg/a.py")
    with pytest.raises(CanonicalModelError, match="unambiguous"):
        legacy_symbol_keys(
            {SymbolId(fa, "A.run")},
            frozenset(
                {
                    FileModuleRelation(fa, ModuleId("pkg.a")),
                    FileModuleRelation(fa, ModuleId("mounted.a")),
                }
            ),
        )
