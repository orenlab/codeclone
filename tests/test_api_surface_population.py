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

The module kinds answer where a module sits: the test track, shipped or not, a
public or a private namespace. They do not answer whether a symbol is API.
That is the binding question — is there a provable path from a public
namespace to this symbol — and it is answered per symbol by the
external-reachability owner over the namespaces the population owner names.
``httpx.Client`` is defined in ``httpx._client`` and is public API; a helper
in the same module that nothing public binds is not; and a symbol under a
package whose namespace a ``__getattr__`` serves is ``unresolved``, which is
included, never private.

The declared cases live in ``tests/fixtures/source_kind/ground_truth.json`` so
the expectations are a fixture the fixture tree can be checked against, not
literals retyped beside the code that produces them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

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
from codeclone.models import ApiSurfaceSnapshot, ModuleApiSurface, PublicSymbol
from codeclone.paths.module_identity.inventory import build_module_registry
from tests._ast_metrics_helpers import tree_collector_and_imports
from tests._pipeline_fixtures import (
    analysis_boot,
    golden_ground_truth,
    golden_root,
    payload_mapping,
    payload_sequence,
    run_pipeline_once,
)

if TYPE_CHECKING:
    from tests._pipeline_fixtures import PipelineRun

_FIXTURE_ROOT = golden_root("source_kind") / "distribution"


