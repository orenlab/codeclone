# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Age may make a stored artifact a candidate; it may never be the authority.

``memory.receipt_retention_days`` and ``memory.trajectory_retention_days``
were accepted, validated and materialized onto ``MemoryConfig`` with no reader
anywhere. Giving each its own delete loop would have been the wrong repair:
the keys govern *eligibility*, and eligibility is a conjunction —

    old enough AND unreferenced AND not rooted AND lifecycle allows deletion

Both directions of that rule are pinned here, each error under its own test,
because a retention rule can fail in two opposite ways and only one of them is
loud. Refusing where it should permit stalls a sweep. Permitting where it
should refuse destroys evidence, silently, at whatever moment the sweeper that
consumes the verdict is finally written. The second is the expensive one, so
the refusals get the closer guard: every blind spot in the reference graph
must outrank everything the artifact itself could say.

Two facts about this build the tests hold on to deliberately:

* The production graph resolves *nothing*. That is measured, not assumed, and
  it is why every production sweep refuses. A test that let the production
  graph claim a source it cannot resolve would turn the refusal into a guess.
* No sweeper exists. The vacuum asks the rule about artifacts and deletes only
  records, and that is pinned against a store double which raises on any
  method beyond the record deletion it already had — so the patch cannot have
  started deleting anything.
