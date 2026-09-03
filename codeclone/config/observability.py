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
import sys
from collections.abc import Mapping
from importlib.util import find_spec

from ..budget.estimator import (
    TOKEN_ESTIMATOR_CHARS_APPROX,
    TOKEN_ESTIMATOR_MODES,
    TOKEN_ESTIMATOR_TIKTOKEN,
)
from ..contracts.errors import DiagnosedUserError
from ..models import (
    DEFAULT_OBSERVABILITY_MAX_OPERATIONS,
    DEFAULT_OBSERVABILITY_MAX_SPANS,
    DEFAULT_OBSERVABILITY_RETENTION_DAYS,
    DEFAULT_OBSERVABILITY_TOKEN_ESTIMATOR,
    ObservabilityConfig,
)
from ..utils.ci import is_ci_environment

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class ObservabilityConfigError(DiagnosedUserError, ValueError):
    """Invalid observability configuration (profile without [perf], reserved key)."""


_DISABLED = ObservabilityConfig(enabled=False)


def _env_flag(environ: Mapping[str, str], key: str, *, default: bool = False) -> bool:
    raw = environ.get(key, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return default


def _positive_env_int(environ: Mapping[str, str], key: str, *, default: int) -> int:
    raw = environ.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ObservabilityConfigError(
            f"observability {key} must be a positive integer"
        ) from exc
    if value <= 0:
        raise ObservabilityConfigError(
            f"observability {key} must be a positive integer"
        )
    return value


def _resolve_token_estimator(environ: Mapping[str, str]) -> tuple[str, bool]:
    """Return ``(effective_mode, downgraded)`` for the payload token estimator.

    ``chars_approx`` stays the default: the MCP server is a long-lived process
    and tiktoken keeps native encoding state resident once imported. The probe
    for tiktoken therefore runs only when the exact mode is actually requested.

    A missing tiktoken downgrades rather than raising — unlike ``profile``,
    which has no weaker correct answer and must not be silently off. The
    downgrade is returned as a fact so nothing downstream can present
    approximated units as an exact tokenizer count.
    """
    raw = environ.get("CODECLONE_OBSERVABILITY_TOKEN_ESTIMATOR", "").strip().lower()
    if not raw:
        return DEFAULT_OBSERVABILITY_TOKEN_ESTIMATOR, False
    if raw not in TOKEN_ESTIMATOR_MODES:
        expected = ", ".join(sorted(TOKEN_ESTIMATOR_MODES))
        raise ObservabilityConfigError(
            f"observability token estimator must be one of: {expected}"
        )
    if raw == TOKEN_ESTIMATOR_TIKTOKEN and find_spec("tiktoken") is None:
        return TOKEN_ESTIMATOR_CHARS_APPROX, True
    return raw, False


_PERF_UNSET_STEP = "Or unset CODECLONE_OBSERVABILITY_PROFILE to run without profiling."


def _perf_extra_steps() -> tuple[str, ...]:
    """The two ways out of a missing ``perf`` extra, and where the first applies.

    Measured 2026-09-02: the extra was installed with
    ``uv sync --upgrade --all-extras`` and the refusal came back word for
    word, because the ``codeclone`` on PATH was a shim into a uv-tool
    environment that ``uv sync`` never fills. The sentence was true about an
    interpreter it declined to name, so the step it offered had already been
    performed -- somewhere else -- and the user had nowhere left to go. A
    remediation that does not identify its own subject is a loop.

    ``sys.executable`` is the answer because it is the environment that
    actually lacks psutil, whatever installed it and whatever the shim on
    PATH is called. It is documented as possibly empty, and an unnamed
    interpreter still gets the step without the subject rather than a step
    with a hole in it.

    The second way out is not a footnote. The first asks the user to write to
    an environment they may not own -- a uv-tool install, a system Python, a
    container image built elsewhere -- and the flag that asked for profiling
    is theirs in every one of those cases.

    The path is put in the remediation and never in the message: this is a
    local diagnostic for the terminal of the person who owns that filesystem,
    and ``remediation`` is read only there, while the message travels into
    MCP responses, logs, and pasted bug reports.
    """

    interpreter = sys.executable
    if not interpreter:
        return (
            "Install the extra into the environment running CodeClone: "
            'pip install "codeclone[perf]"',
            _PERF_UNSET_STEP,
        )
    return (
        "Install the extra into the interpreter running CodeClone: "
        f'"{interpreter}" -m pip install "codeclone[perf]"',
        _PERF_UNSET_STEP,
    )


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
            "observability profile=true requires the codeclone[perf] extra (psutil).",
            remediation=_perf_extra_steps(),
        )
    token_estimator, token_estimator_downgraded = _resolve_token_estimator(env)
    return ObservabilityConfig(
        enabled=True,
        persist=_env_flag(env, "CODECLONE_OBSERVABILITY_PERSIST", default=True),
        profile=profile,
        capture_payload_sizes=_env_flag(
            env, "CODECLONE_OBSERVABILITY_CAPTURE_PAYLOAD_SIZES", default=True
        ),
        retention_days=_positive_env_int(
            env,
            "CODECLONE_OBSERVABILITY_RETENTION_DAYS",
            default=DEFAULT_OBSERVABILITY_RETENTION_DAYS,
        ),
        max_operations_per_process=_positive_env_int(
            env,
            "CODECLONE_OBSERVABILITY_MAX_OPERATIONS_PER_PROCESS",
            default=DEFAULT_OBSERVABILITY_MAX_OPERATIONS,
        ),
        max_spans_per_operation=_positive_env_int(
            env,
            "CODECLONE_OBSERVABILITY_MAX_SPANS_PER_OPERATION",
            default=DEFAULT_OBSERVABILITY_MAX_SPANS,
        ),
        token_estimator=token_estimator,
        token_estimator_downgraded=token_estimator_downgraded,
    )


__all__ = [
    "ObservabilityConfigError",
    "resolve_observability_config",
]
