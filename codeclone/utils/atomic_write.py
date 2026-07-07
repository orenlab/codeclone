# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared atomic text write helpers."""

from __future__ import annotations

import os
import stat
import tempfile
from errno import EACCES, EBADF, EINVAL, ENOSYS, ENOTSUP, EPERM
from pathlib import Path

_UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS = frozenset(
    {EACCES, EBADF, EINVAL, ENOSYS, ENOTSUP, EPERM}
)


def write_text_atomically(path: Path, text: str) -> None:
    """Write text via temp file + ``os.replace``."""

    validate_atomic_target(path)
    target_mode = _target_write_mode(path)
    fd_num, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        suffix=".tmp",
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd_num, "wb") as handle:
            _chmod_open_file(handle.fileno(), tmp_path, target_mode)
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _fsync_parent_directory(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _target_write_mode(path: Path) -> int:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return _default_file_create_mode()


def _default_file_create_mode() -> int:
    current_umask = os.umask(0)
    try:
        return 0o666 & ~current_umask
    finally:
        os.umask(current_umask)


def _chmod_open_file(fd_num: int, path: Path, mode: int) -> None:
    if hasattr(os, "fchmod"):
        os.fchmod(fd_num, mode)
        return
    os.chmod(path, mode)


def _fsync_parent_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd_num = os.open(path.parent, flags)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
            return
        raise
    try:
        try:
            os.fsync(fd_num)
        except OSError as exc:
            if exc.errno not in _UNSUPPORTED_DIRECTORY_FSYNC_ERRNOS:
                raise
    finally:
        os.close(fd_num)


def validate_atomic_target(path: Path) -> None:
    if path.is_symlink():
        raise OSError(f"Refusing to replace symlink target: {path}")
    parent = path.parent
    if parent.exists() and parent.is_symlink():
        raise OSError(f"Refusing to write through symlink directory: {parent}")


__all__ = ["validate_atomic_target", "write_text_atomically"]
