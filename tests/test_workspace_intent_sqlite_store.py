# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from codeclone.config.intent_registry import (
    DEFAULT_INTENT_REGISTRY_BACKEND,
    DEFAULT_INTENT_REGISTRY_DB_PATH,
    DEFAULT_INTENT_REGISTRY_RETENTION_DAYS,
    IntentRegistryConfig,
    IntentRegistryConfigError,
    intent_registry_summary,
    resolve_intent_registry_backend,
    resolve_intent_registry_config,
    resolve_intent_registry_db_path,
    resolve_intent_registry_retention_days,
)
from codeclone.surfaces.mcp import _workspace_intents as workspace_intents
from codeclone.surfaces.mcp._workspace_intent_lifecycle import gc_status_for_reason
from codeclone.surfaces.mcp._workspace_intent_models import (
    signed_payload_json_from_record,
)
from codeclone.surfaces.mcp._workspace_intent_paths import intent_path
from codeclone.surfaces.mcp._workspace_intent_schema import (
    INTENT_REGISTRY_SCHEMA_VERSION,
    get_meta,
    open_intent_registry_db,
)
from codeclone.surfaces.mcp._workspace_intent_staleness import is_stale, stale_reason
from codeclone.surfaces.mcp._workspace_intent_store import (
    FileWorkspaceIntentStore,
    SqliteWorkspaceIntentStore,
    _record_from_json,
    clear_workspace_intent_store_cache,
    get_workspace_intent_store,
    lazy_close_eligible_records,
)
from tests.test_workspace_intents import _record


@contextmanager
def _open_sqlite_store(
    sqlite_root: Path,
    *,
    retention_days: int = 7,
) -> Iterator[SqliteWorkspaceIntentStore]:
    db_path = sqlite_root / DEFAULT_INTENT_REGISTRY_DB_PATH
    store = SqliteWorkspaceIntentStore(db_path=db_path, retention_days=retention_days)
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def sqlite_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    clear_workspace_intent_store_cache()
    return tmp_path


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
    # No edition ceiling: any value at or above the minimum is accepted.
    assert resolve_intent_registry_retention_days(30) == 30
    assert resolve_intent_registry_retention_days(365) == 365


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
    with pytest.raises(IntentRegistryConfigError, match="must be a string"):
        resolve_intent_registry_db_path(root_path=tmp_path, value=123)
    with pytest.raises(IntentRegistryConfigError, match="must not be empty"):
        resolve_intent_registry_db_path(root_path=tmp_path, value="   ")
    with pytest.raises(IntentRegistryConfigError, match="must end with"):
        resolve_intent_registry_db_path(
            root_path=tmp_path,
            value=".cache/intents.txt",
        )


@pytest.mark.parametrize("value", [True, "7"])
def test_resolve_intent_registry_retention_days_rejects_non_int(
    value: object,
) -> None:
    with pytest.raises(IntentRegistryConfigError, match="must be an integer"):
        resolve_intent_registry_retention_days(value)


def test_resolve_intent_registry_backend_rejects_non_string() -> None:
    with pytest.raises(IntentRegistryConfigError, match="must be a string"):
        resolve_intent_registry_backend(123)


def test_resolve_intent_registry_config_ignores_invalid_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_BACKEND", raising=False)
    (tmp_path / "pyproject.toml").write_bytes(b"not-valid-toml{")
    config = resolve_intent_registry_config(tmp_path)
    assert config.backend == DEFAULT_INTENT_REGISTRY_BACKEND


def test_intent_registry_summary_falls_back_to_absolute_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = Path("/tmp/codeclone-intent-registry-outside.sqlite3")

    def _outside_config(_root: Path) -> IntentRegistryConfig:
        return IntentRegistryConfig(
            backend="sqlite",
            storage_path=outside,
            retention_days=DEFAULT_INTENT_REGISTRY_RETENTION_DAYS,
        )

    monkeypatch.setattr(
        "codeclone.config.intent_registry.resolve_intent_registry_config",
        _outside_config,
    )
    summary = intent_registry_summary(tmp_path)
    assert summary["registry_backend"] == "sqlite"
    assert summary["registry_storage"] == str(outside)


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
    archived = store._fetch_record_unlocked(
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


def test_sqlite_store_list_records_for_hygiene_and_find_raw(
    sqlite_root: Path,
) -> None:
    record = _record(intent_id="intent-hygiene-001")
    store = get_workspace_intent_store(sqlite_root)
    assert store.write(record)
    hygiene_records = store.list_records_for_hygiene()
    assert record in hygiene_records
    assert store.find_raw(record.intent_id) == record
    raw_records = store.list_records_raw()
    assert record in raw_records


def test_sqlite_store_active_rewrite_clears_closed_at(sqlite_root: Path) -> None:
    with _open_sqlite_store(sqlite_root) as store:
        record = _record(intent_id="intent-reopen-001")
        assert store.write(replace(record, status="clean"))
        closed_row = store._conn.execute(
            "SELECT closed_at_utc FROM workspace_intents WHERE intent_id = ?",
            (record.intent_id,),
        ).fetchone()
        assert closed_row is not None
        assert closed_row[0] is not None

        assert store.write(record)
        reopened_row = store._conn.execute(
            "SELECT closed_at_utc FROM workspace_intents WHERE intent_id = ?",
            (record.intent_id,),
        ).fetchone()
        assert reopened_row is not None
        assert reopened_row[0] is None
        assert store.find(record.intent_id) == record


def test_sqlite_store_remove_rejects_invalid_intent_id(sqlite_root: Path) -> None:
    store = get_workspace_intent_store(sqlite_root)
    assert store.remove(pid=1, start_epoch=1, intent_id="not-an-intent") is False


def test_sqlite_store_lazy_close_eligible_records(sqlite_root: Path) -> None:
    stale = replace(
        _record(intent_id="intent-lazy-close-001"),
        expires_at_utc=workspace_intents.format_utc(
            workspace_intents.utc_now() - timedelta(hours=1)
        ),
    )
    store = get_workspace_intent_store(sqlite_root)
    assert store.write(stale)
    result = lazy_close_eligible_records(store)
    assert stale.intent_id in result.closed_ids


def test_sqlite_store_gc_closes_corrupted_and_stale(sqlite_root: Path) -> None:
    with _open_sqlite_store(sqlite_root, retention_days=14) as store:
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
        archived = store._fetch_record_unlocked(
            pid=stale.agent_pid,
            start_epoch=stale.agent_start_epoch,
            intent_id=stale.intent_id,
        )
        assert archived is not None
        assert archived.status == "expired"


def test_sqlite_store_retention_purges_closed_rows(sqlite_root: Path) -> None:
    with _open_sqlite_store(sqlite_root) as store:
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
            store._fetch_record_unlocked(
                pid=closed.agent_pid,
                start_epoch=closed.agent_start_epoch,
                intent_id=closed.intent_id,
            )
            is None
        )


