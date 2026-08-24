# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Behavioral consumers of the ``near_miss_token_domains`` golden fixture.

The CxB composition: the near-miss tier confirms distance in two declared
token domains. ``y8`` is the normalized statement token space the tier has
always used; ``renamed`` re-tokenizes the same statements through the
``renamed_structure`` ordinal canonicalization, so a pair whose only
differences are a consistent renaming plus ONE true edit is confirmable
within the unchanged budget. The deletion index, the K=1 bound and the
canonical witness law transfer unchanged; the domains never share an index.

Dedup law, pinned here: a pair confirmable in both domains is reported
exactly once, in the ``y8`` domain, so every fact the tier reported before
the sub-mode existed stays byte-identical.

Expected outcomes are read from the fixture's ``ground_truth.json`` — never
inlined here.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from codeclone.contracts import (
    NEAR_MISS_ALGORITHM_REVISION,
    NEAR_MISS_MAX_EDIT_STATEMENTS,
)
from codeclone.findings.clones.grouping import build_groups, clone_eligible_units
from codeclone.findings.clones.near_miss import (
    _token_domain_pairs,
    build_near_miss_pairs,
)
from codeclone.findings.clones.renamed_structure import build_renamed_structure_groups
from codeclone.report.document.builder import build_report_body
from tests._pipeline_fixtures import (
    analysis_boot,
    extract_units,
    golden_ground_truth,
    golden_root,
    package_tree,
    payload_mapping,
    payload_sequence,
    run_pipeline_once,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from codeclone.core._types import BootstrapResult
    from codeclone.models import NearMissPair

DOMAIN = "near_miss_token_domains"
FIXTURE_ROOT = golden_root(DOMAIN)

# The fixture pairs are sized for these floors; every declared case clears
# them, so eligibility never silently decides a token-domain assertion here.
FIXTURE_MIN_LOC = 6
FIXTURE_MIN_STMT = 4


def _case(case_id: str) -> dict[str, Any]:
    cases: list[dict[str, Any]] = golden_ground_truth(DOMAIN)["cases"]
    for case in cases:
        if case["id"] == case_id:
            return case
    raise AssertionError(f"unknown ground-truth case {case_id}")


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


def _member_set(pair: NearMissPair) -> frozenset[str]:
    return frozenset(_local_name(member.qualname) for member in pair.members)


def _pairs_for(case_id: str) -> list[NearMissPair]:
    expected = frozenset(_case(case_id)["members"])
    return [
        pair
        for pair in build_near_miss_pairs(_fixture_units())
        if _member_set(pair) == expected
    ]


def _domain_member_sets(
    units: list[dict[str, object]],
    token_domain: Literal["y8", "renamed"],
) -> set[frozenset[str]]:
    """Member sets one token domain confirms on its own, before any dedup."""

    return {_member_set(pair) for pair in _token_domain_pairs(units, token_domain)}


def _near_miss_payload(
    units: list[dict[str, object]],
    pairs: tuple[NearMissPair, ...],
) -> Mapping[str, object]:
    """Build a report body over the fixture and return its near-miss channel."""

    body = build_report_body(
        func_groups=build_groups(units),
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(FIXTURE_ROOT)},
        near_miss_pairs=pairs,
    )
    groups = payload_mapping(payload_mapping(body["findings"])["groups"])
    return payload_mapping(groups["near_miss"])


def _reported_domains(near_miss: Mapping[str, object]) -> dict[frozenset[str], str]:
    """Map each published pair's member set to its declared token domain."""

    return {
        frozenset(
            _local_name(str(payload_mapping(member)["qualname"]))
            for member in payload_sequence(payload_mapping(pair)["members"])
        ): str(payload_mapping(pair)["token_domain"])
        for pair in payload_sequence(near_miss["pairs"])
    }


def test_algorithm_revision_names_the_token_domain_generation() -> None:
    """Revision 3 is the sub-mode: what near-miss can find has changed."""

    assert NEAR_MISS_ALGORITHM_REVISION == "3"


def test_renamed_domain_finds_the_rename_plus_insert_pair() -> None:
    """The acceptance shape: attribute renames + one true insert, distance 1.

    Under y8 tokens the consistent receiver-attribute renames price one
    statement as a replace, so the distance is 2 and the pair is out of
    budget BY RULE. The renamed-canonical tokens absorb the renames, leaving
    the true insertion as the only edit.
    """

    case = _case("PAIR-TD-RENAMED-INSERT")
    pairs = _pairs_for("PAIR-TD-RENAMED-INSERT")
    assert len(pairs) == 1, "the acceptance pair must be reported exactly once"
    pair = pairs[0]
    assert pair.token_domain == case["expected"]["token_domain"]
    assert pair.edit_statements == case["expected"]["edit_statements"]
    assert pair.edit_kind == case["expected"]["edit_kind"]


