# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys

import pytest

from codeclone.config.observability import (
    ObservabilityConfig,
    ObservabilityConfigError,
    resolve_observability_config,
)


def _resolve(**env: str) -> ObservabilityConfig:
    return resolve_observability_config(environ=env)


def test_default_disabled() -> None:
    assert _resolve().enabled is False


def test_enabled_via_env_defaults() -> None:
    cfg = _resolve(CODECLONE_OBSERVABILITY_ENABLED="1")
    assert cfg.enabled is True
    assert cfg.persist is True
    # Payload sizing is ON by default when enabled (byte+token sizes matter).
    assert cfg.capture_payload_sizes is True
    assert cfg.profile is False


def test_explicit_off_wins_over_force() -> None:
    cfg = _resolve(
        CODECLONE_OBSERVABILITY_ENABLED="0",
        CODECLONE_OBSERVABILITY_FORCE="1",
    )
    assert cfg.enabled is False


def test_ci_disables_unless_explicit_or_forced() -> None:
    assert _resolve(CI="true").enabled is False
    assert _resolve(CI="true", CODECLONE_OBSERVABILITY_ENABLED="1").enabled is True
    assert (
        _resolve(
            CI="true",
            CODECLONE_OBSERVABILITY_FORCE="1",
            CODECLONE_OBSERVABILITY_ENABLED="1",
        ).enabled
        is True
    )
    # FORCE only lifts the CI gate; it never enables on its own.
    assert _resolve(CI="true", CODECLONE_OBSERVABILITY_FORCE="1").enabled is False


def test_payload_snapshot_rejected() -> None:
    with pytest.raises(ObservabilityConfigError, match="payload_snapshot"):
        _resolve(
            CODECLONE_OBSERVABILITY_ENABLED="1",
            CODECLONE_OBSERVABILITY_PAYLOAD_SNAPSHOT="1",
        )


def test_profile_without_perf_extra_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("codeclone.config.observability.find_spec", lambda _name: None)
    with pytest.raises(ObservabilityConfigError, match=r"codeclone\[perf\]"):
        _resolve(
            CODECLONE_OBSERVABILITY_ENABLED="1",
            CODECLONE_OBSERVABILITY_PROFILE="1",
        )


def test_profile_with_perf_extra_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "codeclone.config.observability.find_spec", lambda _name: object()
    )
    cfg = _resolve(
        CODECLONE_OBSERVABILITY_ENABLED="1",
        CODECLONE_OBSERVABILITY_PROFILE="1",
    )
    assert cfg.profile is True


def test_disabled_resolution_does_not_import_psutil() -> None:
    sys.modules.pop("psutil", None)
    resolve_observability_config(environ={})
    assert "psutil" not in sys.modules
