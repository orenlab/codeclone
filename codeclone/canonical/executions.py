# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The run store's execution registry: where a published run can be found
again by a process that did not publish it, and whether it still can.

One row per finalized EXECUTION (``run_executions``), keyed by the
execution's own identity -- the ``execution_event_id`` its producer minted
before it read a byte -- and never by the report's or the store's run id:
two executions of one report are two rows, exactly as they are two events
(RULING-2026-09-02).  A row names the store run its execution published
(``store_run_id``), the report identity that evaluated it, the checkout it
ran under, and carries the producer's execution overlay as opaque bytes
under a contract name the producer owns; the store proves the row's bytes
against their own digest before it hands them back, and interprets nothing
else.

Three properties are the registry's law (ruling 2026-10-12, recovery):

* **It is not a second truth.**  No fact of a run lives here: the run's
  facts are its membership, its id is its content address, the report's
  relation to it is the bridge edge.  The row is operational -- where to
  find the run and whether it can still be found.
* **Availability is never stored.**  Whether a registered run is available
  is read off the run row in the same snapshot as the record
  (:data:`EXECUTION_AVAILABLE` / :data:`EXECUTION_EXPIRED` /
  :data:`EXECUTION_NOT_PUBLISHED`), so "the registry says published, the
  snapshot is gone" cannot be represented at all -- not even after a
  collector of an older build, which knows nothing of this table, deleted
  the run.
* **A record outlives its run on purpose.**  The row addresses its run by
  content address, not by foreign key, so the collector can take the run
  and leave the record: a record whose run is gone IS the proof that the
  run was published, promised and then collected (``run_expired``), where
  no record proves nothing (``run_not_found``).  The witness has its own
  bound (:class:`RetentionWindow.max_execution_records`), after which the honest
  answer degrades to "not found".

The rows are immutable once written: a ``BEFORE UPDATE`` trigger refuses
every update inside SQLite itself, and the module owns no ``UPDATE``.
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from ..models import deadline_passed
from .errors import ExecutionRecordError, StoreIntegrityError

#: Domain of a record's digest: the row's identity columns, its contract
#: name and its overlay bytes.  The finalization time stays outside it --
#: when a promise was made is operational, never part of what was promised.
_RECORD_DIGEST_DOMAIN: Final = b"codeclone.run_store.execution_record.v1\x00"

#: A registered run the store still holds published.
EXECUTION_AVAILABLE: Final = "available"
#: A registered run the store no longer holds: the record survived it, and
#: is the proof that the run was published and then collected.
EXECUTION_EXPIRED: Final = "expired"
#: A registered run whose row is present and not published -- a staging row
#: of a later republication of the same content; never served.
EXECUTION_NOT_PUBLISHED: Final = "not_published"
EXECUTION_AVAILABILITIES: Final[frozenset[str]] = frozenset(
    {EXECUTION_AVAILABLE, EXECUTION_EXPIRED, EXECUTION_NOT_PUBLISHED}
)

_RECORD_COLUMNS: Final = (
    "execution_pk, execution_event_id, root, report_run_identity, "
    "store_run_id, record_contract, finalized_at, overlay, record_digest"
)

