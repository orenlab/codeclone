# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""A connection whose ``execute`` steps ``PRAGMA incremental_vacuum`` once.

CPython 3.11's ``sqlite3`` resets a statement that reports no result columns
after its first step, so ``execute("PRAGMA incremental_vacuum").fetchall()``
hands back one page per call there, while 3.10 and 3.12+ step it to the end
(measured 2026-09-27, one SQLite 3.50.4 under all three: 375 free pages ->
374 on 3.11, -> 0 elsewhere). ``executescript`` drains it on every one.

The proxy reproduces the 3.11 stepping on any interpreter, so a release path
is held to a form that empties the freelist regardless of which CPython runs
the suite -- the pin does not wait for a 3.11 runner to turn red.
"""

from __future__ import annotations

import sqlite3
from typing import Any


class SingleStepConnection:
    """Wrap a connection; ``execute`` of the vacuum pragma frees one page."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def execute(self, sql: str, *args: Any) -> sqlite3.Cursor:
        if "incremental_vacuum" in sql.lower():
            return self._inner.execute("PRAGMA incremental_vacuum(1)", *args)
        return self._inner.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
