# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Behavioral consumers of the ``renamed_structure`` golden fixture.

Wave C of the post-rebench route. The strict exact tier deliberately keeps
semantically meaningful names rigid, so a pair whose only difference is a
bijective, consistent renaming of local bindings and receiver attributes is
invisible to it. The declared rule closing that gap:

    two clone-eligible units group as ``renamed_structure`` when their
    ordinal-canonical digests are equal — an exact match in the tier's own
    digest domain, with no pairwise matcher and no similarity score.

Confinement mirrors the near-miss precedent: the channel never enters
``func_groups``, so it reaches no observation lane, no baseline novelty and
no gate. A group whose members all share one strict-exact fingerprint is the
exact tier's business and is not reported here.

Expected outcomes are read from the fixture's ``ground_truth.json`` — never
inlined here.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from codeclone.contracts import RENAMED_STRUCTURE_ALGORITHM_REVISION
from codeclone.findings.clones.grouping import build_groups, clone_eligible_units
from codeclone.findings.clones.renamed_structure import build_renamed_structure_groups
from codeclone.report.document._findings_groups import build_renamed_structure_payload
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
    from codeclone.models import RenamedStructureGroup

DOMAIN = "renamed_structure"
FIXTURE_ROOT = golden_root(DOMAIN)

# The fixture pairs are sized for these floors; every declared case except the
# deliberate eligibility-out pair clears them, so eligibility never silently
# decides a tier assertion here.
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


def _member_sets(
    groups: tuple[RenamedStructureGroup, ...],
) -> set[frozenset[str]]:
    return {
        frozenset(_local_name(member.qualname) for member in group.members)
        for group in groups
    }


def _co_grouped(member_sets: set[frozenset[str]], members: frozenset[str]) -> bool:
    return any(members <= group_set for group_set in member_sets)


def test_declared_renamed_structure_pairs_group() -> None:
    """The rerun's lost Type-2 pairs must be found by the declared tier."""

    found = _member_sets(build_renamed_structure_groups(_fixture_units()))
    declared = _cases_by_tier("renamed_structure")
    assert declared, "ground truth declares no renamed_structure case"
    for case in declared:
        expected = frozenset(case["members"])
        assert _co_grouped(found, expected), (
            f"{case['id']} did not group as renamed_structure"
        )


def test_negative_twins_stay_unmatched() -> None:
    """One negative twin per contract clause; each must stay out."""

    found = _member_sets(build_renamed_structure_groups(_fixture_units()))
    declared = _cases_by_tier("unmatched")
    assert declared, "ground truth declares no negative twin"
    for case in declared:
        members = frozenset(case["members"])
        assert not _co_grouped(found, members), (
            f"{case['id']} must not group: {case['expected']['clause']}"
        )


def test_exact_only_twins_stay_out_of_the_channel() -> None:
    """A group with one strict-exact fingerprint is the exact tier's business."""

    units = _fixture_units()
    found = _member_sets(build_renamed_structure_groups(units))
    exact_sets = {
        frozenset(_local_name(str(item["qualname"])) for item in items)
        for items in build_groups(units).values()
    }
    for case in _cases_by_tier("exact"):
        members = frozenset(case["members"])
        assert members in exact_sets, f"{case['id']} must reach the exact tier"
        assert not _co_grouped(found, members), (
            f"{case['id']} must stay out of renamed_structure"
        )


def test_groups_span_multiple_exact_fingerprints() -> None:
    """Every reported group carries at least one genuinely renamed pair."""

    groups = build_renamed_structure_groups(_fixture_units())
    assert groups, "the fixture must produce at least one group"
    for group in groups:
        fingerprints = {member.fingerprint for member in group.members}
        assert len(fingerprints) >= 2, (
            f"group {group.group_key} has one exact fingerprint; it belongs "
            "to the exact tier"
        )
        assert group.distinct_exact_fingerprints == len(fingerprints)


def test_single_statement_pair_is_out_by_eligibility() -> None:
    """RS-OUT-INT-01 is expected-out today: eligibility is Wave E territory."""

    case = _case("RS-OUT-INT-01")
    assert case["expected"]["cross_reference"] == "wave-E-eligibility"
    eligible = {_local_name(str(unit["qualname"])) for unit in _fixture_units()}
    for member in case["members"]:
        assert member not in eligible, (
            f"{member} unexpectedly cleared the clone floors; revisit the "
            "ground truth against Wave E"
        )
    found = _member_sets(build_renamed_structure_groups(_fixture_units()))
    assert not _co_grouped(found, frozenset(case["members"]))


