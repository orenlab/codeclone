"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .errors import ValidationError

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

    # Keep legacy behavior: if root path already includes an excluded segment,
    # no files are yielded.
    if any(part in excludes_set for part in rootp.parts):
        return

    # Collect and filter first, then sort for deterministic output.
    candidates: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(rootp, topdown=True, followlinks=False):
        dirnames[:] = [name for name in dirnames if name not in excludes_set]
        base = Path(dirpath)
        for filename in filenames:
            file_path = base / filename
            if not _is_included_python_file(
                file_path=file_path,
                excludes_set=excludes_set,
                rootp=rootp,
            ):
                continue
            candidates.append(file_path)
            if len(candidates) > max_files:
                raise ValidationError(
                    f"File count exceeds limit of {max_files}. "
                    "Use more specific root or increase limit."
                )

    for p in sorted(candidates, key=lambda path: str(path)):
        yield str(p)


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
