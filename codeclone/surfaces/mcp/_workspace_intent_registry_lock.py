# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Cross-process exclusive lock for workspace intent registry I/O."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS: Final[float] = 5.0
_REGISTRY_LOCK_POLL_SECONDS: Final[float] = 0.05


class WorkspaceRegistryLockError(OSError):
    """Raised when the workspace registry lock cannot be acquired in time."""


@contextmanager
def workspace_registry_lock(
    lock_path: Path,
    *,
    timeout_seconds: float = DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire an exclusive cross-process lock for registry mutations."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    with open(lock_path, "a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        while True:
            try:
                _acquire_exclusive_lock(handle)
            except (OSError, BlockingIOError) as exc:
                if time.monotonic() >= deadline:
                    raise WorkspaceRegistryLockError(
                        f"Timed out acquiring workspace registry lock at {lock_path}"
                    ) from exc
                time.sleep(_REGISTRY_LOCK_POLL_SECONDS)
                continue
            try:
                yield
            finally:
                _release_exclusive_lock(handle)
            return


def _acquire_exclusive_lock(handle: object) -> None:
    fileno = handle.fileno()  # type: ignore[attr-defined]
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fileno, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(fileno, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_exclusive_lock(handle: object) -> None:
    fileno = handle.fileno()  # type: ignore[attr-defined]
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fileno, fcntl.LOCK_UN)


__all__ = [
    "DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS",
    "WorkspaceRegistryLockError",
    "workspace_registry_lock",
]
