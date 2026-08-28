# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``--changed-only`` counts the ``authority`` family, on a proven membership.

The defect: ``ChangedCloneGate.findings_total`` walked four of the five
baseline-tracked families. ``authority`` was lost when the family was added,
and the number reaches the user through ``surfaces/cli/summary.py`` as
"Findings <n> total" -- a word that was false for any repository carrying an
authority violation in a changed file.

Widening it needed a membership proof first, because a family belongs in a
*changed-scope* total only if a changed path can decide it:

    authority finding -> canonical source address -> changed-scope predicate

The proof is the edge ``group["items"][*]["relative_path"]``: the one address
``_finding_touches_changed_paths`` reads, and the one the authority producer
fills from the violation's own locations. It is pinned here on a **real**
authority group -- ``tests/_authority_findings`` runs the producer chain end to
end -- and never on a group dict typed by hand, which would pin this module's
belief about the producer's shape rather than the shape.

Why a fixture repository at all: this project's own run reports
``authority: 0``, so the published number cannot move on a self-check and
every assertion about it would be green before and after the fix. The fixture
is *distinguishing* by construction -- one authority violation inside the
changed paths and one outside -- so the widening is observable, and "count
everything" cannot be mistaken for "count what the diff touched".
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest

from codeclone.contracts import BASELINE_TRACKED_GROUP_KEYS
from codeclone.surfaces.cli import changed_scope
from codeclone.utils import finding_groups as owner

from ._authority_findings import (
    PARTIAL_SEGMENT_PATH,
    SHADOW_IN_PATH,
    SHADOW_OUT_PATH,
    UNTOUCHED_PATH,
    build_authority_report_document,
    with_advisory_tiers,
)


