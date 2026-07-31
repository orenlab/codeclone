# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Behavioral consumers of the ``design_metrics`` golden fixture.

Phase 39Y slice Y5: clone-lane eligibility floors (``min_loc`` / ``min_stmt``)
must not decide which functions carry metric facts.

Phase 39Y slice Y6: CBO counts both declared edge lanes — local typed
collaborators and imported-domain edges (see the edge contract in
``codeclone/metrics/coupling.py``). A call position is an edge only when the
callee provably resolves to an analyzed class; syntax alone is not evidence.

Expected values are read from the fixture's ``ground_truth.json`` — never
inlined here.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.units import extract_units_and_stats_from_source
from codeclone.findings.clones.grouping import build_groups, clone_eligible_units
from codeclone.metrics.coupling import resolve_project_class_coupling
from codeclone.metrics.dependencies import build_dep_graph
from codeclone.paths.module_identity.inventory import build_module_registry

if TYPE_CHECKING:
    from codeclone.models import ClassMetrics, ModuleDep, Unit

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "design_metrics"

# Each mount is its own project, and every extraction below mounts it as one.
# Analyzed from the domain root instead, ``acme`` sits one level below the root
# and every ``from acme...`` import resolves external, so nothing inside the
# tree resolves internally and the declared dependency cycle cannot be observed
# at all. That is a property of the fixture layout, not of the code under test.
_MOUNTS = ("original", "renamed")

# The pyscn benchmark ran CodeClone with clone floors aligned to the
# competitor's unit size (min_loc=10). `simple` spans two physical lines and
# one statement, so both floors reject it as a clone unit — that rejection is
# what used to erase it from the complexity facts.
ALIGNED_MIN_LOC = 10
ALIGNED_MIN_STMT = 4

_UnitKey = tuple[str, str]


def _ground_truth() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (FIXTURE_ROOT / "ground_truth.json").read_text("utf-8")
    )
    return payload


def _cases_with(expected_key: str) -> list[dict[str, Any]]:
    return [
        case for case in _ground_truth()["cases"] if expected_key in case["expected"]
    ]


def _extract_units(*, min_loc: int, min_stmt: int) -> dict[_UnitKey, Unit]:
    """Return every emitted unit of the fixture tree keyed by (path, symbol).

    Mounted per project, so a unit carries the same module identity it would
    carry if the mount were the repository root.
    """

    cfg = NormalizationConfig()
    units_by_key: dict[_UnitKey, Unit] = {}
    for mount in _MOUNTS:
        mount_root = FIXTURE_ROOT / mount
        registry = build_module_registry(root=mount_root)
        for relative_path, entry in sorted(registry.entries_by_path.items()):
            source = (mount_root / relative_path).read_text("utf-8")
            units, *_rest = extract_units_and_stats_from_source(
                source=source,
                filepath=relative_path,
                identity=entry.identity,
                registry=registry,
                cfg=cfg,
                min_loc=min_loc,
                min_stmt=min_stmt,
            )
            for unit in units:
                key = (f"{mount}/{relative_path}", unit.qualname.rsplit(":", 1)[-1])
                units_by_key[key] = unit
    return units_by_key


def _cycle_modules(mount: str) -> frozenset[str]:
    """Return every module of one mount that sits on a dependency cycle."""

    mount_root = FIXTURE_ROOT / mount
    registry = build_module_registry(root=mount_root)
    cfg = NormalizationConfig()
    deps: list[ModuleDep] = []
    for relative_path, entry in sorted(registry.entries_by_path.items()):
        source = (mount_root / relative_path).read_text("utf-8")
        *_lanes, file_metrics, _findings = extract_units_and_stats_from_source(
            source=source,
            filepath=relative_path,
            identity=entry.identity,
            registry=registry,
            cfg=cfg,
            min_loc=ALIGNED_MIN_LOC,
            min_stmt=ALIGNED_MIN_STMT,
        )
        deps.extend(file_metrics.module_deps)
    graph = build_dep_graph(registry=registry, deps=deps)
    return frozenset(module for cycle in graph.cycles for module in cycle)


def _module_of(mount: str, relative_path: str) -> str:
    """Return the module identity a path carries when its mount is the root."""

    registry = build_module_registry(root=FIXTURE_ROOT / mount)
    identity = registry.entries_by_path[relative_path].identity
    assert identity.python_module is not None, relative_path
    return identity.python_module.module


