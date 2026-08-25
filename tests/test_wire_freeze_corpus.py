# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The wire-freeze distinguishing corpus (ruling 2026-08-24 §10, step 2b).

Four canonical-family candidates carried **zero rows** on the frozen
self-repo corpus, so their natural keys were never proven on data:
``dependency_cycles`` (F7), ``clone_groups`` (F8), ``violations``, and
``sorted_novelty_facts``.  This corpus exists to keep every one of them
**non-zero** — it is the data source of the wire-freeze gate, and these
pins are what keep it from rotting into a corpus that no longer
distinguishes anything.

The tree lives in ``tests/fixtures/wire_freeze_corpus/`` as inert ``*.txt``
carriers and is materialized into ``tmp_path`` here, because analyzable
``.py`` files inside this repository would enter the self-analysis and red
the baseline-relative gates (``fail_on_new_metrics`` gates new import
cycles, new dead code, and negative health delta; the golden_fixture
channel absorbs clone groups only).  Discovery is ``.py``-suffix-based, so
the carriers are invisible to the self-run by construction.

Measured ground truth of the materialized tree (2026-08-25 night):

* F7 ``cycle_details``: exactly 3 rows — 2 ``import_cycle`` (a 2-cycle and
  a 3-cycle) and 1 ``deferred_cycle`` (a lap closed only by a
  function-level import).  A deferred back-edge over a pair that already
  carries an import-time cycle does NOT produce a second row — one cycle
  row per module set, kind classified once.
* F8 clone groups: 3 ``function`` groups (one of them post-baseline) and
  1 ``block`` group whose three items include an intra-function pair;
  ``segment`` groups stayed 0 — a named residual (segment grouping demands
  the same window hash twice within one function AND the shared runs here
  are consumed by block matching first).
* violations: 3 rows in 2 kinds — ``owner_bypass`` for each of the two
  shadow writers plus one ``multiple_independent_producers`` over both.
* ``sorted_novelty_facts``: 4 rows, 3 ``known`` + 1 ``new`` (the
  post-baseline clone pair), keyed ``(lane, identity)``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

import codeclone.surfaces.cli.workflow as cli

_CORPUS = Path(__file__).parent / "fixtures" / "wire_freeze_corpus"

# The post-baseline stage: materialized only after the baseline is written,
# so its clone pair is the corpus's one genuinely NEW novelty row.
_POST_BASELINE = "pkg/clones_three.py"


def materialize_corpus(target: Path, *, post_baseline: bool) -> None:
    """Write the corpus tree from its inert carriers.

    Every ``*.txt`` carrier becomes the file named by stripping the
    trailing ``.txt``; ``post_baseline=False`` withholds the stage-B file.
    """
    for carrier in sorted(_CORPUS.rglob("*.txt")):
        relative = carrier.relative_to(_CORPUS).with_suffix("")
        if not post_baseline and relative.as_posix() == _POST_BASELINE:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(carrier.read_text("utf-8"), "utf-8")


def _run_cli(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["codeclone", *args])
    cli.main()


