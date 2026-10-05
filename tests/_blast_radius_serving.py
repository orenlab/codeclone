# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The populations behind the blast-radius serving pins (consumer migration C7).

The run summary's sixteen populations (``tests/_run_summary_serving.py``) are
reused as they are -- the same executions, built once per session -- and one
population is added that only a blast radius distinguishes: ``fanout``, the
projection corpus (an import cycle, a dynamic load, a security surface, a
clone trio) with a module twenty-four modules import (a high radius whose
review context is cut to its shown length), a transitive dependent, a large
module the overloaded-module ranking calls a candidate, a dependent holding a
security surface, a golden-fixture clone pair (suppressed clone groups), and
two files that are not Python.

The population is chosen to DISTINGUISH (Probe Validity Law), measured on
the inventory before the edge was written (2026-10-03,
``census-c7-ade7d398.csv``): every radius level, every review-context
category, every do-not-touch category, a truncated and an untruncated
summary, both depths, several origins, non-Python and unknown origins.  The
equivalence pins state the accounting before they count.

This module is a helper, not a test module, so it may read the canonical
store beside the surface (the Phase 39S test-import law binds
``tests/test_*.py`` only).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from codeclone.canonical.identity import FileId, ModuleId
from codeclone.surfaces.mcp._blast_radius import blast_radius_to_payload
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from codeclone.utils.coerce import as_mapping, as_sequence
from tests import conftest as corpora
from tests._run_summary_serving import (
    SUMMARY_POPULATIONS,
    SummaryPopulation,
    serving_environment,
    shared_populations,
    store_row_replaced,
)

#: The blast radius's populations, by name, and the publication each states.
BLAST_POPULATIONS: dict[str, str] = {**SUMMARY_POPULATIONS, "fanout": "published"}

#: The fan-out tree on top of the projection corpus.
FANOUT_TREE: dict[str, str] = {
    "pyproject.toml": (
        "[tool.codeclone]\nsemantic_authority = true\n"
        'golden_fixture_paths = ["tests/fixtures/golden_*"]\n'
    ),
    "pkg/core.py": (
        '"""Core: large, imported by every user, importing four modules."""\n\n'
        "from pkg.cyc_a import a\nfrom pkg.danger import run_a\n"
        "from pkg.loader import load\nfrom pkg.trio_a import fold\n\n\n"
        'def core() -> int:\n    """Core."""\n    return 1\n\n\n'
        + "\n\n".join(
            f"def helper_{i}(value: int) -> int:\n"
            f'    """Helper {i}."""\n'
            f"    if value > {i}:\n        return a() + fold([value, {i}])\n"
            f"    return value - {i} if load is not run_a else 0\n"
            for i in range(40)
        )
    ),
    **{
        f"pkg/user_{i}.py": (
            f'"""User {i}."""\n\nfrom pkg.core import core\n\n\n'
            f'def use_{i}() -> int:\n    """Use."""\n    return core() + {i}\n'
        )
        for i in range(22)
    },
    "pkg/a_danger.py": (
        '"""A dependent of core holding a security surface."""\n\n'
        "from pkg.core import core\n\n\n"
        'def run(source: str) -> object:\n    """Run."""\n'
        "    return eval(source) or core()\n"
    ),
    "pkg/top.py": (
        '"""Top: a transitive dependent of core."""\n\n'
        "from pkg.user_0 import use_0\n\n\n"
        'def top() -> int:\n    """Top."""\n    return use_0()\n'
    ),
    "pkg/leaf.py": (
        '"""Leaf: imports core, nobody imports it."""\n\n'
        "from pkg import core\n\n\n"
        'def leaf() -> int:\n    """Leaf."""\n    return core.core()\n'
    ),
    "README.md": "# fan-out\n",
    "pkg/data.json": '{"k": 1}\n',
    **{
        f"tests/fixtures/golden_twins/twin_{side}.py": corpora._TWIN_SOURCE.replace(
            "twin_tally", f"twin_tally_{side}"
        )
        for side in ("a", "b")
    },
}

#: Origins no registry file stands for: two non-Python files, a path the
#: run never saw, and a ``./``-spelled one the request normalizes.
SPECIAL_ORIGINS: tuple[tuple[str, ...], ...] = (
    ("README.md",),
    ("pkg/data.json",),
    ("nonexistent/zz.py",),
    ("./pkg/core.py",),
)