def _module_by_suffix(mount: str, suffix: str) -> str:
    """Return the one module of a mount whose path ends with ``suffix``.

    The renamed twin renames packages as well as symbols, so a mount-agnostic
    assertion cannot spell a package name.
    """

    registry = build_module_registry(root=FIXTURE_ROOT / mount)
    matches = [
        path for path in sorted(registry.entries_by_path) if path.endswith(suffix)
    ]
    assert len(matches) == 1, f"{mount}: {suffix} matched {matches}"
    return _module_of(mount, matches[0])


def _extract_class_metrics() -> dict[_UnitKey, tuple[int, tuple[str, ...]]]:
    """Return ``(cbo, coupled_classes)`` per (path, class name) of the tree.

    Resolution of imported call targets is a whole-project fact, so each mount
    is extracted file by file and then folded exactly as the pipeline folds it.
    """

    metrics_by_key: dict[_UnitKey, tuple[int, tuple[str, ...]]] = {}
    cfg = NormalizationConfig()
    for mount in _MOUNTS:
        mount_root = FIXTURE_ROOT / mount
        registry = build_module_registry(root=mount_root)
        collected: list[ClassMetrics] = []
        for relative_path, entry in sorted(registry.entries_by_path.items()):
            source = (mount_root / relative_path).read_text("utf-8")
            *_clone_lanes, file_metrics, _findings = (
                extract_units_and_stats_from_source(
                    source=source,
                    filepath=relative_path,
                    identity=entry.identity,
                    registry=registry,
                    cfg=cfg,
                    min_loc=ALIGNED_MIN_LOC,
                    min_stmt=ALIGNED_MIN_STMT,
                )
            )
            collected.extend(file_metrics.class_metrics)
        for metric in resolve_project_class_coupling(collected):
            key = (f"{mount}/{metric.filepath}", metric.qualname.rsplit(":", 1)[-1])
            metrics_by_key[key] = (metric.cbo, metric.coupled_classes)
    return metrics_by_key


@pytest.mark.parametrize(
    "case",
    _cases_with("coupling"),
    ids=lambda case: str(case["id"]),
)
def test_coupling_counts_both_declared_edge_lanes(case: dict[str, Any]) -> None:
    """CBO meets ground truth for local AND imported-domain collaborators."""

    metrics = _extract_class_metrics()
    key = (str(case["path"]), str(case["symbol"]))

    assert key in metrics, (
        f"{case['id']}: no class metric for {case['symbol']}; "
        f"emitted classes for this file: "
        f"{sorted(symbol for path, symbol in metrics if path == case['path'])}"
    )
    cbo, coupled_classes = metrics[key]
    assert cbo == case["expected"]["coupling"], (
        f"{case['id']}: CBO {cbo} != ground truth "
        f"{case['expected']['coupling']}; counted edges: {coupled_classes}"
    )


def test_call_position_edges_require_proven_class_resolution() -> None:
    """A call position is an edge only when its callee resolves to a class.

    The four call sites are syntactically identical. ``Invoice()`` and
    ``catalog.Receipt()`` resolve to analyzed classes and are edges; the
    function, the decorator factory and the import that leaves the analysis
    root resolve to no class and are therefore not edges. Counting ``Call``
    syntax cannot separate them, which is exactly the defect this rule closes.
    """

    metrics = _extract_class_metrics()
    path = "original/acme/instantiation.py"

    assert metrics[(path, "ResolvedConstructorCall")] == (1, ("Invoice",))
    assert metrics[(path, "DottedConstructorCall")] == (1, ("Receipt",))
    assert metrics[(path, "OpaqueCallTargets")] == (0, ())


def test_import_alias_does_not_change_the_coupling_count() -> None:
    """Importing the same class under an alias yields the same CBO.

    The edge is labelled with the binding the source itself uses — the same
    convention the annotation lane follows — but the count, which is the
    metric, must not move because a name was rebound.
    """

    metrics = _extract_class_metrics()
    path = "original/acme/instantiation.py"
    direct_cbo, _direct_edges = metrics[(path, "ResolvedConstructorCall")]
    aliased_cbo, aliased_edges = metrics[(path, "AliasedConstructorCall")]

    assert aliased_cbo == direct_cbo == 1
    assert aliased_edges == ("Bill",)