def test_renamed_domain_witness_points_at_the_real_inserted_statement() -> None:
    """Evidence shows the user their actual code, not a canonical spelling.

    The canonicalization exists for comparison only: the witness span must
    resolve to the true inserted clamp statement in the source file, and the
    shorter side carries no differing span at all.
    """

    case = _case("PAIR-TD-RENAMED-INSERT")
    (pair,) = _pairs_for("PAIR-TD-RENAMED-INSERT")
    differing = {
        _local_name(member.qualname): (
            member.differing_start_line,
            member.differing_end_line,
        )
        for member in pair.members
    }
    assert differing["open_invoice_exposure"] == (0, 0)
    start, end = differing["open_lease_exposure"]
    assert (start, end) != (0, 0)
    assert end == start
    source_line = (
        (FIXTURE_ROOT / case["path"]).read_text("utf-8").splitlines()[start - 1]
    )
    expected_text = case["expected"]["witness_text"]["open_lease_exposure"]
    assert source_line.strip() == expected_text


def test_acceptance_shape_is_invisible_to_every_prior_tier() -> None:
    """The gap statement: no pre-sub-mode tier can claim this pair.

    fp3 cannot (the sequences differ), renamed_structure cannot (the
    statement counts differ), and the y8 token domain cannot (distance 2 is
    out of budget by rule). This is the fixture's reason to exist, so it is
    pinned as a fact rather than assumed.
    """

    units = _fixture_units()
    expected = frozenset(_case("PAIR-TD-RENAMED-INSERT")["members"])
    exact = {
        frozenset(_local_name(str(item["qualname"])) for item in items)
        for items in build_groups(units).values()
    }
    assert not any(expected <= group for group in exact)
    renamed_groups = {
        frozenset(_local_name(member.qualname) for member in group.members)
        for group in build_renamed_structure_groups(units)
    }
    assert not any(expected <= group for group in renamed_groups)
    assert expected not in _domain_member_sets(units, "y8")


def test_pair_confirmable_in_both_domains_reports_once_as_y8() -> None:
    """The dedup law: y8 wins, and the guard is proven non-inert.

    The renamed domain independently confirms this local-rename-plus-insert
    pair — asserted against the domain probe directly, so the dedup below is
    known to have something to deduplicate — yet the published channel
    carries the pair exactly once, in the y8 domain.
    """

    case = _case("PAIR-TD-BOTH-DOMAINS")
    assert frozenset(case["members"]) in _domain_member_sets(
        _fixture_units(), "renamed"
    ), "the dedup guard would be inert"
    pairs = _pairs_for("PAIR-TD-BOTH-DOMAINS")
    assert len(pairs) == 1, "a both-domain pair must never double-report"
    assert pairs[0].token_domain == case["expected"]["token_domain"]
    assert pairs[0].edit_statements == case["expected"]["edit_statements"]
    assert pairs[0].edit_kind == case["expected"]["edit_kind"]


def test_two_edit_pair_stays_out_of_budget_in_both_domains() -> None:
    """The budget transfers unchanged: distance 2 is a refusal, not a score."""

    assert _pairs_for("PAIR-TD-BUDGET-NEG") == []


def test_renamed_distance_zero_stays_renamed_structure_business() -> None:
    """Tier separation: a pure renaming is the C tier's find, never near-miss."""

    units = _fixture_units()
    expected = frozenset(_case("PAIR-TD-ZERO-NEG")["members"])
    assert _pairs_for("PAIR-TD-ZERO-NEG") == []
    renamed_groups = {
        frozenset(_local_name(member.qualname) for member in group.members)
        for group in build_renamed_structure_groups(units)
    }
    assert any(expected <= group for group in renamed_groups), (
        "the zero-distance twin must reach the renamed_structure tier"
    )


def test_report_payload_declares_the_token_domain_per_pair() -> None:
    """The container states what it holds: every published pair is labelled."""

    units = _fixture_units()
    near_miss = _near_miss_payload(units, build_near_miss_pairs(units))
    assert near_miss["algorithm_revision"] == NEAR_MISS_ALGORITHM_REVISION
    reported = _reported_domains(near_miss)
    assert reported[frozenset(_case("PAIR-TD-RENAMED-INSERT")["members"])] == "renamed"
    assert reported[frozenset(_case("PAIR-TD-BOTH-DOMAINS")["members"])] == "y8"


