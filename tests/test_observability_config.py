# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys

import pytest

from codeclone.budget.estimator import (
    TOKEN_ESTIMATOR_CHARS_APPROX,
    TOKEN_ESTIMATOR_MODES,
    TOKEN_ESTIMATOR_TIKTOKEN,
)
from codeclone.config.intent_registry import IntentRegistryConfigError
from codeclone.config.observability import (
    ObservabilityConfigError,
    resolve_observability_config,
)
from codeclone.config.pyproject_loader import ConfigValidationError
from codeclone.contracts.errors import DiagnosedUserError
from codeclone.models import DEFAULT_OBSERVABILITY_TOKEN_ESTIMATOR, ObservabilityConfig


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
    assert cfg.retention_days == 7
    assert cfg.max_operations_per_process == 2000
    assert cfg.max_spans_per_operation == 100
    # chars_approx stays the default: the MCP server is long-lived and must not
    # keep tiktoken's native encoding state resident just because it is present.
    assert cfg.token_estimator == TOKEN_ESTIMATOR_CHARS_APPROX
    assert cfg.token_estimator_downgraded is False


def test_retention_and_caps_resolve_from_env() -> None:
    cfg = _resolve(
        CODECLONE_OBSERVABILITY_ENABLED="1",
        CODECLONE_OBSERVABILITY_RETENTION_DAYS="3",
        CODECLONE_OBSERVABILITY_MAX_OPERATIONS_PER_PROCESS="9",
        CODECLONE_OBSERVABILITY_MAX_SPANS_PER_OPERATION="4",
    )
    assert cfg.retention_days == 3
    assert cfg.max_operations_per_process == 9
    assert cfg.max_spans_per_operation == 4


@pytest.mark.parametrize(
    "key,value",
    [
        ("CODECLONE_OBSERVABILITY_RETENTION_DAYS", "0"),
        ("CODECLONE_OBSERVABILITY_MAX_OPERATIONS_PER_PROCESS", "bad"),
        ("CODECLONE_OBSERVABILITY_MAX_SPANS_PER_OPERATION", "-1"),
    ],
)
def test_retention_and_caps_reject_invalid_values(key: str, value: str) -> None:
    with pytest.raises(ObservabilityConfigError, match="positive integer"):
        _resolve(CODECLONE_OBSERVABILITY_ENABLED="1", **{key: value})


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


def test_token_estimator_resolves_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "codeclone.config.observability.find_spec", lambda _name: object()
    )
    cfg = _resolve(
        CODECLONE_OBSERVABILITY_ENABLED="1",
        CODECLONE_OBSERVABILITY_TOKEN_ESTIMATOR="tiktoken",
    )
    assert cfg.token_estimator == TOKEN_ESTIMATOR_TIKTOKEN
    assert cfg.token_estimator_downgraded is False


def test_token_estimator_downgrades_without_tiktoken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing optional package is a downgrade, not a crash — and it is named.

    ``profile`` raises for a missing ``psutil`` because profiling silently off
    would be read as "this build has no memory cost". A token estimator has a
    correct weaker answer, so it falls back — but the config carries the fact,
    so nothing downstream can report ``tiktoken`` numbers that were never taken.
    """
    monkeypatch.setattr("codeclone.config.observability.find_spec", lambda _name: None)
    cfg = _resolve(
        CODECLONE_OBSERVABILITY_ENABLED="1",
        CODECLONE_OBSERVABILITY_TOKEN_ESTIMATOR="tiktoken",
    )
    assert cfg.token_estimator == TOKEN_ESTIMATOR_CHARS_APPROX
    assert cfg.token_estimator_downgraded is True


def test_token_estimator_rejects_unknown_value() -> None:
    with pytest.raises(ObservabilityConfigError, match="token estimator"):
        _resolve(
            CODECLONE_OBSERVABILITY_ENABLED="1",
            CODECLONE_OBSERVABILITY_TOKEN_ESTIMATOR="bpe",
        )


def test_chars_approx_default_is_not_a_second_vocabulary() -> None:
    """``models`` may only import ``contracts``, so it restates the default.

    A restated literal drifts silently: a set of relative pins ("the default is
    not tiktoken") stays green whatever the string says. This re-derives the
    default from the estimator that owns the vocabulary.
    """
    assert DEFAULT_OBSERVABILITY_TOKEN_ESTIMATOR == TOKEN_ESTIMATOR_CHARS_APPROX
    assert DEFAULT_OBSERVABILITY_TOKEN_ESTIMATOR in TOKEN_ESTIMATOR_MODES


def test_default_resolution_does_not_probe_for_tiktoken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default path must not pay for a package it will not use."""
    probed: list[str] = []

    def _tracking_find_spec(name: str) -> object:
        probed.append(name)
        return object()

    monkeypatch.setattr("codeclone.config.observability.find_spec", _tracking_find_spec)
    _resolve(CODECLONE_OBSERVABILITY_ENABLED="1")
    assert probed == []


def test_observability_persist_can_be_disabled_explicitly() -> None:
    cfg = _resolve(
        CODECLONE_OBSERVABILITY_ENABLED="1",
        CODECLONE_OBSERVABILITY_PERSIST="0",
    )
    assert cfg.enabled is True
    assert cfg.persist is False


def test_env_flag_false_values_are_honored() -> None:
    cfg = _resolve(
        CODECLONE_OBSERVABILITY_ENABLED="1",
        CODECLONE_OBSERVABILITY_CAPTURE_PAYLOAD_SIZES="false",
    )
    assert cfg.capture_payload_sizes is False


# ---------------------------------------------------------------------------
# Classification: these are the user's configuration, not CodeClone's faults
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_class",
    [ConfigValidationError, IntentRegistryConfigError, ObservabilityConfigError],
)
def test_every_configuration_family_is_classified_diagnosed(
    error_class: type[Exception],
) -> None:
    """The classification, not the instance.

    Each of these is raised only while validating configuration the user
    supplied, and each already names the exact key and the exact
    expectation. A family left off this list is a family the CLI envelope
    reports as "Unexpected exception" with a bug-report link -- measured on
    the observability family on 2026-09-01, and the reason the envelope now
    reads the marker class rather than a list of exceptions it has met.
    """

    assert issubclass(error_class, DiagnosedUserError)


def test_the_missing_perf_extra_carries_the_command_that_installs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measured condition, with the step that resolves it attached.

    The message alone told the user what was wrong and nothing about what to
    do; the envelope filled that gap with a traceback offer and a bug report,
    neither of which can help. The step belongs to the code that diagnosed
    the condition, because that is the only place that knows it.
    """

    monkeypatch.setattr("codeclone.config.observability.find_spec", lambda name: None)

    with pytest.raises(ObservabilityConfigError) as raised:
        _resolve(
            CODECLONE_OBSERVABILITY_ENABLED="1",
            CODECLONE_OBSERVABILITY_PROFILE="1",
        )

    assert str(raised.value) == (
        "observability profile=true requires the codeclone[perf] extra (psutil)."
    )
    assert raised.value.remediation == 'Run: pip install "codeclone[perf]"'


def test_a_family_that_has_nothing_to_add_carries_no_step() -> None:
    """A next step is attached where one exists, never invented."""

    assert ConfigValidationError("bad key").remediation == ""
