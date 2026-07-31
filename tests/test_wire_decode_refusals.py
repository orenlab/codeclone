# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Fail-closed refusals of the cache wire decoders.

The whole wire obeys one rule, stated in ``decode_wire_unit_fact_row``: a fact
that cannot be decoded must never read as an absent fact. A warm run serves
units straight off the wire without re-parsing, so a decoder that returned an
empty result for a malformed row would turn "unknown" into a confident "none"
-- no statements would read as no near-miss pairs, no regions as nothing
unreachable. Every test here feeds one specific malformation and pins the
refusal, because the cost of a silently-lenient decoder is a wrong answer
rather than a slow one.
"""

from __future__ import annotations

import pytest

from codeclone.cache._wire_decode import (
    _apply_wire_unit_facts,
    _as_unreachable_reason,
    _as_wire_str_tuple,
    _build_unreachable_statement_item,
    _decode_binding_context_digest,
    _decode_optional_wire_class_bases,
    _decode_wire_dead_candidate,
    _decode_wire_units_with_sequences,
)
from codeclone.cache._wire_helpers import (
    _decode_optional_wire_coupled_classes,
    _decode_wire_qualname_span_size,
    _decode_wire_unit_sequence_row,
    decode_wire_unit_fact_row,
)
from codeclone.cache.entries import UnitDict

_VALID_UNIT_ROW: list[object] = [
    "pkg:a",
    1,
    2,
    10,
    3,
    "fp",
    "1-19",
    1,
    0,
    "low",
    "raw",
]

_BINDING_DOMAIN = "codeclone.cache.binding-context.v1"


def _unit(qualname: str = "pkg:a", start_line: int = 1) -> UnitDict:
    return UnitDict(
        qualname=qualname,
        filepath="a.py",
        start_line=start_line,
        end_line=start_line + 1,
        loc=2,
        stmt_count=1,
        fingerprint="fp",
        loc_bucket="1-19",
    )


# --------------------------------------------------------------------------
# _wire_helpers: the shared row framing
# --------------------------------------------------------------------------


def test_qualname_span_size_refuses_a_row_whose_span_is_malformed() -> None:
    """The size is only read once the span behind it decoded."""

    assert _decode_wire_qualname_span_size([1, 2, 3, 4]) is None


@pytest.mark.parametrize(
    "row",
    [
        "not-a-list",
        ["only-one"],
        ["q", 1],
        ["q", 1, [], "extra"],
    ],
)
def test_unit_fact_row_refuses_rows_that_are_not_a_three_column_row(
    row: object,
) -> None:
    """The framing is ``[qualname, start_line, fields]`` or it is not a row."""

    assert decode_wire_unit_fact_row(row, stride=1, build=lambda f: f) is None


@pytest.mark.parametrize(
    "row",
    [
        [1, 1, []],
        ["q", "one", []],
        ["q", 1, "not-a-list"],
    ],
)
def test_unit_fact_row_refuses_a_mistyped_unit_key(row: object) -> None:
    """A row whose key cannot be read cannot be attached to any unit."""

    assert decode_wire_unit_fact_row(row, stride=1, build=lambda f: f) is None


def test_unit_fact_row_refuses_fields_that_do_not_fill_whole_facts() -> None:
    """Facts are flattened at a fixed stride; a partial tail is corruption."""

    row = ["q", 1, ["a", 1, 2, "b", 3]]
    assert decode_wire_unit_fact_row(row, stride=3, build=lambda f: f) is None


def test_unit_fact_row_refuses_the_whole_row_when_one_fact_fails() -> None:
    """One undecodable fact rejects the row, not just that fact."""

    row = ["q", 1, ["a", 1, 2, "b", "bad", 4]]
    assert _decode_wire_unit_sequence_row(row) is None


def test_unit_fact_row_decodes_every_fact_when_all_are_well_formed() -> None:
    """The positive case fixes what the refusals are refusing."""

    row = ["q", 1, ["a", 1, 2, "b", 3, 4]]
    assert _decode_wire_unit_sequence_row(row) == (
        ("q", 1),
        (("a", 1, 2), ("b", 3, 4)),
    )


@pytest.mark.parametrize(
    "rows",
    [
        ["not-a-row"],
        [["q"]],
        [["q", ["base"], "extra"]],
        [[1, ["base"]]],
        [["q", "not-a-list"]],
        [["q", ["base", 2]]],
    ],
)
def test_coupled_classes_refuses_any_malformed_pair(rows: object) -> None:
    """Each row is ``[qualname, [name, ...]]``; anything else rejects the map."""

    assert _decode_optional_wire_coupled_classes(obj={"cc": rows}, key="cc") is None


# --------------------------------------------------------------------------
# _wire_decode: digests, reachability facts, class bases, dead candidates
# --------------------------------------------------------------------------


def test_binding_context_digest_refuses_a_value_that_is_not_a_sha256() -> None:
    """The wire carries the digest text unvalidated, so the model validates it.

    ``_decode_sha256_value`` checks the domain and algorithm but returns the
    value as-is, which makes ``DigestObject``'s own hex guard the only thing
    standing between a corrupt digest and a cache hit that claims provenance
    it cannot prove.
    """

    assert _decode_binding_context_digest([_BINDING_DOMAIN, "sha256", "nope"]) is None


def test_binding_context_digest_accepts_a_well_formed_value() -> None:
    """The refusal above is about the value, not about the decoder path."""

    digest = _decode_binding_context_digest([_BINDING_DOMAIN, "sha256", "a" * 64])
    assert digest is not None
    assert digest.value == "a" * 64


def test_unreachable_reason_refuses_a_reason_outside_the_closed_set() -> None:
    """The reason vocabulary is closed; an unknown one is writer/reader drift."""

    assert _as_unreachable_reason("someday_new_reason") is None


@pytest.mark.parametrize(
    "fields",
    [
        ["not_a_reason", 1, 2, 1],
        ["after_terminator", "x", 2, 1],
        ["after_terminator", 1, "x", 1],
        ["after_terminator", 1, 2, "x"],
    ],
)
def test_unreachable_item_refuses_mistyped_fields(fields: list[object]) -> None:
    """Every one of the four fields is required to decode."""

    assert _build_unreachable_statement_item(fields) is None


@pytest.mark.parametrize(
    "fields",
    [
        ["after_terminator", 0, 2, 1],
        ["after_terminator", 5, 4, 1],
        ["after_terminator", 1, 2, 0],
    ],
)
def test_unreachable_item_refuses_spans_the_model_would_reject(
    fields: list[object],
) -> None:
    """The decoder screens the span itself rather than letting the model raise.

    ``UnreachableStatementItem`` refuses a fabricated span by raising; on this
    path a corrupt row must degrade to "re-analyse the file", so the decoder
    returns ``None`` instead of propagating the exception.
    """

    assert _build_unreachable_statement_item(fields) is None


def test_unreachable_item_decodes_a_well_formed_region() -> None:
    """Pins the accepted shape the refusals above are drawn against."""

    item = _build_unreachable_statement_item(["after_terminator", 3, 7, 4])
    assert item is not None
    assert (item.reason, item.start_line, item.end_line, item.statement_count) == (
        "after_terminator",
        3,
        7,
        4,
    )


def test_unit_facts_refuse_a_family_that_is_not_a_list() -> None:
    """A present-but-unreadable family rejects the entry."""

    assert not _apply_wire_unit_facts(
        obj={"us": "not-a-list"},
        units=[_unit()],
        key="us",
        decode_row=_decode_wire_unit_sequence_row,
        assign=lambda unit, facts: None,
    )


def test_unit_facts_refuse_a_family_row_that_cannot_be_decoded() -> None:
    """One bad row rejects the family, and the family rejects the entry."""

    assert not _apply_wire_unit_facts(
        obj={"us": [["q", 1, ["a", 1]]]},
        units=[_unit()],
        key="us",
        decode_row=_decode_wire_unit_sequence_row,
        assign=lambda unit, facts: None,
    )


def test_unit_facts_refuse_a_family_that_omits_a_unit() -> None:
    """Facts recorded for other units do not make this unit's facts known."""

    assert not _apply_wire_unit_facts(
        obj={"us": [["other", 9, ["a", 1, 2]]]},
        units=[_unit()],
        key="us",
        decode_row=_decode_wire_unit_sequence_row,
        assign=lambda unit, facts: None,
    )


