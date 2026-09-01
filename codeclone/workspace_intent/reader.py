# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read-only workspace intent registry access shared by local clients."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

from ..config.intent_registry import IntentRegistryConfig
from .contract import WorkspaceIntentRecord
from .models import (
    parse_workspace_document,
    parse_workspace_document_json,
    record_from_document,
)
from .paths import read_payload, record_sort_key, registry_files
from .schema import open_intent_registry_db_readonly


def load_registry_records_read_only(
    root: Path,
    config: IntentRegistryConfig,
) -> tuple[WorkspaceIntentRecord, ...]:
    """Load records without creating, migrating, or mutating registry state.

    This module is the single owner of queue order. Records come back sorted
    by ``record_sort_key`` -- ``(declared_at_utc, agent_pid, intent_id)`` --
    and every consumer inherits that sequence instead of re-deriving it. The
    order is load-bearing, not cosmetic: the edit gate names the head of this
    queue as the intent that blocks, so whoever reverses it changes which
    agent the user is told to coordinate with.
    """

    if config.backend == "file":
        return load_file_records(root)
    if config.backend == "sqlite":
        return load_sqlite_records(config.storage_path)
    raise ValueError(f"Unsupported intent registry backend: {config.backend!r}")


def load_file_records(root: Path) -> tuple[WorkspaceIntentRecord, ...]:
    records: list[WorkspaceIntentRecord] = []
    for path in registry_files(root):
        payload = read_payload(path)
        record = record_from_payload(payload)
        if record is not None:
            records.append(record)
    return tuple(sorted(records, key=record_sort_key))


def load_sqlite_records(
    db_path: Path,
    *,
    open_readonly: Callable[[Path], sqlite3.Connection] = (
        open_intent_registry_db_readonly
    ),
) -> tuple[WorkspaceIntentRecord, ...]:
    if not db_path.is_file():
        return ()
    conn = open_readonly(db_path)
    try:
        # No ORDER BY: the sort below owns the sequence. Asking SQL for it as
        # well applied the same law a second time, and measurably worse --
        # ordering by the declared index turns a plain table scan into an
        # index scan that must still fetch ``payload_json`` per row, for a
        # query with no LIMIT that materialises everything anyway.
        rows = conn.execute(
            """
            SELECT payload_json
            FROM workspace_intents
            """
        ).fetchall()
    finally:
        conn.close()
    records = [
        record
        for record in (record_from_payload(row[0]) for row in rows)
        if record is not None
    ]
    return tuple(sorted(records, key=record_sort_key))


def record_from_payload(payload: object) -> WorkspaceIntentRecord | None:
    if isinstance(payload, str):
        document = parse_workspace_document_json(payload)
    elif isinstance(payload, Mapping):
        document = parse_workspace_document(payload)
    else:
        return None
    if document is None:
        return None
    return record_from_document(document)


__all__ = ["load_registry_records_read_only"]
