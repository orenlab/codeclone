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
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

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


__all__ = [
    "BLAST_POPULATIONS",
    "FANOUT_TREE",
    "INCLUDES",
    "SPECIAL_ORIGINS",
    "BlastPopulations",
    "BlastRequest",
    "PolicyRequest",
    "blast_answer",
    "blast_requests",
    "forget_answers",
    "policy_answer",
    "policy_requests",
    "registry_files",
    "shared_blast_populations",
]
