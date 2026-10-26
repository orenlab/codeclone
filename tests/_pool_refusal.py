# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A worker pool whose start fails, for suites that read a surface above it.

The surface suites (MCP) bind their own ring and may not import the engine's
pool module; the refusal is installed from here, as the conftest builders do
for the same reason.
"""

from __future__ import annotations

import errno
import multiprocessing
import os
from types import SimpleNamespace

import pytest

import codeclone.core.parallelism as core_parallelism
import codeclone.core.worker_recovery as core_recovery
from codeclone.core.parallelism import _parallel_min_files
from tests import _worker_death_probe as probe

#: What a real process limit raised at pool start on spawn, forkserver and
#: fork alike (measured 2026-10-26).
PROCESS_LIMIT_REFUSAL = BlockingIOError(
    errno.EAGAIN, "Resource temporarily unavailable"
)


class _RefusedPool:
    """A pool whose start fails with :attr:`error`, where the real one does."""

    error: BaseException = PROCESS_LIMIT_REFUSAL

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise self.error


def files_for_a_pool(processes: int) -> int:
    """How many files make a run of ``processes`` workers start its pool."""

    return _parallel_min_files(processes) + 1


def crash_a_worker_and_refuse_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """The file named ``worker_killer*`` kills the first worker that runs it,
    and the operating system then refuses the recovery process (EAGAIN).
    The probe directory sits beside the project, as the probe requires."""

    monkeypatch.setattr(
        core_parallelism, "_invoke_process_file", probe.die_once_in_worker
    )
    monkeypatch.setattr(
        core_recovery,
        "multiprocessing",
        SimpleNamespace(Pipe=multiprocessing.Pipe, Process=probe.RefusedProcess),
    )
    monkeypatch.setattr(os, "cpu_count", lambda: 4)


KILLER_FILE = f"{probe.WORKER_KILLER_PREFIX}_mod.py"
PROBE_DIR_NAME = probe.PROBE_DIR_NAME


def refuse_the_pool(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    """Make every pool start fail with ``error``."""

    monkeypatch.setattr(_RefusedPool, "error", error)
    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _RefusedPool)
    # The MCP server caps the pool at the host's CPUs; a one-CPU runner would
    # never start a pool at all, and the probe would prove nothing.
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
