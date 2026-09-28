# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The comparison and evaluation tiers on the canonical wire (epoch E4).

Canonical epochs E2 and E3 carried the two houses as model and store state
only; the wire of their revision had no member for them.  The generation
bump emits both, as the two root members after ``facts``::

    format · revisions · values · domains · sets · scope · facts ·
    comparison · evaluation · integrity

Each member names every family of its house, in sorted order, even when the
house is empty: an unwitnessed run is a ``comparison`` member whose witness
record is ``{}`` -- "not witnessed by this artifact" -- never an absent
member that a reader could take for "not emitted by this revision".  A
record family is one object of its stored fields; a row family is one
column per stored field.  The cells are the store's own row form (one
owner, :mod:`codeclone.canonical.tier_storage`), so what the wire says of a
run and what the store holds of it are one spelling.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from codeclone.canonical import (
    CanonicalModelError,
    ComparisonFacts,
    EvaluationFacts,
    RunStore,
    WireDecodeError,
    decode_canonical_json,
    encode_canonical_json,
    export_run,
)
from codeclone.canonical import codec as codec_module
from codeclone.canonical.registry import (
    COMPARISON_FAMILY_FIELDS,
    COMPARISON_RECORD_FAMILIES,
    EVALUATION_FAMILY_FIELDS,
    EVALUATION_RECORD_FAMILIES,
    comparison_stored_fields,
    evaluation_stored_fields,
)
from codeclone.canonical.tier_storage import comparison_house, tier_families
from codeclone.contracts import CANONICAL_WIRE_REVISION
from tests.test_canonical_roundtrip import (
    comparison_fixture_facts,
    comparison_fixture_model,
    evaluated_fixture_model,
    fixture_model,
)

_TIERS = (
    ("comparison", COMPARISON_FAMILY_FIELDS, COMPARISON_RECORD_FAMILIES),
    ("evaluation", EVALUATION_FAMILY_FIELDS, EVALUATION_RECORD_FAMILIES),
)


def _stored_fields(tier: str, family: str) -> list[str]:
    if tier == "comparison":
        return list(comparison_stored_fields(family))
    return list(evaluation_stored_fields(family))


def _resealed(document: dict[str, object]) -> bytes:
    """Serialize an edited document and seal it again, so the edit -- not
    the seal -- is what a reader has to refuse."""
    body = json.dumps(
        {key: value for key, value in document.items() if key != "integrity"},
        ensure_ascii=False,
        separators=(",", ":"),
    )[1:-1]
    domain = f"cc-canonical-wire:{CANONICAL_WIRE_REVISION}\x00".encode()
    digest = hashlib.sha256(domain + body.encode("utf-8")).hexdigest()
    return (
        "{" + body + f',"integrity":{{"algorithm":"sha256","value":"{digest}"}}}}'
    ).encode("utf-8")


def test_the_root_carries_both_tiers_after_facts() -> None:
    document = json.loads(encode_canonical_json(fixture_model()))
    assert list(document) == [
        "format",
        "revisions",
        "values",
        "domains",
        "sets",
        "scope",
        "facts",
        "comparison",
        "evaluation",
        "integrity",
    ]


@pytest.mark.parametrize(("tier", "families", "records"), _TIERS)
def test_an_unwitnessed_run_names_every_family_empty(
    tier: str, families: dict[str, object], records: frozenset[str]
) -> None:
    """Four-state law: the member is present, every family is named, a record
    is ``{}`` and a row family is its declared columns, each empty."""
    member = json.loads(encode_canonical_json(fixture_model()))[tier]
    assert list(member) == sorted(families)
    for family in families:
        if family in records:
            assert member[family] == {}, family
        else:
            assert member[family] == {
                column: [] for column in _stored_fields(tier, family)
            }, family


def test_the_wire_carries_the_comparison_house_and_reads_it_back() -> None:
    compared = comparison_fixture_model()
    data = encode_canonical_json(compared)
    assert data != encode_canonical_json(fixture_model())
    member = json.loads(data)["comparison"]
    assert member["baseline_witness"] != {}
    decoded = decode_canonical_json(data)
    assert decoded.facts.comparison == compared.normalize().facts.comparison
    assert decoded == compared.normalize()


def test_the_wire_carries_the_evaluation_house_and_reads_it_back() -> None:
    evaluated = evaluated_fixture_model()
    data = encode_canonical_json(evaluated)
    document = json.loads(data)
    assert document["evaluation"]["gate_outcome"] != {}
    assert document["comparison"]["health_delta"]["value"] != []
    decoded = decode_canonical_json(data)
    assert decoded.facts.evaluation == evaluated.normalize().facts.evaluation
    assert decoded == evaluated.normalize()


@pytest.mark.parametrize(("tier", "families", "records"), _TIERS)
def test_every_emitted_cell_is_a_declared_stored_field(
    tier: str, families: dict[str, object], records: frozenset[str]
) -> None:
    member = json.loads(encode_canonical_json(evaluated_fixture_model()))[tier]
    populated = 0
    for family in families:
        cells = member[family]
        if family in records and cells == {}:
            continue
        populated += 1
        assert list(cells) == _stored_fields(tier, family), family
    assert populated, "the fixture populates no family of this tier"


@pytest.mark.parametrize("tier", ["comparison", "evaluation"])
def test_a_document_without_a_tier_member_is_refused(tier: str) -> None:
    document = json.loads(encode_canonical_json(evaluated_fixture_model()))
    del document[tier]
    with pytest.raises(WireDecodeError) as refusal:
        decode_canonical_json(_resealed(document))
    assert refusal.value.code == "W01"


