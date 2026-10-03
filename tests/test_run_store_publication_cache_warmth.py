# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One run publishes one store run, whatever the analysis cache remembers.

A run's store snapshot is built from the facts of THAT run: a capability
the run switches off publishes exactly what it publishes on a cold cache,
whatever an earlier run left in the cache, and a capability the run keeps
on publishes, warm, exactly what it publishes cold.  Measured 2026-10-03:
a metrics-skipping run (CLI ``--skip-metrics``; MCP ``clones_only``) over
the cache its own first run wrote was handed the cached semantic events,
contract summaries and relationship facts its cold walk drops, and
published 47 contracts and graph nodes, 3 authority violations and 48
relationship observations beside a population that says its metrics were
disabled -- under a store run id of its own.

The population is built to distinguish (Probe Validity Law, AGENTS.md
§17.3): the tree carries an authority registry, so the authority lane runs
even where the metrics are skipped; its full run publishes every carrier
the leak moves; and every warm cell is shown warm -- each file a cache hit
and none analysed -- before anything is compared.  Every capability a CLI
run can switch off is one row; each is analysed cold, warm over its own
rows, warm over the rows of a full run, and partially warm (one file
changed) beside a cold run of the changed tree.  The CLI door is driven
here; the MCP door's ``clones_only`` rerun is the ``clones_only_warm``
population of ``tests/test_run_summary_store_equivalence.py``.
"""

from __future__ import annotations

import shutil
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

import codeclone.core.reporting as reporting
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.store import RunStore
from codeclone.core._types import DiscoveryResult, ProcessingResult
from codeclone.core.canonical_snapshot import publish_run_snapshot
from codeclone.models import RunSnapshotPublication
from tests import conftest as corpora


@dataclass(frozen=True, slots=True)
class _Run:
    """One CLI analysis: what its producers handed the publisher, and what
    the store holds under the run id the publication named."""

    discovery: DiscoveryResult
    processing: ProcessingResult
    publication: RunSnapshotPublication
    model: CanonicalModel


#: The arguments of the full run: every capability on (the authority lane
#: through the pyproject key and its registry).
_FULL = ("--api-surface", "--coverage", "{coverage}")

#: Every capability a CLI run can switch off: the run's arguments and the
#: pyproject keys it removes.  ``--skip-metrics`` refuses the
#: ``semantic_authority`` key, so that row drops the key and keeps the
#: registry -- which still turns the authority lane on.
CAPABILITIES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "none": (_FULL, ()),
    "metrics": (("--skip-metrics",), ("flag",)),
    "dead_code": ((*_FULL, "--skip-dead-code"), ()),
    "dependencies": ((*_FULL, "--skip-dependencies"), ()),
    "semantic_authority": (_FULL, ("flag", "registry")),
    "api_surface": (("--coverage", "{coverage}"), ()),
    "coverage_join": (("--api-surface",), ()),
}

#: Whether a run of the row is served the rows a full run wrote, measured
#: 2026-10-03.  A metrics-skipping run keys its dependent lane on
#: a profile of its own, and an API-less run refuses rows that carry an API
#: surface (the cache's materialization witness), so for those two rows the
#: "warm over a full run" cell recomputes every file -- stated here so the
#: cell is not read as a warm one.
_REUSES_FULL_ROWS: dict[str, bool] = {
    "none": True,
    "metrics": False,
    "dead_code": True,
    "dependencies": True,
    "semantic_authority": True,
    "api_surface": False,
    "coverage_join": True,
}

_FLAG = "semantic_authority = true\n"
_REGISTRY = "[[tool.codeclone.authority]]"

#: The file the partially warm cell changes: it hosts the authority owner,
#: so its own rows are among the carriers.
_TOUCHED = "pkg/authority_owner.py"

#: The six semantic-authority families of the analysis house.
_AUTHORITY = (
    "contracts",
    "graph_nodes",
    "sink_roles",
    "candidates",
    "semantic_edges",
    "violations",
)

#: The cells compared with a cold run of the same tree.
_WARM_CELLS = ("warm", "after_full")


def _edit_pyproject(root: Path, removed: Iterable[str]) -> None:
    pyproject = root / "pyproject.toml"
    text = pyproject.read_text("utf-8")
    for key in removed:
        before = text
        text = text.replace(_FLAG, "") if key == "flag" else text.split(_REGISTRY, 1)[0]
        # An edit that changed nothing would make its row a hollow cell.
        assert text != before, key
    pyproject.write_text(text, "utf-8")


def _coverage_report(root: Path) -> str:
    """A Cobertura report hitting every other line of one hotspot."""
    lines = "".join(
        f'<line number="{number}" hits="{number % 2}"/>' for number in range(1, 52)
    )
    return (
        '<?xml version="1.0" ?>\n<coverage version="7.0" line-rate="0.5">'
        f"<sources><source>{root}</source></sources>"
        '<packages><package name="pkg"><classes>'
        '<class name="complex_old.py" filename="pkg/complex_old.py">'
        f"<lines>{lines}</lines></class></classes></package></packages></coverage>\n"
    )


@contextmanager
def _publications() -> Iterator[list[tuple[object, ...]]]:
    """Every publication of the runs inside, with the discovery and the
    processing result the producer edge handed the publisher."""
    seen: list[tuple[object, ...]] = []

    def _spy(**kwargs: object) -> RunSnapshotPublication:
        publication = publish_run_snapshot(**kwargs)  # type: ignore[arg-type]
        seen.append((kwargs["discovery"], kwargs["processing"], publication))
        return publication

    patch = pytest.MonkeyPatch()
    try:
        patch.setattr(reporting, "publish_run_snapshot", _spy)
        yield seen
    finally:
        patch.undo()


def _analyse(root: Path, store: Path, arguments: tuple[str, ...]) -> _Run:
    coverage = str(root / "coverage.xml")
    argv = [str(root), "--no-progress", "--quiet"]
    argv += [value.format(coverage=coverage) for value in arguments]
    environment = {
        "CODECLONE_RUN_STORE_ENABLED": "1",
        "CODECLONE_RUN_STORE_FORCE": "1",
        "CODECLONE_RUN_STORE_PATH": str(store),
    }
    with _publications() as seen:
        code = corpora._run_codeclone_cli_exit(argv, environment)
    assert code in (None, 0), (code, argv)
    ((discovery, processing, publication),) = seen
    assert isinstance(discovery, DiscoveryResult)
    assert isinstance(processing, ProcessingResult)
    assert isinstance(publication, RunSnapshotPublication)
    assert publication.run_id, publication
    with RunStore(store, create=False) as handle:
        model = handle.read_run(publication.run_id)
    return _Run(discovery, processing, publication, model)


def _row_runs(pristine: Path, base: Path, capability: str) -> dict[str, _Run]:
    """One capability row: cold, warm over its own rows, warm over a full
    run's rows, and partially warm beside a cold run of the changed tree."""
    arguments, removed = CAPABILITIES[capability]
    root = base / capability / "tree"
    shutil.copytree(pristine, root)
    stores = base / capability / "stores"
    stores.mkdir()
    full_pyproject = (root / "pyproject.toml").read_text("utf-8")

    def analyse(cell: str, *, full: bool = False) -> _Run:
        (root / "pyproject.toml").write_text(full_pyproject, "utf-8")
        if not full:
            _edit_pyproject(root, removed)
        return _analyse(root, stores / f"{cell}.sqlite3", _FULL if full else arguments)

    def forget() -> None:
        shutil.rmtree(root / ".codeclone")

    runs = {"cold": analyse("cold"), "warm": analyse("warm")}
    forget()
    analyse("full", full=True)
    runs["after_full"] = analyse("after_full")
    forget()
    analyse("seed")
    touched = root / _TOUCHED
    touched.write_text(touched.read_text("utf-8") + "\n# changed\n", "utf-8")
    runs["partial"] = analyse("partial")
    forget()
    runs["cold_touched"] = analyse("cold_touched")
    return runs


