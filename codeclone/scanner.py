"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

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

    root_str = str(rootp)
    temp_root = _get_tempdir()
    in_temp = False
    try:
        rootp.relative_to(temp_root)
        in_temp = True
    except ValueError:
        in_temp = False

    if not in_temp:
        if root_str in SENSITIVE_DIRS:
            raise ValidationError(f"Cannot scan sensitive directory: {root}")

        for sensitive in SENSITIVE_DIRS:
            if root_str.startswith(sensitive + "/"):
                raise ValidationError(f"Cannot scan under sensitive directory: {root}")

    file_count = 0
    for p in rootp.rglob("*.py"):
        # Verify path is actually under root (prevent symlink attacks)
        try:
            p.resolve().relative_to(rootp)
        except ValueError:
            # Skipping file outside root (possible symlink traversal)
            continue

        parts = set(p.parts)
        if any(ex in parts for ex in excludes):
            continue

        file_count += 1
        if file_count > max_files:
            raise ValidationError(
                f"File count exceeds limit of {max_files}. "
                "Use more specific root or increase limit."
            )
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