def test_report_carries_renamed_structure_outside_the_clone_lane() -> None:
    """Report channel, not a clone lane: gate-neutral and novelty-free."""

    units = _fixture_units()
    groups = build_renamed_structure_groups(units)
    body = build_report_body(
        func_groups=build_groups(units),
        block_groups={},
        segment_groups={},
        meta={"scan_root": str(FIXTURE_ROOT)},
        renamed_structure_groups=groups,
    )
    findings_payload = payload_mapping(body["findings"])
    findings_groups = payload_mapping(findings_payload["groups"])
    clone_families = sorted(payload_mapping(findings_groups["clones"]))
    assert clone_families == ["blocks", "functions", "segments"]
    channel = payload_mapping(findings_groups["renamed_structure"])
    expected_standing = {
        "tier": "renamed_structure",
        "algorithm_revision": RENAMED_STRUCTURE_ALGORITHM_REVISION,
        "gate_relevant": False,
        "novelty": "untracked",
    }
    assert {key: channel[key] for key in expected_standing} == expected_standing
    rendered = payload_sequence(channel["groups"])
    assert channel["count"] == len(rendered) == len(groups)
    reported = {
        frozenset(
            _local_name(str(payload_mapping(member)["qualname"]))
            for member in payload_sequence(payload_mapping(group)["members"])
        )
        for group in rendered
    }
    assert frozenset(_case("RS-PAIR-T2-01")["members"]) in reported
    for group in rendered:
        group_payload = payload_mapping(group)
        # No similarity score of any kind: the payload carries identity and
        # membership facts only.
        assert set(group_payload) == {
            "group_key",
            "member_count",
            "distinct_exact_fingerprints",
            "members",
        }
        for member in payload_sequence(group_payload["members"]):
            assert not str(payload_mapping(member)["relative_path"]).startswith("/")


def test_payloads_are_byte_identical_across_runs() -> None:
    """Two independent extractions must render byte-identical group payloads."""

    def _payload_bytes() -> bytes:
        groups = build_renamed_structure_groups(_fixture_units())
        payload = build_renamed_structure_payload(groups, scan_root=str(FIXTURE_ROOT))
        return json.dumps(payload, sort_keys=True).encode("utf-8")

    assert _payload_bytes() == _payload_bytes()


def _group_signature(
    groups: tuple[RenamedStructureGroup, ...],
) -> tuple[str, ...]:
    return tuple(
        f"{group.group_key}|"
        + ",".join(
            f"{member.qualname}:{member.start_line}-{member.end_line}"
            for member in group.members
        )
        for group in groups
    )


def _pairs_package_boot(tmp_path: Path, *, renamed_structure: bool) -> BootstrapResult:
    """Lay the labelled pair module out as a package and bootstrap over it."""

    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("", "utf-8")
    shutil.copyfile(FIXTURE_ROOT / "pairs.py", package / "pairs.py")
    boot = analysis_boot(
        tmp_path,
        min_loc=FIXTURE_MIN_LOC,
        min_stmt=FIXTURE_MIN_STMT,
        skip_metrics=True,
    )
    boot.args.renamed_structure = renamed_structure
    return boot


def test_renamed_structure_output_matches_cold_and_warm(tmp_path: Path) -> None:
    """The carriage guard: the digest must ride the cache wire.

    Grouping runs over ``processing.units``, and on a warm run those units
    come straight off the cache wire without re-parsing. Unless the
    renamed-structure digest rides the wire, a warm run silently reports
    zero groups — the exact stale-cache trap the own-key/absence-rejects
    carriage rule exists to prevent.
    """

    boot = _pairs_package_boot(tmp_path, renamed_structure=True)
    cache_path = tmp_path / "cache.json"

    cold_cache, cold = run_pipeline_once(boot, cache_path, root=tmp_path, warm=False)
    cold_cache.save()
    _warm_cache, warm = run_pipeline_once(
        boot, cache_path, root=tmp_path, warm=True, expect_cache_hits=2
    )

    cold_groups = cold.result.renamed_structure_groups
    warm_groups = warm.result.renamed_structure_groups
    assert cold_groups is not None and warm_groups is not None, (
        "the opt-in run did not produce the channel"
    )
    cold_signature = _group_signature(cold_groups)
    assert cold_signature, "cold run found no renamed-structure group to compare"
    assert cold_signature == _group_signature(warm_groups)


def test_renamed_structure_channel_is_opt_in(tmp_path: Path) -> None:
    """The tier ships behind its own flag, off by default (near-miss precedent)."""

    def _run(*, renamed_structure: bool) -> tuple[RenamedStructureGroup, ...] | None:
        boot = _pairs_package_boot(tmp_path, renamed_structure=renamed_structure)
        _cache, run = run_pipeline_once(
            boot,
            tmp_path / f"cache-{renamed_structure}.json",
            root=tmp_path,
            warm=False,
        )
        return run.result.renamed_structure_groups

    # Off means not produced (None), never "produced and empty" — the
    # execution witness the T1 tier-state contract serializes as
    # ``state: "disabled"``.
    assert _run(renamed_structure=False) is None
    assert _run(renamed_structure=True), (
        "the opt-in run found no group; the guard is inert"
    )