"""

from __future__ import annotations

import ast
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final

import pytest

from codeclone.memory import retention_eligibility as rule
from codeclone.memory import vacuum as vacuum_module
from codeclone.memory.application import MemoryApplicationContext

from .memory_fixtures import memory_application_context

_NOW: Final = datetime(2026, 8, 28, 12, 0, 0, tzinfo=timezone.utc)


def _stamp(*, days_ago: int) -> str:
    return (_NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _RecordingStore:
    """Vacuum store double that records deletes and refuses anything else.

    ``__getattr__`` fires only for attributes the class does not define, so
    any artifact-deletion call the vacuum might grow raises here instead of
    passing unnoticed. That is the standing proof that no row started being
    deleted: not "we did not see a delete", but "a delete could not have
    happened without this failing".
    """

    def __init__(self) -> None:
        self.deleted_statuses: list[str] = []
        self.committed = False

    def delete_records_older_than(
        self,
        *,
        status: str,
        updated_before_utc: str,
        commit: bool,
    ) -> int:
        del updated_before_utc, commit
        self.deleted_statuses.append(status)
        return 0

    def commit(self) -> None:
        self.committed = True

    def __getattr__(self, name: str) -> object:
        raise AssertionError(
            f"the vacuum reached for store.{name}: this patch must add no "
            "deletion beyond the record retention that already existed"
        )


class _Owner:
    """Retention owner double: the two questions the rule may ask, and no more."""

    def __init__(
        self,
        *,
        days: int | None,
        deletable: tuple[str, ...] = (),
    ) -> None:
        self.days = days
        self.deletable = deletable

    def eligibility_days(self, kind: str) -> int | None:
        del kind
        return self.days

    def deletable_lifecycles(self, kind: str) -> tuple[str, ...]:
        del kind
        return self.deletable


def _complete_graph(
    kind: str = "trajectory",
    **overrides: object,
) -> rule.ArtifactReferenceGraph:
    """A graph that resolved every source declared for *kind*."""
    return rule.ArtifactReferenceGraph(
        resolved_reference_sources=rule.ARTIFACT_REFERENCE_SOURCES[kind],  # type: ignore[index]
        resolved_root_sources=rule.ARTIFACT_ROOT_SOURCES[kind],  # type: ignore[index]
        **overrides,  # type: ignore[arg-type]
    )


def _candidate(
    *,
    kind: str = "trajectory",
    ref: str = "traj-1",
    days_ago: int = 400,
    lifecycle_state: str = "abandoned",
) -> rule.ArtifactCandidate:
    return rule.ArtifactCandidate(
        kind=kind,  # type: ignore[arg-type]
        ref=ref,
        updated_at_utc=_stamp(days_ago=days_ago),
        lifecycle_state=lifecycle_state,
    )


@pytest.fixture(name="aggressive")
def _aggressive(tmp_path: Path) -> MemoryApplicationContext:
    """Every retention set to 0 days: the most destructive legal setting."""
    context = memory_application_context(tmp_path)
    return replace(
        context,
        config=replace(
            context.config,
            active_retention_days=0,
            stale_retention_days=0,
            draft_retention_days=0,
            rejected_retention_days=0,
            archived_retention_days=0,
            receipt_retention_days=0,
            trajectory_retention_days=0,
        ),
    )


# --- the config edge: the keys reach an owner -------------------------------


def test_artifact_retention_days_reach_the_retention_owner(
    aggressive: MemoryApplicationContext,
) -> None:
    """The config edge for the two artifact retention keys."""
    config = replace(
        aggressive.config,
        receipt_retention_days=30,
        trajectory_retention_days=45,
    )
    policy = vacuum_module.MemoryRetentionPolicy.from_config(config)

    assert policy.governed_artifacts == ("receipt", "trajectory")
    assert policy.eligibility_days("receipt") == 30
    assert policy.eligibility_days("trajectory") == 45


def test_governed_artifacts_are_derived_from_the_configured_keys(
    aggressive: MemoryApplicationContext,
) -> None:
    """The owner governs exactly the artifact kinds configuration declares."""
    policy = vacuum_module.MemoryRetentionPolicy.from_config(aggressive.config)
    field_names = {field.name for field in fields(aggressive.config)}

    configured = {
        kind
        for kind in rule.ARTIFACT_KIND_VALUES
        if f"{kind}_retention_days" in field_names
    }
    assert set(policy.governed_artifacts) == configured


def test_negative_artifact_retention_resolves_to_keep_forever(
    aggressive: MemoryApplicationContext,
) -> None:
    """``-1`` is not "delete immediately"; it withholds the age entirely."""
    config = replace(aggressive.config, receipt_retention_days=-1)
    policy = vacuum_module.MemoryRetentionPolicy.from_config(config)

    assert policy.eligibility_days("receipt") is None
    assert policy.eligibility_days("trajectory") == 0


def test_no_artifact_lifecycle_state_is_ratified_as_disposable(
    aggressive: MemoryApplicationContext,
) -> None:
    """The owner declares nothing deletable, for every kind it governs."""
    policy = vacuum_module.MemoryRetentionPolicy.from_config(aggressive.config)
    governed = policy.governed_artifacts
    assert governed, "nothing governed; the decision would be vacuous"

    resolved = {kind: policy.deletable_lifecycles(kind) for kind in governed}
    assert resolved == dict.fromkeys(governed, ())


# --- the production decision: what a real vacuum run gets -------------------


def test_vacuum_refuses_every_governed_artifact_sweep(
    aggressive: MemoryApplicationContext,
) -> None:
    """The production decision: age never authorizes an artifact deletion."""
    store = _RecordingStore()

    report = vacuum_module.run_memory_vacuum(store, aggressive.config, commit=True)  # type: ignore[arg-type]

    policy = vacuum_module.MemoryRetentionPolicy.from_config(aggressive.config)
    assert set(report.artifact_sweep) == set(policy.governed_artifacts)
    assert set(report.artifact_sweep.values()) == {rule.REFERENCES_UNPROVABLE}


def test_vacuum_artifact_outcome_follows_the_configured_value(
    aggressive: MemoryApplicationContext,
) -> None:
    """The enforcement witness: the value changes what production reports.

    Not "the key is read" and not "the key is documented" — the same vacuum
    run reports a different outcome for the receipt lane because the receipt
    key holds a different value, while the trajectory lane is untouched.
    """
    config = replace(aggressive.config, receipt_retention_days=-1)
    store = _RecordingStore()

    report = vacuum_module.run_memory_vacuum(store, config, commit=True)  # type: ignore[arg-type]

    assert report.artifact_sweep == {
        "receipt": rule.RETENTION_UNCONFIGURED,
        "trajectory": rule.REFERENCES_UNPROVABLE,
    }


def test_vacuum_deletes_records_only(
    aggressive: MemoryApplicationContext,
) -> None:
    """No row started being deleted: the store double forbids the attempt."""
    store = _RecordingStore()

    report = vacuum_module.run_memory_vacuum(store, aggressive.config, commit=True)  # type: ignore[arg-type]

    assert store.committed is True
    assert set(store.deleted_statuses) == set(vacuum_module.RETENTION_ENFORCED_STATUSES)
    assert report.total_deleted == 0


def test_production_graph_resolves_no_source_for_any_kind() -> None:
    """The production graph must never claim a source it cannot resolve."""
    graph = rule.production_artifact_reference_graph()

    for kind in rule.ARTIFACT_KIND_VALUES:
        assert (
            graph.missing_reference_sources(kind)
            == (rule.ARTIFACT_REFERENCE_SOURCES[kind])
        )
        assert graph.missing_root_sources(kind) == rule.ARTIFACT_ROOT_SOURCES[kind]
    assert graph.referenced_refs == frozenset()
    assert graph.rooted_refs == frozenset()


# --- the rule refuses: one test per way it can refuse ----------------------


def test_sweep_refuses_when_retention_is_unconfigured() -> None:
    verdict = rule.artifact_sweep_eligibility(
        policy=_Owner(days=None),
        kind="trajectory",
        graph=_complete_graph(),
    )

    assert verdict.outcome == rule.RETENTION_UNCONFIGURED
    assert verdict.eligible is False


def test_sweep_refuses_and_names_an_unresolved_reference_source() -> None:
    graph = rule.ArtifactReferenceGraph(
        resolved_reference_sources=("memory_evidence",),
        resolved_root_sources=rule.ARTIFACT_ROOT_SOURCES["trajectory"],
    )

    verdict = rule.artifact_sweep_eligibility(
        policy=_Owner(days=0, deletable=("abandoned",)),
        kind="trajectory",
        graph=graph,
    )

    assert verdict.outcome == rule.REFERENCES_UNPROVABLE
    assert verdict.missing_sources == ("memory_experience_evidence",)


def test_sweep_refuses_and_names_an_unresolved_root_source() -> None:
    graph = rule.ArtifactReferenceGraph(
        resolved_reference_sources=rule.ARTIFACT_REFERENCE_SOURCES["trajectory"],
        resolved_root_sources=("retained_state", "approved_state"),
    )

    verdict = rule.artifact_sweep_eligibility(
        policy=_Owner(days=0, deletable=("abandoned",)),
        kind="trajectory",
        graph=graph,
    )

    assert verdict.outcome == rule.ROOTS_UNPROVABLE
    assert verdict.missing_sources == ("solved_state", "audit_state")


def test_sweep_refuses_when_no_lifecycle_state_is_ratified() -> None:
    verdict = rule.artifact_sweep_eligibility(
        policy=_Owner(days=0),
        kind="trajectory",
        graph=_complete_graph(),
    )

    assert verdict.outcome == rule.LIFECYCLE_UNRATIFIED


def test_sweep_fails_closed_on_a_kind_that_declares_no_sources() -> None:
    """A kind nobody declared sources for must refuse, not sail through.

    Without this the completeness checks would read "no declared source is
    unresolved" as proof, which is the emptiest possible grant.
    """
    graph = rule.ArtifactReferenceGraph(
        resolved_reference_sources=("memory_evidence",),
        resolved_root_sources=rule.ARTIFACT_ROOT_SOURCES["trajectory"],
    )

    verdict = rule.artifact_sweep_eligibility(
        policy=_Owner(days=0, deletable=("whatever",)),
        kind="blast_cache",  # type: ignore[arg-type]
        graph=graph,
    )

    assert verdict.outcome == rule.REFERENCES_UNPROVABLE
    assert verdict.missing_sources == (rule.UNDECLARED_ARTIFACT_KIND,)


def test_candidate_refuses_when_age_cannot_be_read() -> None:
    candidate = rule.ArtifactCandidate(
        kind="trajectory",
        ref="traj-1",
        updated_at_utc="not-a-timestamp",
        lifecycle_state="abandoned",
    )

    verdict = rule.artifact_candidate_eligibility(
        policy=_Owner(days=0, deletable=("abandoned",)),
        candidate=candidate,
        graph=_complete_graph(),
        now=_NOW,
    )

    assert verdict.outcome == rule.AGE_UNPROVABLE
    assert verdict.ref == "traj-1"


def test_candidate_refuses_while_it_is_younger_than_the_retention() -> None:
    verdict = rule.artifact_candidate_eligibility(
        policy=_Owner(days=365, deletable=("abandoned",)),
        candidate=_candidate(days_ago=364),
        graph=_complete_graph(),
        now=_NOW,
    )

    assert verdict.outcome == rule.TOO_YOUNG


def test_candidate_refuses_when_something_still_references_it() -> None:
    verdict = rule.artifact_candidate_eligibility(
        policy=_Owner(days=365, deletable=("abandoned",)),
        candidate=_candidate(),
        graph=_complete_graph(referenced_refs=("traj-1",)),
        now=_NOW,
    )

    assert verdict.outcome == rule.REFERENCED


def test_candidate_refuses_when_a_root_still_requires_it() -> None:
    verdict = rule.artifact_candidate_eligibility(
        policy=_Owner(days=365, deletable=("abandoned",)),
        candidate=_candidate(),
        graph=_complete_graph(rooted_refs=("traj-1",)),
        now=_NOW,
    )

    assert verdict.outcome == rule.ROOTED


def test_candidate_refuses_a_lifecycle_state_no_ruling_released() -> None:
    verdict = rule.artifact_candidate_eligibility(
        policy=_Owner(days=365, deletable=("abandoned",)),
        candidate=_candidate(lifecycle_state="accepted"),
        graph=_complete_graph(),
        now=_NOW,
    )

    assert verdict.outcome == rule.LIFECYCLE_RETAINS


def test_a_blind_spot_outranks_an_otherwise_eligible_candidate() -> None:
    """Incomplete roots imply no sweep, whatever the artifact looks like.

    The candidate below satisfies every conjunct the rule can check: old
    enough, unreferenced, unrooted among the roots that *were* resolved, and
    in a released lifecycle state. It still refuses, because one declared root
    source was never consulted and an unknown root is indistinguishable from a
    live one.
    """
    graph = rule.ArtifactReferenceGraph(
        resolved_reference_sources=rule.ARTIFACT_REFERENCE_SOURCES["trajectory"],
        resolved_root_sources=("retained_state", "approved_state", "solved_state"),
    )

    verdict = rule.artifact_candidate_eligibility(
        policy=_Owner(days=365, deletable=("abandoned",)),
        candidate=_candidate(),
        graph=graph,
        now=_NOW,
    )

    assert verdict.outcome == rule.ROOTS_UNPROVABLE
    assert verdict.missing_sources == ("audit_state",)
    assert verdict.ref == "traj-1"


# --- the rule permits: the single path to a grant --------------------------


def test_candidate_is_eligible_only_with_every_conjunct_proved() -> None:
    """The grant arm. Reaching it takes a complete graph and a ratified state.

    Neither exists in production, which is the honest state of this build —
    but the arm must stay reachable, or the refusals above would be pinning a
    rule that has no other answer to give.
    """
    verdict = rule.artifact_candidate_eligibility(
        policy=_Owner(days=365, deletable=("abandoned",)),
        candidate=_candidate(days_ago=365),
        graph=_complete_graph(),
        now=_NOW,
    )

    assert verdict.outcome == rule.ELIGIBLE
    assert verdict.eligible is True
    assert verdict.missing_sources == ()


# --- the vocabulary stays knowable from one place --------------------------


def test_every_outcome_the_rule_returns_is_declared() -> None:
    """Mechanically inventory the outcomes, never restate them.

    A hand-kept list of outcomes is the drift it would be meant to catch, so
    the module's own construction sites are the inventory.
    """
    tree = ast.parse(Path(rule.__file__).read_text(encoding="utf-8"))
    returned: set[str] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.func.id != "RetentionEligibility"
        ):
            continue
        for keyword in node.keywords:
            if keyword.arg == "outcome" and isinstance(keyword.value, ast.Name):
                returned.add(getattr(rule, keyword.value.id))

    assert returned, "no outcome construction sites found; the pin is vacuous"
    assert returned <= rule.ARTIFACT_RETENTION_OUTCOMES
    undeclared = rule.ARTIFACT_RETENTION_OUTCOMES - returned - {rule.ELIGIBLE}
    assert not undeclared, (
        f"declared outcomes the rule can never return: {sorted(undeclared)}"
    )


def test_every_governed_artifact_kind_has_its_sources_declared() -> None:
    """No kind may reach the rule without declared referrer and root sources."""
    kinds = set(rule.ARTIFACT_KIND_VALUES)

    assert set(rule.ARTIFACT_REFERENCE_SOURCES) == kinds
    assert set(rule.ARTIFACT_ROOT_SOURCES) == kinds
    assert set(vacuum_module.RATIFIED_DELETABLE_ARTIFACT_LIFECYCLES) == kinds
    assert all(rule.ARTIFACT_REFERENCE_SOURCES[kind] for kind in kinds)
    assert all(rule.ARTIFACT_ROOT_SOURCES[kind] for kind in kinds)
