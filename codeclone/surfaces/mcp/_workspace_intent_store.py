# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from ...config.intent_registry import (
    IntentRegistryConfig,
    resolve_intent_registry_config,
)
from ...report.meta import current_report_timestamp_utc
from ...utils.json_io import write_json_document_atomically
from ...workspace_intent.contract import (
    WorkspaceDocumentRead,
    WorkspaceDocumentReadKind,
    WorkspaceIntentRecord,
)
from ...workspace_intent.lifecycle import (
    WorkspaceIntentStatus,
    gc_status_for_reason,
    is_terminal_workspace_intent_status,
)
from ...workspace_intent.models import (
    WorkspaceIntentRowModel,
    read_workspace_payload,
    signed_payload_dict_from_record,
    signed_payload_json_from_record,
)
from ...workspace_intent.paths import (
    intent_id_from_filename,
    intent_path,
    is_safe_intent_id,
    read_payload,
    record_sort_key,
    registry_dir,
    registry_files,
    safe_remove_own_intent,
    unlink,
)
from ...workspace_intent.schema import open_intent_registry_db
from ._workspace_intent_registry_lock import workspace_registry_lock
from ._workspace_intent_staleness import gc_removal_reason

_STORE_CACHE: dict[
    tuple[str, str, str], FileWorkspaceIntentStore | SqliteWorkspaceIntentStore
] = {}
_FILE_STORE_LOCKS: dict[str, threading.Lock] = {}
_STORE_CACHE_LOCK = threading.Lock()
_FILE_STORE_LOCKS_LOCK = threading.Lock()


def _file_store_process_lock(root: Path) -> threading.Lock:
    key = str(root.resolve())
    with _FILE_STORE_LOCKS_LOCK:
        lock = _FILE_STORE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _FILE_STORE_LOCKS[key] = lock
        return lock


@contextmanager
def registry_transaction(
    store: FileWorkspaceIntentStore | SqliteWorkspaceIntentStore,
) -> Iterator[None]:
    """Cross-process and in-process lock for registry read/write transactions."""
    with workspace_registry_lock(store.registry_lock_path), store.in_process_lock():
        yield