@pytest.fixture(scope="module")
def corpus_report(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    """One two-stage corpus run: baseline on stage A, report on stage B."""
    root = tmp_path_factory.mktemp("wire_freeze_corpus")
    baseline = root / "corpus.baseline.json"
    report_path = root / "corpus.report.json"
    monkeypatch = pytest.MonkeyPatch()
    try:
        materialize_corpus(root, post_baseline=False)
        _run_cli(
            monkeypatch,
            [
                str(root),
                "--baseline",
                str(baseline),
                "--update-baseline",
                "--no-progress",
            ],
        )
        materialize_corpus(root, post_baseline=True)
        _run_cli(
            monkeypatch,
            [
                str(root),
                "--baseline",
                str(baseline),
                "--json",
                str(report_path),
                "--no-progress",
            ],
        )
    finally:
        monkeypatch.undo()
    document = json.loads(report_path.read_text("utf-8"))
    assert isinstance(document, dict)
    return document


def _section(document: dict[str, object], *path: str) -> dict[str, object]:
    """Walk one report sub-object, refusing a wrong shape loudly."""
    node: object = document
    for key in path:
        assert isinstance(node, dict), path
        node = node[key]
    assert isinstance(node, dict)
    return node


def _distinct(keys: Sequence[tuple[object, ...]], expected: int) -> None:
    """The corpus's whole point: `expected` rows, every key distinct."""
    assert len(keys) == expected
    assert len(set(keys)) == expected


def test_f7_dependency_cycles_are_nonzero_and_key_distinct(
    corpus_report: dict[str, object],
) -> None:
    """F7: both cycle kinds present, and the candidate key measured.

    The one-row-per-module-set behavior is part of the pin: the corpus
    carries a deferred back-edge over the import-cycle pair on purpose, and
    it must NOT create a fourth row.
    """
    dependencies = _section(corpus_report, "metrics", "families", "dependencies")
    rows = dependencies["cycle_details"]
    assert isinstance(rows, list)
    assert sorted((row["kind"], tuple(row["modules"])) for row in rows) == [
        ("deferred_cycle", ("pkg.lazy_x", "pkg.lazy_y")),
        ("import_cycle", ("pkg.cycle_a", "pkg.cycle_b")),
        ("import_cycle", ("pkg.tri_a", "pkg.tri_b", "pkg.tri_c")),
    ]
    # every row carries its member_paths evidence
    assert all(row["member_paths"] for row in rows)


def test_f8_clone_groups_are_emitted_in_two_kinds_with_distinct_keys(
    corpus_report: dict[str, object],
) -> None:
    """F8: emitted (not suppressed) groups across two clone kinds.

    The block group's three items include an intra-function pair — group
    arity and item identity are not the same measurement.
    """
    clones = _section(corpus_report, "findings", "groups", "clones")
    keys: list[tuple[object, ...]] = []
    for kind in ("functions", "blocks", "segments"):
        groups = clones.get(kind, [])
        assert isinstance(groups, list)
        keys.extend(
            (group["clone_kind"], group["facts"]["group_key"]) for group in groups
        )
    _distinct(keys, 4)
    assert sorted(str(kind) for kind, _key in keys) == [
        "block",
        "function",
        "function",
        "function",
    ]
    blocks = clones["blocks"]
    assert isinstance(blocks, list)
    block_items = blocks[0]["items"]
    assert len(block_items) == 3
    assert len({item["qualname"] for item in block_items}) == 2  # intra-fn pair


def test_authority_violations_are_nonzero_in_two_kinds(
    corpus_report: dict[str, object],
) -> None:
    """violations: the natural key (contract_id, kind, sink, producers)
    is measured on real rows of two different kinds."""
    semantic = _section(corpus_report, "source_facts", "semantic")
    violations = semantic["violations"]
    assert isinstance(violations, list)
    _distinct(
        [
            (
                row["contract_id"],
                row["kind"],
                row["sink_identity"],
                tuple(sorted(row["producers"])),
            )
            for row in violations
        ],
        3,
    )
    assert sorted(row["kind"] for row in violations) == [
        "multiple_independent_producers",
        "owner_bypass",
        "owner_bypass",
    ]


def test_sorted_novelty_facts_carry_known_and_new_rows(
    corpus_report: dict[str, object],
) -> None:
    """sorted_novelty_facts: non-zero, keyed (lane, identity), and both
    novelty values present — a corpus with only ``known`` rows could not
    distinguish a novelty column from a constant."""
    baseline = _section(corpus_report, "baseline")
    assert baseline["state"] == "trusted"
    rows = baseline["sorted_novelty_facts"]
    assert isinstance(rows, list)
    _distinct([(row["lane"], row["identity"]) for row in rows], 4)
    assert sorted(row["novelty"] for row in rows) == ["known", "known", "known", "new"]
    assert {row["lane"] for row in rows} == {"clones.functions", "clones.blocks"}
