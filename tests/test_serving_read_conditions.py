# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What a serving reading reads is decided by the run it reads.

The run summary, the patch contract and the blast radius read a published
run through ``read_named_families``.  Two families dominate the price of
that read on a large run (serving-cost audit, 2026-10-05): the authority
graph (``graph_node``, ``semantic_edge``), which settles the conclusions of
the violation rows and of nothing else, and the risk observations, which the
summary and the blast radius reach only through a coverage join.  A run
that holds no violation row publishes no violation finding, and a run that
joined no coverage report has no coverage group: reading either family for
such a run reads bytes no answer is made of.

The rule pinned here, per reading and per branch, on every served
population:

* the authority graph is read exactly when the run holds a violation row;
* the risk observations are read by the summary and the blast radius
  exactly when the run holds a coverage join;
* the blast radius never reads a family no novelty row can name -- the
  known-debt owner walks only the published families a novelty row can
  carry an id of, and that set is derived from the id owner and the novelty
  prefix registry, never listed;
* the projected finding groups of one read are computed once.

The populations distinguish: each branch of each condition is reached by a
named population, and the accounting is asserted before the rule is.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.canonical import finding_projection
from codeclone.canonical.blast_radius_projection import blast_radius_facts_from_model
from codeclone.canonical.comparison_projection import (
    NOVELTY_BEARING_FAMILIES,
    group_novelty,
    known_debt_paths,
    novelty_bearing_families,
)
from codeclone.canonical.comparison_rows import NOVELTY_FAMILY_ID_PREFIXES
from codeclone.canonical.finding_projection import (
    PROJECTED_FAMILIES,
    PROJECTED_FAMILY_ID_NAMESPACES,
    projected_family_groups,
    projected_finding_groups,
    projected_once,
)
from codeclone.canonical.model import novelty_families
from codeclone.canonical.serving import (
    read_served_blast_radius_facts,
    read_served_patch_run,
    read_served_run_summary,
)
from codeclone.canonical.store import (
    FAMILY_COVERAGE_JOIN,
    FAMILY_GRAPH_NODE,
    FAMILY_RISK_OBSERVATION,
    FAMILY_SEMANTIC_EDGE,
    FAMILY_STRUCTURAL_GROUP,
    FAMILY_VIOLATION,
    ReadWhen,
    RunStore,
    read_named_families,
)
from codeclone.domain.findings import FAMILY_AUTHORITY, FAMILY_STRUCTURAL
from tests._blast_radius_serving import BLAST_POPULATIONS, shared_blast_populations
from tests._patch_contract_serving import CYCLE_BUILDERS, shared_cycles
from tests._run_summary_serving import RUN_SUMMARY_POPULATIONS, shared_populations
from tests.test_run_summary_declared_families import scanned

__all__ = ["scanned"]

_GRAPH = frozenset({"graph_node", "semantic_edge"})
_RISK = frozenset({"risk_observation"})


@dataclass(frozen=True, slots=True)
class _Run:
    name: str
    path: Path
    run_id: str
    violations: int
    coverage_joined: bool


def _run(name: str, path: Path, run_id: str) -> _Run:
    with RunStore(path, create=False) as store:
        violations = len(store.read_family(run_id, FAMILY_VIOLATION))
        joined = bool(store.read_family(run_id, FAMILY_COVERAGE_JOIN))
    return _Run(name, path, run_id, violations, joined)


@pytest.fixture(scope="module")
def summary_runs(tmp_path_factory: pytest.TempPathFactory) -> list[_Run]:
    populations = shared_populations(tmp_path_factory)
    runs = []
    for name in RUN_SUMMARY_POPULATIONS:
        population = populations[name]
        link = population.record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        runs.append(_run(name, population.store_path, link.store_run_id))
    return runs


@pytest.fixture(scope="module")
def patch_runs(
    tmp_path_factory: pytest.TempPathFactory, summary_runs: list[_Run]
) -> list[_Run]:
    """Every run the patch-contract battery published, and the summary's."""
    cycles = shared_cycles(tmp_path_factory)
    runs = []
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        for side, record in (("before", cycle.before), ("after", cycle.after)):
            link = None if record is None else record.execution.run_snapshot_link
            if link is not None and link.store_run_id:
                runs.append(_run(f"{name}.{side}", cycle.store_path, link.store_run_id))
    return [*runs, *summary_runs]


