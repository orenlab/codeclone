# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The dead-code detector can still say DEAD: a positive control that owns its corpus.

The shrink-only inventory in ``test_dead_code_suppression_ratchet`` is a subset
law, and a subset law is green on an EMPTY population: a detector that stopped
reporting anything would pass it with a perfect score, and the ratchet may not
demand a non-empty inventory because shrinking to nothing is the direction it
exists to allow.  So the control lives here, owns its own two-line corpus and
makes no statement about the repository's inventory: one generated tree with
one provably dead symbol, run through the library dead-code path, must come
back in ``dead_code.items`` - and the one edit that gives the symbol a consumer
must take it out again.  Without the counterfactual the control would also hold
for a detector that calls EVERY symbol dead.

Two traps, both measured on this shape:

* every metric family, ``dead_code`` included, is SKIPPED without a baseline
  unless the bootstrap says ``skip_metrics=False`` - a run that skipped the
  family reads exactly like a detector that found nothing;
* under the product's default OPEN world a PUBLIC module-level name is
  potentially external and abstains (``unresolved`` / ``externally_reachable``)
  instead of dying, so the corpus carries a ``_``-private symbol: the form the
  open lane reports, and the form the repository's own open population is made
  of.  A closed-world control would say nothing about the open lane's extra
  abstention row, which is exactly the row that could swallow that population.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from codeclone.contracts import DEFAULT_MIN_LOC, DEFAULT_MIN_STMT
from tests._pipeline_fixtures import (
    analysis_boot,
    payload_mapping,
    payload_sequence,
    run_pipeline_once,
)

#: One generated tree, one provably dead symbol: a ``_``-private module-level
#: function nothing in the tree references.
_CORPUS: Final[Mapping[str, str]] = {
    "pkg/__init__.py": "",
    "pkg/_support.py": "def _provably_dead() -> int:\n    return 1\n",
}
_DEAD_SYMBOL: Final[str] = "pkg._support:_provably_dead"

#: The counterfactual: one import and one call, and nothing else changes.
_CONSUMER: Final[Mapping[str, str]] = {
    "pkg/consumer.py": (
        "from ._support import _provably_dead\n"
        "\n"
        "\n"
        "def use_it() -> int:\n"
        "    return _provably_dead()\n"
    ),
}

#: The lanes beside ``items``.  LIVE is the absence from all four, so the
#: counterfactual reads every one of them.
_ABSTENTION_LANES: Final[tuple[str, ...]] = (
    "unresolved",
    "unresolved_internal",
    "unresolved_overrides",
)


def _qualnames(rows: object) -> frozenset[str]:
    return frozenset(
        str(payload_mapping(row)["qualname"]) for row in payload_sequence(rows)
    )


def _dead_code_of(
    root: Path,
    tree: Mapping[str, str],
) -> tuple[dict[str, object], frozenset[str]]:
    """The dead-code family of one generated tree, behind a presence witness.

    The library path, not a spawned CLI: ``skip_metrics=False`` on the
    bootstrap and no world override, so the run reads the product default
    (``DEFAULT_DEAD_CODE_WORLD``).  The second value is every function the run
    measured - the complexity family, which the library payload spells
    ``functions``: an absence from ``items`` is what an unanalysed file looks
    like too, and the witness is what tells the two apart.
    """

    project = root / "project"
    for relative_path, source in sorted(tree.items()):
        path = project / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, "utf-8")
    boot = analysis_boot(
        project,
        min_loc=DEFAULT_MIN_LOC,
        min_stmt=DEFAULT_MIN_STMT,
        skip_metrics=False,
    )
    _cache, run = run_pipeline_once(boot, root / "cache.json", root=project, warm=False)
    payload = payload_mapping(run.result.metrics_payload)
    measured = _qualnames(payload_mapping(payload["complexity"])["functions"])
    return payload_mapping(payload["dead_code"]), measured


def test_the_detector_reports_the_one_provably_dead_symbol(tmp_path: Path) -> None:
    """The positive control: a known DEAD, produced on a distinguishing source.

    Exactly the one symbol, so a detector that started calling everything dead
    fails here as well as in the counterfactual.
    """

    dead_code, measured = _dead_code_of(tmp_path, _CORPUS)
    assert _DEAD_SYMBOL in measured, sorted(measured)
    assert _qualnames(dead_code["items"]) == frozenset({_DEAD_SYMBOL})


def test_one_consumer_takes_the_symbol_out_of_the_dead_set(tmp_path: Path) -> None:
    """The counterfactual that makes the control causal.

    A proven internal use must move the symbol out of ``items`` and out of
    every abstention lane, read behind the presence witness so a tree that was
    never analysed cannot pass as a tree whose symbol came alive.
    """

    dead_code, measured = _dead_code_of(tmp_path, {**_CORPUS, **_CONSUMER})
    assert _DEAD_SYMBOL in measured, sorted(measured)
    assert _DEAD_SYMBOL not in _qualnames(dead_code["items"])
    for lane in _ABSTENTION_LANES:
        assert _DEAD_SYMBOL not in _qualnames(dead_code[lane]), lane
