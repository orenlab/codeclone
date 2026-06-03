# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.memory import SemanticConfig
from codeclone.memory.semantic import (
    NullSemanticIndex,
    UnavailableSemanticIndex,
    resolve_semantic_index,
)


@pytest.mark.parametrize(
    ("index", "expected_type", "expected_reason"),
    [
        (
            resolve_semantic_index(SemanticConfig(enabled=False)),
            NullSemanticIndex,
            "disabled",
        ),
        (
            UnavailableSemanticIndex(reason="lancedb_not_installed"),
            UnavailableSemanticIndex,
            "lancedb_not_installed",
        ),
    ],
)
def test_degraded_index_is_empty_and_reports_reason(
    index: NullSemanticIndex | UnavailableSemanticIndex,
    expected_type: type[NullSemanticIndex | UnavailableSemanticIndex],
    expected_reason: str,
) -> None:
    assert isinstance(index, expected_type)
    assert index.search([0.0, 1.0], k=5) == []
    status = index.status()
    assert status.available is False
    assert status.reason == expected_reason


def test_resolve_semantic_index_reports_lancedb_not_installed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index_dir = tmp_path / "semantic_index.lance"
    index_dir.mkdir()
    config = SemanticConfig(enabled=True, index_path=str(index_dir))
    monkeypatch.setattr(
        "codeclone.memory.semantic._resolve_backend",
        lambda *_args, **_kwargs: None,
    )
    index = resolve_semantic_index(config)
    assert isinstance(index, UnavailableSemanticIndex)
    assert index.status().reason == "lancedb_not_installed"


def test_resolve_semantic_index_writer_returns_none_when_backend_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SemanticConfig(enabled=True, index_path="/tmp/unused.lance")
    monkeypatch.setattr(
        "codeclone.memory.semantic._resolve_backend",
        lambda *_args, **_kwargs: None,
    )
    from codeclone.memory.semantic import resolve_semantic_index_writer

    assert resolve_semantic_index_writer(config) is None
