# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""``codeclone setup`` CLI entry (readiness projection and bounded apply)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from ....contracts import ExitCode
from ....utils.json_io import json_text
from ..console import make_query_console
from ..types import PrinterLike
from .engine.apply import apply_setup_plan
from .engine.discover import build_setup_snapshot
from .engine.plan import build_setup_plan
from .render import (
    render_setup_apply,
    render_setup_doctor,
    render_setup_plan,
    render_setup_status,
)

SetupCommand = str
PayloadBuilder = Callable[[Path], dict[str, object]]
PayloadRenderer = Callable[[PrinterLike, dict[str, object]], None]


def setup_main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root_path = Path(args.root).expanduser().resolve()
    if not root_path.is_dir():
        print(f"Repository root does not exist: {root_path}", file=sys.stderr)
        return int(ExitCode.CONTRACT_ERROR)

    command = args.command or "status"
    try:
        payload = _build_payload(command, root_path, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Setup readiness failed: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL_ERROR)

    if args.json:
        _write_json_stdout(payload)
    else:
        _render_payload(command, payload)

    return _exit_code_for_payload(command, payload)


def _build_payload(
    command: SetupCommand,
    root_path: Path,
    *,
    dry_run: bool,
) -> dict[str, object]:
    if command == "apply":
        return apply_setup_plan(root_path, dry_run=dry_run)
    return _PAYLOAD_BUILDERS[command](root_path)


def _exit_code_for_payload(command: SetupCommand, payload: dict[str, object]) -> int:
    if command != "apply":
        return int(ExitCode.SUCCESS)
    status = str(payload.get("status", ""))
    if status in {"failed", "partial"}:
        return int(ExitCode.INTERNAL_ERROR)
    if status == "blocked":
        return int(ExitCode.CONTRACT_ERROR)
    return int(ExitCode.SUCCESS)


def _write_json_stdout(payload: dict[str, object]) -> None:
    sys.stdout.write(
        json_text(
            payload,
            sort_keys=True,
            indent=True,
            trailing_newline=True,
        )
    )


def _render_payload(command: SetupCommand, payload: dict[str, object]) -> None:
    console = make_query_console(no_color=False)
    _PAYLOAD_RENDERERS[command](console, payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codeclone setup")
    parser.add_argument(
        "command",
        nargs="?",
        choices=_COMMANDS,
        default="status",
        help="Readiness view (default: status).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit setup projection JSON to stdout.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="For apply: preview writes without modifying files.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root path.",
    )
    return parser


_COMMANDS: tuple[SetupCommand, ...] = ("status", "doctor", "plan", "apply")

_PAYLOAD_BUILDERS: dict[SetupCommand, PayloadBuilder] = {
    "status": build_setup_snapshot,
    "doctor": build_setup_snapshot,
    "plan": build_setup_plan,
}

_PAYLOAD_RENDERERS: dict[SetupCommand, PayloadRenderer] = {
    "status": lambda console, payload: render_setup_status(
        console=console,
        snapshot=payload,
    ),
    "doctor": lambda console, payload: render_setup_doctor(
        console=console,
        snapshot=payload,
    ),
    "plan": lambda console, payload: render_setup_plan(
        console=console,
        plan=payload,
    ),
    "apply": lambda console, payload: render_setup_apply(
        console=console,
        result=payload,
    ),
}


__all__ = ["setup_main"]
