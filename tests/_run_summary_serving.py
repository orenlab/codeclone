# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The populations behind the run-summary serving pins (consumer migration C1).

Every population is one in-process MCP execution of its own tree, with the
run store on and its own store file, kept alive so a pin can ask the same
execution for its summary twice -- once with the serving switch on the
store, once on memory -- and compare the two answers.  The trees are the
suite's own corpora, built by their own builders in ``tests/conftest.py``;
nothing is restated here but the population each one stands for.

The population is chosen to DISTINGUISH (Probe Validity Law, AGENTS.md
§17.3), measured on the inventory before the edge was written
(2026-10-03): every baseline state (missing, trusted, untrusted scope, a
lane recorded under an older schema in a health lane and in the API lane),
every analysis mode (full, clones-only), every population word of the health
verdict (complete, empty, unmeasured), a truncated run (one unparsable
file), a coverage join in both of its statuses, authority findings, and a
second analysis over a warm cache in both modes.  A field whose memory
answer is one constant over the whole population would let a projection
answering that constant pass; the equivalence pins state the accounting
before they count.

This module is a helper, not a test module, so it may read the canonical
store beside the surface (the Phase 39S test-import law binds
``tests/test_*.py`` only).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from codeclone.api.run_store_serving import (
    ENV_SERVE_FROM,
    SERVE_FROM_RUN_STORE,
    ServedRunSummary,
    read_run_store_summary,
)
from codeclone.canonical.model import CanonicalModel
from codeclone.canonical.store import RunStore
from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests import conftest as corpora
from tests.test_baseline_lane_degradation import downgrade_lane_payload_schema

#: The population, by name, and the publication each one states.
SUMMARY_POPULATIONS: dict[str, str] = {
    "no_baseline": "published",
    "projection_corpus": "published",
    "trusted": "published",
    "foreign_scope": "published",
    "older_schema_dead_code_lane": "published",
    "older_schema_api_lane": "published",
    "api_disabled": "published",
    "partial": "head_withheld",
    "gated": "published",
    "clones_only": "head_withheld",
    "complete_empty": "published",
    "unmeasured": "head_withheld",
    "coverage_ok": "published",
    "coverage_invalid": "published",
    "warm_rerun": "published",
    "clones_only_warm": "head_withheld",
}


@dataclass(frozen=True, slots=True)
class SummaryPopulation:
    """One live MCP execution of one population's tree."""

    name: str
    root: Path
    store_path: Path
    service: CodeCloneMCPService

    @property
    def record(self) -> MCPRunRecord:
        return self.service._runs.resolve_any_root()

    def memory_answer(self) -> dict[str, object]:
        """The answer the surface builds from the record alone."""
        record = self.record
        return self.service._summary_payload(record.summary, record=record)

    def answer(self, *, serve_from: str | None) -> dict[str, object]:
        """``get_run_summary`` under the rollout that published the run and
        the serving switch named (``None``: the switch unset)."""
        with serving_environment(self.store_path, serve_from=serve_from):
            return self.service.get_run_summary(root=str(self.root))


@contextmanager
def serving_environment(store_path: Path, *, serve_from: str | None) -> Iterator[None]:
    """The run-store rollout over ``store_path`` and the serving switch."""
    patch = pytest.MonkeyPatch()
    try:
        patch.setenv("CODECLONE_RUN_STORE_ENABLED", "1")
        patch.setenv("CODECLONE_RUN_STORE_FORCE", "1")
        patch.setenv("CODECLONE_RUN_STORE_PATH", str(store_path))
        if serve_from is None:
            patch.delenv(ENV_SERVE_FROM, raising=False)
        else:
            patch.setenv(ENV_SERVE_FROM, serve_from)
        yield
    finally:
        patch.undo()


