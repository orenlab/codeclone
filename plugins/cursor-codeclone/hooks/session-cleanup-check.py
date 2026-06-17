#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""CodeClone stop hook — warn when workspace intents remain unclosed.

Primary source of truth: workspace intent registry via
``codeclone.workspace_intent.gate.list_unclosed_workspace_intents`` (same family
as the preToolUse gate). Transcript JSONL parsing is a fallback only when the
registry cannot be read.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_io import (
    emit_hook_payload,
    parse_hook_input,
    read_bounded_stdin,
    session_cleanup_followup_message,
    session_cleanup_should_warn,
    transcript_path_from_hook,
    workspace_root_from_hook,
)


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
        workspace_root = workspace_root_from_hook(data)
        repo_root = Path(workspace_root) if workspace_root else None
        transcript_path = transcript_path_from_hook(data)
        transcript = (
            _read_validated_transcript(transcript_path) if transcript_path else None
        )
        should_warn, intent_ids = session_cleanup_should_warn(
            repo_root=repo_root,
            transcript=transcript,
        )
        if should_warn:
            payload = {
                "followup_message": session_cleanup_followup_message(
                    intent_ids=intent_ids,
                ),
            }
    emit_hook_payload(payload)


if __name__ == "__main__":
    main()
