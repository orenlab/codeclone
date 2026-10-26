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

import errno
import multiprocessing
import os
from collections.abc import Callable, Collection, Mapping, Sequence
from concurrent.futures.process import BrokenProcessPool
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from types import MappingProxyType
from typing import Final, NoReturn

from ..analysis.phase_ledger import PhaseLedger
from ..contracts.errors import IncompleteAnalysisError
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


#: Why the operating system refused to create a process, by ``errno``, when
#: the cause is proven to be the environment's and not CodeClone's: each is a
#: limit or a refusal it imposes on starting processes or on the
#: process-shared primitives a worker pool needs (maintainer rulings
#: 2026-10-26). Read ONLY for an operation that creates processes -- a pool's
#: construction and its ``submit``, the recovery child's start -- and only off
#: the errno the operating system set: an ``OSError`` raised without one, or
#: by anything else, proves nothing about the environment. EAGAIN is what a
#: real process limit raised on spawn, forkserver and fork alike (measured
#: 2026-10-26); EWOULDBLOCK is the same number on Linux and macOS.
PROCESS_CREATION_REFUSALS: Final[Mapping[int, str]] = MappingProxyType(
    {
        errno.EAGAIN: "a process or thread limit was reached",
        errno.ENOMEM: "there was not enough memory to start a worker process",
        errno.EMFILE: "the per-process limit on open files was reached",
        errno.ENFILE: "the system-wide limit on open files was reached",
        errno.EPERM: (
            "the operating system or a sandbox refused to start a worker process"
        ),
        errno.EACCES: (
            "the operating system or a sandbox refused a resource the pool needs"
        ),
        errno.ENOSYS: (
            "the platform does not provide the process-shared semaphores the pool needs"
        ),
        errno.ENOSPC: (
            "there was no room for the process-shared semaphores the pool needs"
        ),
    }
)


def process_creation_refusal(error: BaseException) -> str | None:
    """Why the environment refused to create a process, if ``error`` -- raised
    by an operation that creates one -- proves it did.

    ``None`` for every other failure, an unknown one included: an unproven
    cause is never called the environment's, because that would hide what
    may be CodeClone's own defect.
    """

    if isinstance(error, OSError) and error.errno is not None:
        return PROCESS_CREATION_REFUSALS.get(error.errno)
    return None


def _named(error: BaseException) -> str:
    return f"{type(error).__name__}: {error}"


def process_creation_failure(error: BaseException) -> dict[str, object]:
    """A failed process creation, as a failure the diagnosis can carry: the
    errno's name when it proves the environment refused, the error as it is
    otherwise."""

    if isinstance(error, OSError) and process_creation_refusal(error) is not None:
        return {
            "reason": "process_creation_unavailable",
            "errno": errno.errorcode.get(error.errno or 0, str(error.errno)),
            "detail": str(error),
        }
    return {"reason": "process_creation_failed", "detail": _named(error)}


def lost_task_failure(error: BaseException) -> dict[str, object]:
    """Why the pool did not return a file: its worker crashed -- for a cause
    nobody knows -- or the task failed with an error of its own."""

    if isinstance(error, BrokenProcessPool):
        return {"reason": "worker_crashed", "cause": "unknown", "detail": str(error)}
    return {"reason": "worker_failed", "detail": _named(error)}


_FAILURE_WORDS: Final = MappingProxyType(
    {
        "worker_crashed": "worker crashed (cause unknown): {detail}",
        "worker_failed": "worker failed: {detail}",
        "process_creation_unavailable": "process creation refused: {detail}",
        "process_creation_failed": "process creation failed: {detail}",
        "pool_failed": "worker pool failed: {detail}",
    }
)


def _describe(failure: Mapping[str, object]) -> str:
    template = _FAILURE_WORDS.get(str(failure.get("reason")), "{reason}: {detail}")
    return template.format(reason=failure.get("reason"), detail=failure.get("detail"))


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


