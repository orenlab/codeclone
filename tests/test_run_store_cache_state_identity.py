# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A store run is a projection of what was observed, never of the cache state.

Measured 2026-09-25 by the determinism audit (DET-01, DET-02) and again on
this tree before the fix: a cold and a warm reading of ONE tree seal the same
report run identity, yet published two different store runs, and exactly one
family told them apart -- ``run_scalar``, which carried how many files were
parsed and how many were served off the cache as two separate numbers.  The
report's own law (``report/document/integrity.py``) already says that split
is execution provenance and must never reach a digest; its SUM is the fact.
The store broke that law, and the consequence was user-visible: a warm
repeat into one store stated a second edge for one report identity, and the
bridge then read its own healthy index as corrupt.

What is pinned here, and why each piece is separate:

* the carrier -- a split of one observed population, in any proportion,
  becomes one stored scalar, and that scalar is the sum (not the found
  population, not either addend) -- pinned beside the builder's other
  producer pins in ``test_producer_edge_containment``, and the same law on
  the document-oracle side here;
* the whole path -- a real cold and a real warm CLI run over one tree
  publish one store run, and the instrument is proven to have reached the
  cache before the equality is read, because an equality between two cold
  runs would prove nothing;
* the bridge -- the warm repeat into one store leaves one run and one edge,
  and the edge answers;
* the positive control -- a real edit of one file DOES move the store run,
  so the probe is shown able to see two runs when there are two.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from codeclone.canonical.ingest import _run_scalars as document_run_scalars
from codeclone.canonical.model import RunScalars
from codeclone.canonical.store import RunStore, linked_run
from codeclone.core.canonical_snapshot import RUN_SNAPSHOT_NAMESPACE
from codeclone.models import CANONICAL_HEAD_TARGET
from codeclone.utils.run_identity import report_run_identity
from tests.conftest import RunStoreCorpusRunner
from tests.test_run_store_producer_wiring import (  # noqa: F401
    _FULL_METRICS_ARGS,
    corpus,
)


def _document_scalars(*, analyzed: int, cached: int) -> RunScalars:
    """The run scalar the legacy-document oracle reads off one inventory."""

    return document_run_scalars(
        {
            "inventory": {
                "files": {
                    "total_found": 9,
                    "analyzed": analyzed,
                    "cached": cached,
                    "skipped": 2,
                    "source_io_skipped": 0,
                    "unsupported_construct_skipped": 0,
                },
                "code": {
                    "classes": 1,
                    "functions": 5,
                    "methods": 6,
                    "parsed_lines": 80,
                },
            }
        }
    )


def test_the_document_oracle_reads_the_same_sum() -> None:
    """The ingest side of the equivalence reads the split the same way.

    The producer and the document are compared field by field elsewhere
    (``test_run_store_producer_wiring``), which holds only if both halves
    agree; this holds the document half alone, so a mutant on one side
    cannot hide behind the other.
    """

    cold = _document_scalars(analyzed=7, cached=0)
    warm = _document_scalars(analyzed=0, cached=7)
    mixed = _document_scalars(analyzed=4, cached=3)
    assert cold == warm == mixed
    assert mixed.files_observed == 7


def _report(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text("utf-8"))
    assert isinstance(document, dict)
    return document


def _files(document: dict[str, object]) -> dict[str, int]:
    inventory = document["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, dict)
    return files


def _published_runs(store: Path) -> list[str]:
    with closing(sqlite3.connect(store)) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT run_id FROM runs WHERE published = 1 ORDER BY run_pk"
            )
        ]


def _edges(store: Path, identity: str) -> list[str]:
    with closing(sqlite3.connect(store)) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT r.run_id FROM run_report_links l "
                "JOIN runs r ON r.run_pk = l.run_pk "
                "WHERE l.report_run_identity = ? ORDER BY r.run_id",
                (identity,),
            )
        ]


