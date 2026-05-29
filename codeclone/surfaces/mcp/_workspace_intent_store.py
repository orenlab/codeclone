# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ...config.intent_registry import (
    IntentRegistryConfig,
    resolve_intent_registry_config,
)
from ...report.meta import current_report_timestamp_utc
from ...utils.json_io import write_json_document_atomically
from ._workspace_intent_contract import WorkspaceIntentRecord
from ._workspace_intent_lifecycle import (
    WorkspaceIntentStatus,
    gc_removal_reason,
    gc_status_for_reason,
    is_terminal_workspace_intent_status,
)
from ._workspace_intent_models import (
    WorkspaceIntentRowModel,
    parse_workspace_document,
    parse_workspace_document_json,
    record_from_document,
    signed_payload_dict_from_record,
    signed_payload_json_from_record,
)
from ._workspace_intent_paths import (
    intent_path,
    is_safe_intent_id,
    read_payload,
    record_sort_key,
    registry_dir,
    registry_files,
    safe_remove_own_intent,
    unlink,
)
from ._workspace_intent_schema import open_intent_registry_db

_STORE_CACHE: dict[
    tuple[str, str, str], FileWorkspaceIntentStore | SqliteWorkspaceIntentStore
] = {}


@dataclass(frozen=True, slots=True)
class FileWorkspaceIntentStore:
    root: Path

    @property
    def backend(self) -> str:
        return "file"

    @property
    def storage_path(self) -> Path:
        return registry_dir(self.root)

    def write(self, record: WorkspaceIntentRecord) -> bool:
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
        records = [record for _, record in self._valid_entries()]
        return tuple(sorted(records, key=record_sort_key))

    def find(self, intent_id: str) -> WorkspaceIntentRecord | None:
        matches = [
            record
            for _, record in self._valid_entries()
            if record.intent_id == intent_id
        ]
        if not matches:
            return None
        return sorted(matches, key=record_sort_key)[-1]

    def remove(self, *, pid: int, start_epoch: int, intent_id: str) -> bool:
        return safe_remove_own_intent(
            root=self.root,
            pid=pid,
            start_epoch=start_epoch,
            intent_id=intent_id,
        )

    def gc(self) -> dict[str, object]:
        removed_ids: list[str] = []
        removed_reasons: dict[str, str] = {}
        corrupted_filenames: list[str] = []
        for path in registry_files(self.root):
            payload = read_payload(path)
            record = _record_from_json(payload) if payload is not None else None
            if record is None:
                if unlink(path):
                    corrupted_filenames.append(path.name)
                continue
            reason = gc_removal_reason(record)
            if reason is None:
                continue
            if unlink(path):
                removed_ids.append(record.intent_id)
                removed_reasons[record.intent_id] = reason
        remaining = len(self.list_records())
        return {
            "removed": len(removed_ids),
            "removed_intent_ids": removed_ids,
            "removed_reasons": removed_reasons,
            "corrupted_removed": len(corrupted_filenames),
            "corrupted_filenames": corrupted_filenames,
            "remaining": remaining,
        }

    def _valid_entries(self) -> tuple[tuple[Path, WorkspaceIntentRecord], ...]:
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
        self._conn = open_intent_registry_db(db_path)

    @property
    def backend(self) -> str:
        return "sqlite"

    @property
    def storage_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def write(self, record: WorkspaceIntentRecord) -> bool:
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
        with self._lock:
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
                        closed_at_utc = COALESCE(
                            workspace_intents.closed_at_utc,
                            excluded.closed_at_utc
                        )
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
        records = [
            record
            for record in self._load_all_records()
            if not is_terminal_workspace_intent_status(record.status)
        ]
        return tuple(sorted(records, key=record_sort_key))

    def find(self, intent_id: str) -> WorkspaceIntentRecord | None:
        records = [
            record
            for record in self._load_all_records()
            if record.intent_id == intent_id
            and not is_terminal_workspace_intent_status(record.status)
        ]
        if not records:
            return None
        return sorted(records, key=record_sort_key)[-1]

    def remove(self, *, pid: int, start_epoch: int, intent_id: str) -> bool:
        if not is_safe_intent_id(intent_id):
            return False
        record = self._fetch_record(
            pid=pid,
            start_epoch=start_epoch,
            intent_id=intent_id,
        )
        if record is None or is_terminal_workspace_intent_status(record.status):
            return False
        return self.write(
            replace(record, status=WorkspaceIntentStatus.CLEAN.value),
        )

    def gc(self) -> dict[str, object]:
        closed_ids: list[str] = []
        closed_reasons: dict[str, str] = {}
        corrupted_filenames: list[str] = []
        with self._lock:
            try:
                rows = self._conn.execute(
                    """
                    SELECT agent_pid, agent_start_epoch, intent_id, payload_json
                    FROM workspace_intents
                    ORDER BY declared_at_utc, agent_pid, intent_id
                    """
                ).fetchall()
            except sqlite3.Error:
                return _empty_gc_result()
        for agent_pid, agent_start_epoch, intent_id, payload_json in rows:
            storage_key = _sqlite_storage_key(
                pid=int(agent_pid),
                start_epoch=int(agent_start_epoch),
                intent_id=str(intent_id),
            )
            record = _record_from_json(payload_json)
            if record is None:
                if self._delete_row(
                    pid=int(agent_pid),
                    start_epoch=int(agent_start_epoch),
                    intent_id=str(intent_id),
                ):
                    corrupted_filenames.append(storage_key)
                continue
            if is_terminal_workspace_intent_status(record.status):
                continue
            reason = gc_removal_reason(record)
            if reason is None:
                continue
            closed = self.write(
                replace(record, status=gc_status_for_reason(reason)),
            )
            if closed:
                closed_ids.append(record.intent_id)
                closed_reasons[record.intent_id] = reason
        retention_purged = self._purge_retention_rows()
        remaining = len(self.list_records())
        return {
            "removed": len(closed_ids),
            "removed_intent_ids": closed_ids,
            "removed_reasons": closed_reasons,
            "corrupted_removed": len(corrupted_filenames),
            "corrupted_filenames": corrupted_filenames,
            "retention_purged": retention_purged,
            "remaining": remaining,
        }

    def _load_all_records(self) -> tuple[WorkspaceIntentRecord, ...]:
        with self._lock:
            try:
                rows = self._conn.execute(
                    """
                    SELECT payload_json
                    FROM workspace_intents
                    ORDER BY declared_at_utc, agent_pid, intent_id
                    """
                ).fetchall()
            except sqlite3.Error:
                return ()
        return tuple(
            record
            for record in (_record_from_json(row[0]) for row in rows)
            if record is not None
        )

    def _fetch_record(
        self,
        *,
        pid: int,
        start_epoch: int,
        intent_id: str,
    ) -> WorkspaceIntentRecord | None:
        with self._lock:
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

    def _purge_retention_rows(self) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        cutoff_text = cutoff.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self._lock:
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

    def _delete_row(self, *, pid: int, start_epoch: int, intent_id: str) -> bool:
        with self._lock:
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