#: The ``include`` filters asked on the first origins of every population.
INCLUDES: tuple[tuple[str, ...], ...] = (
    ("imports",),
    ("clone_cohorts",),
    ("coverage",),
    ("risk_signals",),
    ("do_not_touch",),
    ("review_context",),
    ("cycles",),
    ("coverage", "risk_signals"),
)


@dataclass(frozen=True, slots=True)
class BlastRequest:
    """One ``get_blast_radius`` question."""

    files: tuple[str, ...]
    depth: str
    include: tuple[str, ...] | None = None

    def key(self) -> str:
        return json.dumps(
            [list(self.files), self.depth, self.include], separators=(",", ":")
        )


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    """One question in the declare / implementation-context shape: a
    forbidden list and a declared edit scope the tool itself never sends."""

    files: tuple[str, ...]
    depth: str
    forbidden: tuple[str, ...]
    allowed: tuple[str, ...]


def registry_files(population: SummaryPopulation) -> list[str]:
    inventory = as_mapping(population.record.served_report.get("inventory"))
    registry = as_mapping(inventory.get("file_registry"))
    return sorted(str(item) for item in as_sequence(registry.get("items")))


def blast_requests(population: SummaryPopulation) -> list[BlastRequest]:
    """Every registry file alone at both depths, the special origins,
    several multi-file origins, and every include filter on the first ones."""
    files = registry_files(population)
    origins: list[tuple[str, ...]] = [(path,) for path in files]
    origins.extend(SPECIAL_ORIGINS)
    origins.extend(tuple(files[start : start + 3]) for start in range(0, 12, 4))
    asked = [
        BlastRequest(origin, depth)
        for origin in origins
        if origin
        for depth in ("direct", "transitive")
    ]
    for origin in origins[:4]:
        asked.extend(
            BlastRequest(origin, "transitive", include) for include in INCLUDES
        )
    return asked


def policy_requests(population: SummaryPopulation) -> list[PolicyRequest]:
    """The first registry files under a forbidden list, and under a declared
    scope that leaves the rest of their zone outside it."""
    asked: list[PolicyRequest] = []
    for path in registry_files(population)[:4]:
        asked.append(
            PolicyRequest((path,), "direct", ("pkg/leaf.py", "docs/**"), (path,))
        )
        asked.append(PolicyRequest((path,), "transitive", (), (path, "pkg/core.py")))
    return asked


def forget_answers(population: SummaryPopulation) -> None:
    """Drop every cached blast radius of the execution, so the next question
    is computed -- and read from the store -- afresh."""
    with population.service._state_lock:
        population.service._blast_radius_cache.clear()


def blast_answer(
    population: SummaryPopulation, request: BlastRequest, *, serve_from: str | None
) -> dict[str, object]:
    """``get_blast_radius`` under the rollout that published the run."""
    with serving_environment(population.store_path, serve_from=serve_from):
        return population.service.get_blast_radius(
            files=list(request.files),
            root=str(population.root),
            depth=request.depth,
            include=None if request.include is None else list(request.include),
        )


def policy_answer(
    population: SummaryPopulation, request: PolicyRequest, *, serve_from: str | None
) -> tuple[dict[str, object], dict[str, object]]:
    """The payload every reader of ``_blast_radius_result`` builds for one
    policy-shaped question, and the serving it was computed under."""
    with serving_environment(population.store_path, serve_from=serve_from):
        result, serving = population.service._served_blast_radius(
            record=population.record,
            files=request.files,
            depth="transitive" if request.depth == "transitive" else "direct",
            forbidden_patterns=request.forbidden,
            allowed_scope=request.allowed,
        )
    return blast_radius_to_payload(result), serving


def _serve_fanout(base: Path) -> SummaryPopulation:
    root = base / "fanout"
    root.mkdir()
    corpora.materialize_projection_corpus(root)
    corpora._write_tree(root, FANOUT_TREE)
    store_path = base / "fanout.sqlite3"
    service = CodeCloneMCPService(history_limit=4)
    with serving_environment(store_path, serve_from=None):
        service.analyze_repository(MCPAnalysisRequest(root=str(root)))
    population = SummaryPopulation(
        name="fanout", root=root, store_path=store_path, service=service
    )
    corpora._published_store_run_id(
        population.record, outcome=BLAST_POPULATIONS["fanout"]
    )
    return population


