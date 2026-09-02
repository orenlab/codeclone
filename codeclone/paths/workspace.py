# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Repo-local CodeClone workspace directories and default artifact paths."""

from __future__ import annotations

from pathlib import Path
from typing import Final, Protocol

from ..contracts.storage_paths import DEFAULT_CACHE_PATH

WORKSPACE_DIR_NAME: Final = ".codeclone"
CACHE_DB_DIR_NAME: Final = "db"
LEGACY_WORKSPACE_DIR_PARTS: Final = (".cache", "codeclone")

# The cache and the five report paths are product default paths with
# cross-layer consumers, so they are owned by contracts.storage_paths and
# not composed a second time here. What stays below is the workspace
# layout: artifacts whose only reader is this ring.
REL_AUDIT_DB_PATH: Final = f"{WORKSPACE_DIR_NAME}/db/audit.sqlite3"
REL_INTENT_REGISTRY_DB_PATH: Final = f"{WORKSPACE_DIR_NAME}/db/intents.sqlite3"
# Canonical run-store location — W1, ratified 2026-08-24 (§5: W2 separate
# file and W3 outside the repo both rejected): one db/ directory, one
# retention policy, symmetric with the audit and intent stores above.
REL_RUN_STORE_DB_PATH: Final = f"{WORKSPACE_DIR_NAME}/db/runs.sqlite3"
REL_MEMORY_DB_PATH: Final = f"{WORKSPACE_DIR_NAME}/memory/engineering_memory.sqlite3"
REL_SEMANTIC_INDEX_PATH: Final = f"{WORKSPACE_DIR_NAME}/memory/semantic_index.lance"
REL_SEMANTIC_EMBEDDING_CACHE_DIR: Final = f"{WORKSPACE_DIR_NAME}/memory/fastembed"

FORBIDDEN_WORKSPACE_GLOBS: Final = (
    f"{WORKSPACE_DIR_NAME}/**",
    ".cache/codeclone/**",
)

REGISTRY_DIR_PARTS: Final = (WORKSPACE_DIR_NAME, "intents")


class _PrinterLike(Protocol):
    def print(self, message: str) -> None: ...


def repo_workspace_dir(root: Path) -> Path:
    return root / WORKSPACE_DIR_NAME


def legacy_repo_workspace_dir(root: Path) -> Path:
    return root.joinpath(*LEGACY_WORKSPACE_DIR_PARTS)


def legacy_home_cache_path() -> Path:
    return Path("~/.cache/codeclone/cache.json").expanduser()


def workspace_dir_for_cache_path(cache_path: Path) -> Path:
    """The workspace directory a cache path belongs to.

    Artifacts that are not cache state used to derive their home from the cache
    file's parent, which was the workspace directory only because the cache
    happened to sit directly inside it. Moving the cache into ``db/`` broke that
    coincidence, so the derivation lives here, with the module that owns the
    layout, instead of being restated wherever somebody needs it.
    """

    parent = cache_path.parent
    return parent.parent if parent.name == CACHE_DB_DIR_NAME else parent


def default_cache_path(root: Path) -> Path:
    # The analysis cache is a row-addressed SQLite store, so it sits in db/
    # beside the audit, intent and run stores rather than as a JSON monolith at
    # the workspace root.  Shared infrastructure, separate semantics: db/ holds
    # both the immutable run authority and this disposable acceleration state,
    # and the cache may lag a published run but must never lead it.
    #
    # Where it sits is not decided here: this projects the ratified
    # DEFAULT_CACHE_PATH contract onto one repository root.
    return root / DEFAULT_CACHE_PATH


def legacy_repo_workspace_has_artifacts(root: Path) -> bool:
    legacy_dir = legacy_repo_workspace_dir(root)
    if not legacy_dir.is_dir():
        return False
    try:
        return any(legacy_dir.iterdir())
    except OSError:
        return False


def emit_legacy_workspace_warnings(
    *,
    root_path: Path,
    cache_path: Path,
    legacy_home_cache_path: Path,
    console: _PrinterLike,
) -> None:
    """Warn when obsolete home or repo-local artifact locations still exist."""
    from .. import ui_messages as ui

    if legacy_home_cache_path.exists():
        try:
            legacy_resolved = legacy_home_cache_path.resolve()
        except OSError:
            legacy_resolved = legacy_home_cache_path
        if legacy_resolved != cache_path:
            console.print(
                ui.fmt_legacy_cache_warning(
                    legacy_path=legacy_resolved,
                    new_path=cache_path,
                )
            )

    if legacy_repo_workspace_has_artifacts(root_path):
        console.print(
            ui.fmt_legacy_repo_workspace_warning(
                legacy_dir=legacy_repo_workspace_dir(root_path),
                new_dir=repo_workspace_dir(root_path),
            )
        )


def service_directories(root: Path) -> tuple[Path, ...]:
    """Every directory CodeClone may write its own service state into.

    The boundary is a set of *directories*, not "inside the repository":
    ``~/.cache/codeclone`` is outside every checkout and is CodeClone's own,
    while a repository's own ``build/`` is inside one and is not.

    Stated once here because the rule it replaces was an enumeration -- "never
    mutates source, baseline, the analysis cache, reports" -- which was both
    too wide and too narrow at once: it forbade a service write that should
    always have been allowed, and said nothing about everything else outside
    these directories. A surface asks whether a path is contained; it does not
    keep its own list of the things it must not touch.
    """

    return tuple(
        directory.resolve()
        for directory in (
            repo_workspace_dir(root),
            legacy_repo_workspace_dir(root),
            legacy_home_cache_path().parent,
        )
    )


def is_service_path(path: Path, *, root: Path) -> bool:
    """Whether *path* is CodeClone's own service state for *root*.

    Both sides are resolved, so ``.codeclone/../../elsewhere`` is outside and a
    sibling named ``.codeclone-not-ours`` is not admitted by prefix.
    """

    resolved = path.resolve()
    return any(
        resolved.is_relative_to(directory) for directory in service_directories(root)
    )


def workspace_glob_patterns() -> tuple[str, ...]:
    return FORBIDDEN_WORKSPACE_GLOBS


__all__ = [
    "CACHE_DB_DIR_NAME",
    "FORBIDDEN_WORKSPACE_GLOBS",
    "LEGACY_WORKSPACE_DIR_PARTS",
    "REGISTRY_DIR_PARTS",
    "REL_AUDIT_DB_PATH",
    "REL_INTENT_REGISTRY_DB_PATH",
    "REL_MEMORY_DB_PATH",
    "REL_RUN_STORE_DB_PATH",
    "REL_SEMANTIC_EMBEDDING_CACHE_DIR",
    "REL_SEMANTIC_INDEX_PATH",
    "WORKSPACE_DIR_NAME",
    "default_cache_path",
    "emit_legacy_workspace_warnings",
    "is_service_path",
    "legacy_home_cache_path",
    "legacy_repo_workspace_dir",
    "legacy_repo_workspace_has_artifacts",
    "repo_workspace_dir",
    "service_directories",
    "workspace_dir_for_cache_path",
    "workspace_glob_patterns",
]
