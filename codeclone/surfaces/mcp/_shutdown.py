# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Bounded graceful shutdown for the MCP server process, with a hard fallback.

Measured 2026-09-05 on this build (python 3.14, stdio transport): the server
did not terminate on ``SIGTERM``, and ``SIGKILL`` was the only exit.  The
handler was installed and it did run -- three separate things went wrong after
that, and only the third is visible from outside:

1. Raising ``SystemExit`` from the signal context does not *ask* the event
   loop to stop; it aborts ``asyncio``'s ``run_forever`` in the middle of
   ``select``.
2. Because the loop was aborted rather than unwound, the FastMCP lifespan's
   ``__aexit__`` never runs.  ``service.shutdown_cleanup()`` -- the entire
   stated purpose of installing the handler -- was measured NEVER CALLED, so
   the "graceful" path delivered exactly what ``SIGKILL`` delivers.
3. Interpreter shutdown then blocks in ``threading._shutdown``, joining
   anyio's non-daemon worker thread whose ``stop()`` was registered as a done
   callback of the task the abort skipped.  The process hangs there forever.

Points 1 and 2 are ours.  Point 3 is not: a blocking ``stdin`` read inside a
non-daemon worker thread is anyio's shape, and no handler of ours can make
that thread joinable.  So this module does not pretend the hang can be argued
away -- it bounds it.  The teardown we own runs first, on our own initiative
rather than through a lifespan that provably is not reached; a deadline is
armed *before* the teardown so a teardown that itself blocks cannot extend the
window; and when the deadline passes the process is ended outright.

Nothing here decides *what* teardown means.  The callable is supplied by
:mod:`codeclone.surfaces.mcp.server`, which owns the service and the
observability runtime; this module owns only when it runs and how long it may
take.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable
from typing import Final

#: Long enough for a sqlite handle and an audit flush, short enough that an
#: operator does not read the wait as a second hang.  Not a measurement of
#: anything -- a declared operational budget, and named as one.
DEFAULT_SHUTDOWN_GRACE_SECONDS: Final = 5.0
MIN_SHUTDOWN_GRACE_SECONDS: Final = 0.1
MAX_SHUTDOWN_GRACE_SECONDS: Final = 60.0
SHUTDOWN_GRACE_ENV: Final = "CODECLONE_MCP_SHUTDOWN_GRACE_SECONDS"


def resolved_shutdown_grace_seconds(
    value: object = None,
    *,
    env_value: object = None,
) -> float:
    """Clamp a configured grace period, falling back to the default.

    Total over its input by design: an unreadable value yields the default
    rather than an exception, because the one place this is read is a signal
    handler and a shutdown path must not fail to shut down.
    """

    raw = value if value is not None else env_value
    if raw is None or isinstance(raw, bool):
        return DEFAULT_SHUTDOWN_GRACE_SECONDS
    try:
        parsed = float(str(raw).strip())
    except ValueError:
        return DEFAULT_SHUTDOWN_GRACE_SECONDS
    if parsed != parsed:  # NaN compares unequal to itself; min/max would keep it
        return DEFAULT_SHUTDOWN_GRACE_SECONDS
    return min(MAX_SHUTDOWN_GRACE_SECONDS, max(MIN_SHUTDOWN_GRACE_SECONDS, parsed))


def hard_exit_status(signum: int) -> int:
    """The shell convention for "ended by signal N", so the exit code is honest.

    A process that had to be ended by its own deadline did not exit cleanly,
    and reporting 0 would say it did.
    """

    return 128 + int(signum)


def _spawn_deadline(delay: float, on_deadline: Callable[[], None]) -> None:
    """Arm the deadline on a daemon timer.

    Daemon on purpose: this thread must never be one of the threads interpreter
    shutdown waits for, or the watchdog would join the queue it exists to
    break.
    """

    timer = threading.Timer(delay, on_deadline)
    timer.daemon = True
    timer.start()


class ShutdownCoordinator:
    """One shutdown, at most one teardown, and a deadline that always ends it.

    Deliberately not a dataclass: the Phase 39S model-store ratchet reserves
    structure definitions for ``codeclone.models`` and ``codeclone.canonical``,
    and this is a process-lifecycle object rather than a fact.
    """

    def __init__(
        self,
        *,
        grace_seconds: float | None = None,
        hard_exit: Callable[[int], None] = os._exit,
        arm_deadline: Callable[[float, Callable[[], None]], None] = _spawn_deadline,
    ) -> None:
        #: ``None`` means "read the environment when the signal arrives", so a
        #: value set after import is still honoured.
        self._grace_seconds = grace_seconds
        self._hard_exit = hard_exit
        self._arm_deadline = arm_deadline
        self._lock = threading.Lock()
        self._teardown: Callable[[], None] | None = None
        self._teardown_ran = False
        self._requested_signum: int | None = None

    def grace_seconds(self) -> float:
        if self._grace_seconds is not None:
            return self._grace_seconds
        return resolved_shutdown_grace_seconds(
            env_value=os.environ.get(SHUTDOWN_GRACE_ENV)
        )

    def set_teardown(self, teardown: Callable[[], None] | None) -> None:
        """Register the teardown, and re-arm the once-guard for it.

        Re-arming matters: one process may build more than one server (the test
        suite does), and a guard that stayed latched would silently skip the
        second server's own teardown.
        """

        with self._lock:
            self._teardown = teardown
            self._teardown_ran = False

    def run_teardown_once(self) -> None:
        """Run the registered teardown at most once, whichever door reached it.

        Both doors lead here -- the lifespan's ``__aexit__`` and the signal
        path -- because on the stdio transport only the second one is actually
        reached, and on a clean end-of-input only the first.  Never raises: a
        teardown that fails must not stop the shutdown it is part of.
        """

        with self._lock:
            teardown = self._teardown
            if teardown is None or self._teardown_ran:
                return
            self._teardown_ran = True
        with contextlib.suppress(Exception):
            teardown()

    def request_shutdown(self, signum: int) -> None:
        """Handle one termination signal.  Raises ``SystemExit`` on the first.

        Order is load-bearing.  The deadline is armed *before* the teardown so
        that a teardown which blocks -- on the service state lock held by an
        in-flight tool call, say -- is bounded by it rather than replacing it.
        """

        with self._lock:
            already_requested = self._requested_signum is not None
            if not already_requested:
                self._requested_signum = int(signum)
        if already_requested:
            # A second signal is an operator saying the wait is over.
            self._hard_exit(hard_exit_status(signum))
            return
        # The status is bound here rather than re-read when the deadline
        # fires: a fallback that had to reconstruct which signal it was
        # answering would need a branch for "none recorded", and no input can
        # reach that branch -- the deadline is armed only from this line.
        status = hard_exit_status(signum)
        self._arm_deadline(self.grace_seconds(), lambda: self._hard_exit(status))
        self.run_teardown_once()
        raise SystemExit(0)


__all__ = [
    "DEFAULT_SHUTDOWN_GRACE_SECONDS",
    "MAX_SHUTDOWN_GRACE_SECONDS",
    "MIN_SHUTDOWN_GRACE_SECONDS",
    "SHUTDOWN_GRACE_ENV",
    "ShutdownCoordinator",
    "hard_exit_status",
    "resolved_shutdown_grace_seconds",
]