def _population(*, include_private_modules: bool = False) -> ApiSurfacePopulation:
    return ApiSurfacePopulation(
        scan_root=str(_FIXTURE_ROOT),
        module_registry=build_module_registry(root=_FIXTURE_ROOT),
        distributed_packages=collect_project_distributed_packages(_FIXTURE_ROOT),
        include_private_modules=include_private_modules,
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


def _declared_exposure_cases() -> list[dict[str, object]]:
    cases = golden_ground_truth("source_kind")["api_exposure_cases"]
    assert isinstance(cases, list) and cases
    return [dict(case) for case in cases]


@pytest.fixture(scope="module")
def fixture_run(tmp_path_factory: pytest.TempPathFactory) -> PipelineRun:
    """One cold pipeline run over the distribution fixture.

    Shared by the end-to-end pins because the population is a whole-run
    decision: the binding graph, the class index and the manifest exist only
    where the pipeline joins them.
    """

    boot = analysis_boot(
        _FIXTURE_ROOT,
        min_loc=1,
        min_stmt=1,
        skip_metrics=False,
        api_surface=True,
    )
    _cache, run = run_pipeline_once(
        boot,
        tmp_path_factory.mktemp("api-population") / "cache.json",
        root=_FIXTURE_ROOT,
        warm=False,
    )
    return run


def _collected(run: PipelineRun) -> dict[str, tuple[ModuleApiSurface, PublicSymbol]]:
    """Every symbol the run collected, with the module row that carries it."""

    project_metrics = run.result.project_metrics
    assert project_metrics is not None
    snapshot = project_metrics.api_surface
    assert snapshot is not None
    return {
        symbol.qualname: (module, symbol)
        for module in snapshot.modules
        for symbol in module.symbols
    }


def _reported(run: PipelineRun) -> tuple[dict[str, object], list[str]]:
    """The family summary and the qualnames of its items, as the report says."""

    family = payload_mapping(payload_mapping(run.result.metrics_payload)["api_surface"])
    summary = payload_mapping(family["summary"])
    items = [
        str(payload_mapping(item)["qualname"])
        for item in payload_sequence(family["items"])
    ]
    return summary, items


def _symbol(qualname: str, exposure: str | None) -> PublicSymbol:
    return PublicSymbol(
        qualname=qualname,
        kind="function",
        start_line=1,
        end_line=2,
        exposure=exposure,  # type: ignore[arg-type]
    )


def _module(kind: str, *symbols: PublicSymbol) -> ModuleApiSurface:
    return ModuleApiSurface(
        module="pkg.mod",
        filepath="pkg/mod.py",
        symbols=symbols,
        surface_kind=kind,
    )


# ---------------------------------------------------------------------------
# The module kinds: where a module sits.
# ---------------------------------------------------------------------------


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
    """Same distributed package, same manifest: only the module name differs.

    ``product_internal`` is a statement about the NAMESPACE — a private module
    is not a public path — and never about its symbols: those are decided one
    by one by the binding question below. The kind is what tells the evaluator
    that a definition here is not exposed by definition.
    """

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


def test_the_manifest_reader_tells_undeclared_from_declared_nothing() -> None:
    """``None`` and an empty set are different answers about one repository."""

    assert collect_project_distributed_packages(_FIXTURE_ROOT) == frozenset(
        {"lazy", "shipped", "shipped.testing"}
    )
    assert collect_project_distributed_packages(Path(_FIXTURE_ROOT / "scripts")) is None


# ---------------------------------------------------------------------------
# The namespaces: which modules an external caller can name.
# ---------------------------------------------------------------------------


def test_the_population_owner_names_the_public_namespaces() -> None:
    """A public namespace is a shipped module on a public dotted path.

    The test track, an unshipped tree and a private module are all Python
    modules a caller could import, and none of them is a place the project
    promises a name at. The reachability owner exposes by definition only
    inside this set, so a wider set is a wider API by construction.
    """

    namespaces = _population().public_namespaces()
    assert {
        "lazy",
        "shipped",
        "shipped.testing",
        "shipped.testing.helpers",
        "shipped.tool",
    } <= namespaces
    assert namespaces.isdisjoint(
        {
            "lazy._impl",
            "scripts.tool",
            "shipped._internal",
            "shipped._star",
            "tests.test_probe",
        }
    )


def test_the_namespaces_need_the_registry() -> None:
    """Without the registry there is no universe to seed from, and an empty
    seed set would read as "nothing is API" - a refusal, never a silence."""

    with pytest.raises(ValueError, match="module registry"):
        ApiSurfacePopulation(scan_root=str(_FIXTURE_ROOT)).public_namespaces()


def test_include_private_modules_makes_private_product_modules_namespaces() -> None:
    """The flag says "my private modules are part of my surface", and only that.

    It admits the private modules of the DISTRIBUTED package; it does not turn
    an unshipped tree or the test track into a namespace, because the flag is
    about privacy and those are excluded for other reasons.
    """

    admitted = _population(include_private_modules=True).public_namespaces()
    assert {"lazy._impl", "shipped._internal", "shipped._star"} <= admitted
    assert admitted.isdisjoint({"scripts.tool", "tests.test_probe"})
    assert "shipped._internal" not in _population().public_namespaces()


def test_include_private_modules_reaches_the_exposure_decision(
    tmp_path: Path,
) -> None:
    """The flag is enforced only if a structural path leads from its owner to
    the decision it claims to control; this is that path, end to end.

    Under the flag a private product module is a namespace, so ``hidden`` --
    excluded in the run above because nothing public binds it -- is exposed
    by definition and reported as API.
    """

    from codeclone.metrics.api_population import is_api_visible

    boot = analysis_boot(
        _FIXTURE_ROOT,
        min_loc=1,
        min_stmt=1,
        skip_metrics=False,
        api_surface=True,
    )
    boot.args.api_include_private_modules = True
    _cache, run = run_pipeline_once(
        boot, tmp_path / "cache.json", root=_FIXTURE_ROOT, warm=False
    )
    module, hidden = _collected(run)["shipped._internal:hidden"]
    assert hidden.exposure == "reachable"
    assert is_api_visible(module, hidden)
    _summary, items = _reported(run)
    assert "shipped._internal:hidden" in items


def test_the_manifest_reader_reads_three_build_backends(tmp_path: Path) -> None:
    """The distribution input is only as general as the manifests it reads.

    A reader that understood this project's own backend alone would be a
    manifest owner that works on exactly one repository; setuptools' find
    globs, hatch's wheel packages and poetry's package table are each read to
    the same dotted prefixes.
    """

    def read(text: str) -> frozenset[str] | None:
        (tmp_path / "pyproject.toml").write_text(text, encoding="utf-8")
        return collect_project_distributed_packages(tmp_path)

    assert read(
        '[tool.setuptools.packages.find]\ninclude = ["acme*", "acme.sub.*"]\n'
    ) == frozenset({"acme", "acme.sub"})
    assert read(
        '[tool.hatch.build.targets.wheel]\npackages = ["src/acme", "lib/acme_tools"]\n'
    ) == frozenset({"acme", "acme_tools"})
    assert read(
        "[tool.poetry]\npackages = ["
        '{include = "acme", from = "src"}, {include = "acme_tools/"}]\n'
    ) == frozenset({"acme", "acme_tools"})
    assert read('[project]\nname = "acme"\n') is None


def test_the_api_population_is_invariant_under_the_world_contract(
    fixture_run: PipelineRun, tmp_path: Path
) -> None:
    """The seeds do not depend on the world contract.

    ``closed`` removes exposure as a basis for LIVENESS; it does not empty the
    namespaces the api evaluator seeds from, or the api surface would become
    vacuously unreachable everywhere under the world most CI runs declare.
    """

    boot = analysis_boot(
        _FIXTURE_ROOT, min_loc=1, min_stmt=1, skip_metrics=False, api_surface=True
    )
    boot.args.dead_code_world = "closed"
    _cache, closed = run_pipeline_once(
        boot, tmp_path / "cache.json", root=_FIXTURE_ROOT, warm=False
    )
    verdicts = {
        qualname: (module.surface_kind, symbol.exposure)
        for qualname, (module, symbol) in _collected(closed).items()
    }
    assert verdicts == {
        qualname: (module.surface_kind, symbol.exposure)
        for qualname, (module, symbol) in _collected(fixture_run).items()
    }
    assert _reported(closed)[1] == _reported(fixture_run)[1]


_CYCLE_TREE: dict[str, str] = {
    "pyproject.toml": (
        '[project]\nname = "cyclic"\nversion = "0.0.0"\n\n'
        '[tool.setuptools]\npackages = ["cyclic"]\n'
    ),
    "cyclic/__init__.py": "from ._a import *  # noqa: F403\n",
    "cyclic/_a/__init__.py": (
        "from .._b import *  # noqa: F403\n\n\ndef a_thing() -> int:\n    return 1\n"
    ),
    "cyclic/_b/__init__.py": (
        "from .._a import *  # noqa: F403\nfrom ._impl import Foo\n\n"
        '__all__ = ["Foo", "b_thing"]\n\n\ndef b_thing() -> int:\n    return 2\n'
    ),
    "cyclic/_b/_impl.py": (
        '__all__ = ["Foo"]\n\n\nclass Foo:\n    def method(self) -> None:\n'
        "        return None\n"
    ),
}


def _cycle_run(root: Path, *, public_entry: bool) -> PipelineRun:
    """Lay the maintainer's cycle out as a real tree and run the pipeline.

    Built under ``tmp_path`` rather than checked in: a wildcard cycle is a
    dependency cycle, and a checked-in one would be a finding of this
    repository's own analysis. The tree is the fixture; its home is not.
    """

    for relative, text in _CYCLE_TREE.items():
        if relative == "cyclic/__init__.py" and not public_entry:
            text = ""
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    boot = analysis_boot(
        root, min_loc=1, min_stmt=1, skip_metrics=False, api_surface=True
    )
    _cache, run = run_pipeline_once(boot, root / "cache.json", root=root, warm=False)
    return run


def test_the_fixed_point_reaches_a_cycle_from_one_public_entry_end_to_end(
    tmp_path: Path,
) -> None:
    """RULING 2026-09-02, end to end: ``_a.__init__ -> _b``, ``_b.__init__ ->
    _a``, ``_b.__init__ -> Foo``. With no public entry nothing is API; with one
    proven ``cyclic -> _a`` wildcard, after convergence the namespace's own
    definition and the re-exported class are API. ``a_thing`` is absent in
    both: a bare private module declares no export list and is never
    collected, which is the collector's limit, not the graph's.
    """

    from codeclone.metrics.api_population import is_api_visible

    silent = _collected(_cycle_run(tmp_path / "silent", public_entry=False))
    assert "cyclic._a:a_thing" not in silent
    for qualname in (
        "cyclic._b:b_thing",
        "cyclic._b._impl:Foo",
        "cyclic._b._impl:Foo.method",
    ):
        module, symbol = silent[qualname]
        assert symbol.exposure == "not_reachable", qualname
        assert not is_api_visible(module, symbol), qualname

    converged = _collected(_cycle_run(tmp_path / "converged", public_entry=True))
    assert "cyclic._a:a_thing" not in converged
    for qualname in (
        "cyclic._b:b_thing",
        "cyclic._b._impl:Foo",
        "cyclic._b._impl:Foo.method",
    ):
        module, symbol = converged[qualname]
        assert module.surface_kind == SURFACE_KIND_PRODUCT_INTERNAL, qualname
        assert symbol.exposure == "reachable", qualname
        assert is_api_visible(module, symbol), qualname


# ---------------------------------------------------------------------------
# The collector: Python visibility, and nothing else.
# ---------------------------------------------------------------------------


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
_PRIVATE_MODULE_WITHOUT_ALL = "def helper(value: int) -> int:\n    return value\n"


def test_a_private_module_declaring_all_is_collected_whatever_the_flag_says() -> None:
    """The per-file collector reports what Python makes visible.

    ``__all__`` is the language's export list and it is read first, in a
    private module as in a public one. Where a definition sits is not where
    it becomes externally observable — ``httpx.Client`` lives in
    ``httpx._client`` — so a collector that dropped private modules would
    drop the definitions the binding walk needs to find, and the population
    could never contain them. Privacy is asked one layer up, per symbol, by
    the exposure verdict; here it must not narrow anything.
    """

    for include_private in (False, True):
        assert _visibility(
            _PRIVATE_MODULE_WITH_ALL,
            module_name="pkg._internal",
            include_private=include_private,
        ) == frozenset({"helper"})
    tree, collector, imports = tree_collector_and_imports(
        _PRIVATE_MODULE_WITH_ALL, module_name="pkg._internal"
    )
    surface = collect_module_api_surface(
        tree=tree,
        module_name="pkg._internal",
        filepath="pkg/_internal.py",
        collector=collector,
        imported_names=imports,
    )
    assert surface is not None
    assert [symbol.qualname for symbol in surface.symbols] == ["pkg._internal:helper"]


def test_a_bare_private_module_is_collected_only_under_the_flag() -> None:
    """Without ``__all__`` a private module declares no export list at all.

    Its public-named definitions are collected only when the run says private
    modules are part of the surface. The public twin proves the exclusion is
    about the module's privacy and not about the public-name arm being broken.
    """

    assert (
        _visibility(
            _PRIVATE_MODULE_WITHOUT_ALL,
            module_name="pkg._internal",
            include_private=False,
        )
        == frozenset()
    )
    assert _visibility(
        _PRIVATE_MODULE_WITHOUT_ALL,
        module_name="pkg._internal",
        include_private=True,
    ) == frozenset({"helper"})
    assert _visibility(
        _PRIVATE_MODULE_WITHOUT_ALL,
        module_name="pkg.public",
        include_private=False,
    ) == frozenset({"helper"})


# ---------------------------------------------------------------------------
# The exposure verdict: is there a provable binding path from a namespace?
# ---------------------------------------------------------------------------


def test_every_declared_exposure_case_gets_the_state_the_fixture_declares(
    fixture_run: PipelineRun,
) -> None:
    """The whole exposure table, from one real run over the fixture tree.

    Every case differs from a twin by exactly one construct — a named import
    in the package ``__init__``, an alias, a second hop, a wildcard under
    ``__all__``, a module-level ``__getattr__``, the manifest — and
    ``api_exposure_twins`` records which. All three states are represented so
    that no state can be answered by a rule that never fires.
    """

    from codeclone.metrics.api_population import is_api_visible

    collected = _collected(fixture_run)
    verdicts: dict[str, dict[str, object]] = {}
    for case in _declared_exposure_cases():
        module, symbol = collected[str(case["qualname"])]
        verdicts[str(case["id"])] = {
            "surface_kind": module.surface_kind,
            "exposure": symbol.exposure,
            "api_visible": is_api_visible(module, symbol),
        }
    expected = {
        str(case["id"]): dict(payload_mapping(case["expected"]))
        for case in _declared_exposure_cases()
    }
    assert verdicts == expected
    assert {row["exposure"] for row in expected.values()} == {
        "reachable",
        "not_reachable",
        "unresolved",
    }


def test_absent_cases_are_never_collected(fixture_run: PipelineRun) -> None:
    """Some names are not in the population at all, and that is a fact too.

    The test track leaves before classification, and a name a module's
    ``__all__`` does not list is not Python-visible anywhere. Neither is an
    exposure verdict; both are absences the table above must not be read as.
    """

    collected = _collected(fixture_run)
    for case in golden_ground_truth("source_kind")["api_absent_cases"]:
        assert str(case["qualname"]) not in collected, case["id"]


def test_a_private_module_symbol_re_exported_by_name_is_api(
    fixture_run: PipelineRun,
) -> None:
    """The ``httpx.Client`` shape: defined in ``httpx._client``, bound as
    ``httpx.Client`` by a named import in the package ``__init__``.

    Module privacy used to be the authority and answered this wrongly —
    measured on httpx, ``public_symbols`` 254 -> 1. The definition site is not
    where a fact becomes externally observable; the binding path is.
    """

    from codeclone.metrics.api_population import is_api_visible

    module, symbol = _collected(fixture_run)["shipped._internal:helper"]
    assert module.surface_kind == SURFACE_KIND_PRODUCT_INTERNAL
    assert symbol.exposure == "reachable"
    assert is_api_visible(module, symbol)
    _summary, items = _reported(fixture_run)
    assert "shipped._internal:helper" in items


def test_a_private_module_symbol_with_no_public_binding_is_not_api(
    fixture_run: PipelineRun,
) -> None:
    """The opposite boundary, from the same module and the same ``__all__``.

    ``hidden`` is collected — the exclusion is a verdict on a symbol the run
    holds, not an absence — and nothing public binds it, so it is not part of
    anyone's contract and must not reach the api-break gate.
    """

    from codeclone.metrics.api_population import is_api_visible

    module, symbol = _collected(fixture_run)["shipped._internal:hidden"]
    assert symbol.exposure == "not_reachable"
    assert not is_api_visible(module, symbol)
    _summary, items = _reported(fixture_run)
    assert "shipped._internal:hidden" not in items


def test_unresolved_exposure_is_included_never_private(
    fixture_run: PipelineRun,
) -> None:
    """A binding the walk cannot read is ``unresolved``, and unresolved is API.

    ``lazy/__init__.py`` defines a module-level ``__getattr__`` (PEP 562), so
    any name below the package may be served at runtime. Concluding "not API"
    from an inability to prove the re-export is how a gate goes confidently
    silent exactly where its data is insufficient; the state is carried as its
    own word and lands on the included side.
    """

    from codeclone.metrics.api_population import is_api_visible

    collected = _collected(fixture_run)
    _summary, items = _reported(fixture_run)
    for qualname in ("lazy._impl:Thing", "lazy._impl:Thing.method"):
        module, symbol = collected[qualname]
        assert symbol.exposure == "unresolved", qualname
        assert is_api_visible(module, symbol), qualname
        assert qualname in items, qualname


def test_a_repository_support_module_is_not_a_public_namespace(
    fixture_run: PipelineRun,
) -> None:
    """The same wildcard, from two importers of different kinds.

    ``scripts/tool.py`` star-imports ``shipped._internal`` exactly as
    ``shipped/__init__.py`` star-imports ``shipped._star``. Only the importing
    module's kind differs: a shipped package is a namespace and carries
    ``starred`` out; an unshipped tree is not and carries nothing, so
    ``hidden`` stays excluded. The premise is asserted on the run's own
    dependency edges so the pin cannot pass by the import having been dropped.
    """

    star_sources = {
        dep.source
        for dep in fixture_run.processing.module_deps
        if dep.target == "shipped._internal" and "*" in dep.requested_names
    }
    assert "scripts.tool" in star_sources
    collected = _collected(fixture_run)
    assert collected["shipped._internal:hidden"][1].exposure == "not_reachable"
    assert collected["shipped._star:starred"][1].exposure == "reachable"


def test_the_family_reports_the_visible_population(
    fixture_run: PipelineRun,
) -> None:
    """The family is the API, not the collection.

    The run keeps every collected symbol — that is what the lane stores, and
    narrowing the stored population against an older baseline reads every
    dropped symbol as removed. What the report calls ``public_symbols`` and
    lists as ``items`` is the visible projection of it, and the projection is
    proven real by two collected symbols that must not appear.
    """

    from codeclone.metrics.api_population import is_api_visible

    collected = _collected(fixture_run)
    visible = sorted(
        qualname
        for qualname, (module, symbol) in collected.items()
        if is_api_visible(module, symbol)
    )
    excluded = set(collected) - set(visible)
    assert {"scripts.tool:run", "shipped._internal:hidden"} <= excluded
    summary, items = _reported(fixture_run)
    # The report orders its rows by file and line, which is its own contract;
    # the population is the set.
    assert sorted(items) == visible
    assert len(items) == len(visible)
    assert summary["enabled"] is True
    assert summary["public_symbols"] == len(visible)
    assert summary["modules"] == len(
        {qualname.partition(":")[0] for qualname in visible}
    )


# ---------------------------------------------------------------------------
# The gating projection: which symbols may reach ``fail_on_api_break``.
# ---------------------------------------------------------------------------


def test_only_product_kinds_can_gate() -> None:
    """Gating is a projection of the kind and the exposure, not a second rule.

    Asserted over the whole vocabulary so a new kind cannot quietly default
    into the gating population.
    """

    from codeclone.metrics.api_population import is_api_visible

    verdicts = {
        kind: is_api_visible(
            _module(kind, _symbol("pkg.mod:run", "reachable")),
            _symbol("pkg.mod:run", "reachable"),
        )
        for kind in SURFACE_KIND_ORDER
    }
    assert verdicts == {
        SURFACE_KIND_PRODUCT_PUBLIC: True,
        SURFACE_KIND_PRODUCT_INTERNAL: True,
        SURFACE_KIND_REPOSITORY_SUPPORT: False,
        SURFACE_KIND_TEST_SUPPORT: False,
    }


def test_exposure_decides_inside_a_product_kind() -> None:
    """Both included states and both excluded ones, for both product kinds.

    ``unresolved`` sits on the included side by law. ``None`` is "no run
    classified this", and an unstamped symbol must not gate: reading it as
    included would restore the definition-site population silently.
    """

    from codeclone.metrics.api_population import is_api_visible

    for kind in (SURFACE_KIND_PRODUCT_PUBLIC, SURFACE_KIND_PRODUCT_INTERNAL):
        verdicts = {
            exposure: is_api_visible(
                _module(kind, _symbol("pkg.mod:run", exposure)),
                _symbol("pkg.mod:run", exposure),
            )
            for exposure in ("reachable", "unresolved", "not_reachable", None)
        }
        assert verdicts == {
            "reachable": True,
            "unresolved": True,
            "not_reachable": False,
            None: False,
        }, kind


def _snapshot(
    *rows: tuple[str, str, tuple[tuple[str, str | None], ...]],
    prefix: str = "",
) -> ApiSurfaceSnapshot:
    """A snapshot whose file paths can be spelled differently from the twin's.

    ``prefix`` exists because the two sides of the comparison genuinely disagree
    about path spelling — the run carries absolute runtime paths, the container
    repository-relative ones — and a test that spelled both sides identically
    could not see a join keyed on the wrong field.
    """

    modules: list[ModuleApiSurface] = []
    for path, kind, symbols in rows:
        module = path.replace("/", ".").removesuffix(".py")
        modules.append(
            ModuleApiSurface(
                module=module,
                filepath=f"{prefix}{path}",
                symbols=tuple(
                    _symbol(f"{module}:{local}", exposure)
                    for local, exposure in symbols
                ),
                surface_kind=kind,
            )
        )
    return ApiSurfaceSnapshot(modules=tuple(modules))


def _qualnames(snapshot: ApiSurfaceSnapshot | None) -> list[str]:
    assert snapshot is not None
    return [symbol.qualname for module in snapshot.modules for symbol in module.symbols]


def test_the_comparison_narrows_both_sides_by_the_current_verdict() -> None:
    """The gate population is narrowed symmetrically, or it manufactures breaks.

    The current side keeps what the run calls visible. A stored symbol the run
    still holds follows the run's verdict for it, on both sides together, so a
    private helper nothing binds cannot read as removed. A stored symbol the
    run no longer holds is kept — its removal is the signal the lane exists
    for, and its exposure at baseline time is unprovable now, which is
    ``unresolved`` and lands on the included side — unless its module is one
    the run classified as never gating. A stored module the run has no row
    for at all is a deleted module and is kept whole.

    Repository-relative on the baseline side, absolute on the run's: measured
    with a path join, that difference turned 51 breaking changes into 183 on
    an untouched tree.
    """

    from codeclone.baseline.metrics_baseline import _gating_api_surfaces

    current = _snapshot(
        ("shipped/tool.py", SURFACE_KIND_PRODUCT_PUBLIC, (("run", "reachable"),)),
        (
            "shipped/_internal.py",
            SURFACE_KIND_PRODUCT_INTERNAL,
            (("helper", "reachable"), ("hidden", "not_reachable")),
        ),
        (
            "scripts/tool.py",
            SURFACE_KIND_REPOSITORY_SUPPORT,
            (("run", "not_reachable"),),
        ),
        prefix="/abs/checkout/",
    )
    baseline = _snapshot(
        ("shipped/tool.py", "", (("run", None),)),
        (
            "shipped/_internal.py",
            "",
            (("helper", None), ("hidden", None), ("vanished", None)),
        ),
        ("scripts/tool.py", "", (("run", None), ("old", None))),
        ("shipped/deleted.py", "", (("gone", None),)),
    )
    narrowed_baseline, narrowed_current = _gating_api_surfaces(
        baseline=baseline, current=current
    )
    assert _qualnames(narrowed_current) == [
        "shipped.tool:run",
        "shipped._internal:helper",
    ]
    assert _qualnames(narrowed_baseline) == [
        "shipped.tool:run",
        "shipped._internal:helper",
        "shipped._internal:vanished",
        "shipped.deleted:gone",
    ]


def test_an_unstamped_current_symbol_does_not_gate() -> None:
    """Both stamps are load-bearing, so the absence of either is not permissive.

    A run attaches the kind to every module and the exposure to every symbol
    it collects. If either stopped, reading the gap as gating would restore
    an old population silently; reading it as non-gating empties the gate and
    reds loudly here and in the pipeline pins above.
    """

    from codeclone.baseline.metrics_baseline import _gating_api_surfaces

    _, kindless = _gating_api_surfaces(
        baseline=None,
        current=_snapshot(("shipped/tool.py", "", (("run", "reachable"),))),
    )
    assert kindless is not None
    assert kindless.modules == ()
    _, unexposed = _gating_api_surfaces(
        baseline=None,
        current=_snapshot(
            ("shipped/tool.py", SURFACE_KIND_PRODUCT_PUBLIC, (("run", None),))
        ),
    )
    assert unexposed is not None
    assert unexposed.modules == ()
