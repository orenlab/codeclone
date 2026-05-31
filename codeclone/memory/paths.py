# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import PurePosixPath


def normalize_repo_path(raw_path: str) -> str:
    text = raw_path.replace("\\", "/").strip().removeprefix("./")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        msg = "path must be repo-relative without traversal"
        raise ValueError(msg)
    return path.as_posix()


def repo_path_to_module_key(rel_path: str) -> str:
    module_path = normalize_repo_path(rel_path).removesuffix(".py").replace("/", ".")
    if module_path.endswith(".__init__"):
        module_path = module_path[: -len(".__init__")]
    return module_path


def expand_scope_paths(scope_paths: frozenset[str]) -> frozenset[str]:
    expanded: set[str] = set()
    for raw_path in scope_paths:
        normalized = normalize_repo_path(raw_path)
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
        normalized = normalize_repo_path(scope_path)
        module_key = repo_path_to_module_key(normalized)
        if key in {normalized, module_key}:
            return 1.0
        if key.startswith(f"{normalized}/") or normalized.startswith(f"{key}/"):
            best = max(best, 0.8)
        if key.startswith(f"{module_key}.") or module_key.startswith(f"{key}."):
            best = max(best, 0.8)
    return best


__all__ = [
    "expand_scope_paths",
    "normalize_repo_path",
    "repo_path_to_module_key",
    "subject_matches_scope",
]
