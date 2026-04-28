# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

from ..domain.source_scope import (
    SOURCE_KIND_FIXTURES,
    SOURCE_KIND_OTHER,
    SOURCE_KIND_PRODUCTION,
    SOURCE_KIND_TESTS,
)

_TEST_FILE_NAMES = {"conftest.py"}


def normalize_repo_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def relative_repo_path(filepath: str, *, scan_root: str = "") -> str:
    normalized_path = normalize_repo_path(filepath)
    normalized_root = normalize_repo_path(scan_root).rstrip("/")
    if not normalized_path:
        return normalized_path
    if not normalized_root:
        return normalized_path
    prefix = f"{normalized_root}/"
    if normalized_path.startswith(prefix):
        return normalized_path[len(prefix) :]
    if normalized_path == normalized_root:
        return normalized_path.rsplit("/", maxsplit=1)[-1]
    return normalized_path


def classify_source_kind(filepath: str, *, scan_root: str = "") -> str:
    rel = relative_repo_path(filepath, scan_root=scan_root)
    parts = [part for part in rel.lower().split("/") if part and part != "."]
    if not parts:
        return SOURCE_KIND_OTHER
    for idx, part in enumerate(parts):
        if part != SOURCE_KIND_TESTS:
            continue
        if idx + 1 < len(parts) and parts[idx + 1] == SOURCE_KIND_FIXTURES:
            return SOURCE_KIND_FIXTURES
        return SOURCE_KIND_TESTS
    return SOURCE_KIND_PRODUCTION


def is_test_filepath(filepath: str) -> bool:
    source_kind = classify_source_kind(filepath)
    if source_kind in {SOURCE_KIND_TESTS, SOURCE_KIND_FIXTURES}:
        return True
    filename = Path(filepath).name.lower()
    return filename in _TEST_FILE_NAMES or filename.startswith("test_")