@pytest.fixture(scope="module")
def rows(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, _Run]]:
    base = tmp_path_factory.mktemp("cache_warmth").resolve()
    holder = base / "_tree"
    holder.mkdir()
    pristine = corpora._served_comparison_tree(
        holder, "trusted", corpora._comparison_baseline(holder)
    )
    (pristine / "coverage.xml").write_text(_coverage_report(pristine), "utf-8")
    assert not (pristine / ".codeclone").exists()
    return {name: _row_runs(pristine, base, name) for name in CAPABILITIES}


def _pairs(runs: Mapping[str, _Run]) -> list[tuple[str, _Run, _Run]]:
    """Every warm cell beside the cold run it must equal."""
    return [
        *((cell, runs[cell], runs["cold"]) for cell in _WARM_CELLS),
        ("partial", runs["partial"], runs["cold_touched"]),
    ]


def _families(model: CanonicalModel) -> dict[str, object]:
    found: dict[str, object] = {
        field.name: getattr(model, field.name)
        for field in fields(model)
        if field.name != "facts"
    }
    for house in ("analysis", "comparison", "evaluation"):
        holder = getattr(model.facts, house)
        for field in fields(holder):
            found[f"{house}.{field.name}"] = getattr(holder, field.name)
    return found


def _authority_rows(run: _Run) -> dict[str, int]:
    facts = run.model.facts.analysis
    return {family: len(getattr(facts, family)) for family in _AUTHORITY}


def _multiset(values: Iterable[object]) -> Counter[str]:
    return Counter(repr(value) for value in values)


# -- the accounting: which cells are warm ------------------------------------


