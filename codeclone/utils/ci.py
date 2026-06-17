# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""CI environment detection.

A pure env check with no project dependencies, so any layer (config, memory,
observability) can import it without an upward dependency. Single source — the
memory jobs module re-exports it for its existing callers.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

_CI_ENV_KEYS: tuple[str, ...] = (
    "CI",
    "GITHUB_ACTIONS",
    "BUILDKITE",
    "TF_BUILD",
    "TEAMCITY_VERSION",
)


def is_ci_environment(environ: Mapping[str, str] | None = None) -> bool:
    active = environ if environ is not None else os.environ
    return any(active.get(key, "").strip() for key in _CI_ENV_KEYS)


__all__ = ["is_ci_environment"]
