# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Behavioral consumers of the ``clone_tiers`` golden fixture — near-miss tier.

Phase 39Y slice Y8 (EMP-CC-003b). The exact tier cannot match two functions
whose normalized statement counts differ, so ``PAIR-T3-01`` — identical bodies
apart from renames plus ONE inserted statement — was invisible. The declared
rule: two clone-eligible units group as ``near_miss`` when their normalized
statement sequences differ by at most
``NEAR_MISS_MAX_EDIT_STATEMENTS`` inserted, deleted or replaced statements and
by at least one (distance zero is the exact tier's business).

The bound is an integer contract constant; there is no similarity score. The
negative twin (``PAIR-T3-NEG``, two-statement divergence) proves the rule is the
declared predicate rather than a fixture key, and the ``PAIR-T4-*`` seeds stay
honestly unclaimed because no tier in this phase reasons about semantics.

Expected outcomes are read from the fixture's ``ground_truth.json`` — never
inlined here.
"""

from __future__ import annotations

import shutil
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import codeclone.findings.clones.near_miss as near_miss_mod
from codeclone.contracts import NEAR_MISS_MAX_EDIT_STATEMENTS
from codeclone.contracts.errors import ValidationError
from codeclone.findings.clones.grouping import build_groups, clone_eligible_units
from codeclone.findings.clones.near_miss import build_near_miss_pairs
from codeclone.report.document.builder import build_report_body
from tests._pipeline_fixtures import (
    analysis_boot,
    extract_units,
    golden_ground_truth,
    golden_root,
    payload_mapping,
    payload_sequence,
    run_pipeline_once,
)

if TYPE_CHECKING:
    from codeclone.core._types import BootstrapResult
    from codeclone.models import NearMissPair

DOMAIN = "clone_tiers"
FIXTURE_ROOT = golden_root(DOMAIN)

# The fixture pairs are sized for the benchmark's floors; every declared case
# clears them, so eligibility never silently decides a tier assertion here.
FIXTURE_MIN_LOC = 6
FIXTURE_MIN_STMT = 4


def _cases_by_tier(tier: str) -> list[dict[str, Any]]:
    return [
        case
        for case in golden_ground_truth(DOMAIN)["cases"]
        if case["expected"].get("tier") == tier
    ]


def _case(case_id: str) -> dict[str, Any]:
    cases: list[dict[str, Any]] = golden_ground_truth(DOMAIN)["cases"]
    for case in cases:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"unknown ground-truth case {case_id}")


def _fixture_units() -> list[dict[str, object]]:
    """Clone-eligible unit facts of the fixture tree.

    The extraction is shared; the eligibility filter is not, because it is the
    clone lane's own question and no other suite asks it.
    """

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


def _near_miss_member_sets(
    pairs: tuple[NearMissPair, ...],
) -> set[frozenset[str]]:
    return {
        frozenset(_local_name(member.qualname) for member in pair.members)
        for pair in pairs
    }


def _exact_member_sets(units: list[dict[str, object]]) -> set[frozenset[str]]:
    return {
        frozenset(_local_name(str(item["qualname"])) for item in items)
        for items in build_groups(units).values()
    }


def test_near_miss_bound_is_a_named_integer_contract() -> None:
    """No similarity floats: the tier is bounded by one named integer."""

    assert isinstance(NEAR_MISS_MAX_EDIT_STATEMENTS, int)
    assert not isinstance(NEAR_MISS_MAX_EDIT_STATEMENTS, bool)
    assert NEAR_MISS_MAX_EDIT_STATEMENTS == 1
    assert _case("PAIR-T3-01")["expected"]["edit_statements"] == (
        NEAR_MISS_MAX_EDIT_STATEMENTS
    )


def test_declared_near_miss_pairs_group() -> None:
    """EMP-CC-003b: one inserted statement must not hide a clone."""

    units = _fixture_units()
    found = _near_miss_member_sets(build_near_miss_pairs(units))
    declared = _cases_by_tier("near_miss")
    assert declared, "ground truth declares no near_miss case"
    for case in declared:
        expected = frozenset(case["members"])
        assert expected in found, f"{case['id']} did not group as near_miss"


def test_near_miss_carries_edit_distance_and_differing_span() -> None:
    """The evidence is the differing statement, not a score."""

    units = _fixture_units()
    case = _case("PAIR-T3-01")
    expected = frozenset(case["members"])
    pair = next(
        found
        for found in build_near_miss_pairs(units)
        if frozenset(_local_name(member.qualname) for member in found.members)
        == expected
    )
    assert pair.edit_statements == case["expected"]["edit_statements"]
    assert pair.edit_kind in {"insert", "delete", "replace"}
    # `active_customer_value_clamped` carries the inserted `total = max(total, 0)`;
    # the shorter side has no differing statement of its own. Both members read
    # the same attributes, so the clamp is the only edit (39Y-FP row 7).
    differing = {
        _local_name(member.qualname): (
            member.differing_start_line,
            member.differing_end_line,
        )
        for member in pair.members
    }
    assert differing["active_customer_value_clamped"] != (0, 0)
    assert differing["active_customer_value"] == (0, 0)
    start, end = differing["active_customer_value_clamped"]
    source_line = (
        (FIXTURE_ROOT / case["path"]).read_text("utf-8").splitlines()[start - 1]
    )
    assert source_line.strip() == "total = max(total, 0)"
    assert end == start


def _assert_tier_absent_from_near_miss(tier: str, *, because: str) -> None:
    """Assert no ground-truth case of ``tier`` was reported as a near miss."""

    units = _fixture_units()
    found = _near_miss_member_sets(build_near_miss_pairs(units))
    for case in _cases_by_tier(tier):
        assert frozenset(case["members"]) not in found, f"{case['id']} {because}"


def test_two_statement_divergence_negative_twin_does_not_group() -> None:
    """The rule is the declared predicate, not a fixture key."""

    _assert_tier_absent_from_near_miss(
        "unmatched",
        because="must not group as near_miss",
    )


def test_parked_type4_pairs_stay_unclaimed_by_every_tier() -> None:
    """Y-OUT: semantic equivalence is refused, so these stay unmatched."""

    units = _fixture_units()
    tiers = _near_miss_member_sets(build_near_miss_pairs(units)) | _exact_member_sets(
        units
    )
    for case_id in ("PAIR-T4-01", "PAIR-T4-02", "R-PAIR-T4-01", "R-PAIR-T4-02"):
        expected = frozenset(_case(case_id)["members"])
        assert expected not in tiers, f"{case_id} must stay unclaimed"


def test_declared_exact_pairs_actually_reach_the_exact_tier() -> None:
    """Every declared tier claim must be asserted, never merely written down.

    ``PAIR-INT-02`` sat in the golden as ``{"tier": "exact"}`` with nothing
    reading it, and the claim was false: both members are a single multi-line
    dict-return statement, so the pair never clears the clone lane's
    ``min_stmt`` floor and never becomes an eligible unit at all. A golden
    claim no test can fail is not a golden - hence this fence over the whole
    declared set rather than a hand-picked id.
    """

    units = _fixture_units()
    exact = _exact_member_sets(units)
    declared = {
        str(case["id"]): frozenset(case["members"])
        for case in golden_ground_truth(DOMAIN)["cases"]
        if case["expected"].get("tier") == "exact"
    }
    assert declared, "no exact case declared; the fence would be inert"
    assert {
        case_id: members in exact for case_id, members in declared.items()
    } == dict.fromkeys(declared, True)


def test_exact_pairs_never_enter_the_near_miss_channel() -> None:
    """Distance zero belongs to the exact tier; near_miss never merges it."""

    _assert_tier_absent_from_near_miss(
        "exact",
        because="must stay in the exact tier",
    )


def test_rename_twins_classify_identically() -> None:
    """Rename invariance: renamed twins reach the same tier as their origin."""

    units = _fixture_units()
    found = _near_miss_member_sets(build_near_miss_pairs(units))
    for origin_id, twin_id in golden_ground_truth(DOMAIN)["rename_twins"]:
        origin = frozenset(_case(origin_id)["members"])
        twin = frozenset(_case(twin_id)["members"])
        assert (origin in found) == (twin in found), (
            f"{origin_id} and {twin_id} reached different near_miss verdicts"
        )


def _near_miss_signature(pairs: tuple[NearMissPair, ...]) -> tuple[str, ...]:
    return tuple(
        f"{pair.pair_key}|{pair.edit_kind}|{pair.edit_statements}|"
        + ",".join(
            f"{member.qualname}:{member.differing_start_line}"
            f"-{member.differing_end_line}"
            for member in pair.members
        )
        for pair in pairs
    )


def test_report_carries_near_miss_outside_the_clone_lane() -> None:
    """Report channel, not a clone lane: gate-neutral and novelty-free.

    ``near_miss`` sits beside ``clones`` rather than inside it. That placement
    is the confinement: the clone lane's keys become baseline lane keys and
    feed gates and novelty, so a near-miss pair carried there would stop being
    advisory. The price, stated honestly here and in the payload, is that
    near-miss pairs carry no baseline novelty at all.
    """

    units = _fixture_units()
    pairs = build_near_miss_pairs(units)
    body = build_report_body(
        func_groups=build_groups(units),
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(FIXTURE_ROOT)},
        near_miss_pairs=pairs,
    )
    groups = payload_mapping(payload_mapping(body["findings"])["groups"])
    assert set(payload_mapping(groups["clones"])) == {"functions", "blocks", "segments"}
    near_miss = payload_mapping(groups["near_miss"])
    assert near_miss["novelty"] == "untracked"
    assert near_miss["gate_relevant"] is False
    assert near_miss["max_edit_statements"] == NEAR_MISS_MAX_EDIT_STATEMENTS
    reported_pairs = payload_sequence(near_miss["pairs"])
    assert len(reported_pairs) == len(pairs)
    reported = {
        frozenset(
            _local_name(str(payload_mapping(member)["qualname"]))
            for member in payload_sequence(payload_mapping(pair)["members"])
        )
        for pair in reported_pairs
    }
    assert frozenset(_case("PAIR-T3-01")["members"]) in reported
    # Paths are reported relative to the scan root, never as absolute paths.
    for pair in reported_pairs:
        for member in payload_sequence(payload_mapping(pair)["members"]):
            assert not str(payload_mapping(member)["relative_path"]).startswith("/")


def _pairs_package_boot(tmp_path: Path, *, near_miss: bool) -> BootstrapResult:
    """Lay the labelled pair module out as a package and bootstrap over it."""

    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    shutil.copyfile(FIXTURE_ROOT / "pairs.py", package / "pairs.py")
    return analysis_boot(
        tmp_path,
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
        skip_metrics=True,
        near_miss=near_miss,
    )


def test_near_miss_output_matches_cold_and_warm(tmp_path: Path) -> None:
    """The carriage guard (39J pattern) for the CACHE_VERSION 3.2 wire.

    Near-miss grouping runs over ``processing.units``, and on a warm run those
    units come straight off the cache wire without re-parsing. Unless the
    per-unit statement sequence rides the wire, a warm run silently reports zero
    near-miss pairs — the exact stale-cache trap the own-key/absence-rejects
    carriage rule exists to prevent.
    """

    # The channel is opt-in (Y8), so the carriage guard must ask for it; the
    # "no pair to compare" assertion below keeps it from going inert.
    boot = _pairs_package_boot(tmp_path, near_miss=True)
    cache_path = tmp_path / "cache.json"

    cold_cache, cold = run_pipeline_once(boot, cache_path, root=tmp_path, warm=False)
    cold_cache.save()
    _warm_cache, warm = run_pipeline_once(
        boot, cache_path, root=tmp_path, warm=True, expect_cache_hits=2
    )

    cold_pairs = cold.result.near_miss_pairs
    warm_pairs = warm.result.near_miss_pairs
    assert cold_pairs is not None and warm_pairs is not None, (
        "the opt-in run did not produce the channel"
    )
    cold_signature = _near_miss_signature(cold_pairs)
    assert cold_signature, "cold run found no near-miss pair to compare"
    assert cold_signature == _near_miss_signature(warm_pairs)


def test_raising_the_bound_is_refused_instead_of_silently_under_reporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The module is a K=1 construction and must say so when K moves.

    ``NEAR_MISS_MAX_EDIT_STATEMENTS`` is read as if it were authoritative, but
    two pieces of this module are built for exactly one edit: the deletion
    index emits a single one-statement deletion per sequence, and the bounded
    confirmation locates one divergence and reports distance 1. Raising the
    constant would therefore not widen the tier - it would keep finding only
    distance-1 pairs while claiming a wider bound, which is silent
    under-reporting. The contract must fail loudly instead.
    """

    monkeypatch.setattr(near_miss_mod, "NEAR_MISS_MAX_EDIT_STATEMENTS", 2)
    with pytest.raises(ValidationError, match="NEAR_MISS_MAX_EDIT_STATEMENTS"):
        near_miss_mod.build_near_miss_pairs(_fixture_units())


def test_near_miss_channel_is_opt_in(tmp_path: Path) -> None:
    """Y8: the tier ships behind its own flag, and the flag is off by default.

    Gate-neutrality is already structural — these pairs never become
    ``func_groups``, so they reach no lane, no novelty and no gate. The brief
    asks for one thing more: the channel itself is opt-in, owned by a single
    ``OptionSpec`` in ``config/spec.py``. Producing it unconditionally would
    publish a new finding kind to every existing user who never asked for it,
    and would make "advisory" a property of where the output lands rather than
    a choice the operator made.
    """

    def _run(*, near_miss: bool) -> tuple[NearMissPair, ...] | None:
        boot = _pairs_package_boot(tmp_path, near_miss=near_miss)
        _cache, run = run_pipeline_once(
            boot, tmp_path / f"cache-{near_miss}.json", root=tmp_path, warm=False
        )
        return run.result.near_miss_pairs

    # Off means not produced (None), never "produced and empty" — the
    # execution witness the T1 tier-state contract serializes as
    # ``state: "disabled"``.
    assert _run(near_miss=False) is None
    assert _run(near_miss=True), "the opt-in run found no pair; the guard is inert"