def stored_blocks(population: SummaryPopulation) -> ServedRunSummary:
    """The store's blocks of one execution's run, read through the door the
    surface reads through -- never a reading of the test's own."""
    record = population.record
    with serving_environment(population.store_path, serve_from=SERVE_FROM_RUN_STORE):
        stored, outcome = read_run_store_summary(
            root=record.root, link=record.execution.run_snapshot_link
        )
    assert stored is not None, outcome
    return stored


def _declare_gates(root: Path) -> None:
    pyproject = root / "pyproject.toml"
    declared = "".join(
        f"{name} = {value}\n" for name, value in corpora.SERVED_EVALUATION_GATES.items()
    )
    pyproject.write_text(
        pyproject.read_text("utf-8").replace(
            "[tool.codeclone]\n", f"[tool.codeclone]\n{declared}", 1
        ),
        "utf-8",
    )


def _drop_semantic_authority(root: Path) -> None:
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text("utf-8").replace("semantic_authority = true\n", ""),
        "utf-8",
    )


#: The hotspot the coverage report measures (24 branches, stage A of the
#: comparison corpus) and how many lines its body spans.
_COVERED_HOTSPOT = "pkg/complex_old.py"
_COVERED_HOTSPOT_LINES = 51


def _quarter_covered_report(root: Path) -> str:
    """A Cobertura report hitting every fourth line of the covered hotspot."""
    lines = "".join(
        f'<line number="{number}" hits="{int(number % 4 == 0)}"/>'
        for number in range(1, _COVERED_HOTSPOT_LINES + 1)
    )
    return (
        '<?xml version="1.0" ?>\n<coverage version="7.0" line-rate="0.25">'
        f"<sources><source>{root}</source></sources>"
        '<packages><package name="pkg"><classes>'
        f'<class name="complex_old.py" filename="{_COVERED_HOTSPOT}">'
        f"<lines>{lines}</lines></class></classes></package></packages></coverage>\n"
    )


