# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codeclone.audit.schema import ensure_schema, open_audit_db
from codeclone.audit.validation import (
    AUDIT_SCHEMA_VERSION,
    AuditConfigError,
    AuditSchemaError,
    resolve_audit_path,
    validate_payload_mode,
    validate_retention_days,
)


def test_open_audit_db_creates_schema_and_meta(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"

    conn = open_audit_db(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        schema = conn.execute(
            "SELECT value FROM audit_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    assert {"controller_events", "audit_meta"}.issubset(tables)
    assert schema == (AUDIT_SCHEMA_VERSION,)


def test_ensure_schema_rejects_unknown_version(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE audit_meta(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT INTO audit_meta(key, value) VALUES ('schema_version', '999')"
        )
        conn.commit()

        with pytest.raises(AuditSchemaError, match="Unsupported audit schema"):
            ensure_schema(conn)
    finally:
        conn.close()


def test_resolve_audit_path_accepts_repo_relative_sqlite_path(tmp_path: Path) -> None:
    resolved = resolve_audit_path(
        root_path=tmp_path,
        value=".cache/codeclone/audit.db",
    )
    assert resolved == tmp_path / ".cache" / "codeclone" / "audit.db"


@pytest.mark.parametrize(
    "value",
    ["/tmp/audit.sqlite3", "../audit.sqlite3", "audit.txt"],
)
def test_resolve_audit_path_rejects_unsafe_values(
    tmp_path: Path,
    value: str,
) -> None:
    with pytest.raises(AuditConfigError):
        resolve_audit_path(root_path=tmp_path, value=value)


def test_payload_mode_and_retention_validation() -> None:
    assert validate_payload_mode("off") == "off"
    assert validate_payload_mode("compact") == "compact"
    assert validate_payload_mode("full") == "full"
    assert validate_retention_days(30) == 30

    with pytest.raises(AuditConfigError):
        validate_payload_mode("verbose")
    with pytest.raises(AuditConfigError):
        validate_retention_days(0)
