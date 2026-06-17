#!/usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Cross-platform hook entrypoint for Cursor (Windows, macOS, Linux).

Configure hooks as:

    python <path-to-plugin>/hooks/run_hook.py post-tool-use
    python <path-to-plugin>/hooks/run_hook.py session-cleanup

Cursor invokes ``python``; this module re-runs the target hook with the same
interpreter (``sys.executable``), preserving stdin/stdout JSON contracts.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_HOOKS: dict[str, str] = {
    "pre-tool-use-gate": "pre_tool_use_change_control.py",
    "post-tool-use": "post-tool-use-python-edit.py",
    "session-cleanup": "session-cleanup-check.py",
}


def main() -> None:
    if len(sys.argv) != 2:
        return
    script_name = _HOOKS.get(sys.argv[1])
    if script_name is None:
        return
    target = Path(__file__).resolve().parent / script_name
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
