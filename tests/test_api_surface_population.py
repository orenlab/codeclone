# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Who owns the api-surface population, and what each of its inputs decides.

``is_product_api_module`` was a predicate with optional inputs, called from
nineteen places with four different input sets. The owner replaces it with one
verdict per module over a closed vocabulary, and every test here exists because
one specific input decides one specific verdict — drop the input and a
different, wrong verdict is returned, which is what the mutation battery reds.

The declared cases live in ``tests/fixtures/source_kind/ground_truth.json`` so
the expectations are a fixture the fixture tree can be checked against, not
literals retyped beside the code that produces them.
"""

from __future__ import annotations

from pathlib import Path

from codeclone.core.entrypoints import collect_project_distributed_packages
from codeclone.domain.source_scope import (
    SURFACE_KIND_ORDER,
    SURFACE_KIND_PRODUCT_INTERNAL,
    SURFACE_KIND_PRODUCT_PUBLIC,
    SURFACE_KIND_REPOSITORY_SUPPORT,
    SURFACE_KIND_TEST_SUPPORT,
)
from codeclone.metrics._visibility import build_module_visibility
from codeclone.metrics.api_population import ApiSurfacePopulation
from codeclone.metrics.api_surface import collect_module_api_surface
from codeclone.models import ApiSurfaceSnapshot, ModuleApiSurface
from codeclone.paths.module_identity.inventory import build_module_registry
from tests._ast_metrics_helpers import tree_collector_and_imports
from tests._pipeline_fixtures import golden_ground_truth, golden_root

_FIXTURE_ROOT = golden_root("source_kind") / "distribution"


def _population() -> ApiSurfacePopulation:
    return ApiSurfacePopulation(
        scan_root=str(_FIXTURE_ROOT),
        module_registry=build_module_registry(root=_FIXTURE_ROOT),
        distributed_packages=collect_project_distributed_packages(_FIXTURE_ROOT),
    )


def _declared_cases() -> list[dict[str, str]]:
    cases = golden_ground_truth("source_kind")["surface_kind_cases"]
    assert isinstance(cases, list) and cases
    return [
        {
            "id": str(case["id"]),
            "path": str(case["path"]),
            "module": str(case["module"]),
            "surface_kind": str(case["expected"]["surface_kind"]),
        }
        for case in cases
    ]


def test_every_declared_case_gets_the_kind_the_fixture_declares() -> None:
    """The whole decision table, driven from the fixture's own ground truth.

    Five cases, four kinds, and each case differs from at least one other by
    exactly one input — that is what ``surface_kind_twins`` records. A rule
    that dropped any single input answers at least one of these wrongly.
    """

    population = _population()
    verdicts = {
        case["id"]: population.surface_kind(
            filepath=str(golden_root("source_kind") / case["path"]),
            module=case["module"],
        )
        for case in _declared_cases()
    }
    expected = {case["id"]: case["surface_kind"] for case in _declared_cases()}
    assert verdicts == expected
    assert set(expected.values()) == set(SURFACE_KIND_ORDER), (
        "the fixture stopped covering every declared kind, so at least one "
        "branch of the owner has no input reaching it"
    )


def test_the_distribution_manifest_is_what_separates_the_shipped_twin() -> None:
    """Same path shape, same public surface: only the manifest differs.

    ``shipped/tool.py`` and ``scripts/tool.py`` are byte-identical modules of
    identical source kind. Without the manifest input both are product surface,
    which is the state this repository measured: 219 of 5409 collected symbols
    sat outside the distributed package and every one of them could gate.
    """

    with_manifest = _population()
    without_manifest = ApiSurfacePopulation(
        scan_root=str(_FIXTURE_ROOT),
        module_registry=build_module_registry(root=_FIXTURE_ROOT),
    )
    shipped = str(_FIXTURE_ROOT / "shipped" / "tool.py")
    unshipped = str(_FIXTURE_ROOT / "scripts" / "tool.py")

    assert (
        with_manifest.surface_kind(filepath=shipped, module="shipped.tool")
        == SURFACE_KIND_PRODUCT_PUBLIC
    )
    assert (
        with_manifest.surface_kind(filepath=unshipped, module="scripts.tool")
        == SURFACE_KIND_REPOSITORY_SUPPORT
    )
    # Undeclared is not "nothing ships": the owner keeps the pre-split answer
    # rather than emptying the lane for every repository whose build backend it
    # cannot read.
    assert (
        without_manifest.surface_kind(filepath=unshipped, module="scripts.tool")
        == SURFACE_KIND_PRODUCT_PUBLIC
    )


def test_module_privacy_is_what_separates_the_internal_twin() -> None:
    """Same distributed package, same manifest: only the module name differs."""

    population = _population()
    assert (
        population.surface_kind(
            filepath=str(_FIXTURE_ROOT / "shipped" / "_internal.py"),
            module="shipped._internal",
        )
        == SURFACE_KIND_PRODUCT_INTERNAL
    )
    assert (
        population.surface_kind(
            filepath=str(_FIXTURE_ROOT / "shipped" / "tool.py"),
            module="shipped.tool",
        )
        == SURFACE_KIND_PRODUCT_PUBLIC
    )


def test_the_test_track_wins_over_every_other_input() -> None:
    """A test tree is test support whatever the manifest and the name say.

    Order inside the decision table is itself a decision: the repository's own
    suite must not become ``repository_support`` (which would read as "shipped
    question, answered no") or ``product_internal``.
    """

    population = _population()
    assert (
        population.surface_kind(
            filepath=str(_FIXTURE_ROOT / "tests" / "test_probe.py"),
            module="tests.test_probe",
        )
        == SURFACE_KIND_TEST_SUPPORT
    )


def test_a_declared_testing_subpackage_still_ships() -> None:
    """The registry, not the directory name, decides a ``testing`` subpackage.

    This is the input the tests/ half of the split already depended on, kept
    under the owner so a manifest that lists ``shipped.testing`` cannot be
    overruled by the directory vocabulary.
    """

    population = _population()
    assert (
        population.surface_kind(
            filepath=str(_FIXTURE_ROOT / "shipped" / "testing" / "helpers.py"),
            module="shipped.testing.helpers",
        )
        == SURFACE_KIND_PRODUCT_PUBLIC
    )


def test_only_product_public_gates() -> None:
    """Gating is a projection of the kind, not a second rule.

    Asserted over the whole vocabulary so a new kind cannot quietly default
    into the gating population.
    """

    population = _population()
    gating = {
        case["id"]: population.surface_kind(
            filepath=str(golden_root("source_kind") / case["path"]),
            module=case["module"],
        )
        == SURFACE_KIND_PRODUCT_PUBLIC
        for case in _declared_cases()
    }
    expected = {
        case["id"]: case["surface_kind"] == SURFACE_KIND_PRODUCT_PUBLIC
        for case in _declared_cases()
    }
    assert gating == expected


def _visibility(
    source: str, *, module_name: str, include_private: bool
) -> frozenset[str]:
    tree, collector, imports = tree_collector_and_imports(
        source, module_name=module_name
    )
    return build_module_visibility(
        tree=tree,
        module_name=module_name,
        collector=collector,
        imported_names=imports,
        include_private_modules=include_private,
    ).exported_names


_PRIVATE_MODULE_WITH_ALL = (
    '__all__ = ["helper"]\n\n\ndef helper(value: int) -> int:\n    return value\n'
)


def test_a_private_module_declaring_all_reaches_the_privacy_guard() -> None:
    """M8: some input trips ``include_private_modules``, in both directions.

    Before the fix this flag was inert for every module declaring ``__all__``:
    the export list was consulted first, so a private module's names were
    admitted whatever the flag said. Measured on this repository, 303 of 5409
    collected symbols entered that way and reached the api-break gate. A guard
    no input can reach is theatre, so both directions are asserted here — the
    excluded case AND the included one, from the same source.
    """

    assert (
        _visibility(
            _PRIVATE_MODULE_WITH_ALL,
            module_name="pkg._internal",
            include_private=False,
        )
        == frozenset()
    )
    assert _visibility(
        _PRIVATE_MODULE_WITH_ALL,
        module_name="pkg._internal",
        include_private=True,
    ) == frozenset({"helper"})
    # The public twin proves the exclusion is about privacy and not about
    # ``__all__`` having stopped working.
    assert _visibility(
        _PRIVATE_MODULE_WITH_ALL,
        module_name="pkg.public",
        include_private=False,
    ) == frozenset({"helper"})


def test_a_private_module_declaring_all_collects_no_api_surface() -> None:
    """The consequence one layer up, where the population is actually built."""

    tree, collector, imports = tree_collector_and_imports(
        _PRIVATE_MODULE_WITH_ALL, module_name="pkg._internal"
    )
    assert (
        collect_module_api_surface(
            tree=tree,
            module_name="pkg._internal",
            filepath="pkg/_internal.py",
            collector=collector,
            imported_names=imports,
        )
        is None
    )
    assert (
        collect_module_api_surface(
            tree=tree,
            module_name="pkg._internal",
            filepath="pkg/_internal.py",
            collector=collector,
            imported_names=imports,
            include_private_modules=True,
        )
        is not None
    )


def _snapshot(*rows: tuple[str, str], prefix: str = "") -> ApiSurfaceSnapshot:
    """A snapshot whose file paths can be spelled differently from the twin's.

    ``prefix`` exists because the two sides of the comparison genuinely disagree
    about path spelling — the run carries absolute runtime paths, the container
    repository-relative ones — and a test that spelled both sides identically
    could not see a join keyed on the wrong field.
    """

    return ApiSurfaceSnapshot(
        modules=tuple(
            ModuleApiSurface(
                module=path.replace("/", ".").removesuffix(".py"),
                filepath=f"{prefix}{path}",
                symbols=(),
                surface_kind=kind,
            )
            for path, kind in rows
        )
    )


def test_the_comparison_narrows_both_sides_of_a_non_gating_module() -> None:
    """The gate population is narrowed symmetrically, or it manufactures breaks.

    Narrowing only the current side is the same mechanism as an unmaterialized
    cache row: the baseline still holds the module, the run no longer offers
    it, and every stored symbol reads as removed. A stored module the run did
    not classify at all is kept — that is a deleted module, and its removal is
    the signal the lane exists for.
    """

    from codeclone.baseline.metrics_baseline import _gating_api_surfaces

    current = _snapshot(
        ("shipped/tool.py", SURFACE_KIND_PRODUCT_PUBLIC),
        ("scripts/tool.py", SURFACE_KIND_REPOSITORY_SUPPORT),
        ("shipped/_internal.py", SURFACE_KIND_PRODUCT_INTERNAL),
        prefix="/abs/checkout/",
    )
    # Repository-relative on the baseline side, absolute on the run's: the
    # spelling the two sides actually use. Measured with a path join, this
    # exact difference turned 51 breaking changes into 183 on an untouched
    # tree, because every stored module fell through the "never classified"
    # branch while the current side had already been narrowed.
    baseline = _snapshot(
        ("shipped/tool.py", ""),
        ("scripts/tool.py", ""),
        ("shipped/_internal.py", ""),
        ("shipped/deleted.py", ""),
    )
    narrowed_baseline, narrowed_current = _gating_api_surfaces(
        baseline=baseline, current=current
    )
    assert narrowed_current is not None
    assert [module.module for module in narrowed_current.modules] == ["shipped.tool"]
    assert narrowed_baseline is not None
    assert [module.module for module in narrowed_baseline.modules] == [
        "shipped.tool",
        "shipped.deleted",
    ]


def test_an_unclassified_current_module_does_not_gate() -> None:
    """The stamp is load-bearing, so its absence must not be permissive.

    A run attaches the kind to every module it collects. If it stopped, an
    unstamped module reading as gating would restore the old population
    silently; reading as non-gating empties the gate and reds loudly here and
    in the pipeline pin below.
    """

    from codeclone.baseline.metrics_baseline import _gating_api_surfaces

    _, narrowed_current = _gating_api_surfaces(
        baseline=None, current=_snapshot(("shipped/tool.py", ""))
    )
    assert narrowed_current is not None
    assert narrowed_current.modules == ()


def test_the_manifest_reader_tells_undeclared_from_declared_nothing() -> None:
    """``None`` and an empty set are different answers about one repository."""

    assert collect_project_distributed_packages(_FIXTURE_ROOT) == frozenset(
        {"shipped", "shipped.testing"}
    )
    assert collect_project_distributed_packages(Path(_FIXTURE_ROOT / "scripts")) is None
