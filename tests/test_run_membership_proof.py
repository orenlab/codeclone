# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A served run is proven whole by its object ids, once per process.

The bounded reads behind the run summary, the patch contract and the blast
radius prove every row they read against its content address, and could
not prove what only the whole run can: that the run still has exactly the
members it was published with.  ``canonical.store.prove_run_membership``
proves it without decoding a payload of the run -- the member ids streamed
in content-address order reproduce the membership digest, the analyzed
files reproduce the scope receipt, the run id recomputes -- once per
process per store file and run, and the door runs it before the first fact
of a run is read.  Pinned here, each refusal on its own population (a copy
of a published store with one thing changed), and the cost bound: the ids
come off two covering indexes, sorted by the index, never by SQLite.
"""

from __future__ import annotations

import shutil
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from codeclone.api.run_store_serving import (
    RunStoreServingOutcome,
    forget_served_facts,
    read_run_store_blast_radius_facts,
    read_run_store_patch_run,
    read_run_store_summary,
)
from codeclone.canonical import store as store_module
from codeclone.canonical.errors import StoreIntegrityError
from codeclone.canonical.store import (
    RunStore,
    forget_proven_memberships,
    prove_run_membership,
)
from tests._patch_contract_serving import CYCLE_BUILDERS, shared_cycles
from tests._run_summary_serving import (
    RUN_SUMMARY_POPULATIONS,
    SummaryPopulation,
    serving_environment,
    shared_populations,
)

_DOORS: dict[str, Callable[..., tuple[object | None, RunStoreServingOutcome]]] = {
    "run_summary": read_run_store_summary,
    "patch_run": read_run_store_patch_run,
    "blast_radius": read_run_store_blast_radius_facts,
}


@pytest.fixture(autouse=True)
def _cold_process() -> Iterator[None]:
    forget_proven_memberships()
    forget_served_facts()
    yield
    forget_proven_memberships()
    forget_served_facts()


@pytest.fixture
def executed() -> Iterator[list[str]]:
    """Every statement the stores opened in a test execute."""
    seen: list[str] = []
    original = RunStore._open_connection

    def _tracing(self: RunStore, *, create: bool, fresh: bool) -> None:
        original(self, create=create, fresh=fresh)
        self._connection.set_trace_callback(seen.append)

    patch = pytest.MonkeyPatch()
    patch.setattr(RunStore, "_open_connection", _tracing)
    yield seen
    patch.undo()


def _id_streams(statements: list[str]) -> int:
    return sum(
        "CROSS JOIN run_members m" in sql
        and "ORDER BY o.object_id" in sql
        and "payload" not in sql
        for sql in statements
    )


def _run_id(population: SummaryPopulation) -> str:
    link = population.record.execution.run_snapshot_link
    assert link is not None and link.store_run_id
    return link.store_run_id


def test_every_published_run_of_the_populations_proves_its_membership(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The streamed ids reproduce the digest the publisher wrote, on every
    run of the three suites -- the stream is the digest's own order."""
    populations = shared_populations(tmp_path_factory)
    runs: list[tuple[Path, str]] = [
        (populations[name].store_path, _run_id(populations[name]))
        for name in RUN_SUMMARY_POPULATIONS
    ]
    cycles = shared_cycles(tmp_path_factory)
    for name in CYCLE_BUILDERS:
        cycle = cycles[name]
        for record in (cycle.before, cycle.after):
            link = None if record is None else record.execution.run_snapshot_link
            if link is not None and link.store_run_id:
                runs.append((cycle.store_path, link.store_run_id))
    assert len(runs) == 50
    for path, run_id in runs:
        with RunStore(path, create=False) as store:
            prove_run_membership(store, run_id)
            run_pk = int(
                store._connection.execute(
                    "SELECT run_pk FROM runs WHERE run_id = ?", (run_id,)
                ).fetchone()[0]
            )
            ids = [
                store_module._address_hex(row[0])
                for row in store._connection.execute(
                    "SELECT o.object_id FROM run_members m JOIN objects o "
                    "ON o.object_pk = m.object_pk WHERE m.run_pk = ?",
                    (run_pk,),
                )
            ]
            assert store_module._streamed_membership_digest(
                store._connection, run_pk
            ) == store_module._membership_digest(ids)


