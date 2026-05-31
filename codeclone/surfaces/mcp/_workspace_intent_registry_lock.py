# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Cross-process exclusive lock for workspace intent registry I/O."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from ...utils.file_lock import advisory_file_lock

DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS: Final[float] = 5.0


class WorkspaceRegistryLockError(OSError):
    """Raised when the workspace registry lock cannot be acquired in time."""


@contextmanager
def workspace_registry_lock(
    lock_path: Path,
    *,
    timeout_seconds: float = DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire an exclusive cross-process lock for registry mutations."""
    with advisory_file_lock(
        lock_path,
        timeout_seconds=timeout_seconds,
        timeout_error=lambda path: WorkspaceRegistryLockError(
            f"Timed out acquiring workspace registry lock at {path}"
        ),
    ):
        yield


__all__ = [
    "DEFAULT_REGISTRY_LOCK_TIMEOUT_SECONDS",
    "WorkspaceRegistryLockError",
    "workspace_registry_lock",
]