def test_renamed_domain_pairs_inherit_the_advisory_confinement() -> None:
    """Gate-neutral exactly as before: no func_group, no novelty, no gate.

    The renamed domain publishes inside the near-miss channel, so it
    inherits the channel's confinement: pairs never become clone-lane keys,
    the payload stays ``gate_relevant: false`` and ``novelty: untracked``,
    and the exact lane's groups are byte-identical with the sub-mode's
    findings present.
    """

    units = _fixture_units()
    pairs = build_near_miss_pairs(units)
    assert any(pair.token_domain == "renamed" for pair in pairs)
    near_miss = _near_miss_payload(units, pairs)
    assert near_miss["gate_relevant"] is False
    assert near_miss["novelty"] == "untracked"
    assert near_miss["max_edit_statements"] == NEAR_MISS_MAX_EDIT_STATEMENTS
    exact = {
        frozenset(_local_name(str(item["qualname"])) for item in items)
        for items in build_groups(units).values()
    }
    assert not (set(_reported_domains(near_miss)) & exact)


def test_near_miss_payloads_are_deterministic_across_runs() -> None:
    """Two independent builds must serialize byte-identically, domains included."""

    def _serialized() -> str:
        units = _fixture_units()
        payload = _near_miss_payload(units, build_near_miss_pairs(units))
        return json.dumps(payload, sort_keys=True)

    assert _serialized() == _serialized()


def _pairs_package_boot(tmp_path: Path, *, near_miss: bool) -> BootstrapResult:
    """Lay the labelled pair module out as a package and bootstrap over it."""

    package_tree(tmp_path, FIXTURE_ROOT / "pairs.py")
    return analysis_boot(
        tmp_path,
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
        skip_metrics=True,
        near_miss=near_miss,
    )


def _signature(pairs: tuple[NearMissPair, ...]) -> tuple[str, ...]:
    return tuple(
        f"{pair.pair_key}|{pair.token_domain}|{pair.edit_kind}|"
        f"{pair.edit_statements}|"
        + ",".join(
            f"{member.qualname}:{member.differing_start_line}"
            f"-{member.differing_end_line}"
            for member in pair.members
        )
        for pair in pairs
    )


def _cold_then_warm_signatures(
    tmp_path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Run the pipeline cold, save, run warm, and sign both near-miss outputs."""

    boot = _pairs_package_boot(tmp_path, near_miss=True)
    cache_path = tmp_path / "cache.json"
    signatures: list[tuple[str, ...]] = []
    for warm in (False, True):
        extra = {"expect_cache_hits": 2} if warm else {}
        cache, run = run_pipeline_once(
            boot, cache_path, root=tmp_path, warm=warm, **extra
        )
        if not warm:
            cache.save()
        pairs = run.result.near_miss_pairs
        assert pairs is not None, "the opt-in run did not produce the channel"
        signatures.append(_signature(pairs))
    return signatures[0], signatures[1]


def test_renamed_domain_output_matches_cold_and_warm(tmp_path: Path) -> None:
    """The carriage guard for the CACHE_VERSION 3.4 wire.

    A warm run serves units straight off the cache wire without re-parsing,
    so the renamed-canonical statement sequence must ride the wire — and it
    must survive every hand-written copy of the unit fact, including the
    ``_neutral_facts`` rebuild at save time that silently dropped a unit
    field once before. A warm run that loses the sequence would report only
    y8 pairs, so the domain-tagged signatures must match exactly.
    """

    cold_signature, warm_signature = _cold_then_warm_signatures(tmp_path)
    assert any("|renamed|" in row for row in cold_signature), (
        "cold run found no renamed-domain pair; the carriage guard is inert"
    )
    assert cold_signature == warm_signature


def test_renamed_domain_obeys_the_near_miss_opt_in(tmp_path: Path) -> None:
    """One flag owns the channel: off means the channel is not produced.

    ``None`` is the execution witness "the producer was never invoked" — the
    T1 tier-state contract serializes it as ``state: "disabled"`` — so an
    opt-out run must not manufacture an empty measurement in any domain.
    """

    boot = _pairs_package_boot(tmp_path, near_miss=False)
    _cache, run = run_pipeline_once(
        boot, tmp_path / "cache.json", root=tmp_path, warm=False
    )
    assert run.result.near_miss_pairs is None
