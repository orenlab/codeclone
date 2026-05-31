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


__all__ = ["normalize_repo_path", "repo_path_to_module_key"]
