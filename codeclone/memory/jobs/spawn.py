# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SpawnWorkerResult:
    spawned: bool
    reason: str | None
    pid: int | None


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