_HEX_DIGITS: Final = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRecord:
    """What one finalized execution states to the registry.

    ``root`` is the resolved checkout the execution ran under, as the
    producer spells it; ``overlay`` the producer's execution overlay under
    ``record_contract`` -- opaque to the store, proven by digest.
    """

    execution_event_id: str
    root: str
    report_run_identity: str
    store_run_id: str
    record_contract: str
    overlay: bytes

    def __post_init__(self) -> None:
        for name in (
            "execution_event_id",
            "root",
            "report_run_identity",
            "store_run_id",
            "record_contract",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ExecutionRecordError(f"an execution record needs its {name}")
        if not isinstance(self.overlay, bytes):
            raise ExecutionRecordError("an execution overlay is bytes")

    def digest(self) -> str:
        """The digest the row is proven against before its bytes are used."""
        hasher = hashlib.sha256(_RECORD_DIGEST_DOMAIN)
        for part in (
            self.execution_event_id,
            self.root,
            self.report_run_identity,
            self.store_run_id,
            self.record_contract,
        ):
            hasher.update(part.encode("utf-8"))
            hasher.update(b"\x00")
        hasher.update(self.overlay)
        return hasher.hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisteredExecution:
    """One record as the registry answers it: the record, when it was
    finalized, and whether its run is available NOW -- read in the same
    snapshot as the record."""

    record: ExecutionRecord
    finalized_at: int
    availability: str

    def __post_init__(self) -> None:
        if self.availability not in EXECUTION_AVAILABILITIES:
            raise ExecutionRecordError(
                f"unknown execution availability: {self.availability!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class RetentionWindow:
    """The registered runs a sweep keeps, and how long a record witnesses.

    ``max_runs`` -- the most recently registered runs held, at most;
    ``max_age_seconds`` -- no registered run is held past this age of its
    newest record, whatever its rank (a run leaves at whichever bound it
    reaches first); ``max_execution_records`` -- the newest records kept beyond those
    that make a held run findable, which is the bound of the expiry
    witness.  Leases, retention rows and heads hold runs by their own roots
    whatever the window says.
    """

    max_runs: int
    max_age_seconds: int
    max_execution_records: int

    def __post_init__(self) -> None:
        for name in ("max_runs", "max_age_seconds", "max_execution_records"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ExecutionRecordError(f"{name} must be a positive integer")


def insert_execution_record(
    cursor: sqlite3.Cursor, record: ExecutionRecord, *, finalized_at: int
) -> None:
    """Write one record inside the caller's finalization transaction.

    An execution finalized a second time is refused, typed, before SQLite's
    own ``UNIQUE`` would raise in its own words.
    """
    existing = cursor.execute(
        "SELECT 1 FROM run_executions WHERE execution_event_id = ?",
        (record.execution_event_id,),
    ).fetchone()
    if existing is not None:
        raise ExecutionRecordError(
            f"execution {record.execution_event_id!r} is already finalized; "
            "a record is immutable once written"
        )
    cursor.execute(
        "INSERT INTO run_executions (execution_event_id, root, "
        "report_run_identity, store_run_id, record_contract, finalized_at, "
        "overlay, record_digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.execution_event_id,
            record.root,
            record.report_run_identity,
            record.store_run_id,
            record.record_contract,
            finalized_at,
            record.overlay,
            record.digest(),
        ),
    )


def _proven_record(row: tuple[object, ...]) -> tuple[ExecutionRecord, int]:
    """One stored row as a record, proven against its own digest first."""
    overlay = row[7]
    if not isinstance(overlay, bytes):
        raise StoreIntegrityError(
            f"execution record {str(row[1])[:12]}… overlay is not stored as "
            "BLOB; its bytes cannot be proven against their digest"
        )
    record = ExecutionRecord(
        execution_event_id=str(row[1]),
        root=str(row[2]),
        report_run_identity=str(row[3]),
        store_run_id=str(row[4]),
        record_contract=str(row[5]),
        overlay=overlay,
    )
    if not hmac.compare_digest(record.digest(), str(row[8])):
        raise StoreIntegrityError(
            f"execution record {record.execution_event_id[:12]}… does not "
            "prove against its stored digest"
        )
    return record, int(str(row[6]))


def _availability(cursor: sqlite3.Cursor, store_run_id: str) -> str:
    row = cursor.execute(
        "SELECT published FROM runs WHERE run_id = ?", (store_run_id,)
    ).fetchone()
    if row is None:
        return EXECUTION_EXPIRED
    if int(row[0]) == 1:
        return EXECUTION_AVAILABLE
    return EXECUTION_NOT_PUBLISHED


def _registered(cursor: sqlite3.Cursor, row: tuple[object, ...]) -> RegisteredExecution:
    record, finalized_at = _proven_record(row)
    return RegisteredExecution(
        record=record,
        finalized_at=finalized_at,
        availability=_availability(cursor, record.store_run_id),
    )


def execution_by_id(
    cursor: sqlite3.Cursor, execution_event_id: str
) -> RegisteredExecution | None:
    """The record of one execution, or ``None`` when the registry holds none."""
    row = cursor.execute(
        f"SELECT {_RECORD_COLUMNS} FROM run_executions WHERE execution_event_id = ?",
        (execution_event_id,),
    ).fetchone()
    if row is None:
        return None
    return _registered(cursor, row)


def newest_execution_for_report(
    cursor: sqlite3.Cursor, *, root: str, run_id: str
) -> RegisteredExecution | None:
    """The newest record of the report ``run_id`` names under ``root``.

    ``run_id`` is a report identity or a prefix of one, spelled in lowercase
    hex.  A prefix that names the records of two reports under ``root`` is
    refused, never resolved to the first; a root other than the record's own
    finds nothing.  Among the records of one report the newest finalization
    answers -- the index a caller holding only the report's name can use;
    a caller that names its execution asks :func:`execution_by_id`.
    """
    if not run_id or not set(run_id) <= _HEX_DIGITS:
        return None
    rows = cursor.execute(
        f"SELECT {_RECORD_COLUMNS} FROM run_executions "
        "WHERE root = ? AND substr(report_run_identity, 1, ?) = ? "
        "ORDER BY execution_pk DESC",
        (root, len(run_id), run_id),
    ).fetchall()
    identities = sorted({str(row[3]) for row in rows})
    if len(identities) > 1:
        spelled = ", ".join(identity[:12] for identity in identities)
        raise ExecutionRecordError(
            f"run id prefix {run_id!r} is ambiguous under {root}: it names "
            f"{len(identities)} reports ({spelled}); pass more of the run id"
        )
    if not rows:
        return None
    return _registered(cursor, rows[0])


def window_run_pks(
    cursor: sqlite3.Cursor, window: RetentionWindow | None, *, now: int
) -> set[int]:
    """The published runs the retention window holds.

    Registered runs ranked by their newest record (the finalization order),
    counting only runs the store still holds published; the newest
    ``max_runs`` are held unless their newest record is past
    ``max_age_seconds`` -- one deadline law, ``deadline_passed``.
    """
    if window is None:
        return set()
    rows = cursor.execute(
        "SELECT r.run_pk, e.finalized_at FROM run_executions e "
        "JOIN runs r ON r.run_id = e.store_run_id AND r.published = 1 "
        "ORDER BY e.execution_pk DESC"
    ).fetchall()
    ranked: dict[int, int] = {}
    for run_pk, finalized_at in rows:
        ranked.setdefault(int(run_pk), int(finalized_at))
    newest = list(ranked.items())[: window.max_runs]
    return {
        run_pk
        for run_pk, finalized_at in newest
        if not deadline_passed(finalized_at + window.max_age_seconds, now)
    }


def _doomed_records(
    rows: Iterable[tuple[object, ...]],
    *,
    held_run_ids: frozenset[str],
    max_execution_records: int,
) -> list[int]:
    """The record pks a sweep deletes: every record that is neither among
    the newest ``max_execution_records`` nor the newest record of a report whose run
    survives the sweep (the one a caller holding the report's name finds)."""
    newest_of_report: set[tuple[str, str]] = set()
    doomed: list[int] = []
    for rank, (execution_pk, root, report, store_run_id) in enumerate(rows):
        key = (str(root), str(report))
        first = key not in newest_of_report
        newest_of_report.add(key)
        findable = first and str(store_run_id) in held_run_ids
        if rank >= max_execution_records and not findable:
            doomed.append(int(str(execution_pk)))
    return doomed


def sweep_execution_records(
    cursor: sqlite3.Cursor, window: RetentionWindow | None
) -> int:
    """Delete the records the window no longer keeps; return how many.

    Run inside the sweep's transaction AFTER its victims left, so "the run
    survives" is read off the rows that do.  Without a window nothing is
    swept: the registry is only bounded by a policy that names its bound.
    """
    if window is None:
        return 0
    held_run_ids = frozenset(
        str(row[0]) for row in cursor.execute("SELECT run_id FROM runs")
    )
    rows = cursor.execute(
        "SELECT execution_pk, root, report_run_identity, store_run_id "
        "FROM run_executions ORDER BY execution_pk DESC"
    ).fetchall()
    doomed = _doomed_records(
        rows,
        held_run_ids=held_run_ids,
        max_execution_records=window.max_execution_records,
    )
    cursor.executemany(
        "DELETE FROM run_executions WHERE execution_pk = ?",
        [(execution_pk,) for execution_pk in doomed],
    )
    return len(doomed)


__all__ = [
    "EXECUTION_AVAILABILITIES",
    "EXECUTION_AVAILABLE",
    "EXECUTION_EXPIRED",
    "EXECUTION_NOT_PUBLISHED",
    "ExecutionRecord",
    "RegisteredExecution",
    "RetentionWindow",
    "execution_by_id",
    "insert_execution_record",
    "newest_execution_for_report",
    "sweep_execution_records",
    "window_run_pks",
]