def test_coupling_facts_are_rename_invariant() -> None:
    """Renamed twins carry identical CBO facts."""

    ground_truth = _ground_truth()
    by_id = {str(case["id"]): case for case in ground_truth["cases"]}
    metrics = _extract_class_metrics()

    checked = 0
    for original_id, renamed_id in ground_truth["rename_twins"]:
        original = by_id[str(original_id)]
        renamed = by_id[str(renamed_id)]
        if "coupling" not in original["expected"]:
            continue
        original_cbo, _ = metrics[(str(original["path"]), str(original["symbol"]))]
        renamed_cbo, _ = metrics[(str(renamed["path"]), str(renamed["symbol"]))]
        assert original_cbo == renamed_cbo, (
            f"{original_id} vs {renamed_id}: CBO differs under rename"
        )
        checked += 1

    assert checked, "no coupling rename twins declared in ground truth"


def test_coupling_negative_twins_stay_distinguishable() -> None:
    """The declared negative pairs keep different CBO values.

    ``CBO-COORDINATOR`` (3 local collaborators) vs ``CBO-ORDER`` (1 imported
    edge) is the fixture's declared two-lane axis: counting only one edge kind
    collapses the pair.
    """

    ground_truth = _ground_truth()
    by_id = {str(case["id"]): case for case in ground_truth["cases"]}
    metrics = _extract_class_metrics()

    checked = 0
    for high_id, low_id in ground_truth["negative_twins"]:
        high = by_id[str(high_id)]
        low = by_id[str(low_id)]
        if "coupling" not in high["expected"] or "coupling" not in low["expected"]:
            continue
        high_cbo, _ = metrics[(str(high["path"]), str(high["symbol"]))]
        low_cbo, _ = metrics[(str(low["path"]), str(low["symbol"]))]
        assert high_cbo > low_cbo, f"{high_id} vs {low_id}: CBO no longer separates"
        checked += 1

    assert checked, "no coupling negative twins declared in ground truth"


@pytest.mark.parametrize(
    "case",
    _cases_with("dependency_cycle"),
    ids=lambda case: str(case["id"]),
)
def test_declared_dependency_cycles_are_observed_per_mount(
    case: dict[str, Any],
) -> None:
    """The ``order`` <-> ``payment`` cycle is a fact of each mounted project.

    These cases were declared in the ground truth from the start but nothing
    asserted them, because the fixture tree was extracted from the domain root
    where the fixture's own imports resolve external and no cycle can form.
    """

    mount, _, relative_path = str(case["path"]).partition("/")
    module = _module_of(mount, relative_path)

    assert (module in _cycle_modules(mount)) is bool(
        case["expected"]["dependency_cycle"]
    ), f"{case['id']}: {module} does not match its declared cycle membership"


def test_dependency_cycle_membership_is_rename_invariant() -> None:
    """The renamed twin carries the same cycle fact under different names."""

    ground_truth = _ground_truth()
    by_id = {str(case["id"]): case for case in ground_truth["cases"]}
    cycles_by_mount = {mount: _cycle_modules(mount) for mount in _MOUNTS}

    checked = 0
    for original_id, renamed_id in ground_truth["rename_twins"]:
        original = by_id[str(original_id)]
        renamed = by_id[str(renamed_id)]
        if "dependency_cycle" not in original["expected"]:
            continue
        pair = []
        for case in (original, renamed):
            mount, _, relative_path = str(case["path"]).partition("/")
            pair.append(_module_of(mount, relative_path) in cycles_by_mount[mount])
        assert pair[0] == pair[1], (
            f"{original_id} vs {renamed_id}: cycle membership differs under rename"
        )
        checked += 1

    assert checked, "no dependency-cycle rename twins declared in ground truth"


def test_acyclic_modules_of_the_same_mount_are_not_reported_as_cyclic() -> None:
    """Negative control: only the declared mutual pair is on a cycle.

    The mount holds internal imports that are not cycles — the instantiation
    cases import the catalog module one way. A detector that called every
    internal edge a cycle would fail here.
    """

    for mount in _MOUNTS:
        cyclic = _cycle_modules(mount)
        assert len(cyclic) == 2, f"{mount}: expected one mutual pair, got {cyclic}"
        acyclic = _module_by_suffix(mount, "instantiation.py")
        assert acyclic not in cyclic


@pytest.mark.parametrize(
    "case",
    _cases_with("complexity"),
    ids=lambda case: str(case["id"]),
)
def test_complexity_facts_are_not_gated_by_clone_floors(case: dict[str, Any]) -> None:
    """Every defined function carries its complexity fact at any clone floor."""

    units = _extract_units(min_loc=ALIGNED_MIN_LOC, min_stmt=ALIGNED_MIN_STMT)
    key = (str(case["path"]), str(case["symbol"]))

    assert key in units, (
        f"{case['id']}: no metric fact for {case['symbol']} at clone floors "
        f"min_loc={ALIGNED_MIN_LOC}/min_stmt={ALIGNED_MIN_STMT}; "
        f"emitted symbols for this file: "
        f"{sorted(symbol for path, symbol in units if path == case['path'])}"
    )
    assert units[key].cyclomatic_complexity == case["expected"]["complexity"]


