# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Shared SQLite open helpers with observability instrumentation."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from ..utils.sqlite_store import open_sqlite_db, open_sqlite_db_readonly


def open_instrumented_sqlite_db(
    path: Path,
    *,
    ensure_schema: Callable[[sqlite3.Connection], None],
    foreign_keys: bool = False,
    synchronous: str | None = None,
) -> sqlite3.Connection:
    from codeclone.observability.runtime import counting_connection_factory

    return open_sqlite_db(
        path,
        ensure_schema=ensure_schema,
        foreign_keys=foreign_keys,
        synchronous=synchronous,
        factory=counting_connection_factory(),
    )


def open_instrumented_sqlite_db_readonly(
    path: Path,
    *,
    validate_schema: Callable[[sqlite3.Connection], None],
) -> sqlite3.Connection:
    from codeclone.observability.runtime import counting_connection_factory

    return open_sqlite_db_readonly(
        path,
        validate_schema=validate_schema,
        factory=counting_connection_factory(),
    )


__all__ = [
    "open_instrumented_sqlite_db",
    "open_instrumented_sqlite_db_readonly",
]