@pytest.fixture(scope="module")
def authority_document(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """A report document whose ``authority`` container is producer-built."""

    root: Path = tmp_path_factory.mktemp("changed_scope_authority")
    return build_authority_report_document(root)


def _authority_groups(
    document: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    return owner.family_group_list(owner.groups_root_of_document(document), "authority")


def _addresses(group: Mapping[str, object]) -> set[str]:
    return {
        str(cast(Mapping[str, object], item).get("relative_path", ""))
        for item in cast(Sequence[object], group.get("items", ()))
    }


def _group_at(
    document: Mapping[str, object],
    relative_path: str,
) -> Mapping[str, object]:
    matches = [
        group
        for group in _authority_groups(document)
        if relative_path in _addresses(group)
    ]
    assert len(matches) == 1, f"expected one authority group at {relative_path}"
    return matches[0]


# --------------------------------------------------------------------------
# The membership proof: a real authority finding is addressable by path
# --------------------------------------------------------------------------


def test_a_real_authority_finding_carries_the_changed_scope_address(
    authority_document: dict[str, object],
) -> None:
    """The producer fills the one address the changed-scope predicate reads."""

    groups = _authority_groups(authority_document)
    assert len(groups) == 2
    assert {address for group in groups for address in _addresses(group)} == {
        SHADOW_IN_PATH,
        SHADOW_OUT_PATH,
    }
    for group in groups:
        assert str(group.get("family")) == "authority"
        assert group.get("items"), "an authority group with no items is not decidable"
        for address in _addresses(group):
            assert address.strip(), "relative_path is the membership function's input"


@pytest.mark.parametrize(
    ("changed_paths", "expected"),
    [
        pytest.param((SHADOW_IN_PATH,), True, id="exact-file"),
        pytest.param(("pkg",), True, id="directory-prefix"),
        pytest.param((SHADOW_OUT_PATH,), False, id="sibling-file"),
        pytest.param((PARTIAL_SEGMENT_PATH,), False, id="partial-segment"),
        pytest.param((), False, id="empty-selection"),
    ],
)
def test_the_changed_scope_predicate_decides_a_real_authority_finding(
    authority_document: dict[str, object],
    changed_paths: tuple[str, ...],
    expected: bool,
) -> None:
    """Membership is total and segment-bounded on the real group, not a mock."""

    group = _group_at(authority_document, SHADOW_IN_PATH)
    assert (
        changed_scope._finding_touches_changed_paths(group, changed_paths=changed_paths)
        is expected
    )


# --------------------------------------------------------------------------
# The published total
# --------------------------------------------------------------------------


def test_changed_scope_total_counts_the_authority_finding_it_touches(
    authority_document: dict[str, object],
) -> None:
    """The lost family reaches ``findings_total``.

    Before the widening this gate published ``0`` while an authority finding
    sat in the changed file: the number the CLI prints as "total" omitted a
    published family.
    """

    gate = changed_scope._changed_clone_gate_from_report(
        authority_document, changed_paths=(SHADOW_IN_PATH,)
    )
    assert gate.findings_total == 1


def test_changed_scope_total_leaves_out_the_authority_finding_it_misses(
    authority_document: dict[str, object],
) -> None:
    """The widening is scope-filtered, not "count every authority group".

    The document carries two authority findings; a diff touching neither file
    must still publish zero, and a path cut mid-component is not a hit.
    Without this control a predicate stuck at ``True`` would pass the test
    above and be called a fix.
    """

    missing = changed_scope._changed_clone_gate_from_report(
        authority_document, changed_paths=(UNTOUCHED_PATH,)
    )
    assert missing.findings_total == 0

    partial = changed_scope._changed_clone_gate_from_report(
        authority_document, changed_paths=(PARTIAL_SEGMENT_PATH,)
    )
    assert partial.findings_total == 0


def test_changed_scope_total_counts_each_touched_authority_finding_once(
    authority_document: dict[str, object],
) -> None:
    """A package-wide diff reaches both findings, and no more than both."""

    gate = changed_scope._changed_clone_gate_from_report(
        authority_document, changed_paths=("pkg",)
    )
    assert gate.findings_total == 2


def test_the_authority_finding_reaches_its_own_novelty_counter(
    authority_document: dict[str, object],
) -> None:
    """It enters the total through a counter, not as an unaccounted remainder.

    An authority group carries ``novelty: unavailable`` -- its comparison
    never ran -- so the third novelty term is where it must land. A finding
    counted in the total but in none of the novelty counters would break the
    arithmetic the summary line prints.
    """

    gate = changed_scope._changed_clone_gate_from_report(
        authority_document, changed_paths=("pkg",)
    )
    assert gate.findings_unavailable == 2
    assert gate.findings_new == 0
    assert gate.findings_known == 0
    assert (
        gate.findings_new + gate.findings_known + gate.findings_unavailable
        == gate.findings_total
    )


# --------------------------------------------------------------------------
# The universe, and where it is resolved from
# --------------------------------------------------------------------------


def test_the_changed_scope_universe_is_the_whole_owner_universe() -> None:
    """No family is subtracted, and no tier is admitted.

    Both directions matter, and only one of them has a second line of
    defence. Dropping ``authority`` restores the defect and moves the
    published number, so the value tests below catch it too. Admitting
    ``near_miss`` or ``renamed_structure`` moves no number at all -- the next
    test measures why -- so this declaration is the *only* place that error
    class reds. That is what makes the assertion here load-bearing rather
    than decorative.
    """

    universe = changed_scope.changed_scope_group_keys()
    assert universe == tuple(BASELINE_TRACKED_GROUP_KEYS)
    assert "authority" in universe
    for tier in ("near_miss", "renamed_structure"):
        assert tier not in universe


def test_the_changed_scope_universe_follows_a_redirected_owner(
    monkeypatch: pytest.MonkeyPatch,
    authority_document: dict[str, object],
) -> None:
    """The enforcement witness: the universe is resolved from the owner.

    A consumer holding a private enumeration is observationally identical to
    one that asks the owner -- until the owner is redirected. Redirecting it
    to the authority family alone, and then away from it, must move both the
    declared universe and the number this gate publishes; a private list stays
    behind and reds here while every other test in this module stays green.
    """

    monkeypatch.setattr(owner, "BASELINE_TRACKED_GROUP_KEYS", ("authority",))
    assert changed_scope.changed_scope_group_keys() == ("authority",)
    only_authority = changed_scope._changed_clone_gate_from_report(
        authority_document, changed_paths=(SHADOW_OUT_PATH,)
    )
    assert only_authority.findings_total == 1

    monkeypatch.setattr(owner, "BASELINE_TRACKED_GROUP_KEYS", ("clones",))
    assert changed_scope.changed_scope_group_keys() == ("clones",)
    without_authority = changed_scope._changed_clone_gate_from_report(
        authority_document, changed_paths=("pkg",)
    )
    assert without_authority.findings_total == 0


def test_an_admitted_advisory_tier_still_cannot_reach_the_total(
    monkeypatch: pytest.MonkeyPatch,
    authority_document: dict[str, object],
) -> None:
    """What actually keeps the tiers out of this number -- measured, not assumed.

    The declaration above is the guard: the universe never names a tier. This
    test measures what stands behind it, by admitting both tiers into the
    universe on purpose and watching what happens, and the answer is not the
    tidy one. ``renamed_structure`` nests under ``groups``, so the family walk
    really does hand its record to the gate; ``near_miss`` keys its list
    ``pairs``, so the same walk never sees it at all. Neither one moves the
    published number, and for a third reason again: a tier record carries
    ``members``, never ``items``, so the changed-scope predicate cannot read an
    address off it.

    So the number is structurally blind to this error class and must not be
    mistaken for the thing that guards it -- a reader who assumed otherwise
    would be trusting a test that no mutation can red. What is pinned here is
    the blindness itself: teach the predicate to follow ``members`` and the
    tier record starts counting, and this reds.
    """

    document = with_advisory_tiers(authority_document)
    published = {
        (family, container)
        for family, container, _entries in owner.iter_published_group_lists(document)
    }
    assert ("near_miss", "pairs") in published
    assert ("renamed_structure", "groups") in published

    declared = changed_scope._changed_clone_gate_from_report(
        document, changed_paths=(SHADOW_IN_PATH,)
    )
    assert declared.findings_total == 1

    monkeypatch.setattr(
        owner,
        "BASELINE_TRACKED_GROUP_KEYS",
        (*BASELINE_TRACKED_GROUP_KEYS, "near_miss", "renamed_structure"),
    )
    walked = changed_scope._flatten_report_findings(document)
    assert any("group_key" in group for group in walked), (
        "renamed_structure nests under 'groups'; the family walk must reach it"
    )
    assert not any("pair_key" in group for group in walked), (
        "near_miss keys its list 'pairs'; the family walk must not reach it"
    )

    admitted = changed_scope._changed_clone_gate_from_report(
        document, changed_paths=(SHADOW_IN_PATH,)
    )
    assert admitted.findings_total == declared.findings_total