def test_clone_lane_still_applies_the_floors() -> None:
    """Decoupling the metric facts must not widen the clone lane.

    The sub-floor function gains a metric fact and stays out of the clone
    population; the above-floor function is in both.
    """

    units = _extract_units(min_loc=ALIGNED_MIN_LOC, min_stmt=ALIGNED_MIN_STMT)
    by_id = {str(case["id"]): case for case in _ground_truth()["cases"]}
    simple = by_id["CC-SIMPLE"]
    branchy = by_id["CC-BRANCHY"]

    eligible = clone_eligible_units(
        [asdict(unit) for unit in units.values()],
        min_loc=ALIGNED_MIN_LOC,
        min_stmt=ALIGNED_MIN_STMT,
    )
    eligible_qualnames = {str(unit["qualname"]) for unit in eligible}

    simple_unit = units[(str(simple["path"]), str(simple["symbol"]))]
    branchy_unit = units[(str(branchy["path"]), str(branchy["symbol"]))]

    assert simple_unit.qualname not in eligible_qualnames
    assert branchy_unit.qualname in eligible_qualnames

    grouped_qualnames = {
        str(item["qualname"])
        for items in build_groups(eligible).values()
        for item in items
    }
    assert simple_unit.qualname not in grouped_qualnames


def test_sub_floor_units_emit_no_clone_artifacts() -> None:
    """A sub-floor unit carries metric facts but no blocks or segments."""

    mount_root = FIXTURE_ROOT / "original"
    registry = build_module_registry(root=mount_root)
    relative_path = "acme/complexity_cases.py"
    entry = registry.entries_by_path[relative_path]
    units, blocks, segments, *_rest = extract_units_and_stats_from_source(
        source=(mount_root / relative_path).read_text("utf-8"),
        filepath=relative_path,
        identity=entry.identity,
        registry=registry,
        cfg=NormalizationConfig(),
        # Floors above every function in the file: nothing is clone-eligible,
        # yet every function keeps its metric fact.
        min_loc=1_000,
        min_stmt=1_000,
        block_min_loc=1,
        block_min_stmt=1,
        segment_min_loc=1,
        segment_min_stmt=1,
    )

    assert {unit.qualname.rsplit(":", 1)[-1] for unit in units} == {"simple", "branchy"}
    assert blocks == []
    assert segments == []


def test_complexity_facts_are_rename_invariant() -> None:
    """Renamed twins carry identical complexity facts."""

    ground_truth = _ground_truth()
    by_id = {str(case["id"]): case for case in ground_truth["cases"]}
    units = _extract_units(min_loc=ALIGNED_MIN_LOC, min_stmt=ALIGNED_MIN_STMT)

    checked = 0
    for original_id, renamed_id in ground_truth["rename_twins"]:
        original = by_id[str(original_id)]
        renamed = by_id[str(renamed_id)]
        if "complexity" not in original["expected"]:
            continue
        original_unit = units[(str(original["path"]), str(original["symbol"]))]
        renamed_unit = units[(str(renamed["path"]), str(renamed["symbol"]))]
        assert (
            original_unit.cyclomatic_complexity == renamed_unit.cyclomatic_complexity
        ), f"{original_id} vs {renamed_id}: complexity differs under rename"
        checked += 1

    assert checked, "no complexity rename twins declared in ground truth"


def test_complexity_negative_twins_stay_distinguishable() -> None:
    """The declared negative pairs keep different complexity values."""

    ground_truth = _ground_truth()
    by_id = {str(case["id"]): case for case in ground_truth["cases"]}
    units = _extract_units(min_loc=ALIGNED_MIN_LOC, min_stmt=ALIGNED_MIN_STMT)

    checked = 0
    for high_id, low_id in ground_truth["negative_twins"]:
        high = by_id[str(high_id)]
        low = by_id[str(low_id)]
        if "complexity" not in high["expected"] or "complexity" not in low["expected"]:
            continue
        high_unit = units[(str(high["path"]), str(high["symbol"]))]
        low_unit = units[(str(low["path"]), str(low["symbol"]))]
        assert high_unit.cyclomatic_complexity > low_unit.cyclomatic_complexity
        checked += 1

    assert checked, "no complexity negative twins declared in ground truth"
