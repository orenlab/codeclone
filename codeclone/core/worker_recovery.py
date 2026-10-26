# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Recovering the files a dead worker never returned: one isolated child.

``core.parallelism`` plans the run, launches the ordinary tasks and accepts
and merges their results. When a worker dies it hands the files it never got
back to this module, which owns everything about getting them back safely:
the single-use child, the per-file deadline, the control of that child, and
the error that ends the run when recovery fails (maintainer rulings
2026-10-26).

The child and the parent speak one protocol over one pipe::

    child -> parent  ("start", path)           about to run ``path``
    child -> parent  ("result", path, result)  ``path`` is done
    child -> parent  ("done",)                 nothing left to send

A file is confirmed only when its RESULT has arrived whole and passed
validation; a START confirms nothing. When the child dies or hangs, the file
it had started is the culprit; when it dies between files -- or before the
first -- no file was in flight and the culprit is UNKNOWN, never the last
name the parent happened to see. Each file has its own deadline. However the
recovery ends, the child is reaped and every descriptor it held is closed.
"""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Final, NoReturn

from ..analysis.phase_ledger import PhaseLedger
from ..models import ModuleRegistryHandle, RehydratedCacheNeutral
from ._types import FileProcessResult
from .worker import _install_module_registry

#: How long the parent waits on each file, in seconds: for the child to start
#: it, and again for its result. Measured 2026-10-26 on this repository (1423
#: files): the slowest file took 1.4 s (a 21 572-line test module), and a
#: fresh child spends about 0.8 s importing the engine before its first file.
#: 120 s is about fifty times that worst case -- room for a much slower
#: machine or a much larger generated file -- while a hung child still ends
#: the run within two minutes of the file it hung on.
ISOLATED_RECOVERY_TIMEOUT_SECONDS: Final = 120.0
UNKNOWN_CULPRIT: Final = "UNKNOWN"
_START: Final = "start"
_RESULT: Final = "result"
_DONE: Final = "done"
_FILE_SAMPLE: Final = 10
_CHILD_EXIT_GRACE_SECONDS: Final = 5.0


def _display_path(path: str, root: str) -> str:
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _sample(paths: Sequence[str], root: str) -> str:
    if not paths:
        return "0"
    shown = ", ".join(_display_path(path, root) for path in paths[:_FILE_SAMPLE])
    rest = len(paths) - _FILE_SAMPLE
    more = f" and {rest} more" if rest > 0 else ""
    return f"{len(paths)} ({shown}{more})"


def checked_result(result: object, filepath: str) -> FileProcessResult:
    """``result``, if it is a file result and the one for ``filepath``.

    Anything else breaks an engine invariant -- a worker answered for a file
    it was not given, or with something that is not an answer -- and is
    refused before any of it is accepted.
    """

    if not isinstance(result, FileProcessResult):
        raise TypeError(f"expected a file result, got {type(result).__name__}")
    if result.filepath != filepath:
        raise ValueError(f"the result is for {result.filepath}")
    return result


class WorkerRecoveryError(Exception):
    """The run cannot be completed: an internal error, exit 5.

    Raised when the isolated retry of a file the pool lost dies, hangs past
    its deadline or cannot start, or when a result breaks an engine
    invariant. It is not a truncation and not an unverified measurement: no
    report is produced, so no partial analysis can look complete and no
    baseline can be published from it. The message names three classes of
    files -- confirmed, the culprit (or UNKNOWN), and not processed -- with
    the reason and the attempts made on the culprit.
    """

    def __init__(
        self,
        *,
        root: str,
        culprit: str | None,
        reason: str,
        attempts: int,
        confirmed: Sequence[str],
        not_processed: Sequence[str],
    ) -> None:
        self.culprit = culprit
        self.reason = reason
        self.attempts = attempts
        self.confirmed = tuple(confirmed)
        self.not_processed = tuple(not_processed)
        head = (
            f"{_display_path(culprit, root)}: {reason}; "
            f"attempts on this file: {attempts}"
            if culprit is not None
            else f"{UNKNOWN_CULPRIT} culprit: {reason}"
        )
        super().__init__(
            f"analysis incomplete: {head}; "
            f"confirmed: {_sample(self.confirmed, root)}; "
            f"not processed: {_sample(self.not_processed, root)}"
        )

    @property
    def unverified(self) -> tuple[str, ...]:
        """Every file whose result was never accepted, the culprit first."""

        lead = (self.culprit,) if self.culprit is not None else ()
        return (*lead, *self.not_processed)


def _recovery_child(
    sender: Connection,
    registry: ModuleRegistryHandle,
    worker: Callable[..., FileProcessResult],
    files: Sequence[str],
    neutral_reuse: Mapping[str, RehydratedCacheNeutral | None],
    collect_phases: bool,
) -> None:
    """The child's side: announce each file, run it, send its whole result.

    The reuse lookup and the ledger come before the announcement, so a death
    there is a death between files, with no file in flight.
    """

    _install_module_registry(registry)
    for filepath in files:
        reuse = neutral_reuse.get(filepath)
        ledger = PhaseLedger(active=True) if collect_phases else None
        sender.send((_START, filepath))
        result = worker(filepath, phase_ledger=ledger, neutral_reuse=reuse)
        sender.send((_RESULT, filepath, result))
    sender.send((_DONE,))
    sender.close()


def _start_recovery_process(
    args: tuple[object, ...],
) -> tuple[BaseProcess, Connection]:
    """Start the one recovery child and return it with its channel."""

    receiver, sender = multiprocessing.Pipe(duplex=False)
    try:
        child = multiprocessing.Process(
            target=_recovery_child, args=(sender, *args), daemon=True
        )
        child.start()
    except BaseException:
        receiver.close()
        raise
    finally:
        # The parent's copy of the sending end must go, or a dead child never
        # reads as end-of-file and every death would wait out the deadline.
        sender.close()
    return child, receiver


class _Progress:
    """Which files are confirmed, and which one -- if any -- is in flight."""

    __slots__ = ("confirmed", "files", "in_flight")

    def __init__(self, *, files: Sequence[str], confirmed: Sequence[str]) -> None:
        self.files = files
        self.confirmed = list(confirmed)
        self.in_flight: str | None = None

    def remaining(self) -> list[str]:
        settled = set(self.confirmed)
        if self.in_flight is not None:
            settled.add(self.in_flight)
        return [path for path in self.files if path not in settled]


class _NoMessage(Exception):
    """The child sent nothing usable: it died, hung, or broke the protocol."""


def _next_message(child: BaseProcess, receiver: Connection) -> tuple[object, ...]:
    """The next whole message, within one file's deadline."""

    if not receiver.poll(ISOLATED_RECOVERY_TIMEOUT_SECONDS):
        raise _NoMessage(f"no result within {ISOLATED_RECOVERY_TIMEOUT_SECONDS:g} s")
    try:
        message = receiver.recv()
    except EOFError:
        child.join(timeout=_CHILD_EXIT_GRACE_SECONDS)
        raise _NoMessage(
            f"isolated process exited with code {child.exitcode}"
        ) from None
    if not isinstance(message, tuple) or not message:
        raise _NoMessage(f"isolated process sent {type(message).__name__}")
    return message


