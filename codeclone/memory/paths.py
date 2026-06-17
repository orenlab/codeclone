# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from .exceptions import MemoryContractError

MEMORY_ROOT_SCOPE_ERROR = (
    "Engineering Memory requires a file, symbol, or declared intent scope. "
    "Project root is not a valid memory scope. Use status/search for project "
    "orientation."
)

MEMORY_RETRIEVAL_SCOPE_REQUIRED_ERROR = (
    "get_relevant_memory requires scope, intent_id, or symbols. "
    "Use query_engineering_memory(mode=status|search) for project orientation."
)

MEMORY_COVERAGE_SCOPE_REQUIRED_ERROR = (
    "mode=coverage requires one or more repo-relative scope paths."
)


def normalize_repo_path(raw_path: str) -> str:
    text = raw_path.replace("\\", "/").strip().removeprefix("./")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        msg = "path must be repo-relative without traversal"
        raise ValueError(msg)
    return path.as_posix()


def is_root_scope_path(normalized_path: str) -> bool:
    return normalized_path in {"", "."}


def normalize_memory_scope_path(raw_path: str) -> str:
    normalized = normalize_repo_path(raw_path)
    if is_root_scope_path(normalized):
        raise MemoryContractError(MEMORY_ROOT_SCOPE_ERROR)
    return normalized


def normalize_memory_scope_paths(raw_paths: Sequence[str]) -> tuple[str, ...]:
    if not raw_paths:
        raise MemoryContractError(MEMORY_COVERAGE_SCOPE_REQUIRED_ERROR)
    return tuple(normalize_memory_scope_path(item) for item in raw_paths)


def repo_path_to_module_key(rel_path: str) -> str:
    module_path = normalize_repo_path(rel_path).removesuffix(".py").replace("/", ".")
    if module_path.endswith(".__init__"):
        module_path = module_path[: -len(".__init__")]
    return module_path


def expand_scope_paths(scope_paths: frozenset[str]) -> frozenset[str]:
    expanded: set[str] = set()
    for raw_path in scope_paths:
        normalized = normalize_memory_scope_path(raw_path)
        expanded.add(normalized)
        expanded.add(repo_path_to_module_key(normalized))
    return frozenset(expanded)


def subject_matches_scope(
    subject_key: str,
    *,
    scope_paths: frozenset[str],
) -> float:
    key = subject_key.replace("\\", "/").strip("/")
    best = 0.0
    for scope_path in scope_paths:
        normalized = normalize_memory_scope_path(scope_path)
        module_key = repo_path_to_module_key(normalized)
        if key in {normalized, module_key}:
            return 1.0
        if key.startswith(f"{normalized}/") or normalized.startswith(f"{key}/"):
            best = max(best, 0.8)
        if key.startswith(f"{module_key}.") or module_key.startswith(f"{key}."):
            best = max(best, 0.8)
    return best


__all__ = [
    "MEMORY_COVERAGE_SCOPE_REQUIRED_ERROR",
    "MEMORY_RETRIEVAL_SCOPE_REQUIRED_ERROR",
    "MEMORY_ROOT_SCOPE_ERROR",
    "expand_scope_paths",
    "is_root_scope_path",
    "normalize_memory_scope_path",
    "normalize_memory_scope_paths",
    "normalize_repo_path",
    "repo_path_to_module_key",
    "subject_matches_scope",
]
