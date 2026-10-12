# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run comparison's pair population (consumer migration C3).

``compare_runs`` reads two runs of one session.  Its pairs here are every
before/after pair of the patch-contract battery (``tests/_patch_contract_
serving.py``) asked forward, backward and against itself, and the pairs the
battery cannot hold, each in its own session over its own store:

* ``clones_only`` -- two clones-only runs, the second with one clone pair
  more: a clone comparison that runs, and structural / metrics focuses the
  mode never analysed;
* ``clones_only_vs_full`` -- a clones-only run against a full run of the
  same tree: different analysis settings;
* ``unmeasured`` -- a run that read none of its files (every one refused by
  the parser) against the run after one parsable file was added;
* ``complete_empty`` -- a run of a scope with no source file against the
  run after one was added: an empty scope is a measured one;
* ``different_root`` -- two trees, one session, one store.

Each pair is asked under each focus and under each position of the serving
switch; the answer, the switch and the store are the only things that vary.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from codeclone.surfaces.mcp._session_shared import MCPAnalysisRequest, MCPRunRecord
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests import conftest as corpora
from tests._patch_contract_serving import CYCLE_BUILDERS, _twin, shared_cycles
from tests._run_store_paths import run_store_service_path
from tests._run_summary_serving import serving_environment

#: Every focus ``compare_runs`` takes.
COMPARE_FOCUSES: tuple[str, ...] = ("all", "clones", "structural", "metrics")
#: The clone pair a pair's second run adds.
_TWIN_PAIR: dict[str, str] = {
    "pkg/c3_twin_a.py": _twin("c3_twin_a"),
    "pkg/c3_twin_b.py": _twin("c3_twin_b"),
}


@dataclass(frozen=True, slots=True)
class ComparePair:
    """Two runs of one session, and the store their executions published to."""

    name: str
    service: CodeCloneMCPService
    store_path: Path
    before: MCPRunRecord
    after: MCPRunRecord
    #: The root selector the question passes: the pair's own root, or
    #: ``None`` for a pair of two roots (resolved globally, run by run).
    root: str | None

    def ask(self, focus: str, *, serve_from: str | None) -> dict[str, object]:
        """``compare_runs`` of this pair under one focus and one switch."""
        with serving_environment(self.store_path, serve_from=serve_from):
            return self.service.compare_runs(
                before_run_id=self.before.run_id,
                after_run_id=self.after.run_id,
                root=self.root,
                focus=focus,
            )


def _analyse(
    service: CodeCloneMCPService, store_path: Path, root: Path, **options: object
) -> MCPRunRecord:
    with serving_environment(store_path, serve_from=None):
        service.analyze_repository(
            MCPAnalysisRequest(root=str(root), **options)  # type: ignore[arg-type]
        )
    return service._runs.records()[-1]


def _battery_pairs(factory: pytest.TempPathFactory) -> Iterator[ComparePair]:
    cycles = shared_cycles(factory)
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        after = cycle.after
        if after is None:
            continue
        for side, (before_run, after_run) in {
            "forward": (cycle.before, after),
            "backward": (after, cycle.before),
            "same": (after, after),
        }.items():
            yield ComparePair(
                name=f"{name}.{side}",
                service=cycle.service,
                store_path=cycle.store_path,
                before=before_run,
                after=after_run,
                root=str(cycle.root),
            )


def _corpus_tree(root: Path) -> Path:
    corpora.materialize_comparison_corpus(root, stage_b=True)
    return root


def _session(root: Path) -> tuple[CodeCloneMCPService, Path]:
    """A session and the store it publishes ``root`` into: the root's own,
    at the default path -- so a session over two roots reads each run in
    the store that root published it into (``conftest.name_run_store``)."""
    return CodeCloneMCPService(history_limit=10), run_store_service_path(root)


def _clones_only_pairs(base: Path) -> Iterator[ComparePair]:
    root = _corpus_tree(base / "clones_only")
    service, store = _session(root)
    before = _analyse(service, store, root, analysis_mode="clones_only")
    corpora._write_tree(root, _TWIN_PAIR)
    after = _analyse(service, store, root, analysis_mode="clones_only")
    full = _analyse(service, store, root, analysis_mode="full")
    yield ComparePair("clones_only", service, store, before, after, str(root))
    yield ComparePair("clones_only_vs_full", service, store, after, full, str(root))


def _population_pair(base: Path, name: str, *, unparsable: bool) -> ComparePair:
    root = base / name
    (root / "pkg").mkdir(parents=True)
    if unparsable:
        corpora._write_unparsable(root)
    service, store = _session(root)
    before = _analyse(service, store, root, analysis_mode="full")
    corpora._write_tree(root, _TWIN_PAIR)
    after = _analyse(service, store, root, analysis_mode="full")
    return ComparePair(name, service, store, before, after, str(root))


def _different_root_pair(base: Path) -> ComparePair:
    first = _corpus_tree(base / "root_one")
    second = _corpus_tree(base / "root_two")
    corpora._write_tree(second, {"pkg/c3_twin_a.py": _twin("c3_twin_a")})
    service, store = _session(first)
    before = _analyse(service, store, first, analysis_mode="full")
    after = _analyse(service, store, second, analysis_mode="full")
    return ComparePair("different_root", service, store, before, after, None)


_SHARED: dict[str, dict[str, ComparePair]] = {}


def shared_pairs(factory: pytest.TempPathFactory) -> dict[str, ComparePair]:
    """The session's pair population, built once under its temporary root."""
    key = str(factory.getbasetemp())
    if key not in _SHARED:
        base = factory.mktemp("compare_runs_pairs").resolve()
        pairs = [
            *_battery_pairs(factory),
            *_clones_only_pairs(base),
            _population_pair(base, "unmeasured", unparsable=True),
            _population_pair(base, "complete_empty", unparsable=False),
            _different_root_pair(base),
        ]
        _SHARED[key] = {pair.name: pair for pair in pairs}
    return _SHARED[key]


__all__ = ["COMPARE_FOCUSES", "ComparePair", "shared_pairs"]
