# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys

from .surfaces.cli.workflow import main as _cli_main


def _dispatch_mcp_flag(argv: list[str]) -> None:
    """Run ``codeclone --mcp ARGS`` as ``codeclone-mcp ARGS``.

    A link between the two console scripts, not a command of its own: the
    flag counts only as the first token, the server module loads only when it
    is given, and every argument after it reaches the same server entry point,
    which also owns the refusal when the ``mcp`` extra is missing.
    """
    if argv[1:2] != ["--mcp"]:
        return
    from .surfaces.mcp.server import main as mcp_main

    mcp_main(argv[2:])
    raise SystemExit


def main() -> None:
    _dispatch_mcp_flag(sys.argv)
    _cli_main()


__all__ = ["main"]


if __name__ == "__main__":
    main()
