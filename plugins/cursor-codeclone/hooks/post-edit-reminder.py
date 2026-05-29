#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""CodeClone post-edit hook — reminds the agent to re-analyze after file edits.

Receives JSON on stdin with hook context (file path, edit details).
Returns a followup_message prompting re-analysis when Python files change.

Cross-platform: works on Windows, macOS, and Linux.
Security: file path is untrusted input — validated before use.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        print("{}")
        return

    file_path: str = data.get("path", "")

    # --- Input validation (defense-in-depth) ---
    # Reject empty paths, null bytes, and directory traversal sequences.
    if (
        not file_path
        or "\0" in file_path
        or ".." in file_path.split("/")
        or ".." in file_path.split("\\")
    ):
        print("{}")
        return

    if file_path.endswith(".py"):
        print(
            json.dumps(
                {
                    "followup_message": (
                        "A Python file was edited. Consider re-running "
                        "`analyze_repository` to check for structural "
                        "regressions before finishing. If you have an active "
                        "change intent, run `finish_controlled_change` with "
                        "the declared `intent_id`."
                    )
                }
            )
        )
    else:
        print("{}")


if __name__ == "__main__":
    main()