class BlastPopulations:
    """The run summary's populations and the fan-out one, built on first use."""

    def __init__(self, factory: pytest.TempPathFactory) -> None:
        self._summary = shared_populations(factory)
        self._factory = factory
        self._fanout: SummaryPopulation | None = None

    def __getitem__(self, name: str) -> SummaryPopulation:
        assert name in BLAST_POPULATIONS, name
        if name != "fanout":
            return self._summary[name]
        if self._fanout is None:
            self._fanout = _serve_fanout(
                self._factory.mktemp("blast_radius_fanout").resolve()
            )
        return self._fanout

    def __iter__(self) -> Iterator[SummaryPopulation]:
        return (self[name] for name in BLAST_POPULATIONS)


#: One set per pytest session, whichever module asks first.
_SHARED: dict[str, BlastPopulations] = {}


def shared_blast_populations(factory: pytest.TempPathFactory) -> BlastPopulations:
    key = str(factory.getbasetemp())
    if key not in _SHARED:
        _SHARED[key] = BlastPopulations(factory)
    return _SHARED[key]


# -- one store row replaced: the carrier perturbations ----------------------
#
# Each perturbation replaces ONE stored row of a run as the store decodes it
# (``store_row_replaced``, the run summary's instrument: between the member
# decoder and the model assembly, so the bounded read meets the replaced row),
# and the answer field that row carries must move -- through the store only:
# the execution's memory is untouched, so the edge answers ``divergent`` and
# names the field.  A carrier read from memory instead would stay ``served``.

_Rows = dict[str, list[object]]
_Perturb = Callable[[_Rows], None]


def _one(
    family: str,
    match: Callable[[Any], bool],
    edit: Callable[[Any], object] | None,
) -> _Perturb:
    """Replace (or, with no edit, drop) the one row ``match`` selects."""

    def perturb(collected: _Rows) -> None:
        rows = collected.get(family)
        if rows is None:  # a family this reading did not read
            return
        (index,) = [position for position, row in enumerate(rows) if match(row)]
        if edit is None:
            del rows[index]
        else:
            rows[index] = edit(rows[index])

    return perturb


def _at_file(path: str) -> Callable[[Any], bool]:
    return lambda row: row.file == FileId(path)


def _site_in(path: str) -> Callable[[Any], bool]:
    return lambda row: any(item.symbol.file == FileId(path) for item in row.items)


def _symbol_in(path: str, attribute: str = "symbol") -> Callable[[Any], bool]:
    return lambda row: getattr(row, attribute).file == FileId(path)


def _band(dimension: str, path: str) -> Callable[[Any], bool]:
    return lambda row: row.dimension == dimension and row.symbol.file == FileId(path)


def _known_cycle(row: Any) -> bool:
    return bool(row.novelty == "known" and "pkg.tri_a" in row.finding_id)


def _known_block_clone(row: Any) -> bool:
    return bool(row.novelty == "known" and row.finding_id.startswith("clone:block"))


@dataclass(frozen=True, slots=True)
class Carrier:
    """One stored row, the question it answers, the fields it must move."""

    population: str
    request: BlastRequest
    perturb: _Perturb
    fields: tuple[str, ...]


