#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""CodeClone stop hook — warn when workflow intents look unclosed.

Reads ``transcript_path`` from the Cursor hook base payload (on ``stop``).
Uses workflow tool names (``start_controlled_change`` / ``finish_controlled_change``)
with legacy ``manage_change_intent`` declare/clear as fallback.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_io import (
    emit_hook_payload,
    parse_hook_input,
    read_bounded_stdin,
    transcript_path_from_hook,
    workflow_intent_looks_unclosed,
)

_WARNING = {
    "followup_message": (
        "CodeClone: this session may have started change control without a matching "
        "`finish_controlled_change` (intent_cleared). Before ending, run "
        "`finish_controlled_change` with the active `intent_id`, or "
        '`manage_change_intent(action="list_workspace", root=<abs>)` in the next '
        "session to check for stale intents."
    )
}


def _read_validated_transcript(raw_path: str) -> str | None:
    if not raw_path or "\0" in raw_path:
        return None
    try:
        resolved = Path(raw_path).resolve(strict=True)
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
    payload: dict[str, object] | None = None
    data = parse_hook_input(read_bounded_stdin())
    if data is not None:
        transcript_path = transcript_path_from_hook(data)
        if transcript_path:
            content = _read_validated_transcript(transcript_path)
            if content is not None and workflow_intent_looks_unclosed(content):
                payload = _WARNING
    emit_hook_payload(payload)


if __name__ == "__main__":
    main()
