# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
from collections.abc import Generator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from codeclone.config.intent_registry import (
    DEFAULT_INTENT_REGISTRY_BACKEND,
    DEFAULT_INTENT_REGISTRY_DB_PATH,
    DEFAULT_INTENT_REGISTRY_RETENTION_DAYS,
    IntentRegistryConfigError,
    intent_registry_summary,
    resolve_intent_registry_backend,
    resolve_intent_registry_config,
    resolve_intent_registry_db_path,
    resolve_intent_registry_retention_days,
)
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_schema import (
    INTENT_REGISTRY_SCHEMA_VERSION,
    get_meta,
    open_intent_registry_db,
)
from codeclone.surfaces.mcp._workspace_intent_store import (
    SqliteWorkspaceIntentStore,
    clear_workspace_intent_store_cache,
    get_workspace_intent_store,
)
from codeclone.surfaces.mcp._workspace_intents import WorkspaceIntentRecord


@pytest.fixture(autouse=True)
def _clear_store_cache() -> Generator[None, None, None]:
    clear_workspace_intent_store_cache()
    yield
    clear_workspace_intent_store_cache()


@pytest.fixture
def sqlite_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    clear_workspace_intent_store_cache()
    return tmp_path


def _record(
    *,
    intent_id: str = "intent-abcdef12-001",
    pid: int | None = None,
    start_epoch: int = 100,
    status: str = "active",
) -> WorkspaceIntentRecord:
    declared_at = workspace_intents.utc_now()
    scope_payload: dict[str, object] = {
        "allowed_files": ["pkg/a.py"],
        "allowed_related": ["tests/test_a.py"],
        "forbidden": [".cache/codeclone/**", "codeclone.baseline.json"],
    }
    return WorkspaceIntentRecord(
        intent_id=intent_id,
        agent_pid=pid or os.getpid(),
        agent_start_epoch=start_epoch,
        agent_label="agent-a",
        run_id="abcdef1234567890",
        declared_at_utc=workspace_intents.format_utc(declared_at),
        expires_at_utc=workspace_intents.format_utc(declared_at + timedelta(hours=1)),
        ttl_seconds=3600,
        status=status,
        intent="edit pkg.a",
        scope=scope_payload,
        scope_digest=workspace_intents.compute_scope_digest(scope_payload),
        blast_radius_summary={"radius_level": "medium"},
        lease_renewed_at_utc=workspace_intents.format_utc(declared_at),
        lease_seconds=workspace_intents.DEFAULT_LEASE_SECONDS,
        report_digest="digest-a",
    )


def test_resolve_intent_registry_backend_defaults() -> None:
    assert resolve_intent_registry_backend(None) == DEFAULT_INTENT_REGISTRY_BACKEND
    assert resolve_intent_registry_backend("sqlite") == "sqlite"
    with pytest.raises(IntentRegistryConfigError):
        resolve_intent_registry_backend("postgres")


def test_resolve_intent_registry_retention_days_defaults_and_bounds() -> None:
    assert (
        resolve_intent_registry_retention_days(None)
        == DEFAULT_INTENT_REGISTRY_RETENTION_DAYS
    )
    assert resolve_intent_registry_retention_days(7) == 7
    assert resolve_intent_registry_retention_days(14) == 14
    with pytest.raises(IntentRegistryConfigError):
        resolve_intent_registry_retention_days(0)
    with pytest.raises(IntentRegistryConfigError, match="plans-and-retention"):
        resolve_intent_registry_retention_days(15)


def test_resolve_intent_registry_db_path_rejects_unsafe_values(
    tmp_path: Path,
) -> None:
    with pytest.raises(IntentRegistryConfigError):
        resolve_intent_registry_db_path(
            root_path=tmp_path,
            value="/tmp/intents.sqlite3",
        )
    with pytest.raises(IntentRegistryConfigError):
        resolve_intent_registry_db_path(
            root_path=tmp_path,
            value="../outside.sqlite3",
        )


def test_sqlite_store_write_list_find_update_close(sqlite_root: Path) -> None:
    record = _record()
    store = get_workspace_intent_store(sqlite_root)
    assert store.backend == "sqlite"
    assert store.write(record)
    listed = store.list_records()
    assert listed == (record,)
    assert store.find(record.intent_id) == record

    assert store.remove(
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )
    assert store.find(record.intent_id) is None
    assert isinstance(store, SqliteWorkspaceIntentStore)
    archived = store._fetch_record(
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )
    assert archived is not None
    assert archived.status == "clean"

    closed_via_status = _record(intent_id="intent-close-002", start_epoch=101)
    assert store.write(closed_via_status)
    assert workspace_intents.update_workspace_intent_status(
        root=sqlite_root,
        pid=closed_via_status.agent_pid,
        start_epoch=closed_via_status.agent_start_epoch,
        intent_id=closed_via_status.intent_id,
        new_status="clean",
    )
    assert store.find(closed_via_status.intent_id) is None


