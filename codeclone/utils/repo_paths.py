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
    # Allowlists that only constrain paths resolving *outside* ``root`` (i.e.
    # when ``allow_external`` is set). Empty defaults preserve the historical
    # "any external path" behaviour, so existing callers are unaffected.
    external_suffixes: frozenset[str] = frozenset()
    external_roots: tuple[Path, ...] = ()
    # Reject an *existing* path that is not a regular file (directory, device,
    # FIFO, socket). Does not require the path to exist.
    reject_special_files: bool = False


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
    if not _is_relative_to(resolved, root_path):
        if not policy.allow_external:
            raise PathOutsideRepoError(f"path escapes repository root: {raw_path}")
        _enforce_external_allowlist(resolved, raw_path=raw_path, policy=policy)
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


def _enforce_external_allowlist(
    path: Path, *, raw_path: Path, policy: RepoPathPolicy
) -> None:
    """Constrain a path that has escaped ``root`` under ``allow_external``.

    The extension check runs against the *resolved* real path, so a symlink
    whose target carries a disallowed suffix is rejected even when the link
    name looks allowed.
    """

    if policy.external_suffixes and path.suffix.lower() not in policy.external_suffixes:
        allowed = ", ".join(sorted(policy.external_suffixes))
        raise PathOutsideRepoError(
            f"external artifact must use one of [{allowed}]: {path.name}"
        )
    if policy.external_roots and not any(
        _is_relative_to(path, allowed_root) for allowed_root in policy.external_roots
    ):
        raise PathOutsideRepoError(
            f"external artifact escapes permitted roots: {raw_path}"
        )


def _enforce_type_policy(path: Path, *, policy: RepoPathPolicy) -> None:
    if policy.must_be_file and not path.is_file():
        raise RepoPathError(f"path must be a file: {path}")
    if policy.must_be_dir and not path.is_dir():
        raise RepoPathError(f"path must be a directory: {path}")
    if policy.reject_special_files and path.exists() and not path.is_file():
        raise RepoPathError(f"path must be a regular file: {path}")


__all__ = [
    "PathOutsideRepoError",
    "RepoPathError",
    "RepoPathPolicy",
    "display_repo_path",
    "resolve_repo_relative_path",
    "resolve_under_repo_root",
]
