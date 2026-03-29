# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

__all__ = ["format_spread_text"]


def format_spread_text(files: int, functions: int) -> str:
    file_word = "file" if files == 1 else "files"
    function_word = "function" if functions == 1 else "functions"
    return f"{files} {file_word} / {functions} {function_word}"
