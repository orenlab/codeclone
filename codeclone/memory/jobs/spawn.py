# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ...observability import current_operation_context


@dataclass(frozen=True, slots=True)
class SpawnWorkerResult:
    spawned: bool
    reason: str | None
    pid: int | None


def _worker_env() -> dict[str, str] | None:
    """Subprocess env carrying the observability correlation handoff, or ``None``
    to inherit the parent environment unchanged (no active operation).
    """
    context = current_operation_context()
    if context is None:
        return None
    operation_id, correlation_id = context
    return {
        **os.environ,
        "CODECLONE_OBSERVABILITY_CORRELATION_ID": correlation_id,
        "CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID": operation_id,
    }


def spawn_projection_jobs_worker(*, root_path: Path) -> SpawnWorkerResult:
    root = root_path.resolve()
    argv = [
        sys.executable,
        "-m",
        "codeclone.main",
        "memory",
        "jobs",
        "run-once",
        "--root",
        str(root),
    ]
    try:
        proc = subprocess.Popen(
            argv,
            cwd=root,
            env=_worker_env(),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return SpawnWorkerResult(spawned=False, reason=str(exc), pid=None)
    return SpawnWorkerResult(spawned=True, reason=None, pid=proc.pid)


def run_projection_jobs_worker_sync(
    *, root_path: Path
) -> subprocess.CompletedProcess[str]:
    root = root_path.resolve()
    argv = [
        sys.executable,
        "-m",
        "codeclone.main",
        "memory",
        "jobs",
        "run-once",
        "--root",
        str(root),
    ]
    return subprocess.run(
        argv,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


__all__ = [
    "SpawnWorkerResult",
    "run_projection_jobs_worker_sync",
    "spawn_projection_jobs_worker",
]
