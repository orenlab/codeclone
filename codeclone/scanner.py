# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import ValidationError

if TYPE_CHECKING:
    from collections.abc import Iterable

DEFAULT_EXCLUDES = (
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "site-packages",
    "migrations",
    "alembic",
    "dist",
    "build",
    ".tox",
)

SENSITIVE_DIRS = {
    "/etc",
    "/sys",
    "/proc",
    "/dev",
    "/root",
    "/boot",
    "/var",
    "/private/var",
    "/usr/bin",
    "/usr/sbin",
    "/private/etc",
}


def _get_tempdir() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _ensure_not_sensitive_root(*, rootp: Path, root_arg: str) -> None:
    root_str = str(rootp)
    temp_root = _get_tempdir()
    try:
        rootp.relative_to(temp_root)
        return
    except ValueError:
        pass

    if root_str in SENSITIVE_DIRS:
        raise ValidationError(f"Cannot scan sensitive directory: {root_arg}")

    for sensitive in SENSITIVE_DIRS:
        if root_str.startswith(sensitive + "/"):
            raise ValidationError(f"Cannot scan under sensitive directory: {root_arg}")


def _is_included_python_file(
    *,
    file_path: Path,
    excludes_set: set[str],
    rootp: Path,
) -> bool:
    if not file_path.name.endswith(".py"):
        return False
    if any(part in excludes_set for part in file_path.parts):
        return False
    if not file_path.is_symlink():
        return True
    try:
        resolved = file_path.resolve()
    except OSError:
        return False
    return _is_under_root(resolved, rootp)


def _walk_file_candidate(
    *,
    dirpath: str,
    filename: str,
    excludes_set: set[str],
    rootp: Path,
) -> str | None:
    if not filename.endswith(".py"):
        return None
    file_path = os.path.join(dirpath, filename)
    if os.path.islink(file_path) and not _is_included_python_file(
        file_path=Path(file_path),
        excludes_set=excludes_set,
        rootp=rootp,
    ):
        return None
    return file_path


def iter_py_files(
    root: str,
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES,
    *,
    max_files: int = 100_000,
) -> Iterable[str]:
    try:
        rootp = Path(root).resolve(strict=True)
    except (OSError, RuntimeError) as e:
        raise ValidationError(f"Invalid root path '{root}': {e}") from e

    if not rootp.is_dir():
        raise ValidationError(f"Root must be a directory: {root}")

    _ensure_not_sensitive_root(rootp=rootp, root_arg=root)

    excludes_set = set(excludes)

    # Keep legacy behavior only when the requested root directory itself is excluded
    # (e.g. scanning "<repo>/__pycache__"). Parent directories must not suppress
    # scanning, otherwise valid roots like ".../build/project" become empty.
    if rootp.name in excludes_set:
        return

    # Collect and filter first, then sort for deterministic output.
    candidates: list[str] = []
    for dirpath, dirnames, filenames in os.walk(
        rootp,
        topdown=True,
        followlinks=False,
    ):
        dirnames[:] = [name for name in dirnames if name not in excludes_set]
        for filename in filenames:
            candidate = _walk_file_candidate(
                dirpath=dirpath,
                filename=filename,
                excludes_set=excludes_set,
                rootp=rootp,
            )
            if candidate is None:
                continue
            candidates.append(candidate)
            if len(candidates) > max_files:
                raise ValidationError(
                    f"File count exceeds limit of {max_files}. "
                    "Use more specific root or increase limit."
                )

    yield from sorted(candidates)


def module_name_from_path(root: str, filepath: str) -> str:
    rootp = Path(root).resolve()
    fp = Path(filepath).resolve()
    rel = fp.relative_to(rootp)
    # strip ".py"
    stem = rel.with_suffix("")
    # __init__.py -> package name
    if stem.name == "__init__":
        stem = stem.parent
    return ".".join(stem.parts)
