# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""SQLite connection tracking for pytest teardown.

Connections opened through ``sqlite3.connect`` during a test are registered
in a per-process list and closed after every test.  ``sqlite3.Connection``
does not support weak references, so the registry holds strong refs until
teardown.

The expensive ``gc.get_objects()`` sweep is reserved for tests marked
``@pytest.mark.needs_sqlite_cleanup``.
"""

from __future__ import annotations

import gc
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from typing import Any

_ConnectFactory = Callable[..., sqlite3.Connection]

_tracked: list[sqlite3.Connection] = []
_tracked_ids: set[int] = set()


def register_sqlite_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    if type(conn) is sqlite3.Connection:
        conn_id = id(conn)
        if conn_id not in _tracked_ids:
            _tracked_ids.add(conn_id)
            _tracked.append(conn)
    return conn


def close_tracked_sqlite_connections() -> None:
    while _tracked:
        conn = _tracked.pop()
        with suppress(Exception):
            conn.close()
    _tracked_ids.clear()


def sweep_leaked_sqlite_connections_via_gc() -> None:
    """Best-effort full-heap scan for sqlite3 handles left open by a test."""
    for obj in gc.get_objects():
        if type(obj) is sqlite3.Connection:
            with suppress(Exception):
                obj.close()
    gc.collect()


def make_tracking_connect(real_connect: _ConnectFactory) -> _ConnectFactory:
    def tracking_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return register_sqlite_connection(real_connect(*args, **kwargs))

    return tracking_connect
