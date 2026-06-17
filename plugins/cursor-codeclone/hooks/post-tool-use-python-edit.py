#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""CodeClone postToolUse hook — inject change-control reminder after Python writes.

Cursor documents ``additional_context`` on ``postToolUse`` (not ``afterFileEdit``).
Matches Write / StrReplace / ApplyPatch via hooks.json matcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hook_io import (
    edited_path_from_post_tool_use,
    emit_hook_payload,
    is_python_source_path,
    parse_hook_input,
    python_edit_reminder_context,
    read_bounded_stdin,
    workspace_root_from_hook,
)


def main() -> None:
    payload: dict[str, object] | None = None
    data = parse_hook_input(read_bounded_stdin())
    if data is not None:
        edited_path = edited_path_from_post_tool_use(data)
        if is_python_source_path(edited_path):
            workspace_root = workspace_root_from_hook(data)
            payload = {
                "additional_context": python_edit_reminder_context(
                    workspace_root=workspace_root,
                ),
            }
    emit_hook_payload(payload)


if __name__ == "__main__":
    main()
