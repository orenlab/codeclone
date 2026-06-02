# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from codeclone.config.intent_registry import IntentRegistryConfig
from codeclone.workspace_intent import gate as gate_mod
from tests.test_workspace_intents import _record
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


def test_gate_unsupported_backend_and_payload_type_edges() -> None:
    class _Config:
        backend = "unknown"
        storage_path = Path("x")

    with pytest.raises(ValueError, match="Unsupported intent registry backend"):
        gate_mod._load_registry_records_read_only(
            Path("."),
            cast(IntentRegistryConfig, _Config()),
        )

    assert gate_mod._record_from_payload(123) is None
    assert gate_mod._record_from_payload('{"version": 99}') is None


def test_gate_decision_ignores_terminal_and_non_active_records() -> None:
    records = [
        _record(status="accepted"),
        _record(status="blocked"),
    ]
    decision = gate_mod._decision_from_records(
        records,
        registry_backend="file",
        registry_path=".cache/codeclone/intents",
    )
    assert decision.allowed is False
    assert decision.reason == "no_active_intent"