@pytest.fixture(scope="module")
def blast_runs(tmp_path_factory: pytest.TempPathFactory) -> list[_Run]:
    populations = shared_blast_populations(tmp_path_factory)
    runs = []
    for name in BLAST_POPULATIONS:
        population = populations[name]
        link = population.record.execution.run_snapshot_link
        assert link is not None and link.store_run_id
        runs.append(_run(name, population.store_path, link.store_run_id))
    return runs


def _families_read(run: _Run, read: object, scanned: list[str]) -> frozenset[str]:
    scanned.clear()
    with RunStore(run.path, create=False) as store:
        read(store, run.run_id)  # type: ignore[operator]
    return frozenset(scanned)


def _branches(runs: list[_Run], *, graph: bool) -> tuple[list[str], list[str]]:
    held = [
        run.name
        for run in runs
        if (run.violations > 0 if graph else run.coverage_joined)
    ]
    empty = [run.name for run in runs if run.name not in held]
    return held, empty


@pytest.mark.parametrize(
    ("reading", "runs_fixture"),
    [
        (read_served_run_summary, "summary_runs"),
        (read_served_patch_run, "patch_runs"),
    ],
    ids=["run_summary", "patch_contract"],
)
def test_the_authority_graph_is_read_exactly_when_the_run_holds_a_violation(
    request: pytest.FixtureRequest,
    reading: object,
    runs_fixture: str,
    scanned: list[str],
) -> None:
    runs: list[_Run] = request.getfixturevalue(runs_fixture)
    held, empty = _branches(runs, graph=True)
    assert held and empty, (held, empty)
    for run in runs:
        read = _families_read(run, reading, scanned)
        assert read.issuperset(_GRAPH) is (run.violations > 0), (run.name, sorted(read))
        assert read.isdisjoint(_GRAPH) is (run.violations == 0), run.name


@pytest.mark.parametrize(
    ("reading", "runs_fixture"),
    [
        (read_served_run_summary, "summary_runs"),
        (read_served_blast_radius_facts, "blast_runs"),
    ],
    ids=["run_summary", "blast_radius"],
)
def test_the_risk_observations_are_read_exactly_when_the_run_joined_coverage(
    request: pytest.FixtureRequest,
    reading: object,
    runs_fixture: str,
    scanned: list[str],
) -> None:
    runs: list[_Run] = request.getfixturevalue(runs_fixture)
    held, empty = _branches(runs, graph=False)
    assert held and empty, (held, empty)
    for run in runs:
        read = _families_read(run, reading, scanned)
        assert read.issuperset(_RISK) is run.coverage_joined, (run.name, sorted(read))


def test_the_patch_contract_reads_its_risk_observations_on_every_run(
    patch_runs: list[_Run], scanned: list[str]
) -> None:
    """The complexity index and the design maxima are the risk lane's on
    every run: no condition holds this family back for the verifier."""
    for run in patch_runs:
        assert _families_read(run, read_served_patch_run, scanned).issuperset(_RISK)


def test_the_blast_radius_reads_no_family_a_novelty_row_cannot_name(
    blast_runs: list[_Run], scanned: list[str]
) -> None:
    """Not the authority graph, not the violation rows that decide it, not
    the structural groups -- on runs with violations as on runs without."""
    held, _empty = _branches(blast_runs, graph=True)
    assert held
    never = _GRAPH | {FAMILY_VIOLATION.family, FAMILY_STRUCTURAL_GROUP.family}
    for run in blast_runs:
        read = _families_read(run, read_served_blast_radius_facts, scanned)
        assert read.isdisjoint(never), (run.name, sorted(read & never))


def test_the_known_debt_paths_need_no_family_a_novelty_row_cannot_name(
    blast_runs: list[_Run],
) -> None:
    """The known-debt owner answers from the families a novelty row can
    name, alone, and its answer is the walk over EVERY published family of
    the whole read -- the oracle here walks them all through the novelty
    word of each group, not through the owner under test.  The population
    holds known debt in the clone family, which a walk that dropped it
    would lose."""
    held, _empty = _branches(blast_runs, graph=True)
    assert held
    known_clones = 0
    for run in blast_runs:
        with RunStore(run.path, create=False) as store:
            whole = store.read_run(run.run_id)
            facts = read_served_blast_radius_facts(store, run.run_id)
        words = group_novelty(whole)
        groups = projected_finding_groups(whole)
        known = [
            (family, group)
            for family in PROJECTED_FAMILIES
            for group in groups[family]
            if words[str(group["id"])] == "known"
        ]
        known_clones += sum(1 for family, _group in known if family == "clone")
        oracle = tuple(
            sorted(
                {
                    str(item["relative_path"])
                    for _family, group in known
                    for item in group["items"]  # type: ignore[attr-defined]
                }
                - {""}
            )
        )
        assert facts.known_debt_paths == known_debt_paths(whole) == oracle, run.name
        assert facts == blast_radius_facts_from_model(whole), run.name
    assert known_clones


