# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Cost shape of the trajectory rebuild's audit reads.

These pin a *slope*, never a wall-clock: the projection walks the audit trail
one workflow at a time, so an implementation that re-establishes a read-only
connection per workflow is linear in connections and in setup SQL. The
invariants below stay true for any per-workflow cost and fail the moment an
open moves back inside the loop.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from codeclone.audit.events import repo_root_digest
from codeclone.audit.reader import (
    open_audit_event_core_reader,
    read_audit_event_core_records,
)
from codeclone.audit.schema import open_audit_db_readonly
from codeclone.memory.models import MemoryProject
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore

from .memory_fixtures import memory_store, seed_trajectory_audit_workflow

# Points spread over two orders of magnitude. 200 is the size of the real
# controller audit trail, so it is the one point that is not extrapolation.
WORKFLOW_SERIES = (1, 2, 5, 10, 20, 40, 200)


@dataclass(frozen=True, slots=True)
class AuditSqlCost:
    """Connections and statements one operation spent on the audit database."""

    connections: int
    setup: int
    data: int


class AuditSqlMeter:
    """Trace every statement on every connection opened against ``db_path``.

    Statements are split into *setup* (the fixed statements
    ``open_audit_db_readonly`` runs to establish and validate a connection) and
    *data* (everything else). The setup vocabulary is measured, not declared:
    see :func:`_measure_connection_setup`.
    """

    def __init__(self, db_path: Path, setup_statements: Sequence[str]) -> None:
        self._target = str(db_path.resolve())
        self._setup = tuple(setup_statements)
        self._real = sqlite3.connect
        self.connections = 0
        self.statements: list[str] = []

    def __enter__(self) -> AuditSqlMeter:
        real = self._real

        def wrapper(*args: Any, **kwargs: Any) -> sqlite3.Connection:
            conn: sqlite3.Connection = real(*args, **kwargs)
            opened = str(args[0]) if args else str(kwargs.get("database", ""))
            if self._target in opened:
                self.connections += 1
                conn.set_trace_callback(self.statements.append)
            return conn

        sqlite3.connect = wrapper  # type: ignore[assignment]
        return self

    def __exit__(self, *exc: object) -> None:
        sqlite3.connect = self._real

    def cost(self) -> AuditSqlCost:
        setup = sum(1 for sql in self.statements if sql in self._setup)
        return AuditSqlCost(
            connections=self.connections,
            setup=setup,
            data=len(self.statements) - setup,
        )


def _measure_connection_setup(db_path: Path) -> tuple[str, ...]:
    """Measure what establishing one read-only audit connection costs.

    Derived by observation rather than written down as a literal, so the
    O(1)-setup pin re-derives its own basis: adding or removing a connection
    PRAGMA moves this and the assertions keep their meaning.
    """
    meter = AuditSqlMeter(db_path, ())
    with meter:
        open_audit_db_readonly(db_path).close()
    assert meter.connections == 1
    return tuple(meter.statements)


def _seed_trail(root: Path, audit_db: Path, count: int) -> None:
    for index in range(count):
        seed_trajectory_audit_workflow(
            audit_db=audit_db,
            root=root,
            intent_id=f"intent-cost-{index:04d}",
            scope_path=f"pkg/mod_{index:04d}.py",
        )


GAP_EVENT_ID = "evt-cost-gap-row"
GAP_WORKFLOW_ID = "intent:cost-gap-row"


