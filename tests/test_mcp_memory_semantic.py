# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

import codeclone.surfaces.mcp._session_memory_mixin as memory_mixin
from codeclone.memory.semantic.models import SemanticHit, SemanticIndexStatus
from codeclone.surfaces.mcp.service import CodeCloneMCPService
from tests.memory_fixtures import cli_memory_repo


def _semantic_payload(result: dict[str, object]) -> dict[str, object]:
    semantic = result["semantic"]
    assert isinstance(semantic, dict)
    return semantic


def test_mcp_manage_memory_rebuild_semantic_index_skipped_when_disabled(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        payload = service.manage_engineering_memory(
            root=str(root.resolve()),
            action="rebuild_semantic_index",
        )
    assert payload["action"] == "rebuild_semantic_index"
    assert payload["status"] == "skipped"
    assert payload["reason"] == "disabled"


def test_mcp_query_semantic_block_present_when_disabled(tmp_path: Path) -> None:
    # The semantic param flows through the MCP layer to the service and back.
    # With the default config (semantic disabled) the index resolves to the
    # Null object, so recall degrades clear: used=False, reason=disabled.
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        service = CodeCloneMCPService(history_limit=2)
        result = service.query_engineering_memory(
            root=str(root), mode="search", query="module", semantic=True
        )
    semantic = _semantic_payload(result)
    assert semantic["used"] is False
    assert semantic["reason"] == "disabled"
    payload = result["payload"]
    assert isinstance(payload, dict)
    # Typed-separate envelope is present even when semantic degrades.
    assert "records" in payload
    assert "audit_events" in payload


def test_mcp_query_semantic_provider_unavailable_degrades(
    tmp_path: Path,
) -> None:
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        (root / "pyproject.toml").write_text(
            "[tool.codeclone.memory.semantic]\n"
            "enabled = true\n"
            'embedding_provider = "local_model"\n',
            encoding="utf-8",
        )
        service = CodeCloneMCPService(history_limit=2)
        result = service.query_engineering_memory(
            root=str(root), mode="search", query="module", semantic=True
        )

    semantic = _semantic_payload(result)
    assert semantic["used"] is False
    assert semantic["provider"] == "local_model"
    assert "local_model embedding provider is not available" in str(semantic["reason"])
    payload = result["payload"]
    assert isinstance(payload, dict)
    assert "records" in payload
    assert "audit_events" in payload


def test_mcp_query_semantic_closes_read_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ClosableIndex:
        closed = False

        def search(
            self, vector: Sequence[float], *, k: int, source: str | None = None
        ) -> list[SemanticHit]:
            del vector, k, source
            return []

        def status(self) -> SemanticIndexStatus:
            return SemanticIndexStatus(
                available=True,
                backend="fake",
                embedding_model="diagnostic-hash-v1",
                dimension=64,
                indexed_count=0,
            )

        def close(self) -> None:
            self.closed = True

    index = _ClosableIndex()
    monkeypatch.setattr(
        memory_mixin,
        "resolve_semantic_index",
        lambda _config: index,
    )
    with cli_memory_repo(tmp_path, with_draft=False) as (root, _project, _store):
        (root / "pyproject.toml").write_text(
            "[tool.codeclone.memory.semantic]\nenabled = true\ndimension = 64\n",
            encoding="utf-8",
        )
        service = CodeCloneMCPService(history_limit=2)
        result = service.query_engineering_memory(
            root=str(root), mode="search", query="module", semantic=True
        )

    assert result["status"] == "ok"
    assert index.closed is True
