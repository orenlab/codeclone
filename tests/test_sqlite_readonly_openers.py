# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.audit.schema import (
    open_audit_db,
    open_audit_db_readonly,
)
from codeclone.audit.validation import AuditSchemaError
from codeclone.surfaces.mcp._workspace_intent_schema import (
    IntentRegistrySchemaError,
    open_intent_registry_db,
    open_intent_registry_db_readonly,
)
from codeclone.utils.sqlite_store import open_sqlite_db_readonly


def test_generic_readonly_opener_does_not_create_missing_database(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "missing.sqlite3"

    with pytest.raises(FileNotFoundError):
        open_sqlite_db_readonly(db_path, validate_schema=lambda _conn: None)

    assert not db_path.exists()


def test_audit_readonly_opener_rejects_writes(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    writable = open_audit_db(db_path)
    writable.close()

    conn = open_audit_db_readonly(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM controller_events").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM controller_events")
    finally:
        conn.close()


def test_audit_readonly_opener_accepts_migratable_schema_without_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "audit.sqlite3"
    writable = open_audit_db(db_path)
    try:
        writable.execute("UPDATE audit_meta SET value='3' WHERE key='schema_version'")
        writable.commit()
    finally:
        writable.close()

    readonly = open_audit_db_readonly(db_path)
    readonly.close()

    raw = sqlite3.connect(db_path)
    try:
        assert raw.execute(
            "SELECT value FROM audit_meta WHERE key='schema_version'"
        ).fetchone() == ("3",)
    finally:
        raw.close()


def test_audit_readonly_opener_rejects_unsupported_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    writable = open_audit_db(db_path)
    try:
        writable.execute("UPDATE audit_meta SET value='999' WHERE key='schema_version'")
        writable.commit()
    finally:
        writable.close()

    with pytest.raises(AuditSchemaError, match="Unsupported audit schema"):
        open_audit_db_readonly(db_path)


def test_intent_readonly_opener_rejects_stale_schema_without_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "intents.sqlite3"
    writable = open_intent_registry_db(db_path)
    try:
        writable.execute(
            "UPDATE intent_registry_meta SET value='1' WHERE key='schema_version'"
        )
        writable.commit()
    finally:
        writable.close()

    with pytest.raises(IntentRegistrySchemaError, match="requires writable"):
        open_intent_registry_db_readonly(db_path)

    raw = sqlite3.connect(db_path)
    try:
        assert raw.execute(
            "SELECT value FROM intent_registry_meta WHERE key='schema_version'"
        ).fetchone() == ("1",)
    finally:
        raw.close()


@pytest.mark.parametrize(
    "opener",
    [open_audit_db, open_audit_db_readonly, open_intent_registry_db],
)
def test_domain_openers_attach_observability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opener: object,
) -> None:
    audit_path = tmp_path / "audit.sqlite3"
    intent_path = tmp_path / "intents.sqlite3"
    open_audit_db(audit_path).close()
    calls: list[sqlite3.Connection] = []
    monkeypatch.setattr(
        "codeclone.observability.instrument_db_connection",
        calls.append,
    )

    selected = opener
    assert callable(selected)
    path = intent_path if selected is open_intent_registry_db else audit_path
    conn = selected(path)
    try:
        assert calls == [conn]
    finally:
        conn.close()


def test_intent_readonly_opener_attaches_observability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "intents.sqlite3"
    open_intent_registry_db(db_path).close()
    calls: list[sqlite3.Connection] = []
    monkeypatch.setattr(
        "codeclone.observability.instrument_db_connection",
        calls.append,
    )

    conn = open_intent_registry_db_readonly(db_path)
    try:
        assert calls == [conn]
    finally:
        conn.close()
