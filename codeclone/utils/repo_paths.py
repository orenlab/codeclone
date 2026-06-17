# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Repository-root path containment helpers.

The helpers here are intentionally small and policy-driven.  They are used for
security-sensitive state/artifact paths; general CLI output paths keep their
existing behavior unless a caller opts into these stricter rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class RepoPathError(ValueError):
    """Raised when a repository path cannot be resolved safely."""


class PathOutsideRepoError(RepoPathError):
    """Raised when a path escapes the repository root."""


@dataclass(frozen=True, slots=True)
class RepoPathPolicy:
    allow_absolute: bool = False
    allow_external: bool = False
    must_exist: bool = False
    must_be_file: bool = False
    must_be_dir: bool = False


def resolve_under_repo_root(
    root: Path,
    raw: str | Path,
    *,
    policy: RepoPathPolicy,
) -> Path:
    """Resolve ``raw`` relative to ``root`` and enforce containment policy."""

    root_path = _resolved_root(root)
    raw_path = _raw_path(raw)
    if raw_path.is_absolute() and not policy.allow_absolute:
        raise PathOutsideRepoError("absolute paths require explicit opt-in")
    candidate = raw_path if raw_path.is_absolute() else root_path / raw_path
    try:
        resolved = candidate.expanduser().resolve(strict=policy.must_exist)
    except OSError as exc:
        raise RepoPathError(f"cannot resolve path {raw_path}: {exc}") from exc
    if not policy.allow_external and not _is_relative_to(resolved, root_path):
        raise PathOutsideRepoError(f"path escapes repository root: {raw_path}")
    _enforce_type_policy(resolved, policy=policy)
    return resolved


def resolve_repo_relative_path(root: Path, raw: str | Path) -> Path:
    """Resolve a repo-contained path, rejecting absolute or external paths."""

    return resolve_under_repo_root(root, raw, policy=RepoPathPolicy())


def display_repo_path(root: Path, path: Path) -> str:
    """Return a stable repo-relative display path when possible."""

    try:
        resolved_path = path.resolve(strict=False)
        resolved_root = root.resolve(strict=False)
        return resolved_path.relative_to(resolved_root).as_posix()
    except (OSError, ValueError):
        return str(path)


def _raw_path(raw: str | Path) -> Path:
    if isinstance(raw, Path):
        return raw.expanduser()
    text = raw.strip()
    if not text:
        raise RepoPathError("path must not be empty")
    return Path(text).expanduser()


def _resolved_root(root: Path) -> Path:
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RepoPathError(f"cannot resolve repository root {root}: {exc}") from exc
    if not resolved.is_dir():
        raise RepoPathError(f"repository root is not a directory: {resolved}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _enforce_type_policy(path: Path, *, policy: RepoPathPolicy) -> None:
    if policy.must_be_file and not path.is_file():
        raise RepoPathError(f"path must be a file: {path}")
    if policy.must_be_dir and not path.is_dir():
        raise RepoPathError(f"path must be a directory: {path}")


__all__ = [
    "PathOutsideRepoError",
    "RepoPathError",
    "RepoPathPolicy",
    "display_repo_path",
    "resolve_repo_relative_path",
    "resolve_under_repo_root",
]
