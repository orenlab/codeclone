# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The documented retention override is text, and text must parse.

``docs/reference/configuration.md`` promises that
``CODECLONE_INTENT_REGISTRY_RETENTION_DAYS`` overrides
``intent_registry_retention_days``. An environment value is always a string,
and the resolver accepted only ``int`` -- so setting the documented variable
to ``7`` raised on every registry resolution, the default file backend's
included, and took change control down with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.config.intent_registry import (
    IntentRegistryConfigError,
    resolve_intent_registry_config,
    resolve_intent_registry_retention_days,
)

_RETENTION_ENV = "CODECLONE_INTENT_REGISTRY_RETENTION_DAYS"


@pytest.fixture(autouse=True)
def _clean_registry_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_BACKEND", raising=False)
    monkeypatch.delenv("CODECLONE_INTENT_REGISTRY_PATH", raising=False)
    monkeypatch.delenv(_RETENTION_ENV, raising=False)


def _pyproject(root: Path, days: int) -> None:
    (root / "pyproject.toml").write_text(
        f"[tool.codeclone]\nintent_registry_retention_days = {days}\n",
        encoding="utf-8",
    )


def test_env_retention_equals_the_same_number_from_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pyproject(tmp_path, 7)
    from_pyproject = resolve_intent_registry_config(tmp_path)
    (tmp_path / "pyproject.toml").unlink()
    monkeypatch.setenv(_RETENTION_ENV, "7")

    from_env = resolve_intent_registry_config(tmp_path)

    assert from_pyproject.retention_days == 7
    assert from_env == from_pyproject


def test_env_retention_overrides_pyproject(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pyproject(tmp_path, 7)
    monkeypatch.setenv(_RETENTION_ENV, " 30 ")

    assert resolve_intent_registry_config(tmp_path).retention_days == 30


@pytest.mark.parametrize("raw", ["abc", "", "7.5", "seven"])
def test_a_non_numeric_env_retention_is_a_typed_error_naming_the_variable(
    raw: str,
) -> None:
    with pytest.raises(IntentRegistryConfigError, match=_RETENTION_ENV):
        resolve_intent_registry_retention_days(None, env_value=raw)


def test_a_non_numeric_env_retention_fails_the_whole_resolution_typed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_RETENTION_ENV, "a week")

    with pytest.raises(IntentRegistryConfigError, match=_RETENTION_ENV):
        resolve_intent_registry_config(tmp_path)


def test_an_env_retention_below_the_minimum_names_the_variable() -> None:
    with pytest.raises(IntentRegistryConfigError, match=_RETENTION_ENV) as caught:
        resolve_intent_registry_retention_days(None, env_value="0")
    assert "at least 1" in str(caught.value)


def test_pyproject_retention_stays_a_typed_integer() -> None:
    """The parse belongs to the env value, which is text by construction.

    TOML has integers; a quoted number in ``pyproject.toml`` is still a type
    error, and the message keeps naming the pyproject key.
    """

    with pytest.raises(
        IntentRegistryConfigError, match="intent_registry_retention_days"
    ) as caught:
        resolve_intent_registry_retention_days("7")
    assert _RETENTION_ENV not in str(caught.value)


def test_pyproject_retention_below_the_minimum_names_the_key() -> None:
    with pytest.raises(
        IntentRegistryConfigError,
        match="intent_registry_retention_days must be at least 1",
    ):
        resolve_intent_registry_retention_days(0)


def test_the_minimum_itself_is_accepted_from_either_source() -> None:
    """Pins the boundary, not only both sides of it: one day is allowed."""

    assert resolve_intent_registry_retention_days(None, env_value="1") == 1
    assert resolve_intent_registry_retention_days(1) == 1