#: Every carrier family of the blast radius, with one row of it replaced.
STORE_ROW_CARRIERS: dict[str, Carrier] = {
    "dependency_relation": Carrier(
        "fanout",
        BlastRequest(("pkg/core.py",), "direct"),
        _one(
            "dependency_relation",
            lambda row: (
                row.source == ModuleId("pkg.user_0")
                and row.target == ModuleId("pkg.core")
            ),
            lambda row: replace(row, source=ModuleId("pkg.top")),
        ),
        ("direct_dependents",),
    ),
    "file_module": Carrier(
        "fanout",
        BlastRequest(("pkg/core.py",), "direct"),
        _one("file_module", lambda row: row.module == ModuleId("pkg.user_1"), None),
        ("direct_dependents",),
    ),
    "dependency_cycle": Carrier(
        "fanout",
        BlastRequest(("pkg/cyc_a.py",), "direct"),
        _one(
            "dependency_cycle", lambda row: ModuleId("pkg.cyc_a") in row.modules, None
        ),
        ("in_dependency_cycle",),
    ),
    "clone_group": Carrier(
        "fanout",
        BlastRequest(("pkg/trio_a.py",), "direct"),
        _one("clone_group", _site_in("pkg/trio_a.py"), None),
        ("clone_cohort_members",),
    ),
    "suppressed_clone_group": Carrier(
        "fanout",
        BlastRequest(("tests/fixtures/golden_twins/twin_a.py",), "direct"),
        _one(
            "suppressed_clone_group",
            _site_in("tests/fixtures/golden_twins/twin_a.py"),
            None,
        ),
        ("review_context",),
    ),
    "import_observation": Carrier(
        "fanout",
        BlastRequest(("pkg/loader.py",), "direct"),
        _one(
            "import_observation",
            lambda row: row.resolution == "unresolved_dynamic",
            None,
        ),
        ("review_context",),
    ),
    "overloaded_module_candidate": Carrier(
        "fanout",
        BlastRequest(("pkg/core.py",), "direct"),
        _one(
            "overloaded_module",
            lambda row: row.candidate_status == "candidate",
            lambda row: replace(row, candidate_status="non_candidate"),
        ),
        ("structural_risk.overloaded_modules_in_blast_zone",),
    ),
    "overloaded_module": Carrier(
        "fanout",
        BlastRequest(("pkg/core.py",), "direct"),
        _one("overloaded_module", _at_file("pkg/user_0.py"), None),
        ("review_context",),
    ),
    "security_surface": Carrier(
        "fanout",
        BlastRequest(("pkg/core.py",), "direct"),
        _one("security_surface", _at_file("pkg/a_danger.py"), None),
        ("review_context",),
    ),
    "unit_risk_result_complexity": Carrier(
        "trusted",
        BlastRequest(("pkg/complex_old.py",), "direct"),
        _one(
            "unit_risk_result",
            _band("complexity", "pkg/complex_old.py"),
            lambda row: replace(row, band="medium"),
        ),
        ("structural_risk.high_complexity_in_blast_zone",),
    ),
    "unit_risk_result_coupling": Carrier(
        "trusted",
        BlastRequest(("pkg/hub.py",), "direct"),
        _one(
            "unit_risk_result",
            _band("coupling", "pkg/hub.py"),
            lambda row: replace(row, band="medium"),
        ),
        ("structural_risk.high_coupling_in_blast_zone",),
    ),
    "dependency_cycle_novelty": Carrier(
        "trusted",
        BlastRequest(("pkg/tri_a.py",), "transitive"),
        _one(
            "dependency_cycle_novelty",
            _known_cycle,
            lambda row: replace(row, novelty="new"),
        ),
        ("review_context",),
    ),
    "clone_novelty": Carrier(
        "trusted",
        BlastRequest(("pkg/run_host_one.py",), "direct"),
        _one(
            "clone_novelty", _known_block_clone, lambda row: replace(row, novelty="new")
        ),
        ("review_context",),
    ),
    "coverage_unit": Carrier(
        "coverage_ok",
        BlastRequest(("pkg/complex_old.py",), "direct"),
        _one("coverage_unit", _symbol_in("pkg/complex_old.py"), None),
        ("structural_risk.low_coverage_in_blast_zone",),
    ),
    "coverage_join": Carrier(
        "coverage_ok",
        BlastRequest(("pkg/complex_old.py",), "direct"),
        _one(
            "coverage_join",
            lambda _row: True,
            lambda row: replace(row, hotspot_threshold_percent=0),
        ),
        ("structural_risk.low_coverage_in_blast_zone",),
    ),
    "risk_observation": Carrier(
        "coverage_ok",
        BlastRequest(("pkg/complex_old.py",), "direct"),
        _one(
            "risk_observation",
            lambda row: (
                row.dimension == "cyclomatic_complexity"
                and row.symbol.file == FileId("pkg/complex_old.py")
            ),
            lambda row: replace(row, numerator=1),
        ),
        ("structural_risk.low_coverage_in_blast_zone",),
    ),
}


def carrier_answer(
    population: SummaryPopulation, carrier: Carrier
) -> dict[str, object]:
    """The carrier's question, asked of the store with its one row replaced
    -- computed afresh, so no cached answer stands in for the store."""
    forget_answers(population)
    try:
        with store_row_replaced(carrier.perturb):
            return blast_answer(population, carrier.request, serve_from="run_store")
    finally:
        forget_answers(population)


__all__ = [
    "BLAST_POPULATIONS",
    "FANOUT_TREE",
    "INCLUDES",
    "SPECIAL_ORIGINS",
    "STORE_ROW_CARRIERS",
    "BlastPopulations",
    "BlastRequest",
    "Carrier",
    "PolicyRequest",
    "blast_answer",
    "blast_requests",
    "carrier_answer",
    "forget_answers",
    "policy_answer",
    "policy_requests",
    "registry_files",
    "shared_blast_populations",
]