def test_a_foreign_generation_is_refused_at_the_fence_before_its_shape() -> None:
    """A document of another wire generation is named as such (``W21``)
    even though its root lacks the tier members this generation declares:
    the fence runs before the shape is judged."""
    document = json.loads(encode_canonical_json(fixture_model()))
    del document["comparison"]
    del document["evaluation"]
    document["format"] = {"name": "codeclone-canonical", "wire": "0"}
    with pytest.raises(WireDecodeError) as refusal:
        decode_canonical_json(_resealed(document))
    assert refusal.value.code == "W21"


def test_a_malformed_tier_cell_is_refused_typed() -> None:
    document = json.loads(encode_canonical_json(evaluated_fixture_model()))
    comparison = document["comparison"]
    assert isinstance(comparison["baseline_witness"]["loaded"], bool)
    comparison["baseline_witness"]["loaded"] = "yes"
    with pytest.raises(WireDecodeError) as refusal:
        decode_canonical_json(_resealed(document))
    assert refusal.value.code == "W27"
    assert "loaded" in refusal.value.detail


def test_a_tier_row_breaking_its_house_law_is_refused_typed() -> None:
    """Every cell well formed, the house unlawful: a novelty row naming a
    container the run was not compared against."""
    document = json.loads(encode_canonical_json(evaluated_fixture_model()))
    novelty = document["comparison"]["clone_novelty"]
    assert novelty["root_digest"], "the fixture states no clone novelty"
    novelty["root_digest"] = ["f" * 64 for _ in novelty["root_digest"]]
    with pytest.raises(WireDecodeError) as refusal:
        decode_canonical_json(_resealed(document))
    assert refusal.value.code == "W28"


def test_the_bounded_export_streams_both_tiers(tmp_path: Path) -> None:
    """The store's per-family export births the same bytes as the model's
    encoding, both tiers included, and a run without them exports other
    bytes."""
    evaluated = evaluated_fixture_model()
    with RunStore(tmp_path / "runs.sqlite3") as store:
        full = store.write_full_run(
            evaluated, namespace="e4", target="full", expected_generation=0
        ).run_id
        plain = store.write_full_run(
            fixture_model(), namespace="e4", target="plain", expected_generation=0
        ).run_id
        full_sink, plain_sink = io.BytesIO(), io.BytesIO()
        full_envelope = export_run(store, full, full_sink)
        plain_envelope = export_run(store, plain, plain_sink)
        assert full_sink.getvalue() == store.project_run(full)
    assert full_sink.getvalue() == encode_canonical_json(evaluated)
    assert full_sink.getvalue() != plain_sink.getvalue()
    assert full_envelope.artifact_digest != plain_envelope.artifact_digest


def test_the_decoded_empty_houses_are_the_unwitnessed_run() -> None:
    decoded = decode_canonical_json(encode_canonical_json(fixture_model()))
    assert decoded.facts.comparison == ComparisonFacts()
    assert decoded.facts.evaluation == EvaluationFacts()
    assert decoded == replace(fixture_model().normalize())


def test_the_tier_family_list_is_the_registry_and_the_store() -> None:
    """One list, three views that may not drift: every declared family of
    each house has exactly one wire family, and the store's export streams
    exactly their storage families."""
    from codeclone.canonical import store as store_module
    from codeclone.canonical.tier_storage import TIER_FAMILIES

    assert [family.name for family in tier_families("comparison")] == sorted(
        COMPARISON_FAMILY_FIELDS
    )
    assert [family.name for family in tier_families("evaluation")] == sorted(
        EVALUATION_FAMILY_FIELDS
    )
    assert {entry.family for entry in store_module._TIER_FAMILIES} == {
        family.stored for family in TIER_FAMILIES
    }
    assert {family.name for family in TIER_FAMILIES} == set(
        ComparisonFacts.__annotations__
    ) | set(EvaluationFacts.__annotations__)


def test_a_tier_family_with_ragged_columns_is_refused_typed() -> None:
    document = json.loads(encode_canonical_json(evaluated_fixture_model()))
    lanes = document["comparison"]["lane_trust"]
    assert lanes["lane"], "the fixture states no lane trust"
    lanes["lane"] = lanes["lane"][:-1]
    with pytest.raises(WireDecodeError) as refusal:
        decode_canonical_json(_resealed(document))
    assert refusal.value.code == "W15"


def test_a_tier_cell_outside_the_signed_range_is_refused_at_encoding() -> None:
    """Reachability of the signed range: a delta the analysis tables could
    never carry is still bounded -- one past the top is refused, never
    written."""
    evaluated = evaluated_fixture_model()
    comparison = evaluated.facts.comparison
    (delta,) = comparison.health_delta
    too_large = replace(delta, value=2**31)
    model = replace(
        evaluated,
        facts=replace(
            evaluated.facts,
            comparison=replace(comparison, health_delta=frozenset({too_large})),
        ),
    )
    with pytest.raises(CanonicalModelError, match="integer out of wire range"):
        encode_canonical_json(model)


def test_a_row_that_is_not_its_declared_columns_is_refused_at_encoding() -> None:
    lane_trust = next(
        family for family in tier_families("comparison") if family.name == "lane_trust"
    )
    with pytest.raises(CanonicalModelError, match="not the declared stored fields"):
        codec_module._tier_family_member(lane_trust, [{"lane": "clones.functions"}])


def test_the_house_assembly_refuses_a_foreign_row_and_a_second_record() -> None:
    witness = comparison_fixture_facts().baseline_witness
    with pytest.raises(CanonicalModelError, match="carries a str"):
        comparison_house({"lane_trust": ["not a row"]})
    with pytest.raises(CanonicalModelError, match="more than one record"):
        comparison_house({"baseline_witness": [witness, witness]})
