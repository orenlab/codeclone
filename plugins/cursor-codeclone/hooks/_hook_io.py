# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Shared hook I/O helpers for Cursor plugin hooks."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping

MAX_STDIN_BYTES = 65536
_EMPTY_JSON = "{}"


def read_bounded_stdin(max_bytes: int = MAX_STDIN_BYTES) -> str:
    payload = sys.stdin.buffer.read(max_bytes + 1)
    if len(payload) > max_bytes:
        return ""
    return payload.decode("utf-8", errors="replace")


def emit_hook_payload(payload: Mapping[str, object] | None = None) -> None:
    if payload:
        print(json.dumps(dict(payload)))
    else:
        print(_EMPTY_JSON)
