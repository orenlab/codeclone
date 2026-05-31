# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3

from ..utils.sqlite_store import get_meta_value

MEMORY_META_TABLE = "memory_meta"


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    return get_meta_value(conn, meta_table=MEMORY_META_TABLE, key=key)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        f"INSERT INTO {MEMORY_META_TABLE}(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


__all__ = ["MEMORY_META_TABLE", "get_meta", "set_meta"]