class SummaryPopulations:
    """Every population, built on first use and kept for the session."""

    def __init__(self, base: Path) -> None:
        self._base = base
        self._baseline: Path | None = None
        self._built: dict[str, SummaryPopulation] = {}

    def __getitem__(self, name: str) -> SummaryPopulation:
        if name not in self._built:
            self._built[name] = self._serve(name)
        return self._built[name]

    def _stage_a_baseline(self) -> Path:
        if self._baseline is None:
            holder = self._base / "_baseline"
            holder.mkdir()
            self._baseline = corpora._comparison_baseline(holder)
        return self._baseline

    def _comparison_tree(self, name: str, kind: str) -> Path:
        holder = self._base / f"_{name}"
        holder.mkdir()
        return corpora._served_comparison_tree(holder, kind, self._stage_a_baseline())

    def _bare_tree(self, name: str) -> Path:
        root = self._base / name
        root.mkdir()
        return root

    def _tree(self, name: str) -> tuple[Path, MCPAnalysisRequest, int]:
        builders: dict[str, Callable[[], tuple[Path, dict[str, object], int]]] = {
            "no_baseline": self._no_baseline,
            "projection_corpus": self._projection_corpus,
            "older_schema_dead_code_lane": lambda: self._older_schema("dead_code", "3"),
            "older_schema_api_lane": lambda: self._older_schema("api_surface", "2"),
            "gated": self._gated,
            "clones_only": lambda: self._clones_only(analyses=1),
            "clones_only_warm": lambda: self._clones_only(analyses=2),
            "complete_empty": lambda: self._empty(unparsable=False),
            "unmeasured": lambda: self._empty(unparsable=True),
            "coverage_ok": lambda: self._coverage(valid=True),
            "coverage_invalid": lambda: self._coverage(valid=False),
            "warm_rerun": lambda: self._no_baseline(analyses=2),
        }
        build = builders.get(name)
        if build is None:
            root, options, analyses = self._comparison(name)
        else:
            root, options, analyses = build()
        mode = str(options.pop("analysis_mode", "full"))
        request = MCPAnalysisRequest(
            root=str(root),
            analysis_mode=mode,  # type: ignore[arg-type]
            **options,  # type: ignore[arg-type]
        )
        return root, request, analyses

    def _comparison(self, name: str) -> tuple[Path, dict[str, object], int]:
        """One of the served comparison populations of ``tests/conftest.py``."""
        api_surface, _foreign, _partial = corpora.SERVED_COMPARISON_POPULATIONS[name]
        return self._comparison_tree(name, name), {"api_surface": api_surface}, 1

    def _no_baseline(self, analyses: int = 1) -> tuple[Path, dict[str, object], int]:
        root = self._bare_tree("warm_rerun" if analyses > 1 else "no_baseline")
        corpora._materialize_corpus_tree(corpora._RUN_STORE_SERVING_CORPUS, root)
        return root, {}, analyses

    def _projection_corpus(self) -> tuple[Path, dict[str, object], int]:
        root = self._bare_tree("projection_corpus")
        corpora.materialize_projection_corpus(root)
        return root, {}, 1

    def _older_schema(
        self, lane: str, schema: str
    ) -> tuple[Path, dict[str, object], int]:
        root = self._comparison_tree(f"older_schema_{lane}", "trusted")
        downgrade_lane_payload_schema(
            root / "codeclone.baseline.json",
            lane_name=lane,  # type: ignore[arg-type]
            payload_schema=schema,
        )
        return root, {"api_surface": True}, 1

    def _gated(self) -> tuple[Path, dict[str, object], int]:
        """The evaluation carrier under two declared gates, analysed at a
        lower unit floor -- the one population whose analysis profile is not
        the default, so the profile is not a constant over the population."""
        root = self._comparison_tree("gated", "trusted")
        corpora._write_tree(root, corpora.EVALUATION_CARRIER)
        _declare_gates(root)
        return root, {"api_surface": True, "min_loc": 3, "min_stmt": 2}, 1

    def _clones_only(self, *, analyses: int) -> tuple[Path, dict[str, object], int]:
        name = "clones_only_warm" if analyses > 1 else "clones_only"
        root = self._comparison_tree(name, "api_disabled")
        _drop_semantic_authority(root)
        return root, {"analysis_mode": "clones_only"}, analyses

    def _empty(self, *, unparsable: bool) -> tuple[Path, dict[str, object], int]:
        root = self._bare_tree("unmeasured" if unparsable else "complete_empty")
        (root / "pkg").mkdir()
        if unparsable:
            corpora._write_unparsable(root)
        return root, {}, 1

    def _coverage(self, *, valid: bool) -> tuple[Path, dict[str, object], int]:
        """The trusted comparison tree joined with a Cobertura report that
        covers one of its two complexity hotspots a quarter and omits the
        other: a coverage hotspot and a scope gap; or an unreadable one."""
        name = "coverage_ok" if valid else "coverage_invalid"
        root = self._comparison_tree(name, "trusted")
        coverage = root / "coverage.xml"
        coverage.write_text(
            _quarter_covered_report(root) if valid else "<coverage><unclosed>",
            "utf-8",
        )
        return root, {"coverage_xml": coverage.name, "api_surface": True}, 1

    def _serve(self, name: str) -> SummaryPopulation:
        assert name in SUMMARY_POPULATIONS, name
        root, request, analyses = self._tree(name)
        store_path = self._base / f"{name}.sqlite3"
        service = CodeCloneMCPService(history_limit=4)
        with serving_environment(store_path, serve_from=None):
            for _ in range(analyses):
                service.analyze_repository(request)
        population = SummaryPopulation(
            name=name, root=root, store_path=store_path, service=service
        )
        corpora._published_store_run_id(
            population.record, outcome=SUMMARY_POPULATIONS[name]
        )
        return population


# -- one store row replaced: the carrier perturbations ----------------------
#
# Each perturbation replaces ONE stored row (or record) of a run as the
# store hands it back, so a pin can show the field that row carries moves --
# and only through the store: the memory answer of the execution is untouched.