def _tampered(
    population: SummaryPopulation,
    directory: Path,
    family: str,
    *,
    reseal: bool,
) -> Path:
    """A copy of the population's store whose run lost one member of
    ``family``; ``reseal`` rewrites the stored membership digest to the
    remaining members, so only the later proofs can see the loss."""
    copy = directory / f"{population.name}-{family}-{reseal}.sqlite3"
    shutil.copy(population.store_path, copy)
    run_id = _run_id(population)
    with sqlite3.connect(copy) as raw:
        run_pk = raw.execute(
            "SELECT run_pk FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        victim = raw.execute(
            "SELECT MIN(m.object_pk) FROM run_members m "
            "JOIN objects o ON o.object_pk = m.object_pk "
            "JOIN families f ON f.family_pk = o.family_pk "
            "WHERE m.run_pk = ? AND f.family = ?",
            (run_pk, family),
        ).fetchone()[0]
        assert victim is not None, family
        raw.execute(
            "DELETE FROM run_members WHERE run_pk = ? AND object_pk = ?",
            (run_pk, victim),
        )
        if reseal:
            ids = [
                bytes(row[0]).hex()
                for row in raw.execute(
                    "SELECT o.object_id FROM run_members m JOIN objects o "
                    "ON o.object_pk = m.object_pk WHERE m.run_pk = ?",
                    (run_pk,),
                )
            ]
            raw.execute(
                "UPDATE runs SET membership_digest = ? WHERE run_pk = ?",
                (store_module._membership_digest(ids), run_pk),
            )
    raw.close()
    return copy


def _ask(
    population: SummaryPopulation, kind: str, store: Path
) -> tuple[object | None, RunStoreServingOutcome]:
    record = population.record
    with serving_environment(store, serve_from="run_store"):
        return _DOORS[kind](root=record.root, link=record.execution.run_snapshot_link)


@pytest.mark.parametrize("kind", list(_DOORS))
def test_a_member_removed_since_publication_is_refused_and_memory_answers(
    tmp_path_factory: pytest.TempPathFactory, tmp_path: Path, kind: str
) -> None:
    """One membership row of a family none of the three readings reads is
    gone: no bounded read could see it, the id proof does -- even after the
    original store's run was proven and served by this process."""
    population = shared_populations(tmp_path_factory)["trusted"]
    facts, served = _ask(population, kind, population.store_path)
    assert facts is not None and served.reason == "served"
    copy = _tampered(population, tmp_path, "unit_span", reseal=False)
    for _attempt in range(2):  # a refusal is never remembered as a proof
        answer, refused = _ask(population, kind, copy)
        assert answer is None
        assert refused.reason == "integrity", refused
        assert "membership does not reproduce" in refused.detail


@pytest.mark.parametrize(
    ("family", "refusal"),
    [
        ("analyzed_file", "scope receipt does not reproduce"),
        ("unit_span", "identity does not recompute"),
    ],
    ids=["scope_receipt", "run_identity"],
)
def test_each_later_proof_refuses_what_the_membership_digest_was_made_to_hide(
    tmp_path_factory: pytest.TempPathFactory,
    tmp_path: Path,
    family: str,
    refusal: str,
) -> None:
    """The membership digest rewritten to the remaining members: an
    analyzed file gone is the scope receipt's to refuse, any other member
    gone the run identity's."""
    population = shared_populations(tmp_path_factory)["trusted"]
    copy = _tampered(population, tmp_path, family, reseal=True)
    with (
        RunStore(copy, create=False) as store,
        pytest.raises(StoreIntegrityError, match=refusal),
    ):
        prove_run_membership(store, _run_id(population))


def test_a_run_is_proven_once_per_process_per_store_file(
    tmp_path_factory: pytest.TempPathFactory, tmp_path: Path, executed: list[str]
) -> None:
    population = shared_populations(tmp_path_factory)["trusted"]
    run_id = _run_id(population)
    for _attempt in range(3):
        with RunStore(population.store_path, create=False) as store:
            prove_run_membership(store, run_id)
    assert _id_streams(executed) == 1
    copy = tmp_path / "copy.sqlite3"
    shutil.copy(population.store_path, copy)
    with RunStore(copy, create=False) as store:
        prove_run_membership(store, run_id)
    assert _id_streams(executed) == 2


def test_the_ids_come_off_covering_indexes_in_their_own_order(
    tmp_path_factory: pytest.TempPathFactory, executed: list[str]
) -> None:
    """The executed plan: the run by its key, the namespace's ids through
    the objects' covering key, each membership by one covering probe -- no
    sort of SQLite's own, no table row, no payload."""
    population = shared_populations(tmp_path_factory)["trusted"]
    with RunStore(population.store_path, create=False) as store:
        prove_run_membership(store, _run_id(population))
        (stream,) = [
            sql
            for sql in executed
            if "ORDER BY o.object_id" in sql and "payload" not in sql
        ]
        plan = [
            str(row[3])
            for row in store._connection.execute(f"EXPLAIN QUERY PLAN {stream}")
        ]
    assert not any("TEMP B-TREE" in line for line in plan), plan
    assert any(
        line.startswith("SEARCH o USING COVERING INDEX sqlite_autoindex_objects_1")
        for line in plan
    ), plan
    assert any(
        line.startswith("SEARCH m USING COVERING INDEX idx_run_members_object")
        for line in plan
    ), plan
