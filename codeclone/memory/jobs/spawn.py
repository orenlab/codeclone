# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Start the projection worker for a repository without ever running it.

The worker is ``python -m codeclone.main memory jobs run-once --root <repo>``.
It reaches the analysed repository only through the explicit ``--root``
argument: its import path and its working directory stay outside the
repository, so a module there named like a worker dependency is never
imported (``python -m`` would otherwise put the working directory first on
``sys.path``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ...observability import current_operation_context

# Read only by the MCP server's HTTP transport at startup
# (``codeclone.surfaces.mcp.auth.MCP_AUTH_TOKEN_ENV``). The worker never needs
# it, so it is not handed to a process that works beside untrusted code.
_WITHHELD_WORKER_ENV: Final = frozenset({"CODECLONE_MCP_AUTH_TOKEN"})


@dataclass(frozen=True, slots=True)
class SpawnWorkerResult:
    spawned: bool
    reason: str | None
    pid: int | None


def _inherited_env() -> dict[str, str]:
    """The parent environment minus what the worker must not hold."""
    return {
        name: value
        for name, value in os.environ.items()
        if name not in _WITHHELD_WORKER_ENV
    }


def _worker_env() -> dict[str, str]:
    """The inherited environment, plus the observability correlation handoff
    while an operation is active.
    """
    env = _inherited_env()
    context = current_operation_context()
    if context is None:
        return env
    operation_id, correlation_id = context
    env["CODECLONE_OBSERVABILITY_CORRELATION_ID"] = correlation_id
    env["CODECLONE_OBSERVABILITY_PARENT_OPERATION_ID"] = operation_id
    return env


def _isolation_flag(flags: object) -> str:
    """The interpreter switch that keeps the working directory off the
    worker's ``sys.path``.

    ``-P`` exists exactly where ``sys.flags`` has ``safe_path`` (3.11+) and
    drops only that entry, so user site, ``PYTHONPATH`` and the other
    ``PYTHON*`` settings keep working as in the parent. 3.10 has no ``-P``;
    isolated mode ``-I`` is its only switch that drops the entry, and it also
    drops user site and every ``PYTHON*`` variable.
    """
    return "-P" if hasattr(flags, "safe_path") else "-I"


def _worker_cwd() -> Path:
    """The filesystem root: never inside the analysed repository and not
    writable by other users on POSIX, so neither an empty ``PYTHONPATH``
    entry (which ``-P`` keeps) nor a stray relative path reaches the
    repository.
    """
    return Path(os.path.abspath(os.sep))


def _run_once_argv(root: Path, *, not_before_utc: str | None = None) -> list[str]:
    """Argv for the ``memory jobs run-once`` worker subprocess. A non-empty
    ``not_before_utc`` adds ``--not-before <utc>`` so the worker defers its model
    load and corpus drain until that deadline (delayed single-shot flush).
    """
    argv = [
        sys.executable,
        _isolation_flag(sys.flags),
        "-m",
        "codeclone.main",
        "memory",
        "jobs",
        "run-once",
        "--root",
        str(root),
    ]
    if not_before_utc:
        argv += ["--not-before", not_before_utc]
    return argv


def spawn_projection_jobs_worker(
    *, root_path: Path, not_before_utc: str | None = None
) -> SpawnWorkerResult:
    root = root_path.resolve()
    argv = _run_once_argv(root, not_before_utc=not_before_utc)
    try:
        proc = subprocess.Popen(
            argv,
            cwd=_worker_cwd(),
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
    argv = _run_once_argv(root)
    return subprocess.run(
        argv,
        cwd=_worker_cwd(),
        env=_inherited_env(),
        check=False,
        capture_output=True,
        text=True,
    )


__all__ = [
    "SpawnWorkerResult",
    "run_projection_jobs_worker_sync",
    "spawn_projection_jobs_worker",
]
