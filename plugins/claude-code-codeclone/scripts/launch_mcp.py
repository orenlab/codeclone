# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
"""Claude Code plugin MCP launcher entrypoint.

The monorepo delegates to the shared launcher. Storefront synchronization
replaces this file with the full standalone launcher implementation.
"""

from __future__ import annotations

import runpy
from pathlib import Path

SHARED_LAUNCHER = (
    Path(__file__).resolve().parents[2] / "codeclone" / "scripts" / "launch_mcp.py"
)

if __name__ == "__main__":
    runpy.run_path(str(SHARED_LAUNCHER), run_name="__main__")