WorkspaceIntentStore = FileWorkspaceIntentStore | SqliteWorkspaceIntentStore


def get_workspace_intent_store(root: Path) -> WorkspaceIntentStore:
    root_path = root.resolve()
    config = resolve_intent_registry_config(root_path)
    cache_key = (
        str(root_path),
        config.backend,
        str(config.storage_path),
    )
    cached = _STORE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    store = _build_store(root_path=root_path, config=config)
    _STORE_CACHE[cache_key] = store
    return store


def clear_workspace_intent_store_cache() -> None:
    for store in _STORE_CACHE.values():
        close = getattr(store, "close", None)
        if callable(close):
            close()
    _STORE_CACHE.clear()


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
    if isinstance(payload, str):
        document = parse_workspace_document_json(payload)
    elif isinstance(payload, dict):
        document = parse_workspace_document(payload)
    else:
        return None
    if document is None:
        return None
    return record_from_document(document)


def _sqlite_storage_key(*, pid: int, start_epoch: int, intent_id: str) -> str:
    return f"{pid}-{start_epoch}-{intent_id}.sqlite"


def _empty_gc_result() -> dict[str, object]:
    return {
        "removed": 0,
        "removed_intent_ids": [],
        "removed_reasons": {},
        "corrupted_removed": 0,
        "corrupted_filenames": [],
        "retention_purged": 0,
        "remaining": 0,
    }


__all__ = [
    "FileWorkspaceIntentStore",
    "SqliteWorkspaceIntentStore",
    "WorkspaceIntentStore",
    "clear_workspace_intent_store_cache",
    "get_workspace_intent_store",
]
