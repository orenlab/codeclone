# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

_TEST_FILE_NAMES = {"conftest.py"}


def is_test_filepath(filepath: str) -> bool:
    normalized = filepath.lower().replace("\\", "/")
    if "/tests/" in normalized or "/test/" in normalized:
        return True
    filename = Path(filepath).name.lower()
    return filename in _TEST_FILE_NAMES or filename.startswith("test_")
