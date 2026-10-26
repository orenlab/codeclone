# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Worker entry points that die, hang or misbehave on purpose.

Each stands in for ``codeclone.core.parallelism._invoke_process_file`` and is
pickled by reference into real child processes -- the pool's workers and the
isolated recovery child -- so they live in an importable module. A death is
``os._exit``: the abrupt end a segfault or the out-of-memory killer gives,
which no ``try``/``except`` in that process can intercept.

Every call records ``<pid> <file name>`` in ``attempts.log`` under the
directory named by ``CODECLONE_TEST_WORKER_PROBE_DIR``, so a test can prove
which process ran which file -- above all, that the parent never ran a file
a worker died on.
"""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import time
from pathlib import Path

from codeclone.core import worker as _worker
from codeclone.core._types import FileProcessResult

PROBE_DIR_ENV = "CODECLONE_TEST_WORKER_PROBE_DIR"
WORKER_KILLER_PREFIX = "worker_killer"
HANG_SECONDS = 30.0


def _probe_dir() -> Path:
    return Path(os.environ[PROBE_DIR_ENV])


def _record(filepath: str) -> None:
    with (_probe_dir() / "attempts.log").open("a", encoding="utf-8") as log:
        log.write(f"{os.getpid()} {Path(filepath).name}\n")


def _in_child() -> bool:
    return multiprocessing.parent_process() is not None


def _is_killer(filepath: str) -> bool:
    return Path(filepath).name.startswith(WORKER_KILLER_PREFIX)


def _first_attempt(filepath: str) -> bool:
    marker = _probe_dir() / f"{Path(filepath).name}.attempted"
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    return True


def _real(filepath: str, *args: object, **kwargs: object) -> FileProcessResult:
    return _worker._invoke_process_file(filepath, *args, **kwargs)  # type: ignore[arg-type]


def die_once_in_worker(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    """The marked file kills the first process that runs it, and only that."""

    _record(filepath)
    if _in_child() and _is_killer(filepath) and _first_attempt(filepath):
        os._exit(13)
    return _real(filepath, *args, **kwargs)


def die_always_in_worker(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    """The marked file kills every child process that runs it."""

    _record(filepath)
    if _in_child() and _is_killer(filepath):
        os._exit(13)
    return _real(filepath, *args, **kwargs)


def hang_after_first_death(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    """The marked file kills its first process and hangs the next one."""

    _record(filepath)
    if _in_child() and _is_killer(filepath):
        if _first_attempt(filepath):
            os._exit(13)
        time.sleep(HANG_SECONDS)
    return _real(filepath, *args, **kwargs)


def die_on_every_file(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    """A limit that kills every child, whatever file it runs."""

    _record(filepath)
    if _in_child():
        os._exit(13)
    return _real(filepath, *args, **kwargs)


def answer_for_another_file(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    """The marked file comes back as the result of a real sibling, ``a00.py``:
    nothing downstream would refuse it, so only the identity check can."""

    _record(filepath)
    if _is_killer(filepath):
        sibling = str(Path(filepath).with_name("a00.py"))
        return dataclasses.replace(_real(sibling, *args, **kwargs), filepath=sibling)
    return _real(filepath, *args, **kwargs)


def unreadable_everywhere(
    filepath: str, *_args: object, **_kwargs: object
) -> FileProcessResult:
    """A typed per-file failure: a confirmed outcome, not a lost file."""

    return FileProcessResult(
        filepath=filepath,
        success=False,
        source_content_digest=None,
        error="Cannot read file: gone",
        error_kind="source_read_error",
    )