@pytest.fixture
def projections(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """How many times the finding groups were projected: the clone family's
    skeletons are built exactly once per projection."""
    calls: list[int] = []
    original = finding_projection.clone_group_skeletons

    def _counting(*args: object, **kwargs: object) -> object:
        calls.append(1)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(finding_projection, "clone_group_skeletons", _counting)
    yield calls


@pytest.mark.parametrize(
    "reading",
    [read_served_run_summary, read_served_patch_run],
    ids=["run_summary", "patch_contract"],
)
def test_one_read_projects_its_finding_groups_once(
    summary_runs: list[_Run], projections: list[int], reading: object
) -> None:
    """The summary used to project the groups four or five times per read
    (finding counts, novelty counts, new-by-source-kind, the coverage block,
    the dependency comparison terms), the patch contract twice."""
    covered = [run for run in summary_runs if run.coverage_joined]
    assert covered
    for run in summary_runs:
        projections.clear()
        with RunStore(run.path, create=False) as store:
            reading(store, run.run_id)  # type: ignore[operator]
        assert len(projections) == 1, (run.name, len(projections))


def test_a_bounded_model_without_the_graph_projects_a_run_without_violations(
    summary_runs: list[_Run],
) -> None:
    """The owner of the violation rows answers ``()`` for a run that holds
    none without reading the graph it does not need -- the same answer the
    whole read's model gives."""
    from codeclone.canonical.authority_projection import violation_projection_rows
    from codeclone.canonical.serving import RUN_SUMMARY_FAMILIES

    without_graph = [
        entry for entry in RUN_SUMMARY_FAMILIES if entry.family not in _GRAPH
    ]
    empty = [run for run in summary_runs if run.violations == 0]
    assert empty
    for run in empty:
        with RunStore(run.path, create=False) as store:
            model = read_named_families(store, run.run_id, without_graph)
            whole = store.read_run(run.run_id)
        assert (
            violation_projection_rows(model) == violation_projection_rows(whole) == ()
        )


def test_the_families_a_novelty_row_can_name_are_derived_from_the_registries() -> None:
    """The derivation rule, held on registries of its own: a family is
    named when a novelty prefix starts its namespace or its namespace starts
    a prefix -- either side alone admits a family the other refuses -- and
    the families the real registries admit leave out the authority and the
    structural families."""
    assert novelty_bearing_families() == NOVELTY_BEARING_FAMILIES
    assert novelty_bearing_families({}) == ()
    assert novelty_bearing_families({"lane": ("authority:contract:",)}) == (
        FAMILY_AUTHORITY,
    )
    assert novelty_bearing_families({"lane": ("struct",)}) == (FAMILY_STRUCTURAL,)
    every_prefix = [
        p for prefixes in NOVELTY_FAMILY_ID_PREFIXES.values() for p in prefixes
    ]
    for family in PROJECTED_FAMILIES:
        namespace = PROJECTED_FAMILY_ID_NAMESPACES[family]
        overlaps = [
            prefix
            for prefix in every_prefix
            if prefix.startswith(namespace) or namespace.startswith(prefix)
        ]
        assert (family in NOVELTY_BEARING_FAMILIES) is bool(overlaps), family
    assert FAMILY_AUTHORITY not in NOVELTY_BEARING_FAMILIES
    assert FAMILY_STRUCTURAL not in NOVELTY_BEARING_FAMILIES


def test_the_premises_of_the_derivation_hold_on_every_published_run(
    blast_runs: list[_Run], summary_runs: list[_Run]
) -> None:
    """The two premises, read off the whole read of every run: each
    published group's id starts with its family's namespace, and each
    stored novelty row's id with a prefix of its novelty family -- so every
    group of a family the derivation leaves out is ``unavailable``.  The
    population holds authority groups to look at."""
    authority_groups = 0
    for run in {
        (item.path, item.run_id): item for item in [*blast_runs, *summary_runs]
    }.values():
        with RunStore(run.path, create=False) as store:
            whole = store.read_run(run.run_id)
        groups = projected_finding_groups(whole)
        words = group_novelty(whole)
        for family in PROJECTED_FAMILIES:
            namespace = PROJECTED_FAMILY_ID_NAMESPACES[family]
            for group in groups[family]:
                assert str(group["id"]).startswith(namespace), (run.name, group["id"])
                if family not in NOVELTY_BEARING_FAMILIES:
                    assert words[str(group["id"])] == "unavailable", run.name
            if family == FAMILY_AUTHORITY:
                authority_groups += len(groups[family])
        for name, rows in novelty_families(whole.facts.comparison):
            for row in rows:
                assert row.finding_id.startswith(NOVELTY_FAMILY_ID_PREFIXES[name])
    assert authority_groups


@pytest.mark.parametrize(
    ("named", "conditions", "refusal"),
    [
        (
            (FAMILY_COVERAGE_JOIN,),
            (ReadWhen(FAMILY_VIOLATION, (FAMILY_GRAPH_NODE,)),),
            "decided by a family the read does not name: violation",
        ),
        (
            (FAMILY_VIOLATION, FAMILY_GRAPH_NODE),
            (ReadWhen(FAMILY_VIOLATION, (FAMILY_GRAPH_NODE,)),),
            "reads a family the read reads already: graph_node",
        ),
        (
            (FAMILY_VIOLATION, FAMILY_COVERAGE_JOIN),
            (
                ReadWhen(FAMILY_VIOLATION, (FAMILY_SEMANTIC_EDGE,)),
                ReadWhen(FAMILY_COVERAGE_JOIN, (FAMILY_SEMANTIC_EDGE,)),
            ),
            "reads a family the read reads already: semantic_edge",
        ),
    ],
    ids=["undecided", "named_twice", "conditioned_twice"],
)
def test_a_malformed_read_condition_is_refused_before_the_store_is_read(
    summary_runs: list[_Run],
    scanned: list[str],
    named: tuple[object, ...],
    conditions: tuple[ReadWhen, ...],
    refusal: str,
) -> None:
    """Every family is read at most once and every condition is decided by
    a family the read itself reads: anything else is a declaration error,
    refused before a single family is scanned."""
    run = summary_runs[0]
    scanned.clear()
    with (
        RunStore(run.path, create=False) as store,
        pytest.raises(ValueError, match=refusal),
    ):
        read_named_families(store, run.run_id, named, read_when=conditions)  # type: ignore[arg-type]
    assert scanned == []


def test_a_condition_reads_its_families_only_on_the_branch_it_names(
    summary_runs: list[_Run], scanned: list[str]
) -> None:
    """The store side alone, one condition per branch: decided by a family
    the run holds rows of, the condition reads its family; decided by one it
    holds none of, it does not."""
    held = next(run for run in summary_runs if run.coverage_joined)
    empty = next(run for run in summary_runs if not run.coverage_joined)
    condition = (ReadWhen(FAMILY_COVERAGE_JOIN, (FAMILY_RISK_OBSERVATION,)),)
    for run, read in ((held, True), (empty, False)):
        scanned.clear()
        with RunStore(run.path, create=False) as store:
            read_named_families(
                store, run.run_id, (FAMILY_COVERAGE_JOIN,), read_when=condition
            )
        assert scanned == (
            ["coverage_join", "risk_observation"] if read else ["coverage_join"]
        ), run.name


def test_each_family_projected_alone_is_the_same_bytes_as_beside_the_others(
    summary_runs: list[_Run],
) -> None:
    """A family's skeletons do not depend on which families are projected
    beside it, so the known-debt owner may project only the families it
    walks."""
    for run in summary_runs:
        with RunStore(run.path, create=False) as store:
            whole = store.read_run(run.run_id)
        every = projected_finding_groups(whole)
        assert list(every) == list(PROJECTED_FAMILIES)
        for family in PROJECTED_FAMILIES:
            assert projected_family_groups(whole, (family,)) == {
                family: every[family]
            }, (run.name, family)


def test_one_read_scope_hands_each_model_its_own_groups(
    summary_runs: list[_Run],
) -> None:
    """Two models projected in one scope: each is projected once, and
    neither is answered with the other's groups."""
    first, second = (
        next(run for run in summary_runs if run.violations),
        next(run for run in summary_runs if run.coverage_joined),
    )
    models = []
    for run in (first, second):
        with RunStore(run.path, create=False) as store:
            models.append(store.read_run(run.run_id))
    alone = [projected_finding_groups(model) for model in models]
    assert alone[0] != alone[1]
    with projected_once():
        inside = [projected_finding_groups(model) for model in models]
        again = [projected_finding_groups(model) for model in models]
    assert inside == alone
    assert [a is b for a, b in zip(inside, again, strict=True)] == [True, True]