_Perturb = Callable[[CanonicalModel], CanonicalModel]


def _analysis(model: CanonicalModel, **changes: Any) -> CanonicalModel:
    facts = replace(model.facts, analysis=replace(model.facts.analysis, **changes))
    return replace(model, facts=facts)


def _comparison(model: CanonicalModel, **changes: Any) -> CanonicalModel:
    facts = replace(model.facts, comparison=replace(model.facts.comparison, **changes))
    return replace(model, facts=facts)


def _evaluation(model: CanonicalModel, **changes: Any) -> CanonicalModel:
    facts = replace(model.facts, evaluation=replace(model.facts.evaluation, **changes))
    return replace(model, facts=facts)


def _bumped(record: object, name: str) -> object:
    return replace(record, **{name: getattr(record, name) + 1})  # type: ignore[type-var]


def _first_replaced(
    rows: Iterable[object],
    match: Callable[[object], bool],
    edit: Callable[[object], object],
) -> frozenset[object]:
    """The rows with the first matching one (in their sorted order) edited."""
    ordered = sorted(rows, key=repr)
    target = next(row for row in ordered if match(row))
    return frozenset(edit(row) if row is target else row for row in ordered)


def _without_first(rows: Iterable[object]) -> frozenset[object]:
    ordered = sorted(rows, key=repr)
    return frozenset(ordered[1:])


def _population(model: CanonicalModel, **changes: Any) -> CanonicalModel:
    record = model.facts.analysis.analysis_population
    return _analysis(model, analysis_population=replace(record, **changes))  # type: ignore[type-var]


def _raised_profile(model: CanonicalModel) -> CanonicalModel:
    record = model.facts.analysis.analysis_population
    assert record is not None
    raised = tuple((name, value + 1) for name, value in record.analysis_profile)
    return _population(model, analysis_profile=raised)


def _scalars(name: str) -> _Perturb:
    return lambda model: _analysis(
        model, run_scalars=_bumped(model.facts.analysis.run_scalars, name)
    )


def _delta(family: str, term: str) -> _Perturb:
    def perturb(model: CanonicalModel) -> CanonicalModel:
        rows = _first_replaced(
            getattr(model.facts.comparison, family),
            lambda row: getattr(row, "delta", None) == term,
            lambda row: _bumped(row, "value"),
        )
        return _comparison(model, **{family: rows})

    return perturb


def _novelty(family: str, word: str, becomes: str) -> _Perturb:
    def perturb(model: CanonicalModel) -> CanonicalModel:
        rows = _first_replaced(
            getattr(model.facts.comparison, family),
            lambda row: getattr(row, "novelty", None) == word,
            lambda row: replace(row, novelty=becomes),  # type: ignore[type-var]
        )
        return _comparison(model, **{family: rows})

    return perturb