class WorkerRecoveryError(IncompleteAnalysisError):
    """The run cannot be completed: an internal error, exit 5.

    Raised when the isolated retry of a file the pool lost dies, hangs past
    its deadline or cannot start, or when a result breaks an engine
    invariant. It is not a truncation and not an unverified measurement: no
    report is produced, so no partial analysis can look complete and no
    baseline can be published from it. The message names three classes of
    files -- confirmed, the culprit (or UNKNOWN), and not processed -- with
    the attempts made on the culprit.

    A secondary failure must not erase the primary one (maintainer law
    2026-10-26): ``primary_failure`` is why recovery was needed at all -- a
    worker that crashed for a cause nobody knows, or a pool that failed --
    and ``recovery_failure`` why recovery did not finish. Both are kept, the
    first first, in the message and in :meth:`diagnosis`. Exit 5 even when
    the recovery was refused by the environment: the first failure is still
    unexplained, so the environment is not proven to be the whole story.
    """

    def __init__(
        self,
        *,
        root: str,
        culprit: str | None,
        failure: str,
        attempts: int,
        confirmed: Sequence[str],
        not_processed: Sequence[str],
        primary_failure: Mapping[str, object] | None = None,
        recovery_failure: Mapping[str, object] | None = None,
    ) -> None:
        self.culprit = culprit
        self.failure = failure
        self.attempts = attempts
        self.confirmed = tuple(confirmed)
        self.not_processed = tuple(not_processed)
        self.primary_failure = (
            None if primary_failure is None else dict(primary_failure)
        )
        self.recovery_failure = (
            None if recovery_failure is None else dict(recovery_failure)
        )
        self.reason = (
            "worker_recovery_failed"
            if recovery_failure is not None
            else "engine_invariant"
        )
        self._culprit_shown = None if culprit is None else _display_path(culprit, root)
        head = (
            f"{self._culprit_shown}: {failure}; attempts on this file: {attempts}"
            if self._culprit_shown is not None
            else f"{UNKNOWN_CULPRIT} culprit: {failure}"
        )
        # The first failure leads whenever a second one followed it.
        first = (
            f"{_describe(self.primary_failure)}; then "
            if self.primary_failure is not None and self.recovery_failure is not None
            else ""
        )
        super().__init__(
            f"analysis incomplete: {first}{head}; "
            f"confirmed: {_sample(self.confirmed, root)}; "
            f"not processed: {_sample(self.not_processed, root)}"
        )

    def diagnosis(self) -> dict[str, object]:
        return {
            "primary_failure": self.primary_failure,
            "recovery_failure": self.recovery_failure,
            "culprit": self._culprit_shown,
            "attempts": self.attempts,
            "confirmed": len(self.confirmed),
            "not_processed": len(self.not_processed),
        }

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
    """The child sent nothing usable: it died, hung, or broke the protocol.
    ``failure`` says which, as the diagnosis carries it."""

    def __init__(self, text: str, failure: Mapping[str, object]) -> None:
        super().__init__(text)
        self.failure = dict(failure)


def _protocol_breach(text: str) -> _NoMessage:
    return _NoMessage(text, {"reason": "protocol_breach", "detail": text})


def _next_message(child: BaseProcess, receiver: Connection) -> tuple[object, ...]:
    """The next whole message, within one file's deadline."""

    if not receiver.poll(ISOLATED_RECOVERY_TIMEOUT_SECONDS):
        raise _NoMessage(
            f"no result within {ISOLATED_RECOVERY_TIMEOUT_SECONDS:g} s",
            {
                "reason": "recovery_timed_out",
                "seconds": ISOLATED_RECOVERY_TIMEOUT_SECONDS,
            },
        )
    try:
        message = receiver.recv()
    except EOFError:
        child.join(timeout=_CHILD_EXIT_GRACE_SECONDS)
        raise _NoMessage(
            f"isolated process exited with code {child.exitcode}",
            {"reason": "recovery_crashed", "exit_code": child.exitcode},
        ) from None
    if not isinstance(message, tuple) or not message:
        raise _protocol_breach(f"isolated process sent {type(message).__name__}")
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
    primary_failure: Mapping[str, object] | None = None,
) -> None:
    """Run ``files`` once each in one single-use child and ``accept`` every
    confirmed result, or raise :class:`WorkerRecoveryError`.

    ``lost`` are the files the pool was given and never returned: a culprit
    among them has had two attempts, any other one. ``already_confirmed``
    are the files whose results the parent accepted before recovery; an
    error counts them with the files confirmed here, so its three classes
    cover the whole run. ``primary_failure`` is why recovery was needed; an
    error keeps it ahead of its own. No second child is ever started, so a
    limit that kills every process cannot turn recovery into a chain of
    spawns.
    """

    progress = _Progress(files=files, confirmed=already_confirmed)

    def fail(
        failure: str,
        recovery_failure: Mapping[str, object],
        cause: BaseException | None = None,
    ) -> NoReturn:
        culprit = progress.in_flight
        raise WorkerRecoveryError(
            root=root,
            culprit=culprit,
            failure=failure,
            attempts=(2 if culprit in lost else 1) if culprit is not None else 0,
            confirmed=progress.confirmed,
            not_processed=progress.remaining(),
            primary_failure=primary_failure,
            recovery_failure=recovery_failure,
        ) from cause

    try:
        child, receiver = _start_recovery_process(
            (registry, worker, tuple(files), neutral_reuse, collect_phases)
        )
    except Exception as exc:
        fail(
            f"recovery process could not start: {exc}",
            process_creation_failure(exc),
            exc,
        )
    completed = False
    try:
        for filepath in files:
            try:
                started = _next_message(child, receiver)
                if started != (_START, filepath):
                    raise _protocol_breach(f"expected the start of {filepath}")
                progress.in_flight = filepath
                finished = _next_message(child, receiver)
            except _NoMessage as exc:
                fail(str(exc), exc.failure)
            try:
                if len(finished) != 3 or finished[:2] != (_RESULT, filepath):
                    raise ValueError(f"expected the result of {filepath}")
                accept(checked_result(finished[2], filepath))
            except Exception as exc:
                fail(
                    f"result breaks an engine invariant: {exc}",
                    {"reason": "engine_invariant", "detail": str(exc)},
                    exc,
                )
            progress.confirmed.append(filepath)
            progress.in_flight = None
            if on_advance is not None:
                on_advance()
        completed = _said_done(child, receiver)
    finally:
        _release(child, receiver, completed=completed)


__all__ = [
    "ISOLATED_RECOVERY_TIMEOUT_SECONDS",
    "PROCESS_CREATION_REFUSALS",
    "UNKNOWN_CULPRIT",
    "WorkerRecoveryError",
    "checked_result",
    "lost_task_failure",
    "process_creation_failure",
    "process_creation_refusal",
    "recover_in_isolation",
]