def _cold_then_warm(
    root: Path,
    runner: RunStoreCorpusRunner,
    *,
    cold: tuple[Path, Path],
    warm: tuple[Path, Path],
) -> tuple[dict[str, object], dict[str, object]]:
    """Two readings of one tree, the second off the first one's cache.

    Each pair is ``(report path, store path)``.  The instrument is proven on
    before anything is returned: the first reading parsed every file and
    the second really came off the cache.  Without this an equality below
    could hold because neither run ever touched the lane under test.
    """

    runner(root, *_FULL_METRICS_ARGS, "--json", str(cold[0]), store=cold[1])
    runner(root, *_FULL_METRICS_ARGS, "--json", str(warm[0]), store=warm[1])
    cold_report, warm_report = _report(cold[0]), _report(warm[0])
    assert _files(cold_report)["cached"] == 0 < _files(cold_report)["analyzed"]
    assert _files(warm_report)["cached"] > 0
    return cold_report, warm_report


def test_a_cold_and_a_warm_reading_of_one_tree_publish_one_store_run(
    corpus: Path,  # noqa: F811
    run_store_cli: RunStoreCorpusRunner,
    tmp_path: Path,
) -> None:
    cold_store, warm_store = tmp_path / "cold.sqlite3", tmp_path / "warm.sqlite3"
    cold, warm = _cold_then_warm(
        corpus,
        run_store_cli,
        cold=(tmp_path / "cold.json", cold_store),
        warm=(tmp_path / "warm.json", warm_store),
    )

    assert report_run_identity(cold) == report_run_identity(warm)
    cold_runs, warm_runs = _published_runs(cold_store), _published_runs(warm_store)
    assert len(cold_runs) == 1
    assert cold_runs == warm_runs
    # What the one run stores is the fact the report names -- the sum of its
    # provenance split, which differs between the two documents.
    with RunStore(cold_store, create=False) as store:
        scalars = store.read_run(cold_runs[0]).facts.analysis.run_scalars
    assert scalars is not None
    observed = _files(cold)["analyzed"] + _files(cold)["cached"]
    assert scalars.files_observed == observed
    assert _files(warm)["analyzed"] + _files(warm)["cached"] == observed


def test_a_warm_repeat_into_one_store_is_one_run_and_one_answering_edge(
    corpus: Path,  # noqa: F811
    run_store_cli: RunStoreCorpusRunner,
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "runs.sqlite3"
    cold, warm = _cold_then_warm(
        corpus,
        run_store_cli,
        cold=(tmp_path / "cold.json", store_path),
        warm=(tmp_path / "warm.json", store_path),
    )
    identity = report_run_identity(cold)
    assert report_run_identity(warm) == identity

    runs = _published_runs(store_path)
    assert len(runs) == 1
    assert _edges(store_path, identity) == runs
    with RunStore(store_path, create=False) as store:
        edge = linked_run(store, report_run_identity=identity)
        head = store.head(
            namespace=RUN_SNAPSHOT_NAMESPACE, target=CANONICAL_HEAD_TARGET
        )
    assert edge is not None
    assert edge.run_id == runs[0]
    # One run because the warm publication REUSED it, not because it never
    # happened: a contained publish failure would also leave one run and one
    # edge.  The head advanced twice, both times onto that one run.
    assert head is not None
    assert (head.generation, head.run_id) == (2, runs[0])

    # Positive control: the probe CAN see a second run.  A real edit of one
    # file is a different observation, so it takes its own run and its own
    # identity, and each identity keeps exactly one edge.
    edited_json = tmp_path / "edited.json"
    source = corpus / "pkg" / "c1.py"
    source.write_text(
        source.read_text("utf-8") + "\n\ndef gamma() -> int:\n    return 3\n",
        "utf-8",
    )
    run_store_cli(
        corpus, *_FULL_METRICS_ARGS, "--json", str(edited_json), store=store_path
    )
    edited_identity = report_run_identity(_report(edited_json))
    assert edited_identity != identity
    edited_edges = _edges(store_path, edited_identity)
    assert len(edited_edges) == 1
    assert edited_edges[0] != runs[0]
    assert edited_edges[0] in _published_runs(store_path)
