# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Behavioral consumers of the ``near_miss_witness`` fixture.

The near-miss contract is two-layer. The verdict is the scalar minimum edit
distance over the normalized statement sequences — insert, delete and replace
each cost exactly one, equal costs zero — and that scalar is unique, so it
needs no tie-break. The evidence is not unique: with repeated identical
statement fingerprints several equally cheap witnesses exist, and the tier
must report THE canonical one, chosen by the documented total order over the
DP backtrace (see ``near_miss._edit_script``). An undetermined witness under a
determined verdict is a silent-wrongness bug, so this suite pins the evidence
bytes — exact differing line numbers inside repeated-fingerprint runs — and
not only the distance.

Expected outcomes are read from the fixture's ``ground_truth.json`` — never
inlined here.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from codeclone.contracts import (
    NEAR_MISS_ALGORITHM_REVISION,
    NEAR_MISS_MAX_EDIT_STATEMENTS,
)
from codeclone.findings.clones.grouping import build_groups, clone_eligible_units
from codeclone.findings.clones.near_miss import build_near_miss_pairs
from codeclone.report.document.builder import build_report_body
from tests._pipeline_fixtures import (
    extract_units,
    golden_ground_truth,
    golden_root,
    payload_mapping,
)

DOMAIN = "near_miss_witness"
FIXTURE_ROOT = golden_root(DOMAIN)

# The fixture pairs are sized for these floors; every declared case clears
# them, so eligibility never silently decides a tier assertion here.
FIXTURE_MIN_LOC = 6
FIXTURE_MIN_STMT = 4


def _fixture_units() -> list[dict[str, object]]:
    return clone_eligible_units(
        [
            asdict(unit)
            for unit in extract_units(
                FIXTURE_ROOT, min_loc=FIXTURE_MIN_LOC, min_stmt=FIXTURE_MIN_STMT
            )
        ],
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
    )


def _local_name(qualname: str) -> str:
    return qualname.rsplit(":", 1)[-1]


def _case(case_id: str) -> dict[str, Any]:
    cases: list[dict[str, Any]] = golden_ground_truth(DOMAIN)["cases"]
    for case in cases:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"unknown ground-truth case {case_id}")


def _near_miss_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = golden_ground_truth(DOMAIN)["cases"]
    return [case for case in cases if case["expected"].get("tier") == "near_miss"]


def _pair_for(case: dict[str, Any]) -> Any:
    expected = frozenset(case["members"])
    for pair in build_near_miss_pairs(_fixture_units()):
        if frozenset(_local_name(m.qualname) for m in pair.members) == expected:
            return pair
    raise AssertionError(f"{case['id']} was not reported as a near miss")


def _assert_case_witness(case: dict[str, Any]) -> None:
    """One case's full evidence: kind, distance, and exact witness bytes."""

    pair = _pair_for(case)
    expected = case["expected"]
    assert pair.edit_kind == expected["edit_kind"], case["id"]
    assert pair.edit_statements == expected["edit_statements"], case["id"]
    witness = {
        _local_name(member.qualname): [
            member.differing_start_line,
            member.differing_end_line,
        ]
        for member in pair.members
    }
    assert witness == expected["witness"], case["id"]
    source_lines = (FIXTURE_ROOT / case["path"]).read_text("utf-8").splitlines()
    for member_name, text in expected.get("witness_text", {}).items():
        start = expected["witness"][member_name][0]
        assert source_lines[start - 1].strip() == text, case["id"]


def test_declared_near_miss_pairs_and_no_others() -> None:
    """The reported pair set IS the declared set — no misses, no surprises.

    Set equality is the complement assertion: a fixture that quietly grew an
    extra reportable pair fails here just as loudly as a false negative.
    """

    found = {
        frozenset(_local_name(m.qualname) for m in pair.members)
        for pair in build_near_miss_pairs(_fixture_units())
    }
    declared = {frozenset(case["members"]) for case in _near_miss_cases()}
    assert declared, "ground truth declares no near_miss case; the suite is inert"
    assert found == declared


