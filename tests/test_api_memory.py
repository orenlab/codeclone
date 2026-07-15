# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from codeclone.api import memory as api_memory
from codeclone.api.memory import SemanticIndexRebuildDTO, rebuild_semantic_index
from codeclone.config.memory import MemoryConfig
from codeclone.memory.semantic.rebuild_workflow import RebuildSemanticIndexPayload


def _ok_payload() -> RebuildSemanticIndexPayload:
    return {
        "action": "rebuild_semantic_index",
        "status": "ok",
        "index_path": ".codeclone/memory/semantic_index.lance",
        "embedding_provider": "local",
        "indexed": 4,
        "deleted": 1,
        "embedded": 2,
        "skipped_unchanged": 2,
        "by_source": {"trajectory": 1, "memory": 3},
        "embedding_model": "test-model",
    }


def _skipped_payload() -> RebuildSemanticIndexPayload:
    return {
        "action": "rebuild_semantic_index",
        "status": "skipped",
        "reason": "disabled",
        "index_path": ".codeclone/memory/semantic_index.lance",
        "embedding_provider": "local",
        "indexed": 0,
        "deleted": 0,
        "embedded": 0,
        "skipped_unchanged": 0,
        "by_source": {},
        "embedding_model": None,
    }


def _unavailable_payload() -> RebuildSemanticIndexPayload:
    return {
        "action": "rebuild_semantic_index",
        "status": "unavailable",
        "reason": "provider unavailable",
        "index_path": ".codeclone/memory/semantic_index.lance",
        "embedding_provider": "local",
        "indexed": 0,
        "deleted": 0,
        "embedded": 0,
        "skipped_unchanged": 0,
        "by_source": {},
        "embedding_model": None,
    }


@pytest.mark.parametrize(
    "payload",
    [_ok_payload(), _skipped_payload(), _unavailable_payload()],
)
def test_rebuild_semantic_index_delegates_once_and_preserves_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: RebuildSemanticIndexPayload,
) -> None:
    calls: list[tuple[Path, MemoryConfig]] = []

    def _execute(
        *, root_path: Path, config: MemoryConfig
    ) -> RebuildSemanticIndexPayload:
        calls.append((root_path, config))
        return payload

    monkeypatch.setattr(api_memory, "execute_semantic_index_rebuild", _execute)

    dto = rebuild_semantic_index(root_path=tmp_path)

    assert len(calls) == 1
    assert calls[0][0] == tmp_path
    assert dto.to_payload() == payload
    assert dto.by_source == tuple(sorted(payload["by_source"].items()))


def test_semantic_index_rebuild_dto_is_frozen_kw_only_and_slotted() -> None:
    dto = SemanticIndexRebuildDTO(
        action="rebuild_semantic_index",
        status="ok",
        index_path="semantic.lance",
        embedding_provider="local",
        indexed=1,
        deleted=0,
        embedded=1,
        skipped_unchanged=0,
        by_source=(("memory", 1),),
        embedding_model="test-model",
    )

    assert not hasattr(dto, "__dict__")
    assert dto.reason is None
    with pytest.raises(FrozenInstanceError):
        dto.__setattr__("status", "skipped")
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in inspect.signature(SemanticIndexRebuildDTO).parameters.values()
    )
