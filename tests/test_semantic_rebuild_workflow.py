# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from codeclone.config.memory import resolve_memory_config
from codeclone.memory.exceptions import (
    MemoryContractError,
    MemorySemanticUnavailableError,
)
from codeclone.memory.semantic.rebuild_workflow import execute_semantic_index_rebuild

from .memory_fixtures import memory_store


def test_execute_semantic_rebuild_skipped_when_disabled(tmp_path: Path) -> None:
    config = resolve_memory_config(tmp_path)
    payload = execute_semantic_index_rebuild(root_path=tmp_path, config=config)
    assert payload["action"] == "rebuild_semantic_index"
    assert payload["status"] == "skipped"
    assert payload["reason"] == "disabled"
    assert payload["indexed"] == 0


def test_execute_semantic_rebuild_unavailable_without_lancedb(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)
    import codeclone.memory.semantic as semantic_pkg

    monkeypatch.setattr(semantic_pkg, "resolve_semantic_index_writer", lambda _c: None)
    payload = execute_semantic_index_rebuild(root_path=tmp_path, config=config)
    assert payload["status"] == "unavailable"
    assert payload["reason"] == "lancedb_not_installed"


def test_execute_semantic_rebuild_requires_memory_db_when_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.codeclone.memory.semantic]\nenabled = true\n",
        encoding="utf-8",
    )
    config = resolve_memory_config(tmp_path)

    class _Writer:
        closed = False

        def known_ids(self) -> set[str]:
            return set()

        def delete(self, ids: object) -> None:
            return None

        def upsert(self, rows: object) -> None:
            return None

        def close(self) -> None:
            self.closed = True

    import codeclone.memory.semantic as semantic_pkg

    writer = _Writer()
    monkeypatch.setattr(
        semantic_pkg,
        "resolve_semantic_index_writer",
        lambda _config: writer,
    )
    with pytest.raises(MemoryContractError, match="database not found"):
        execute_semantic_index_rebuild(root_path=tmp_path, config=config)
    assert writer.closed is True


def test_execute_semantic_rebuild_unavailable_when_model_fails_at_embed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = resolve_memory_config(tmp_path)
    config = dataclasses.replace(
        base,
        semantic=base.semantic.model_copy(
            update={"enabled": True, "embedding_provider": "diagnostic"}
        ),
    )

    class _Writer:
        def known_ids(self) -> set[str]:
            return set()

        def delete(self, ids: object) -> None:
            return None

        def upsert(self, rows: object) -> None:
            return None

        def close(self) -> None:
            return None

    import codeclone.memory.semantic as semantic_pkg
    from codeclone.memory.semantic import rebuild_workflow

    monkeypatch.setattr(
        semantic_pkg, "resolve_semantic_index_writer", lambda _config: _Writer()
    )
    monkeypatch.setattr(
        rebuild_workflow, "build_semantic_index_sources", lambda **_kwargs: []
    )

    def _raise_unavailable(**_kwargs: object) -> object:
        # Provider resolves fine (lazy); the model only fails when the rebuild
        # actually embeds.
        raise MemorySemanticUnavailableError("model unavailable (download disabled)")

    monkeypatch.setattr(rebuild_workflow, "rebuild_semantic_index", _raise_unavailable)

    with memory_store(tmp_path) as (root, project, store, _db_path):
        payload = execute_semantic_index_rebuild(
            root_path=root, config=config, store=store, project=project
        )
    assert payload["status"] == "unavailable"
    assert "model unavailable" in str(payload["reason"])
