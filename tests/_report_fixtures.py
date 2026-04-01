# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path

REPEATED_STMT_HASH = "0e8579f84e518d186950d012c9944a40cb872332"

REPEATED_ASSERT_SOURCE = (
    "def f(html):\n"
    "    assert 'a' in html\n"
    "    assert 'b' in html\n"
    "    assert 'c' in html\n"
    "    assert 'd' in html\n"
)


def repeated_block_group_key(*, block_size: int = 4) -> str:
    return "|".join([REPEATED_STMT_HASH] * block_size)


def write_repeated_assert_source(path: Path) -> Path:
    path.write_text(REPEATED_ASSERT_SOURCE, "utf-8")
    return path
