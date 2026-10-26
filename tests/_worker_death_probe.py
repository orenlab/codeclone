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

Every call records ``<pid> <file name>`` in ``attempts.log`` in the
``probe`` directory beside the project the file belongs to, so a test can
prove which process ran which file -- above all, that the parent never ran a
file a worker died on.
"""

from __future__ import annotations

import dataclasses
import errno
import multiprocessing
import os
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path

from codeclone.core import worker as _worker
from codeclone.core._types import FileProcessResult

PROBE_DIR_NAME = "probe"
WORKER_KILLER_PREFIX = "worker_killer"
HANG_SECONDS = 30.0
BROKEN_PIPE_MARKER = "broken-pipe"


def _probe_dir(filepath: str) -> Path:
    """The ``probe`` directory beside the project directory holding
    ``filepath``. Derived from the file, never from the environment: a
    forkserver keeps the environment it started with, so a variable a later
    test sets never reaches the workers it forks."""

    return Path(filepath).parent.parent / PROBE_DIR_NAME


def _record(filepath: str) -> None:
    with (_probe_dir(filepath) / "attempts.log").open("a", encoding="utf-8") as log:
        log.write(f"{os.getpid()} {Path(filepath).name}\n")


def _in_child() -> bool:
    return multiprocessing.parent_process() is not None


def _is_killer(filepath: str) -> bool:
    return Path(filepath).name.startswith(WORKER_KILLER_PREFIX)


def _first_attempt(filepath: str) -> bool:
    marker = _probe_dir(filepath) / f"{Path(filepath).name}.attempted"
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


def raise_once_in_worker(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    """The marked file raises in the first worker that runs it: the task is
    lost with an error of its own, and the worker lives on."""

    _record(filepath)
    if _in_child() and _is_killer(filepath) and _first_attempt(filepath):
        raise RuntimeError("the task failed in its worker")
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


# -- probes for the recovery child alone (``worker_recovery``) ---------------

SLOW_SECONDS = 1.2


def _named(filepath: str, name: str) -> bool:
    return Path(filepath).name == name


def run_in_child(filepath: str, *args: object, **kwargs: object) -> FileProcessResult:
    """The real worker, recorded: the baseline every other probe departs from."""

    _record(filepath)
    return _real(filepath, *args, **kwargs)


def die_in_child_on_b(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    _record(filepath)
    if _in_child() and _named(filepath, "b.py"):
        os._exit(13)
    return _real(filepath, *args, **kwargs)


def hang_in_child_on_b(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    _record(filepath)
    if _in_child() and _named(filepath, "b.py"):
        time.sleep(HANG_SECONDS)
    return _real(filepath, *args, **kwargs)


def slow_in_child(filepath: str, *args: object, **kwargs: object) -> FileProcessResult:
    """Every file takes ``SLOW_SECONDS`` in the child: a queue whose total
    outlasts one file's deadline while no single file does."""

    _record(filepath)
    if _in_child():
        time.sleep(SLOW_SECONDS)
    return _real(filepath, *args, **kwargs)


def answer_for_a_on_b(
    filepath: str, *args: object, **kwargs: object
) -> FileProcessResult:
    """For ``b.py`` the child sends the result of ``a.py``."""

    _record(filepath)
    if _in_child() and _named(filepath, "b.py"):
        return _real(str(Path(filepath).with_name("a.py")), *args, **kwargs)
    return _real(filepath, *args, **kwargs)


class DieOnLookup(dict):  # type: ignore[type-arg]
    """A reuse mapping whose lookup for the file ``name`` kills the child.

    The child looks a file's reuse up before it announces the file, so the
    death lands before that file is started and after every earlier result:
    no file is in flight, and the culprit is unknown. For the first file it
    is a death before any file at all. It reaches the child the same way
    whether the start method pickles the arguments or forks with them.
    """

    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name

    def get(self, key: object, default: object = None) -> object:
        if _in_child() and _named(str(key), self.name):
            os._exit(13)
        return super().get(key, default)


class RefusedProcess:
    """A process the operating system will not start: ``start`` fails the
    way ``fork`` does at a process limit."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.pid = None

    def start(self) -> None:
        raise OSError(errno.EAGAIN, "Resource temporarily unavailable")


class UnstartableProcess(RefusedProcess):
    """A process that fails to start for a cause nobody proved to be the
    environment's."""

    def start(self) -> None:
        raise RuntimeError("the start method is misconfigured")


def speak(
    sender: Connection,
    script: tuple[tuple[object, ...], ...],
    worker: Callable[..., FileProcessResult],
    files: tuple[str, ...],
) -> None:
    """A recovery child that says exactly ``script`` and then ends.

    ``("start", i)`` and ``("result", i)`` speak for ``files[i]`` -- the
    result is the real one -- ``("result-only", i)`` sends a result message
    cut short, ``("result-not-a-result", i)`` one whose result is a string,
    ``("raw", value)`` sends ``value`` as it is and
    ``("pause", seconds)`` waits. It never says DONE unless the script does.
    A message the parent no longer listens for is recorded as a
    ``broken-pipe`` marker in the probe directory.
    """

    try:
        for step in script:
            _say(sender, step, worker, files)
    except BrokenPipeError:
        (_probe_dir(files[0]) / BROKEN_PIPE_MARKER).touch()
    sender.close()


def _say(
    sender: Connection,
    step: tuple[object, ...],
    worker: Callable[..., FileProcessResult],
    files: tuple[str, ...],
) -> None:
    kind = step[0]
    if kind == "raw":
        sender.send(step[1])
    elif kind == "pause":
        time.sleep(float(str(step[1])))
    elif kind == "done":
        sender.send(("done",))
    else:
        path = files[int(str(step[1]))]
        if kind == "result":
            outcome = worker(path, phase_ledger=None, neutral_reuse=None)
            sender.send(("result", path, outcome))
        elif kind == "result-only":
            sender.send(("result", path))
        elif kind == "result-not-a-result":
            sender.send(("result", path, "not a result"))
        else:
            sender.send((kind, path))
