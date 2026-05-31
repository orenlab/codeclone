# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Cross-process advisory lock for memory init/refresh."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from ..utils.file_lock import advisory_file_lock
from .exceptions import MemoryInitLockError

DEFAULT_MEMORY_INIT_LOCK_TIMEOUT_SECONDS: Final[float] = 30.0


@contextmanager
def memory_init_lock(
    lock_path: Path,
    *,
    timeout_seconds: float = DEFAULT_MEMORY_INIT_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    with advisory_file_lock(
        lock_path,
        timeout_seconds=timeout_seconds,
        timeout_error=lambda path: MemoryInitLockError(
            f"Timed out acquiring memory init lock at {path}"
        ),
    ):
        yield


__all__ = ["DEFAULT_MEMORY_INIT_LOCK_TIMEOUT_SECONDS", "memory_init_lock"]
