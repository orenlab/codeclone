# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Reusable separate-process proof for passive observer instrumentation."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


def assert_observability_subprocess_equality(
    *,
    disabled_command: Sequence[str],
    enabled_command: Sequence[str],
    disabled_cwd: Path,
    enabled_cwd: Path,
    disabled_artifacts: Mapping[str, Path],
    enabled_artifacts: Mapping[str, Path],
    environ: Mapping[str, str] | None = None,
    reset_paths: Sequence[Path] = (),
) -> None:
    """Assert equal exit status and canonical artifacts with observer off/on."""
    base_env = dict(os.environ)
    if environ is not None:
        base_env.update(environ)

    disabled_env = dict(base_env)
    disabled_env["CODECLONE_OBSERVABILITY_ENABLED"] = "0"
    disabled = subprocess.run(
        tuple(disabled_command),
        cwd=disabled_cwd,
        env=disabled_env,
        capture_output=True,
        check=False,
    )
    disabled_bytes = {
        name: artifact.read_bytes() for name, artifact in disabled_artifacts.items()
    }
    for path in reset_paths:
        path.unlink(missing_ok=True)

    enabled_env = dict(base_env)
    enabled_env["CODECLONE_OBSERVABILITY_ENABLED"] = "1"
    enabled = subprocess.run(
        tuple(enabled_command),
        cwd=enabled_cwd,
        env=enabled_env,
        capture_output=True,
        check=False,
    )

    assert disabled.returncode == enabled.returncode, (
        disabled.stdout,
        disabled.stderr,
        enabled.stdout,
        enabled.stderr,
    )
    assert set(disabled_artifacts) == set(enabled_artifacts)
    for name in sorted(disabled_artifacts):
        assert disabled_bytes[name] == enabled_artifacts[name].read_bytes()


__all__ = ["assert_observability_subprocess_equality"]
