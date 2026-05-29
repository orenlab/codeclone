#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""CodeClone session-end hook — warns about unclosed change intents.

Receives JSON on stdin with session context (transcript_path, etc.).
Returns a followup_message if the transcript mentions intent declaration
without a corresponding clear.

Cross-platform: works on Windows, macOS, and Linux.
Security: transcript_path is untrusted input — validated via realpath,
regular-file check, and home-directory prefix match before any read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_io import read_bounded_stdin

_EMPTY = "{}"

_WARNING = json.dumps(
    {
        "followup_message": (
            "Warning: this session declared change intent(s) that "
            "may not have been cleared. Run "
            '`manage_change_intent(action="list_workspace")` in '
            "the next session to check for stale intents, or use "
            "`gc_workspace` to clean them."
        )
    }
)


def _read_validated_transcript(stdin_payload: str) -> str | None:
    """Parse stdin JSON, validate transcript path, return file content.

    Returns ``None`` when the path is missing, unsafe, or unreadable.
    All validation failures are silent — the hook simply emits ``{}``.

    Security barriers (in order):
    1. Null-byte rejection before any filesystem call.
    2. ``Path.resolve(strict=True)`` — canonical absolute path, target must exist.
    3. ``is_file()`` — regular files only (no devices, sockets, directories).
    4. Home-directory prefix — must reside under ``$HOME`` / ``%USERPROFILE%``.
    """
    try:
        data = json.loads(stdin_payload)
    except (json.JSONDecodeError, OSError):
        return None

    raw: str = data.get("transcript_path", "")
    if not raw or "\0" in raw:
        return None

    try:
        resolved = Path(raw).resolve(strict=True)
    except (OSError, ValueError):
        return None

    if not resolved.is_file():
        return None

    try:
        resolved.relative_to(Path.home().resolve())
    except ValueError:
        return None

    try:
        return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def main() -> None:
    raw = read_bounded_stdin()
    if not raw:
        print(_EMPTY)
        return
    content = _read_validated_transcript(raw)
    if content is None:
        print(_EMPTY)
        return

    lines = content.splitlines()
    declares = sum(1 for ln in lines if "action" in ln and "declare" in ln)
    clears = sum(1 for ln in lines if "action" in ln and "clear" in ln)

    print(_WARNING if declares > clears else _EMPTY)


if __name__ == "__main__":
    main()