def test_sqlite_store_exposes_storage_path_and_closes(sqlite_root: Path) -> None:
    db_path = sqlite_root / DEFAULT_INTENT_REGISTRY_DB_PATH
    with _open_sqlite_store(sqlite_root) as store:
        assert store.storage_path == db_path


def test_sqlite_store_write_returns_false_for_invalid_record(
    sqlite_root: Path,
) -> None:
    with _open_sqlite_store(sqlite_root) as store:
        assert store.write(object()) is False  # type: ignore[arg-type]


def test_sqlite_store_gc_returns_empty_result_on_query_failure(
    sqlite_root: Path,
) -> None:
    with _open_sqlite_store(sqlite_root) as store:
        store.close()
        result = store.gc()
        assert result["removed"] == 0
        assert result["remaining"] == 0


def test_record_from_json_accepts_dict_payload() -> None:
    record = _record()
    payload = json.loads(signed_payload_json_from_record(record))
    parsed = _record_from_json(payload)
    assert parsed == record


def test_record_from_json_rejects_non_mapping_payload() -> None:
    assert _record_from_json(123) is None


def test_file_store_backend_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_BACKEND", raising=False)
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_PATH", raising=False)
    clear_workspace_intent_store_cache()
    store = get_workspace_intent_store(tmp_path)
    assert isinstance(store, FileWorkspaceIntentStore)
    assert store.backend == "file"
    assert store.storage_path == tmp_path / ".codeclone" / "intents"


def test_file_store_write_returns_false_on_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_BACKEND", raising=False)
    clear_workspace_intent_store_cache()
    store = get_workspace_intent_store(tmp_path)
    record = _record()

    def _fail(**_kwargs: object) -> None:
        raise OSError("read-only registry")

    import codeclone.surfaces.mcp._workspace_intent_store as intent_store_mod

    monkeypatch.setattr(intent_store_mod, "write_json_document_atomically", _fail)
    assert store.write(record) is False


def test_file_store_gc_removes_corrupted_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_BACKEND", raising=False)
    clear_workspace_intent_store_cache()
    store = get_workspace_intent_store(tmp_path)
    record = _record(intent_id="intent-corrupt-001")
    bad_path = intent_path(
        root=tmp_path,
        pid=record.agent_pid,
        start_epoch=record.agent_start_epoch,
        intent_id=record.intent_id,
    )
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{not-json", encoding="utf-8")
    result = store.gc()
    assert result["corrupted_removed"] == 1


def test_resolve_intent_registry_config_honors_env_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_RETENTION_DAYS", raising=False)
    monkeypatch.setenv("CODECLONE_INTENT_REGISTRY_BACKEND", "sqlite")
    monkeypatch.setenv(
        "CODECLONE_INTENT_REGISTRY_PATH",
        DEFAULT_INTENT_REGISTRY_DB_PATH,
    )
    config = resolve_intent_registry_config(tmp_path)
    assert config.backend == "sqlite"
    assert config.storage_path == tmp_path / DEFAULT_INTENT_REGISTRY_DB_PATH


def test_intent_registry_summary_file_backend(tmp_path: Path) -> None:
    summary = intent_registry_summary(tmp_path)
    assert summary["registry_backend"] == "file"
    assert summary["registry_storage"] == ".codeclone/intents"
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


def test_gc_status_for_reason_maps_orphaned_status() -> None:
    assert gc_status_for_reason("orphaned") == "orphaned"
    assert gc_status_for_reason("expired") == "expired"


def test_stale_reason_honors_terminal_status_fields() -> None:
    expired = replace(_record(), status="expired")
    orphaned = replace(_record(), status="orphaned")
    assert stale_reason(expired) == "expired"
    assert stale_reason(orphaned) == "orphaned"


def test_is_stale_reports_expired_ttl() -> None:
    stale = replace(
        _record(intent_id="intent-stale-ttl-001"),
        expires_at_utc=workspace_intents.format_utc(
            workspace_intents.utc_now() - timedelta(hours=1)
        ),
    )
    assert is_stale(stale) is True


def test_sqlite_store_write_returns_false_on_closed_connection(
    sqlite_root: Path,
) -> None:
    store = get_workspace_intent_store(sqlite_root)
    assert isinstance(store, SqliteWorkspaceIntentStore)
    record = _record(intent_id="intent-write-fail-001")
    store._conn.close()
    assert store.write(record) is False