def test_unit_facts_absent_family_is_accepted_only_when_no_units_exist() -> None:
    """Absence is "nothing to attach" for zero units and "unknown" otherwise."""

    assert _apply_wire_unit_facts(
        obj={},
        units=[],
        key="us",
        decode_row=_decode_wire_unit_sequence_row,
        assign=lambda unit, facts: None,
    )
    assert not _apply_wire_unit_facts(
        obj={},
        units=[_unit()],
        key="us",
        decode_row=_decode_wire_unit_sequence_row,
        assign=lambda unit, facts: None,
    )


def test_units_with_sequences_refuse_an_unreadable_unit_list() -> None:
    """The unit list itself must decode before any family is considered."""

    assert _decode_wire_units_with_sequences(obj={"u": "bad"}, filepath="a.py") is None


def test_units_with_sequences_refuse_units_whose_facts_are_missing() -> None:
    """A unit missing a fact family is not a usable unit, so the entry dies."""

    obj: dict[str, object] = {"u": [list(_VALID_UNIT_ROW)]}
    assert _decode_wire_units_with_sequences(obj=obj, filepath="a.py") is None


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-list",
        ["not-a-row"],
        [["q", ["b"]]],
        [[1, ["b"], False]],
        [["q", "not-a-list", False]],
        [["q", ["b"], "not-a-bool"]],
    ],
)
def test_class_bases_refuse_any_malformed_sidecar(raw: object) -> None:
    """Each ``bs`` row is ``[qualname, [base, ...], bool]`` exactly."""

    assert _decode_optional_wire_class_bases(obj={"bs": raw}) is None


def test_class_bases_absent_key_is_an_empty_map_not_a_failure() -> None:
    """A 3.1 entry recorded no bases; that is a fact, not corruption."""

    assert _decode_optional_wire_class_bases(obj={}) == {}


@pytest.mark.parametrize("value", ["not-a-list", ["ok", 2], [None]])
def test_wire_str_tuple_refuses_any_non_string_element(value: object) -> None:
    """One non-string element rejects the whole tuple."""

    assert _as_wire_str_tuple(value) is None


def test_wire_str_tuple_accepts_an_all_string_list() -> None:
    """Pins the accepted shape behind the refusals above."""

    assert _as_wire_str_tuple(["a", "b"]) == ("a", "b")


@pytest.mark.parametrize("reason", ["retired_reason", 7])
def test_dead_candidate_refuses_a_live_root_reason_outside_the_closed_set(
    reason: object,
) -> None:
    """An unknown liveness reason means writer and reader disagree."""

    row = ["pkg:a", "a", 1, 2, "function", [], reason]
    assert _decode_wire_dead_candidate(row, "a.py") is None


def test_dead_candidate_accepts_a_known_live_root_reason() -> None:
    """The closed set is a set of two, and both must still decode."""

    row = ["pkg:a", "a", 1, 2, "function", [], "export_root"]
    decoded = _decode_wire_dead_candidate(row, "a.py")
    assert decoded is not None
    assert decoded["live_root_reason"] == "export_root"