@pytest.mark.parametrize("capability", list(CAPABILITIES))
def test_every_cold_cell_is_cold_and_every_warm_cell_warm(
    rows: dict[str, dict[str, _Run]], capability: str
) -> None:
    """Probe validity: a warm cell that recomputed every file would compare
    a cold run with a cold run and could never see a leak."""
    runs = rows[capability]
    found = runs["cold"].discovery.files_found
    assert found > 1
    for cell in ("cold", "cold_touched"):
        assert runs[cell].discovery.cache_hits == 0, cell
        assert runs[cell].processing.files_analyzed == found, cell
    assert runs["warm"].discovery.cache_hits == found
    assert runs["warm"].processing.files_analyzed == 0
    assert runs["partial"].discovery.cache_hits == found - 1
    assert runs["partial"].processing.files_analyzed == 1
    reused = runs["after_full"].discovery.cache_hits
    assert reused == (found if _REUSES_FULL_ROWS[capability] else 0)


# -- one run, one store run ----------------------------------------------------


@pytest.mark.parametrize("capability", list(CAPABILITIES))
def test_one_run_publishes_one_store_run_whatever_the_cache_holds(
    rows: dict[str, dict[str, _Run]], capability: str
) -> None:
    for cell, warm, cold in _pairs(rows[capability]):
        assert (warm.publication.outcome, warm.publication.run_id) == (
            cold.publication.outcome,
            cold.publication.run_id,
        ), cell


@pytest.mark.parametrize("capability", list(CAPABILITIES))
def test_one_run_publishes_one_family_set_whatever_the_cache_holds(
    rows: dict[str, dict[str, _Run]], capability: str
) -> None:
    for cell, warm, cold in _pairs(rows[capability]):
        published, expected = _families(warm.model), _families(cold.model)
        moved = sorted(name for name in expected if published[name] != expected[name])
        assert moved == [], cell


# -- a switched-off capability: each carrier the cache could leak --------------


def test_a_metrics_skipping_warm_run_publishes_no_authority_row_its_cold_run_lacks(
    rows: dict[str, dict[str, _Run]],
) -> None:
    runs = rows["metrics"]
    population = runs["cold"].model.facts.analysis.analysis_population
    assert population is not None
    assert dict(population.producer_states)["semantic_authority"] == "disabled"
    for cell, warm, cold in _pairs(runs):
        assert _authority_rows(warm) == _authority_rows(cold), cell
        assert _multiset(warm.processing.function_contract_summaries) == _multiset(
            cold.processing.function_contract_summaries
        ), cell


def test_a_metrics_skipping_warm_run_publishes_no_relationship_its_cold_run_lacks(
    rows: dict[str, dict[str, _Run]],
) -> None:
    for cell, warm, cold in _pairs(rows["metrics"]):
        assert len(warm.model.facts.analysis.relationship_observations) == len(
            cold.model.facts.analysis.relationship_observations
        ), cell
        assert _multiset(warm.processing.function_relationship_facts) == _multiset(
            cold.processing.function_relationship_facts
        ), cell


def test_a_metrics_skipping_warm_run_takes_no_semantic_event_its_cold_run_lacks(
    rows: dict[str, dict[str, _Run]],
) -> None:
    for cell, warm, cold in _pairs(rows["metrics"]):
        assert _multiset(warm.processing.semantic_events) == _multiset(
            cold.processing.semantic_events
        ), cell


# -- an enabled capability: the same carriers, published warm ------------------


def test_a_full_warm_run_publishes_the_authority_rows_its_cold_run_publishes(
    rows: dict[str, dict[str, _Run]],
) -> None:
    for cell, warm, cold in _pairs(rows["none"]):
        assert all(_authority_rows(cold).values()), (cell, _authority_rows(cold))
        assert _authority_rows(warm) == _authority_rows(cold), cell
        assert _multiset(warm.processing.function_contract_summaries) == _multiset(
            cold.processing.function_contract_summaries
        ), cell


def test_a_full_warm_run_publishes_the_relationships_its_cold_run_publishes(
    rows: dict[str, dict[str, _Run]],
) -> None:
    for cell, warm, cold in _pairs(rows["none"]):
        relationships = cold.model.facts.analysis.relationship_observations
        assert relationships, cell
        published = warm.model.facts.analysis.relationship_observations
        assert published == relationships, cell
        assert _multiset(warm.processing.function_relationship_facts) == _multiset(
            cold.processing.function_relationship_facts
        ), cell


def test_a_full_warm_run_takes_the_semantic_events_its_cold_run_takes(
    rows: dict[str, dict[str, _Run]],
) -> None:
    for cell, warm, cold in _pairs(rows["none"]):
        assert cold.processing.semantic_events, cell
        assert _multiset(warm.processing.semantic_events) == _multiset(
            cold.processing.semantic_events
        ), cell
