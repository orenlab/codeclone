# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``codeclone setup`` CLI entry (read-only readiness projection)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ....contracts import ExitCode
from ....utils.json_io import json_text
from ..console import make_query_console
from .engine.discover import build_setup_snapshot
from .render import render_setup_doctor, render_setup_status


def setup_main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root_path = Path(args.root).expanduser().resolve()
    if not root_path.is_dir():
        print(f"Repository root does not exist: {root_path}", file=sys.stderr)
        return int(ExitCode.CONTRACT_ERROR)

    try:
        snapshot = build_setup_snapshot(root_path)
    except Exception as exc:
        print(f"Setup readiness failed: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL_ERROR)

    if args.json:
        sys.stdout.write(
            json_text(
                snapshot,
                sort_keys=True,
                indent=True,
                trailing_newline=True,
            )
        )
        return int(ExitCode.SUCCESS)

    console = make_query_console(no_color=False)
    command = args.command or "status"
    if command == "doctor":
        render_setup_doctor(console=console, snapshot=snapshot)
    else:
        render_setup_status(console=console, snapshot=snapshot)
    return int(ExitCode.SUCCESS)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeclone setup")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("status", "doctor"),
        default="status",
        help="Readiness view (default: status).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit SetupSnapshot v1 JSON to stdout.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root path.",
    )
    return parser


__all__ = ["setup_main"]