def _seed_unprojectable_row(audit_db: Path, digest: str) -> None:
    """Add one row that carries a workflow but no event-core digest.

    Without it every row in the trail satisfies every filter, so dropping a
    filter would be observationally equivalent and the pins below would hold
    for an implementation that had stopped filtering at all.
    """
    conn = sqlite3.connect(str(audit_db))
    try:
        conn.execute(
            "INSERT INTO controller_events (event_id, event_type, severity, "
            "created_at_utc, repo_root_digest, agent_pid, status, workflow_id, "
            "event_core_json, event_core_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                GAP_EVENT_ID,
                "intent.declared",
                "info",
                "2026-01-01T00:00:00Z",
                digest,
                1,
                "active",
                GAP_WORKFLOW_ID,
                "{}",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _watermark_for(audit_db: Path, digest: str, changed: int) -> int:
    """Return the watermark id that leaves exactly ``changed`` workflows new."""
    conn = sqlite3.connect(f"file:{audit_db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT MAX(id) AS newest FROM controller_events "
            "WHERE repo_root_digest = ? AND workflow_id IS NOT NULL "
            "AND workflow_id != '' AND event_core_json IS NOT NULL "
            "AND event_core_sha256 IS NOT NULL "
            "GROUP BY workflow_id ORDER BY newest DESC",
            (digest,),
        ).fetchall()
    finally:
        conn.close()
    return 0 if changed >= len(rows) else int(rows[changed][0])


def _records_digest(records: Sequence[object]) -> str:
    accumulator = hashlib.sha256()
    for record in records:
        accumulator.update(repr(record).encode("utf-8"))
        accumulator.update(b"\x00")
    return accumulator.hexdigest()


@pytest.fixture(scope="module")
def cost_trail(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[Path, Path, str, MemoryProject, SqliteEngineeringMemoryStore]]:
    """One audit trail of ``max(WORKFLOW_SERIES)`` workflows, built once."""
    tmp_path = tmp_path_factory.mktemp("trajectory-cost")
    with memory_store(tmp_path) as (root, project, store, _db):
        audit_db = tmp_path / "audit.sqlite3"
        _seed_trail(root, audit_db, max(WORKFLOW_SERIES))
        digest = repo_root_digest(root.resolve())
        _seed_unprojectable_row(audit_db, digest)
        yield audit_db, root, digest, project, store


def test_incremental_rebuild_audit_cost_shape(
    cost_trail: tuple[Path, Path, str, MemoryProject, SqliteEngineeringMemoryStore],
) -> None:
    """One connection, constant setup, one data query per workflow."""
    audit_db, root, digest, project, store = cost_trail
    setup_statements = _measure_connection_setup(audit_db)

    costs: dict[int, AuditSqlCost] = {}
    for workflows in WORKFLOW_SERIES:
        # Resolved before metering: the meter counts the rebuild, not the setup.
        watermark = _watermark_for(audit_db, digest, workflows)
        meter = AuditSqlMeter(audit_db, setup_statements)
        with meter:
            result = store.rebuild_trajectories_incremental(
                project=project,
                root_path=root,
                audit_db_path=audit_db,
                after_event_core_id=watermark,
            )
        assert result.run.workflows_seen == workflows
        # The seeded unprojectable row is counted, never projected: proof the
        # O(1) gap query ran and that the event-core filters rejected it.
        assert result.run.legacy_event_count == 1
        costs[workflows] = meter.cost()

    # Connections stay at one however many workflows are re-projected. An open
    # inside the loop makes this grow with N and is the defect this pins.
    assert {cost.connections for cost in costs.values()} == {1}

    # Setup is whatever one connection costs, re-derived above -- not a literal.
    assert {cost.setup for cost in costs.values()} == {len(setup_statements)}

    # Slope exactly one data query per additional workflow, over every
    # consecutive pair. This holds for any fixed intercept, so it survives
    # honest changes to the O(1) queries and dies on a per-workflow one.
    series = sorted(costs)
    slopes = {
        (costs[hi].data - costs[lo].data) / (hi - lo) for lo, hi in pairwise(series)
    }
    assert slopes == {1.0}


def _oracle_rows(audit_db: Path, digest: str) -> list[tuple[object, ...]]:
    """Expected (workflow, sequence, event) triples, read without production SQL.

    An oracle built from the session under test would move with it, so this
    query is written out here: it is what makes the ordering and filter pins
    fail instead of agreeing with a corrupted implementation.
    """
    conn = sqlite3.connect(f"file:{audit_db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT workflow_id, id, event_id FROM controller_events "
            "WHERE repo_root_digest = ? AND workflow_id IS NOT NULL "
            "AND workflow_id != '' AND event_core_json IS NOT NULL "
            "AND event_core_sha256 IS NOT NULL "
            "ORDER BY workflow_id ASC, id ASC",
            (digest,),
        ).fetchall()
    finally:
        conn.close()


def test_session_records_match_an_independent_oracle(
    cost_trail: tuple[Path, Path, str, MemoryProject, SqliteEngineeringMemoryStore],
) -> None:
    """Content, filters and order of the session read, against plain SQL."""
    audit_db, _root, digest, _project, _store = cost_trail
    with open_audit_event_core_reader(audit_db) as session:
        assert session is not None
        records = session.event_core_records(repo_root_digest=digest)

    expected = _oracle_rows(audit_db, digest)
    assert expected, "oracle must be non-empty or it pins nothing"
    assert GAP_EVENT_ID not in {event_id for _wf, _id, event_id in expected}
    assert [
        (record.workflow_id, record.audit_sequence, record.event_id)
        for record in records
    ] == expected


def test_session_reads_are_byte_identical_to_per_call_reads(
    cost_trail: tuple[Path, Path, str, MemoryProject, SqliteEngineeringMemoryStore],
) -> None:
    """Per-workflow session reads reassemble the whole trail, unchanged."""
    audit_db, _root, digest, _project, _store = cost_trail
    with open_audit_event_core_reader(audit_db) as session:
        assert session is not None
        workflow_ids = session.workflow_ids_with_events_after(
            repo_root_digest=digest, after_id=0
        )
        per_workflow = [
            record
            for workflow_id in workflow_ids
            for record in session.event_core_records(
                repo_root_digest=digest, workflow_id=workflow_id
            )
        ]
        session_unfiltered = session.event_core_records(repo_root_digest=digest)

    per_call_unfiltered = read_audit_event_core_records(
        db_path=audit_db, repo_root_digest=digest
    )

    assert len(workflow_ids) == max(WORKFLOW_SERIES)
    assert per_workflow == list(session_unfiltered)
    assert list(per_call_unfiltered) == list(session_unfiltered)
    assert _records_digest(session_unfiltered) == _records_digest(per_call_unfiltered)