def test_sqlite_store_gc_closes_corrupted_and_stale(sqlite_root: Path) -> None:
    db_path = sqlite_root / DEFAULT_INTENT_REGISTRY_DB_PATH
    store = SqliteWorkspaceIntentStore(db_path=db_path, retention_days=14)
    record = _record(intent_id="intent-stale-001")
    stale = replace(
        _record(
            intent_id="intent-expired-002",
            pid=record.agent_pid + 1,
            start_epoch=101,
        ),
        expires_at_utc=workspace_intents.format_utc(
            workspace_intents.utc_now() - timedelta(hours=1)
        ),
    )
    assert store.write(record)
    assert store.write(stale)
    with store._lock:
        store._conn.execute(
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
            """,
            (
                999,
                999,
                "intent-bad-003",
                "2026-01-01T00:00:00Z",
                "{not-json",
                None,
                "2026-01-01T00:00:00Z",
            ),
        )
        store._conn.commit()

    result = store.gc()
    removed = result["removed"]
    corrupted_removed = result["corrupted_removed"]
    assert isinstance(removed, int) and removed >= 1
    assert isinstance(corrupted_removed, int) and corrupted_removed >= 1
    assert store.find("intent-stale-001") is not None
    assert store.find("intent-expired-002") is None
    archived = store._fetch_record(
        pid=stale.agent_pid,
        start_epoch=stale.agent_start_epoch,
        intent_id=stale.intent_id,
    )
    assert archived is not None
    assert archived.status == "expired"


def test_sqlite_store_retention_purges_closed_rows(sqlite_root: Path) -> None:
    db_path = sqlite_root / DEFAULT_INTENT_REGISTRY_DB_PATH
    store = SqliteWorkspaceIntentStore(db_path=db_path, retention_days=7)
    closed = replace(_record(intent_id="intent-old-001"), status="clean")
    assert store.write(closed)
    old_closed_at = workspace_intents.format_utc(
        workspace_intents.utc_now() - timedelta(days=30)
    )
    with store._lock:
        store._conn.execute(
            """
            UPDATE workspace_intents
            SET closed_at_utc = ?
            WHERE intent_id = ?
            """,
            (old_closed_at, closed.intent_id),
        )
        store._conn.commit()

    result = store.gc()
    assert result["retention_purged"] == 1
    assert (
        store._fetch_record(
            pid=closed.agent_pid,
            start_epoch=closed.agent_start_epoch,
            intent_id=closed.intent_id,
        )
        is None
    )


def test_intent_registry_summary_file_backend(tmp_path: Path) -> None:
    summary = intent_registry_summary(tmp_path)
    assert summary["registry_backend"] == "file"
    assert summary["registry_storage"] == ".cache/codeclone/intents"
    assert summary["registry_retention_days"] == str(
        DEFAULT_INTENT_REGISTRY_RETENTION_DAYS
    )


def test_intent_registry_summary_sqlite_backend(sqlite_root: Path) -> None:
    summary = intent_registry_summary(sqlite_root)
    assert summary["registry_backend"] == "sqlite"
    assert summary["registry_storage"] == DEFAULT_INTENT_REGISTRY_DB_PATH
    assert summary["registry_retention_days"] == str(
        DEFAULT_INTENT_REGISTRY_RETENTION_DAYS
    )


def test_pyproject_sqlite_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_BACKEND", raising=False)
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_PATH", raising=False)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "[tool.codeclone]\n"
        'intent_registry_backend = "sqlite"\n'
        f'intent_registry_path = "{DEFAULT_INTENT_REGISTRY_DB_PATH}"\n'
        "intent_registry_retention_days = 14\n",
        encoding="utf-8",
    )
    config = resolve_intent_registry_config(tmp_path)
    assert config.backend == "sqlite"
    assert config.storage_path == tmp_path / DEFAULT_INTENT_REGISTRY_DB_PATH
    assert config.retention_days == 14


def test_sqlite_schema_v2_has_audit_columns(tmp_path: Path) -> None:
    db_path = tmp_path / DEFAULT_INTENT_REGISTRY_DB_PATH
    conn = open_intent_registry_db(db_path)
    try:
        assert get_meta(conn, "schema_version") == INTENT_REGISTRY_SCHEMA_VERSION
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(workspace_intents)")
        }
        assert {"closed_at_utc", "updated_at_utc"}.issubset(columns)
    finally:
        conn.close()


def test_sqlite_payload_roundtrip_preserves_integrity(sqlite_root: Path) -> None:
    record = _record()
    assert workspace_intents.write_workspace_intent(root=sqlite_root, record=record)
    loaded = workspace_intents.list_workspace_intents(root=sqlite_root)[0]
    assert workspace_intents.verify_intent_integrity(
        workspace_intents.signed_payload(loaded)
    )
    payload = json.loads(
        json.dumps(
            workspace_intents.signed_payload(loaded),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    assert payload["integrity"][
        "payload_sha256"
    ] == workspace_intents.compute_intent_digest(
        {k: v for k, v in payload.items() if k != "integrity"}
    )
