# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The ``unit_spans`` family: why it exists, and that it holds.

A source span is an IDENTITY/EXTENT fact about a declaration, not an
observation about it.  ``RiskObservationRow`` carries ``start_line`` only
because, until this family existed, there was no declaration entity to point
at -- its own docstring calls that "the named exception to the rule that
location is evidence".

The placement argument is written here as EXECUTABLE tests rather than left in
a docstring, because reasoning that is not run is read as taste.  The load
bearer is :func:`test_the_risk_key_cannot_police_a_span_but_the_span_key_can`:
under a key carrying ``dimension``, two rows of ONE declaration may hold
CONTRADICTING spans and the model's own uniqueness prover never meets them --
they do not share a key.  Measured on the self-repo tree @ 4512acf0
(2026-09-03): 6 675 of 15 934 declarations carry two risk rows, so the hole is
reachable on the real population, not hypothetical.
"""

from __future__ import annotations

import dataclasses
import hashlib

import orjson
import pytest

import codeclone.canonical.codec as codec_module
from codeclone.canonical import (
    AnalysisFacts,
    CanonicalFacts,
    CanonicalModel,
    FileId,
    RiskObservationRow,
    SymbolId,
    UnitSpanRow,
)
from codeclone.canonical.codec import decode_canonical_json, encode_canonical_json
from codeclone.canonical.errors import CanonicalModelError, WireDecodeError
from codeclone.canonical.identity import canonical_key
from codeclone.canonical.model import _unique_by_key

_FILE = FileId("pkg/mod.py")
_SYMBOL = SymbolId(_FILE, "make")


def _model(*spans: UnitSpanRow) -> CanonicalModel:
    return CanonicalModel(
        analyzed_files=frozenset({_FILE}),
        facts=CanonicalFacts(analysis=AnalysisFacts(unit_spans=frozenset(spans))),
    ).normalize()


# ---------------------------------------------------------------------------
# The owner exists, and it is its OWN family.
# ---------------------------------------------------------------------------


def test_the_analysis_house_names_a_unit_span_owner() -> None:
    """A per-declaration source span has a family of its own."""
    names = {f.name for f in dataclasses.fields(AnalysisFacts)}
    assert "unit_spans" in names


def test_the_span_owner_carries_both_ends_of_the_range() -> None:
    fields = {f.name for f in dataclasses.fields(UnitSpanRow)}
    assert fields == {"symbol", "start_line", "end_line"}


def test_the_span_row_defaults_nothing() -> None:
    """A fact ROW requires every field; only containers may default.

    The sibling rule this repository already learned once: shipping a row
    field without a default is a GUARANTEE, and a guarantee no test holds is
    removable in silence.
    """
    for declared in dataclasses.fields(UnitSpanRow):
        assert declared.default is dataclasses.MISSING, declared.name
        assert declared.default_factory is dataclasses.MISSING, declared.name


# ---------------------------------------------------------------------------
# THE placement argument, executable.
# ---------------------------------------------------------------------------


def test_the_risk_key_cannot_police_a_span_but_the_span_key_can() -> None:
    """Why the span is not a column of ``risk_observations``.

    Two rows of ONE declaration that differ only in ``dimension`` carry
    CONTRADICTING spans.  Under the risk key the prover never meets them; under
    the declaration key it refuses them.  The positive control in the middle is
    what makes the first half evidence instead of an unexercised claim: the
    SAME prover does refuse a contradiction that shares its key, so a silent
    pass above is blindness, not a broken probe.
    """

    @dataclasses.dataclass(frozen=True, slots=True)
    class _RiskRowWithSpan:
        symbol: SymbolId
        dimension: str
        numerator: int
        start_line: int
        end_line: int

    def risk_key(row: _RiskRowWithSpan) -> tuple[object, ...]:
        return (canonical_key(row.symbol), row.dimension, row.start_line)

    def span_key(row: _RiskRowWithSpan) -> tuple[object, ...]:
        return (canonical_key(row.symbol), row.start_line)

    contradiction = (
        _RiskRowWithSpan(_SYMBOL, "cyclomatic_complexity", 3, 10, end_line=42),
        _RiskRowWithSpan(_SYMBOL, "nesting_depth", 2, 10, end_line=999),
    )

    # Blind: the two rows do not share the risk key, so nothing is refused.
    _unique_by_key(contradiction, "risk observation", risk_key)

    # POSITIVE CONTROL: the same prover, the same rows, one shared key.
    same_dimension = (
        _RiskRowWithSpan(_SYMBOL, "cyclomatic_complexity", 3, 10, end_line=42),
        _RiskRowWithSpan(_SYMBOL, "cyclomatic_complexity", 3, 10, end_line=999),
    )
    with pytest.raises(CanonicalModelError, match="one logical key"):
        _unique_by_key(same_dimension, "risk observation", risk_key)

    # The declaration key carries no dimension, so it DOES meet them.
    with pytest.raises(CanonicalModelError, match="one logical key"):
        _unique_by_key(contradiction, "unit span", span_key)


def test_two_declarations_sharing_one_qualname_stay_two_spans() -> None:
    """``start_line`` is a key component, and it earns it.

    ``@overload`` families and property/setter pairs are different
    declarations wearing one name; a site-blind key would collapse them.
    """
    model = _model(UnitSpanRow(_SYMBOL, 10, 24), UnitSpanRow(_SYMBOL, 40, 52))
    assert len(model.facts.analysis.unit_spans) == 2


def test_one_declaration_cannot_hold_two_different_spans() -> None:
    with pytest.raises(CanonicalModelError, match=r"unit_spans\.key"):
        _model(UnitSpanRow(_SYMBOL, 10, 24), UnitSpanRow(_SYMBOL, 10, 25))


# ---------------------------------------------------------------------------
# The row law: both directions of an impossible span, under DIFFERENT tests.
# ---------------------------------------------------------------------------


def test_a_span_that_loses_its_end_is_refused() -> None:
    """Boundary A -- FORGETTING.  An end before its own start is not a range;
    a row that admitted it would let the store answer ``end_line`` with a
    value the source never had."""
    with pytest.raises(CanonicalModelError, match="not before its start"):
        UnitSpanRow(_SYMBOL, 10, 9)


def test_a_span_whose_end_was_never_measured_is_refused() -> None:
    """Boundary A, the zero case: a dropped end reads as 0, and 0 is not a
    line.  Spelled separately from the test above because a producer that
    LOSES an end and one that INVERTS it are different defects."""
    with pytest.raises(CanonicalModelError, match="not before its start"):
        UnitSpanRow(_SYMBOL, 10, 0)


def test_a_span_minted_where_no_declaration_stands_is_refused() -> None:
    """Boundary B -- INVENTING.  A zero site would spell "no declaration" as
    a declaration."""
    with pytest.raises(CanonicalModelError, match="positive int"):
        UnitSpanRow(_SYMBOL, 0, 12)


def test_a_boolean_is_not_a_line_number() -> None:
    with pytest.raises(CanonicalModelError, match="positive int"):
        UnitSpanRow(_SYMBOL, True, 12)


def test_a_one_line_declaration_is_admitted() -> None:
    """The DEGENERATE span is legal and must stay legal: ``end == start`` is a
    real one-line declaration, and 156 of 15 934 units carry one @ 4512acf0.
    Without this the refusal above would be free to over-reach."""
    assert UnitSpanRow(_SYMBOL, 10, 10).end_line == 10


# ---------------------------------------------------------------------------
# Round trip: what goes in comes back, and the pin can FAIL.
# ---------------------------------------------------------------------------


def test_the_span_survives_the_wire_unchanged() -> None:
    model = _model(UnitSpanRow(_SYMBOL, 10, 24), UnitSpanRow(_SYMBOL, 40, 40))
    assert decode_canonical_json(encode_canonical_json(model)) == model


def _resealed(data: bytes, needle: str, replacement: str) -> bytes:
    """Corrupt the body and reseal integrity, so the span law is what refuses
    -- not the integrity digest standing in front of it."""
    text = data.decode("utf-8")
    body, _, _tail = text.partition(',"integrity":')
    assert body.count(needle) == 1, f"needle not unique: {needle!r}"
    new_body = body.replace(needle, replacement)[1:]
    digest = hashlib.sha256(
        codec_module._INTEGRITY_DOMAIN + new_body.encode("utf-8")
    ).hexdigest()
    return (
        "{" + new_body + f',"integrity":{{"algorithm":"sha256","value":"{digest}"}}}}'
    ).encode("utf-8")


def test_a_span_shortened_on_the_wire_is_refused_by_the_decoder() -> None:
    """Mutation, direction 1: the stored end SHRINKS below its start."""
    payload = encode_canonical_json(_model(UnitSpanRow(_SYMBOL, 10, 24)))
    tampered = _resealed(payload, '"end_line":[24]', '"end_line":[9]')
    with pytest.raises(WireDecodeError, match="before"):
        decode_canonical_json(tampered)


def test_a_span_stretched_on_the_wire_changes_what_decodes() -> None:
    """Mutation, direction 2: the stored end GROWS.

    A longer span is a legal span, so the decoder cannot refuse it -- and that
    is exactly why this direction needs its own test: the guarantee here is
    that the value is CARRIED, so a stretched end must come back stretched and
    the round-trip equality above must be able to notice.
    """
    model = _model(UnitSpanRow(_SYMBOL, 10, 24))
    payload = encode_canonical_json(model)
    tampered = _resealed(payload, '"end_line":[24]', '"end_line":[9999]')
    decoded = decode_canonical_json(tampered)
    assert decoded != model
    assert {row.end_line for row in decoded.facts.analysis.unit_spans} == {9999}


def test_the_span_is_not_reconstructed_from_the_risk_family() -> None:
    """The two families are independent: a run may carry risk rows whose
    declarations have no span, and the model must not invent one.  A pin that
    passed because the span was silently derived from ``start_line`` would be
    hollow, and this is what refuses that reading.
    """
    model = CanonicalModel(
        analyzed_files=frozenset({_FILE}),
        facts=CanonicalFacts(
            analysis=AnalysisFacts(
                risk_observations=frozenset(
                    {RiskObservationRow(_SYMBOL, "cyclomatic_complexity", 7, 10)}
                )
            )
        ),
    ).normalize()
    assert model.facts.analysis.unit_spans == frozenset()


def test_the_wire_carries_the_family_even_when_it_is_empty() -> None:
    """ "Measured empty" and "not carried" are different statements, and the
    wire says the first one."""
    payload = orjson.loads(encode_canonical_json(_model()))
    assert "unit_spans" in payload["facts"]