#: Each carrier: (population, one stored row replaced, the answer fields the
#: replacement must move).  The fields are a floor -- a row may carry more
#: than one field -- and the pin holds the floor, never "something moved".
STORE_ROW_PERTURBATIONS: dict[str, tuple[str, _Perturb, tuple[str, ...]]] = {
    "analysis_mode": (
        "trusted",
        lambda model: _population(model, analysis_mode="full_perturbed"),
        ("mode",),
    ),
    "analysis_profile": ("trusted", _raised_profile, ("analysis_profile.min_loc",)),
    "baseline_witness": (
        "trusted",
        lambda model: _comparison(
            model,
            baseline_witness=replace(
                model.facts.comparison.baseline_witness,  # type: ignore[type-var]
                python_tag="cp399",
            ),
        ),
        ("baseline.baseline_python_tag",),
    ),
    "metrics_baseline_witness": (
        "trusted",
        lambda model: _comparison(
            model,
            metrics_baseline_witness=replace(
                model.facts.comparison.metrics_baseline_witness,  # type: ignore[type-var]
                loaded=False,
                status="missing",
            ),
        ),
        ("metrics_baseline.loaded", "metrics_baseline.status"),
    ),
    "run_scalars_files": ("trusted", _scalars("files_found"), ("inventory.files",)),
    "run_scalars_lines": ("trusted", _scalars("parsed_lines"), ("inventory.lines",)),
    "run_scalars_functions": (
        "trusted",
        _scalars("functions"),
        ("inventory.functions",),
    ),
    "run_scalars_classes": ("trusted", _scalars("classes"), ("inventory.classes",)),
    "health_result": (
        "trusted",
        lambda model: _evaluation(
            model,
            health_result=_bumped(model.facts.evaluation.health_result, "score"),
        ),
        ("health.score",),
    ),
    "health_delta": (
        "trusted",
        _delta("health_delta", "health_delta"),
        ("health.delta", "diff.health_delta"),
    ),
    "dead_symbol_group": (
        "trusted",
        lambda model: _analysis(
            model,
            dead_symbol_groups=_without_first(model.facts.analysis.dead_symbol_groups),
        ),
        ("findings.total", "findings.by_family", "dead_code.total"),
    ),
    "dead_symbol_novelty": (
        "trusted",
        _novelty("dead_symbol_novelty", "known", "new"),
        ("findings.new", "findings.known", "findings.new_by_source_kind"),
    ),
    "clone_novelty": (
        "trusted",
        _novelty("clone_novelty", "new", "known"),
        ("diff.new_clones", "findings.new", "findings.known"),
    ),
    "adoption_delta": (
        "trusted",
        _delta("adoption_delta", "docstring_permille_delta"),
        ("diff.docstring_permille_delta",),
    ),
    "api_surface_delta": (
        "trusted",
        _delta("api_surface_delta", "new_api_symbols"),
        ("diff.new_api_symbols",),
    ),
    "dead_code_summary": (
        "trusted",
        lambda model: _analysis(
            model,
            dead_code_summary=_bumped(
                model.facts.analysis.dead_code_summary, "suppressed"
            ),
        ),
        ("dead_code.suppressed",),
    ),
    "coverage_join": (
        "coverage_ok",
        lambda model: _analysis(
            model,
            coverage_join=_bumped(
                model.facts.analysis.coverage_join, "hotspot_threshold_percent"
            ),
        ),
        ("coverage_join.hotspot_threshold_percent",),
    ),
    "security_surface": (
        "projection_corpus",
        lambda model: _analysis(
            model,
            security_surfaces=_without_first(model.facts.analysis.security_surfaces),
        ),
        ("security_surfaces.items",),
    ),
}


@contextmanager
def store_row_replaced(perturb: _Perturb) -> Iterator[None]:
    """Every whole-run read of the store hands back the run with one row
    replaced, for as long as the context lasts."""
    original = RunStore.read_run
    patch = pytest.MonkeyPatch()

    def _read_run(store: RunStore, run_id: str) -> CanonicalModel:
        return perturb(original(store, run_id))

    try:
        patch.setattr(RunStore, "read_run", _read_run)
        yield
    finally:
        patch.undo()


#: One set of populations per pytest session, whichever module asks first:
#: the trees and the executions are the expensive part, and a module-scoped
#: fixture would build them once per module.
_SHARED: dict[str, SummaryPopulations] = {}


def shared_populations(factory: pytest.TempPathFactory) -> SummaryPopulations:
    """The session's populations, under the session's own temporary root."""
    key = str(factory.getbasetemp())
    if key not in _SHARED:
        _SHARED[key] = SummaryPopulations(
            factory.mktemp("run_summary_populations").resolve()
        )
    return _SHARED[key]


__all__ = [
    "STORE_ROW_PERTURBATIONS",
    "SUMMARY_POPULATIONS",
    "SummaryPopulation",
    "SummaryPopulations",
    "serving_environment",
    "shared_populations",
    "store_row_replaced",
    "stored_blocks",
]