@dataclass(frozen=True, slots=True)
class FileWorkspaceIntentStore:
    root: Path

    @property
    def backend(self) -> str:
        return "file"

    @property
    def storage_path(self) -> Path:
        return registry_dir(self.root)

    @property
    def registry_lock_path(self) -> Path:
        return registry_dir(self.root) / ".registry.lock"

    @contextmanager
    def in_process_lock(self) -> Iterator[None]:
        with _file_store_process_lock(self.root):
            yield

    def write(self, record: WorkspaceIntentRecord) -> bool:
        with registry_transaction(self):
            return self.write_unlocked(record)

    def write_unlocked(self, record: WorkspaceIntentRecord) -> bool:
        path = intent_path(
            root=self.root,
            pid=record.agent_pid,
            start_epoch=record.agent_start_epoch,
            intent_id=record.intent_id,
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json_document_atomically(
                path=path,
                document=signed_payload_dict_from_record(record),
                sort_keys=True,
                trailing_newline=True,
            )
        except OSError:
            return False
        return True

    def list_records(self) -> tuple[WorkspaceIntentRecord, ...]:
        return self.list_records_current()

    def list_records_raw(self) -> tuple[WorkspaceIntentRecord, ...]:
        with self.in_process_lock():
            return self._all_valid_records_unlocked()

    def list_records_current(self) -> tuple[WorkspaceIntentRecord, ...]:
        with registry_transaction(self):
            _lazy_close_eligible_records_unlocked(self)
            return self._active_records_unlocked()

    def list_records_for_hygiene(self) -> tuple[WorkspaceIntentRecord, ...]:
        with registry_transaction(self):
            return self._all_valid_records_unlocked()

    def _all_valid_records_unlocked(self) -> tuple[WorkspaceIntentRecord, ...]:
        records = [record for _, record in self._valid_entries_unlocked()]
        return tuple(sorted(records, key=record_sort_key))

    def _active_records_unlocked(self) -> tuple[WorkspaceIntentRecord, ...]:
        # No sort: ``_all_valid_records_unlocked`` is this store's one owner of
        # queue order and a filter preserves it. Re-sorting here made a second
        # owner of the same law, and a broken owner was silently corrected
        # instead of caught.
        return tuple(
            record
            for record in self._all_valid_records_unlocked()
            if not is_terminal_workspace_intent_status(record.status)
        )

    def find(self, intent_id: str) -> WorkspaceIntentRecord | None:
        with registry_transaction(self):
            _lazy_close_eligible_records_unlocked(self)
            return self.find_raw_unlocked(intent_id)

    def find_current_unlocked(self, intent_id: str) -> WorkspaceIntentRecord | None:
        _lazy_close_eligible_records_unlocked(self)
        return self.find_raw_unlocked(intent_id)

    def find_raw_unlocked(self, intent_id: str) -> WorkspaceIntentRecord | None:
        matches = [
            record
            for _, record in self._valid_entries_unlocked()
            if record.intent_id == intent_id
            and not is_terminal_workspace_intent_status(record.status)
        ]
        if not matches:
            return None
        return sorted(matches, key=record_sort_key)[-1]

    def find_raw(self, intent_id: str) -> WorkspaceIntentRecord | None:
        with registry_transaction(self):
            return self.find_raw_unlocked(intent_id)

    def remove(self, *, pid: int, start_epoch: int, intent_id: str) -> bool:
        with registry_transaction(self):
            return safe_remove_own_intent(
                root=self.root,
                pid=pid,
                start_epoch=start_epoch,
                intent_id=intent_id,
            )

    def gc(self) -> dict[str, object]:
        with registry_transaction(self):
            result = _gc_eligible_records_unlocked(self)
            remaining = len(self._active_records_unlocked())
            return {
                **result.to_gc_fragment(),
                "retention_purged": 0,
                "remaining": remaining,
            }

    def _valid_entries_unlocked(self) -> tuple[tuple[Path, WorkspaceIntentRecord], ...]:
        entries: list[tuple[Path, WorkspaceIntentRecord]] = []
        for path in registry_files(self.root):
            payload = read_payload(path)
            record = _record_from_json(payload) if payload is not None else None
            if record is not None:
                entries.append((path, record))
        return tuple(entries)


class SqliteWorkspaceIntentStore:
    def __init__(self, *, db_path: Path, retention_days: int) -> None:
        self._db_path = db_path
        self._retention_days = retention_days
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with workspace_registry_lock(self.registry_lock_path):
            self._conn = open_intent_registry_db(db_path)

    @property
    def backend(self) -> str:
        return "sqlite"

    @property
    def storage_path(self) -> Path:
        return self._db_path

    @property
    def registry_lock_path(self) -> Path:
        return Path(f"{self._db_path}.lock")

    @contextmanager
    def in_process_lock(self) -> Iterator[None]:
        with self._lock:
            yield

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def write(self, record: WorkspaceIntentRecord) -> bool:
        with registry_transaction(self):
            return self.write_unlocked(record)

    def write_unlocked(self, record: WorkspaceIntentRecord) -> bool:
        try:
            payload_json = signed_payload_json_from_record(record)
            now_text = current_report_timestamp_utc()
            closed_at = (
                now_text if is_terminal_workspace_intent_status(record.status) else None
            )
            row = WorkspaceIntentRowModel.from_record_fields(
                agent_pid=record.agent_pid,
                agent_start_epoch=record.agent_start_epoch,
                intent_id=record.intent_id,
                declared_at_utc=record.declared_at_utc,
                payload_json=payload_json,
                updated_at_utc=now_text,
                closed_at_utc=closed_at,
            )
        except (TypeError, ValueError):
            return False
        try:
            self._conn.execute(
                """
                INSERT INTO workspace_intents(
                    agent_pid,
                    agent_start_epoch,
                    intent_id,
                    declared_at_utc,
                    payload_json,
                    closed_at_utc,
                    updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_pid, agent_start_epoch, intent_id) DO UPDATE SET
                    declared_at_utc = excluded.declared_at_utc,
                    payload_json = excluded.payload_json,
                    updated_at_utc = excluded.updated_at_utc,
                    closed_at_utc = excluded.closed_at_utc
                """,
                (
                    row.agent_pid,
                    row.agent_start_epoch,
                    row.intent_id,
                    row.declared_at_utc,
                    row.payload_json,
                    row.closed_at_utc,
                    row.updated_at_utc,
                ),
            )
            self._conn.commit()
        except sqlite3.Error:
            return False
        return True

    def list_records(self) -> tuple[WorkspaceIntentRecord, ...]:
        return self.list_records_current()

    def list_records_raw(self) -> tuple[WorkspaceIntentRecord, ...]:
        with self.in_process_lock():
            return self._list_records_raw_unlocked()

    def list_records_current(self) -> tuple[WorkspaceIntentRecord, ...]:
        with registry_transaction(self):
            _lazy_close_eligible_records_unlocked(self)
            return self._active_records_unlocked()

    def list_records_for_hygiene(self) -> tuple[WorkspaceIntentRecord, ...]:
        with registry_transaction(self):
            return self._load_all_records_unlocked()

    def _list_records_raw_unlocked(self) -> tuple[WorkspaceIntentRecord, ...]:
        # No sort: ``_load_all_records_unlocked`` owns the order here, and a
        # filter preserves it.
        return tuple(
            record
            for record in self._load_all_records_unlocked()
            if not is_terminal_workspace_intent_status(record.status)
        )

    def _active_records_unlocked(self) -> tuple[WorkspaceIntentRecord, ...]:
        return self._list_records_raw_unlocked()

    def find(self, intent_id: str) -> WorkspaceIntentRecord | None:
        with registry_transaction(self):
            _lazy_close_eligible_records_unlocked(self)
            return self.find_raw_unlocked(intent_id)

    def find_current_unlocked(self, intent_id: str) -> WorkspaceIntentRecord | None:
        _lazy_close_eligible_records_unlocked(self)
        return self.find_raw_unlocked(intent_id)

    def find_raw_unlocked(self, intent_id: str) -> WorkspaceIntentRecord | None:
        records = [
            record
            for record in self._load_all_records_unlocked()
            if record.intent_id == intent_id
            and not is_terminal_workspace_intent_status(record.status)
        ]
        if not records:
            return None
        return sorted(records, key=record_sort_key)[-1]

    def find_raw(self, intent_id: str) -> WorkspaceIntentRecord | None:
        with registry_transaction(self):
            return self.find_raw_unlocked(intent_id)

    def remove(self, *, pid: int, start_epoch: int, intent_id: str) -> bool:
        if not is_safe_intent_id(intent_id):
            return False
        with registry_transaction(self):
            record = self._fetch_record_unlocked(
                pid=pid,
                start_epoch=start_epoch,
                intent_id=intent_id,
            )
            if record is None or is_terminal_workspace_intent_status(record.status):
                return False
            return self.write_unlocked(
                replace(record, status=WorkspaceIntentStatus.CLEAN.value),
            )

    def gc(self) -> dict[str, object]:
        with registry_transaction(self):
            result = _gc_eligible_records_unlocked(self)
            retention_purged = self._purge_retention_rows_unlocked()
            remaining = len(self._active_records_unlocked())
            return {
                **result.to_gc_fragment(),
                "retention_purged": retention_purged,
                "remaining": remaining,
            }

    def iter_rows(self) -> tuple[tuple[int, int, str, str], ...]:
        try:
            rows = self._conn.execute(
                """
                SELECT agent_pid, agent_start_epoch, intent_id, payload_json
                FROM workspace_intents
                ORDER BY declared_at_utc, agent_pid, intent_id
                """
            ).fetchall()
        except sqlite3.Error:
            return ()
        return tuple(
            (int(agent_pid), int(agent_start_epoch), str(intent_id), str(payload_json))
            for agent_pid, agent_start_epoch, intent_id, payload_json in rows
        )

    def delete_row_unlocked(
        self,
        *,
        pid: int,
        start_epoch: int,
        intent_id: str,
    ) -> bool:
        try:
            cursor = self._conn.execute(
                """
                DELETE FROM workspace_intents
                WHERE agent_pid = ? AND agent_start_epoch = ? AND intent_id = ?
                """,
                (pid, start_epoch, intent_id),
            )
            self._conn.commit()
        except sqlite3.Error:
            return False
        return cursor.rowcount > 0

    def _load_all_records_unlocked(self) -> tuple[WorkspaceIntentRecord, ...]:
        # No ORDER BY: the sort at the end of this method owns the sequence.
        # Asking SQL for it too applied the same law twice, and measurably
        # worse -- ordering by the declared index turns a plain table scan into
        # an index scan that must still fetch ``payload_json`` per row, for a
        # query with no LIMIT that materialises everything anyway.
        try:
            rows = self._conn.execute(
                """
                SELECT payload_json
                FROM workspace_intents
                """
            ).fetchall()
        except sqlite3.Error:
            return ()
        records = tuple(
            record
            for record in (_record_from_json(row[0]) for row in rows)
            if record is not None
        )
        return tuple(sorted(records, key=record_sort_key))

    def _fetch_record_unlocked(
        self,
        *,
        pid: int,
        start_epoch: int,
        intent_id: str,
    ) -> WorkspaceIntentRecord | None:
        try:
            row = self._conn.execute(
                """
                SELECT payload_json
                FROM workspace_intents
                WHERE agent_pid = ? AND agent_start_epoch = ? AND intent_id = ?
                """,
                (pid, start_epoch, intent_id),
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        return _record_from_json(row[0])

    def _purge_retention_rows_unlocked(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_text = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        try:
            cursor = self._conn.execute(
                """
                DELETE FROM workspace_intents
                WHERE closed_at_utc IS NOT NULL AND closed_at_utc < ?
                """,
                (cutoff_text,),
            )
            self._conn.commit()
        except sqlite3.Error:
            return 0
        return int(cursor.rowcount)


WorkspaceIntentStore = FileWorkspaceIntentStore | SqliteWorkspaceIntentStore


def get_workspace_intent_store(root: Path) -> WorkspaceIntentStore:
    root_path = root.resolve()
    config = resolve_intent_registry_config(root_path)
    cache_key = (
        str(root_path),
        config.backend,
        str(config.storage_path),
    )
    with _STORE_CACHE_LOCK:
        cached = _STORE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        store = _build_store(root_path=root_path, config=config)
        _STORE_CACHE[cache_key] = store
        return store


def write_workspace_intent_with_existing(
    *,
    root: Path,
    record: WorkspaceIntentRecord,
) -> tuple[tuple[WorkspaceIntentRecord, ...], bool]:
    """Atomically snapshot active records and write ``record``.

    The returned existing records are the pre-write active registry view.  This
    closes the list-then-write race for declare conflict evaluation while
    preserving the current advisory conflict semantics.
    """

    store = get_workspace_intent_store(root)
    with registry_transaction(store):
        _lazy_close_eligible_records_unlocked(store)
        existing = store._active_records_unlocked()
        registered = store.write_unlocked(record)
    return existing, registered


def clear_workspace_intent_store_cache() -> None:
    with _STORE_CACHE_LOCK:
        stores = tuple(_STORE_CACHE.values())
        _STORE_CACHE.clear()
    for store in stores:
        close = getattr(store, "close", None)
        if callable(close):
            close()


def _build_store(
    *, root_path: Path, config: IntentRegistryConfig
) -> WorkspaceIntentStore:
    if config.backend == "file":
        return FileWorkspaceIntentStore(root=root_path)
    return SqliteWorkspaceIntentStore(
        db_path=config.storage_path,
        retention_days=config.retention_days,
    )


def _record_from_json(payload: object) -> WorkspaceIntentRecord | None:
    """The record, or nothing — for readers that only project live rows.

    Callers that DELETE on a miss must use :func:`read_workspace_payload`
    instead: this signature cannot say why the record is absent, and acting on
    an answer that cannot distinguish damaged bytes from a document written by
    a newer build is what destroyed live coordination state.
    """

    return read_workspace_payload(payload).record


def _sqlite_storage_key(*, pid: int, start_epoch: int, intent_id: str) -> str:
    return f"{pid}-{start_epoch}-{intent_id}.sqlite"


@dataclass(frozen=True, slots=True)
class LazyCloseResult:
    closed_ids: tuple[str, ...]
    closed_reasons: dict[str, str]
    corrupted_removed: tuple[str, ...]
    #: Rows left exactly as found because a writer signed them and this build
    #: cannot model them.  Reported, never silent: an operator whose intent
    #: stops answering is owed the difference between "removed" and "kept but
    #: not understood here".
    unreadable_retained: tuple[str, ...] = ()
    unreadable_retained_intent_ids: tuple[str, ...] = ()

    def to_gc_fragment(self) -> dict[str, object]:
        return {
            "removed": len(self.closed_ids),
            "removed_intent_ids": list(self.closed_ids),
            "removed_reasons": dict(self.closed_reasons),
            "corrupted_removed": len(self.corrupted_removed),
            "corrupted_filenames": list(self.corrupted_removed),
            "unreadable_retained": len(self.unreadable_retained),
            "unreadable_retained_filenames": list(self.unreadable_retained),
            "unreadable_retained_intent_ids": list(self.unreadable_retained_intent_ids),
        }


def lazy_close_eligible_records(
    store: WorkspaceIntentStore,
) -> LazyCloseResult:
    """Close/delete records where ``gc_removal_reason()`` is not None."""
    with registry_transaction(store):
        return _lazy_close_eligible_records_unlocked(store)


def _lazy_close_eligible_records_unlocked(
    store: WorkspaceIntentStore,
) -> LazyCloseResult:
    return _close_eligible_records_unlocked(store, for_lazy_close=True)


def _gc_eligible_records_unlocked(
    store: WorkspaceIntentStore,
) -> LazyCloseResult:
    return _close_eligible_records_unlocked(store, for_lazy_close=False)


def _close_eligible_records_unlocked(
    store: WorkspaceIntentStore,
    *,
    for_lazy_close: bool,
) -> LazyCloseResult:
    if isinstance(store, FileWorkspaceIntentStore):
        return _close_file_store(store, for_lazy_close=for_lazy_close)
    if isinstance(store, SqliteWorkspaceIntentStore):
        return _close_sqlite_store(store, for_lazy_close=for_lazy_close)
    raise TypeError(f"Unsupported workspace intent store: {type(store)!r}")


def lazy_close_eligible_records_unlocked(
    store: WorkspaceIntentStore,
) -> LazyCloseResult:
    return _lazy_close_eligible_records_unlocked(store)


class ScannedRegistryRow(NamedTuple):
    """One row a registry scan produced, named rather than positional.

    Owned here because it is produced and consumed here and crosses no ring
    boundary: this module is both the scanner and the only reader of a scan.
    The read outcome it carries is the opposite case -- that concept has
    consumers in two rings, so it is owned in
    :mod:`codeclone.workspace_intent.contract` and merely passes through.

    ``keyed_intent_id`` comes from the storage key and never from the
    document, because the key is the only identification available for a row
    this build cannot parse -- and naming the intent is how a refusal stops
    sounding like "no such intent".
    """

    storage_key: str
    keyed_intent_id: str | None
    read: WorkspaceDocumentRead


def _lazy_close_from_entries(
    entries: Iterable[ScannedRegistryRow],
    *,
    for_lazy_close: bool,
    remove_corrupted: Callable[[str], bool],
    close_active: Callable[[WorkspaceIntentRecord, str], bool],
) -> LazyCloseResult:
    """The one owner of removal on the read path, for both backends.

    A row this build cannot read is NOT removed unless its own integrity
    witness fails.  ``read.record is None`` used to be the whole condition,
    and it is true of two unrelated situations: bytes no writer produced, and
    a document a newer writer produced and signed.  Deleting on the second
    turned every forward-compatibility mistake in this subsystem into silent,
    unrecoverable loss of live coordination state.
    """

    closed_ids: list[str] = []
    closed_reasons: dict[str, str] = {}
    corrupted: list[str] = []
    retained: list[str] = []
    retained_ids: list[str] = []
    for storage_key, keyed_intent_id, read in entries:
        record = read.record
        if record is None:
            match read.kind:
                case WorkspaceDocumentReadKind.INCOMPATIBLE:
                    retained.append(storage_key)
                    if keyed_intent_id is not None:
                        retained_ids.append(keyed_intent_id)
                case WorkspaceDocumentReadKind.CORRUPT:
                    if remove_corrupted(storage_key):
                        corrupted.append(storage_key)
                case _:
                    # A scan cannot produce ABSENT, and a kind added later has
                    # no removal rule here. Either way the honest answer is to
                    # stop: falling through would silently pick one of the two
                    # opposite actions for a state nobody decided about.
                    raise ValueError(
                        f"Unhandled workspace document read kind: {read.kind.value!r}"
                    )
            continue
        reason = (
            None
            if is_terminal_workspace_intent_status(record.status)
            else gc_removal_reason(record, for_lazy_close=for_lazy_close)
        )
        if reason is not None and close_active(record, reason):
            closed_ids.append(record.intent_id)
            closed_reasons[record.intent_id] = reason
    return LazyCloseResult(
        closed_ids=tuple(closed_ids),
        closed_reasons=closed_reasons,
        corrupted_removed=tuple(corrupted),
        unreadable_retained=tuple(retained),
        unreadable_retained_intent_ids=tuple(retained_ids),
    )


def _file_entries(
    store: FileWorkspaceIntentStore,
) -> tuple[tuple[Path, ScannedRegistryRow], ...]:
    return tuple(
        (
            path,
            ScannedRegistryRow(
                storage_key=path.name,
                keyed_intent_id=intent_id_from_filename(path.name),
                read=read_workspace_payload(read_payload(path)),
            ),
        )
        for path in registry_files(store.root)
    )


def _close_file_store(
    store: FileWorkspaceIntentStore,
    *,
    for_lazy_close: bool,
) -> LazyCloseResult:
    scanned = _file_entries(store)
    path_by_name = {row.storage_key: path for path, row in scanned}
    path_by_intent = {
        row.read.record.intent_id: path
        for path, row in scanned
        if row.read.record is not None
    }
    return _lazy_close_from_entries(
        (row for _path, row in scanned),
        for_lazy_close=for_lazy_close,
        remove_corrupted=lambda key: unlink(path_by_name[key]),
        close_active=lambda record, _reason: unlink(path_by_intent[record.intent_id]),
    )


def _sqlite_entries(
    store: SqliteWorkspaceIntentStore,
) -> tuple[tuple[tuple[int, int, str], ScannedRegistryRow], ...]:
    return tuple(
        (
            (int(agent_pid), int(agent_start_epoch), str(intent_id)),
            ScannedRegistryRow(
                storage_key=_sqlite_storage_key(
                    pid=int(agent_pid),
                    start_epoch=int(agent_start_epoch),
                    intent_id=str(intent_id),
                ),
                keyed_intent_id=str(intent_id),
                read=read_workspace_payload(payload_json),
            ),
        )
        for agent_pid, agent_start_epoch, intent_id, payload_json in store.iter_rows()
    )


def _close_sqlite_store(
    store: SqliteWorkspaceIntentStore,
    *,
    for_lazy_close: bool,
) -> LazyCloseResult:
    scanned = _sqlite_entries(store)
    row_keys = {row.storage_key: key for key, row in scanned}
    return _lazy_close_from_entries(
        (row for _key, row in scanned),
        for_lazy_close=for_lazy_close,
        remove_corrupted=lambda key: store.delete_row_unlocked(
            pid=row_keys[key][0],
            start_epoch=row_keys[key][1],
            intent_id=row_keys[key][2],
        ),
        close_active=lambda record, reason: store.write_unlocked(
            replace(record, status=gc_status_for_reason(reason)),
        ),
    )


def unreadable_intent_ids(store: WorkspaceIntentStore) -> frozenset[str]:
    """Intent ids whose stored row this build cannot read but must not lose.

    Reads nothing and closes nothing, so a caller asking "is it gone, or is it
    merely beyond me?" can ask without the question having side effects. That
    matters for the recovery path, which deliberately runs without lazy close.
    """

    if isinstance(store, FileWorkspaceIntentStore):
        rows = tuple(row for _path, row in _file_entries(store))
    elif isinstance(store, SqliteWorkspaceIntentStore):
        rows = tuple(row for _key, row in _sqlite_entries(store))
    else:  # pragma: no cover - the union is closed
        raise TypeError(f"Unsupported workspace intent store: {type(store)!r}")
    return frozenset(
        row.keyed_intent_id
        for row in rows
        if row.keyed_intent_id is not None
        and row.read.kind is WorkspaceDocumentReadKind.INCOMPATIBLE
    )


__all__ = [
    "FileWorkspaceIntentStore",
    "LazyCloseResult",
    "ScannedRegistryRow",
    "SqliteWorkspaceIntentStore",
    "WorkspaceIntentStore",
    "clear_workspace_intent_store_cache",
    "get_workspace_intent_store",
    "lazy_close_eligible_records",
    "lazy_close_eligible_records_unlocked",
    "registry_transaction",
    "unreadable_intent_ids",
    "write_workspace_intent_with_existing",
]
