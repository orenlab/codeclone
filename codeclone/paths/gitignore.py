# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Deterministic .gitignore checks for CodeClone workspace hygiene."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .workspace import WORKSPACE_DIR_NAME

_COVERING_PATTERN_CORES: Final[frozenset[str]] = frozenset(
    {
        ".codeclone",
        ".codeclone/**",
        ".cache",
        ".cache/**",
        ".cache/codeclone",
        ".cache/codeclone/**",
    }
)

GITIGNORE_CODECLONE_CACHE_TIP_ID: Final = "gitignore-codeclone-cache"
WORKSPACE_HYGIENE_CATEGORY: Final = "workspace_hygiene"
GITIGNORE_CODECLONE_CACHE_SUGGESTED_ENTRY: Final = f"{WORKSPACE_DIR_NAME}/"
GITIGNORE_CODECLONE_CACHE_MESSAGE: Final = (
    f"Add `{WORKSPACE_DIR_NAME}/` to `.gitignore` to keep CodeClone "
    "coordination state, audit DB, and generated artifacts out of "
    "version control."
)


def normalize_gitignore_pattern(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    if stripped.startswith("\\#"):
        stripped = stripped[1:]
    return stripped.lstrip("/").rstrip("/")


def gitignore_pattern_covers_codeclone_cache(pattern: str) -> bool:
    """Return True when a single gitignore line covers the CodeClone workspace."""
    normalized = normalize_gitignore_pattern(pattern)
    if not normalized or normalized.startswith("!"):
        return False
    core = normalized.lstrip("/").rstrip("/")
    if core in _COVERING_PATTERN_CORES:
        return True
    return core.endswith(
        (
            ".codeclone",
            ".codeclone/**",
            ".cache/codeclone",
            ".cache/codeclone/**",
        )
    )


def repo_gitignore_covers_codeclone_cache(root: Path) -> bool:
    """Return True when the repository root ``.gitignore`` covers CodeClone cache."""
    gitignore_path = root / ".gitignore"
    if not gitignore_path.is_file():
        return False
    try:
        text = gitignore_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(
        gitignore_pattern_covers_codeclone_cache(line) for line in text.splitlines()
    )


def gitignore_codeclone_cache_tip_payload() -> dict[str, object]:
    return {
        "id": GITIGNORE_CODECLONE_CACHE_TIP_ID,
        "severity": "info",
        "category": WORKSPACE_HYGIENE_CATEGORY,
        "message": GITIGNORE_CODECLONE_CACHE_MESSAGE,
        "suggested_entry": GITIGNORE_CODECLONE_CACHE_SUGGESTED_ENTRY,
    }


__all__ = [
    "GITIGNORE_CODECLONE_CACHE_MESSAGE",
    "GITIGNORE_CODECLONE_CACHE_SUGGESTED_ENTRY",
    "GITIGNORE_CODECLONE_CACHE_TIP_ID",
    "WORKSPACE_HYGIENE_CATEGORY",
    "gitignore_codeclone_cache_tip_payload",
    "gitignore_pattern_covers_codeclone_cache",
    "normalize_gitignore_pattern",
    "repo_gitignore_covers_codeclone_cache",
]
