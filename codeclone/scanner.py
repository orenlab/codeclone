from __future__ import annotations

from pathlib import Path
from typing import Iterable

DEFAULT_EXCLUDES = (
    ".git", ".venv", "venv", "__pycache__", "site-packages",
    "migrations", "alembic", "dist", "build", ".tox",
)

def iter_py_files(root: str, excludes: tuple[str, ...] = DEFAULT_EXCLUDES) -> Iterable[str]:
    rootp = Path(root)
    for p in rootp.rglob("*.py"):
        parts = set(p.parts)
        if any(ex in parts for ex in excludes):
            continue
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