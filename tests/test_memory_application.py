# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import codeclone.memory.application as application
from codeclone.config.memory import MemoryConfig
from codeclone.memory.application import MemoryApplicationContext
from codeclone.memory.exceptions import MemorySemanticUnavailableError
from codeclone.memory.models import MemoryProject
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from tests._import_graph import _iter_local_imports


def _context(tmp_path: Path) -> MemoryApplicationContext:
    return MemoryApplicationContext(
        config=cast(
            "MemoryConfig",
            SimpleNamespace(
                backend="sqlite",
                semantic=SimpleNamespace(embedding_provider="fastembed"),
            ),
        ),
        db_path=tmp_path / "memory.sqlite3",
        project=cast("MemoryProject", SimpleNamespace(id="proj-1")),
    )


def _store() -> SqliteEngineeringMemoryStore:
    return cast("SqliteEngineeringMemoryStore", object())


def test_resolve_memory_application_context_uses_canonical_resolvers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = cast("MemoryConfig", object())
    project = cast("MemoryProject", object())
    db_path = tmp_path / "memory.sqlite3"
    monkeypatch.setattr(application, "resolve_memory_config", lambda root: config)
    monkeypatch.setattr(
        application,
        "resolve_memory_db_path",
        lambda root, resolved: db_path if resolved is config else None,
    )
    monkeypatch.setattr(
        application,
        "resolve_project_identity",
        lambda root: project,
    )

    context = application.resolve_memory_application_context(tmp_path)

    assert context == MemoryApplicationContext(config, db_path, project)


def test_execute_memory_query_preserves_arguments_and_closes_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    index = object()
    provider = object()
    audit_path = tmp_path / "audit.sqlite3"
    result: dict[str, object] = {"mode": "search", "payload": {"records": []}}
    calls: dict[str, object] = {}
    closed: list[object | None] = []
    monkeypatch.setattr(application, "resolve_semantic_index", lambda cfg: index)
    monkeypatch.setattr(application, "resolve_embedding_provider", lambda cfg: provider)

    def _query(store: object, **kwargs: object) -> dict[str, object]:
        calls["store"] = store
        calls.update(kwargs)
        return result

    monkeypatch.setattr(application, "query_engineering_memory", _query)
    monkeypatch.setattr(application, "close_semantic_index", closed.append)
    store = _store()

    actual = application.execute_memory_query(
        store,
        context=context,
        root_path=tmp_path,
        mode="search",
        query="phase 34",
        filters={"match_mode": "all"},
        max_results=7,
        include_stale=True,
        include_drafts=True,
        detail_level="full",
        semantic=True,
        audit_db_path=audit_path,
    )

    assert actual is result
    assert calls == {
        "store": store,
        "project_id": "proj-1",
        "root_path": tmp_path,
        "backend": "sqlite",
        "db_path": context.db_path,
        "mode": "search",
        "record_id": None,
        "path": None,
        "symbol": None,
        "query": "phase 34",
        "scope": None,
        "filters": {"match_mode": "all"},
        "max_results": 7,
        "include_stale": True,
        "include_drafts": True,
        "detail_level": "full",
        "semantic": True,
        "semantic_index": index,
        "embedding_provider": provider,
        "provider_label": "fastembed",
        "semantic_reason": None,
        "audit_db_path": audit_path,
    }
    assert closed == [index]


def test_execute_memory_query_keeps_unavailable_provider_advisory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    index = object()
    captured: dict[str, object] = {}
    monkeypatch.setattr(application, "resolve_semantic_index", lambda cfg: index)
    monkeypatch.setattr(
        application,
        "resolve_embedding_provider",
        lambda cfg: (_ for _ in ()).throw(
            MemorySemanticUnavailableError("provider missing")
        ),
    )
    monkeypatch.setattr(
        application,
        "query_engineering_memory",
        lambda store, **kwargs: captured.update(kwargs) or {"payload": {}},
    )
    closed: list[object | None] = []
    monkeypatch.setattr(application, "close_semantic_index", closed.append)

    application.execute_memory_query(
        _store(),
        context=context,
        root_path=tmp_path,
        mode="search",
        semantic=True,
    )

    assert captured["embedding_provider"] is None
    assert captured["semantic_reason"] == "provider missing"
    assert closed == [index]


@pytest.mark.parametrize("failure_stage", ["provider", "query"])
def test_execute_memory_query_closes_index_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    context = _context(tmp_path)
    index = object()
    failure = RuntimeError(f"{failure_stage} failed")
    monkeypatch.setattr(application, "resolve_semantic_index", lambda cfg: index)
    monkeypatch.setattr(
        application,
        "resolve_embedding_provider",
        (
            (lambda cfg: (_ for _ in ()).throw(failure))
            if failure_stage == "provider"
            else (lambda cfg: object())
        ),
    )
    monkeypatch.setattr(
        application,
        "query_engineering_memory",
        (
            (lambda store, **kwargs: (_ for _ in ()).throw(failure))
            if failure_stage == "query"
            else (lambda store, **kwargs: {"payload": {}})
        ),
    )
    closed: list[object | None] = []
    monkeypatch.setattr(application, "close_semantic_index", closed.append)

    with pytest.raises(RuntimeError) as caught:
        application.execute_memory_query(
            _store(),
            context=context,
            root_path=tmp_path,
            mode="search",
            semantic=True,
        )

    assert caught.value is failure
    assert closed == [index]


def test_execute_memory_query_does_not_resolve_semantic_dependencies_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(
        application,
        "resolve_semantic_index",
        lambda cfg: (_ for _ in ()).throw(AssertionError("index resolved")),
    )
    monkeypatch.setattr(
        application,
        "resolve_embedding_provider",
        lambda cfg: (_ for _ in ()).throw(AssertionError("provider resolved")),
    )
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        application,
        "query_engineering_memory",
        lambda store, **kwargs: captured.update(kwargs) or {"payload": {}},
    )
    closed: list[object | None] = []
    monkeypatch.setattr(application, "close_semantic_index", closed.append)

    application.execute_memory_query(
        _store(),
        context=context,
        root_path=tmp_path,
        mode="status",
    )

    assert captured["semantic"] is False
    assert captured["semantic_index"] is None
    assert captured["embedding_provider"] is None
    assert closed == [None]


def test_memory_application_owner_is_surface_neutral_and_used_by_both_transports() -> (
    None
):
    root = Path(__file__).resolve().parents[1]
    application_path = root / "codeclone" / "memory" / "application.py"
    imports = _iter_local_imports(
        "codeclone.memory.application",
        application_path.read_text("utf-8"),
    )
    assert [name for name in imports if name.startswith("codeclone.surfaces")] == []

    for path in (
        root / "codeclone" / "surfaces" / "cli" / "memory.py",
        root / "codeclone" / "surfaces" / "mcp" / "_session_memory_mixin.py",
    ):
        source = path.read_text("utf-8")
        assert "execute_memory_query(" in source
        assert "resolve_memory_application_context(" in source