def _said_done(child: BaseProcess, receiver: Connection) -> bool:
    """Whether the child ended the conversation with DONE.

    Asked only once every file is confirmed, so a child that ends without it
    leaves nothing unverified: it is ended like a failed one, not blamed.
    Reading DONE before closing the channel also keeps the child from
    writing into a pipe its reader has already closed.
    """

    try:
        return _next_message(child, receiver) == (_DONE,)
    except _NoMessage:
        return False


def _release(child: BaseProcess, receiver: Connection, *, completed: bool) -> None:
    """Reap the child and close everything it held, however recovery ended."""

    receiver.close()
    if not completed and child.is_alive():
        child.kill()
    child.join(timeout=_CHILD_EXIT_GRACE_SECONDS)
    if child.is_alive():
        child.kill()
        child.join()
    child.close()


def recover_in_isolation(
    *,
    files: Sequence[str],
    lost: Collection[str],
    worker: Callable[..., FileProcessResult],
    registry: ModuleRegistryHandle,
    neutral_reuse: Mapping[str, RehydratedCacheNeutral | None],
    collect_phases: bool,
    accept: Callable[[FileProcessResult], None],
    on_advance: Callable[[], None] | None,
    root: str,
    already_confirmed: Sequence[str] = (),
) -> None:
    """Run ``files`` once each in one single-use child and ``accept`` every
    confirmed result, or raise :class:`WorkerRecoveryError`.

    ``lost`` are the files the pool was given and never returned: a culprit
    among them has had two attempts, any other one. ``already_confirmed``
    are the files whose results the parent accepted before recovery; an
    error counts them with the files confirmed here, so its three classes
    cover the whole run. No second child is ever started, so a limit that
    kills every process cannot turn recovery into a chain of spawns.
    """

    progress = _Progress(files=files, confirmed=already_confirmed)

    def fail(reason: str, cause: BaseException | None = None) -> NoReturn:
        culprit = progress.in_flight
        raise WorkerRecoveryError(
            root=root,
            culprit=culprit,
            reason=reason,
            attempts=(2 if culprit in lost else 1) if culprit is not None else 0,
            confirmed=progress.confirmed,
            not_processed=progress.remaining(),
        ) from cause

    try:
        child, receiver = _start_recovery_process(
            (registry, worker, tuple(files), neutral_reuse, collect_phases)
        )
    except Exception as exc:
        fail(f"recovery process could not start: {exc}", exc)
    completed = False
    try:
        for filepath in files:
            try:
                started = _next_message(child, receiver)
                if started != (_START, filepath):
                    raise _NoMessage(f"expected the start of {filepath}")
                progress.in_flight = filepath
                finished = _next_message(child, receiver)
            except _NoMessage as exc:
                fail(str(exc))
            try:
                if len(finished) != 3 or finished[:2] != (_RESULT, filepath):
                    raise ValueError(f"expected the result of {filepath}")
                accept(checked_result(finished[2], filepath))
            except Exception as exc:
                fail(f"result breaks an engine invariant: {exc}", exc)
            progress.confirmed.append(filepath)
            progress.in_flight = None
            if on_advance is not None:
                on_advance()
        completed = _said_done(child, receiver)
    finally:
        _release(child, receiver, completed=completed)


__all__ = [
    "ISOLATED_RECOVERY_TIMEOUT_SECONDS",
    "UNKNOWN_CULPRIT",
    "WorkerRecoveryError",
    "checked_result",
    "recover_in_isolation",
]
