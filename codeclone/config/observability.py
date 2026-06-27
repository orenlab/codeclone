# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Platform observability configuration.

Env-first resolution. Default OFF — when disabled, this does the minimal env
check and never imports psutil, never opens a store, never parses a pyproject
observability section (the near-zero-overhead contract, §4.2). The pyproject
``[tool.codeclone.observability]`` table is a later-cycle convenience; for now
every knob is an environment override.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.util import find_spec

from ..utils.ci import is_ci_environment

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

DEFAULT_OBSERVABILITY_RETENTION_DAYS = 7
DEFAULT_OBSERVABILITY_MAX_OPERATIONS = 2000
DEFAULT_OBSERVABILITY_MAX_SPANS = 100


class ObservabilityConfigError(ValueError):
    """Invalid observability configuration (profile without [perf], reserved key)."""


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    enabled: bool
    persist: bool = True
    profile: bool = False
    capture_payload_sizes: bool = True
    retention_days: int = DEFAULT_OBSERVABILITY_RETENTION_DAYS
    max_operations_per_process: int = DEFAULT_OBSERVABILITY_MAX_OPERATIONS
    max_spans_per_operation: int = DEFAULT_OBSERVABILITY_MAX_SPANS


_DISABLED = ObservabilityConfig(enabled=False)


def _env_flag(environ: Mapping[str, str], key: str, *, default: bool = False) -> bool:
    raw = environ.get(key, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return default


def resolve_observability_config(
    *, environ: Mapping[str, str] | None = None
) -> ObservabilityConfig:
    """Resolve config from the environment. Returns the frozen disabled config
    (default) without touching psutil/sqlite when observability is off."""
    env = environ if environ is not None else os.environ
    raw_enabled = env.get("CODECLONE_OBSERVABILITY_ENABLED", "").strip().lower()
    if raw_enabled in _FALSE:
        return _DISABLED
    explicit_on = raw_enabled in _TRUE
    force = _env_flag(env, "CODECLONE_OBSERVABILITY_FORCE")
    # CI disables collection unless explicitly enabled or forced (mirror of the
    # projection-job CI skip, opposite default). FORCE only lifts the CI gate;
    # it does not enable on its own.
    if is_ci_environment(env) and not force and not explicit_on:
        return _DISABLED
    if not explicit_on:
        return _DISABLED
    if _env_flag(env, "CODECLONE_OBSERVABILITY_PAYLOAD_SNAPSHOT"):
        raise ObservabilityConfigError(
            "observability payload_snapshot is reserved and rejected (MVP)."
        )
    profile = _env_flag(env, "CODECLONE_OBSERVABILITY_PROFILE")
    if profile and find_spec("psutil") is None:
        raise ObservabilityConfigError(
            "observability profile=true requires the codeclone[perf] extra (psutil)."
        )
    return ObservabilityConfig(
        enabled=True,
        persist=_env_flag(env, "CODECLONE_OBSERVABILITY_PERSIST", default=True),
        profile=profile,
        capture_payload_sizes=_env_flag(
            env, "CODECLONE_OBSERVABILITY_CAPTURE_PAYLOAD_SIZES", default=True
        ),
    )


__all__ = [
    "ObservabilityConfig",
    "ObservabilityConfigError",
    "resolve_observability_config",
]
