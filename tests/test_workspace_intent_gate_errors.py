# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

import pytest

from tests.workspace_intent_gate_helpers import assert_gate_denied


def test_gate_registry_config_error_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_root: Path) -> object:
        raise ValueError("bad registry config")

    monkeypatch.setattr(
        "codeclone.workspace_intent.gate.resolve_intent_registry_config",
        _boom,
    )
    decision = assert_gate_denied(tmp_path, reason="registry_error")
    assert decision.registry_backend is None


def test_gate_sqlite_load_error_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Config:
        backend = "sqlite"
        storage_path = Path(".cache/codeclone/db/intents.sqlite3")

    monkeypatch.setattr(
        "codeclone.workspace_intent.gate.resolve_intent_registry_config",
        lambda _root: _Config(),
    )

    def _load_fail(*_args: object, **_kwargs: object) -> object:
        raise OSError("cannot read sqlite")

    monkeypatch.setattr(
        "codeclone.workspace_intent.gate._load_registry_records_read_only",
        _load_fail,
    )
    decision = assert_gate_denied(tmp_path, reason="registry_error")
    assert decision.registry_backend == "sqlite"