def test_rename_plus_single_insertion_is_found_within_budget() -> None:
    """The empirical PAIR-T3-01 shape: renames plus one true insertion."""

    _assert_case_witness(_case("PAIR-NM-INSERT"))


def test_single_replace_is_one_edit_not_two() -> None:
    """A substituted unequal statement costs one edit, never delete+insert."""

    _assert_case_witness(_case("PAIR-NM-REPLACE"))


def test_two_true_insertions_stay_out_of_budget() -> None:
    """The negative twin: two inserted statements exceed the declared bound."""

    case = _case("PAIR-NM-DOUBLE-NEG")
    expected = frozenset(case["members"])
    found = {
        frozenset(_local_name(m.qualname) for m in pair.members)
        for pair in build_near_miss_pairs(_fixture_units())
    }
    assert expected not in found, f"{case['id']} must not group as near_miss"


def test_pure_rename_pair_stays_the_exact_tiers_business() -> None:
    """Distance zero: one exact cohort, and never a near-miss candidate pair."""

    case = _case("PAIR-NM-RENAME-EXACT")
    expected = frozenset(case["members"])
    units = _fixture_units()
    exact = {
        frozenset(_local_name(str(item["qualname"])) for item in items)
        for items in build_groups(units).values()
    }
    assert expected in exact, f"{case['id']} must group in the exact tier"
    near_miss = {
        frozenset(_local_name(m.qualname) for m in pair.members)
        for pair in build_near_miss_pairs(units)
    }
    assert expected not in near_miss, f"{case['id']} must not be double-reported"


def test_repeated_run_at_the_tail_carries_the_canonical_witness() -> None:
    """Ambiguity class: insertion into a repeated-fingerprint run at the tail.

    Every run position is an equally cheap witness; the canonical law fixes
    the leftmost. The assertion is on exact line numbers because all run lines
    carry identical text — the number IS the evidence.
    """

    _assert_case_witness(_case("PAIR-NM-RUN-TAIL"))


def test_repeated_run_at_the_head_carries_the_canonical_witness() -> None:
    """Ambiguity class: insertion into a repeated-fingerprint run at the head."""

    _assert_case_witness(_case("PAIR-NM-RUN-HEAD"))


def _signature(pairs: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(
        f"{pair.pair_key}|{pair.edit_kind}|{pair.edit_statements}|"
        + ",".join(
            f"{member.qualname}:{member.differing_start_line}"
            f"-{member.differing_end_line}"
            for member in pair.members
        )
        for pair in pairs
    )


def test_report_payload_publishes_the_near_miss_algorithm_revision() -> None:
    """The payload names which counting law produced the pairs.

    The revision is the near-miss lane's OWN algorithm identity: bumping it
    documents the move to the sequence edit distance and the canonical
    witness law without touching the exact lane's fingerprint constants.
    """

    units = _fixture_units()
    body = build_report_body(
        func_groups=build_groups(units),
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(FIXTURE_ROOT)},
        near_miss_pairs=build_near_miss_pairs(units),
    )
    groups = payload_mapping(payload_mapping(body["findings"])["groups"])
    near_miss = payload_mapping(groups["near_miss"])
    assert near_miss["algorithm_revision"] == NEAR_MISS_ALGORITHM_REVISION
    assert near_miss["max_edit_statements"] == NEAR_MISS_MAX_EDIT_STATEMENTS


def test_two_runs_produce_identical_findings_and_identical_witnesses() -> None:
    """Determinism over the full evidence, not only the verdict.

    Extraction and pairing run twice from the source tree; the two signatures
    must agree byte for byte, witness spans included.
    """

    first = _signature(build_near_miss_pairs(_fixture_units()))
    second = _signature(build_near_miss_pairs(_fixture_units()))
    assert first, "the determinism check found no pair to compare; it is inert"
    assert first == second
