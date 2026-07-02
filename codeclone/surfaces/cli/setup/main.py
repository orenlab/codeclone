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
from ....ui_messages import setup as setup_ui
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
from .wizard import run_setup_wizard

SetupCommand = str
PayloadBuilder = Callable[[Path], dict[str, object]]
PayloadRenderer = Callable[[PrinterLike, dict[str, object]], None]

_APPLY_FAILURE_STATUS: frozenset[str] = frozenset({"failed", "partial"})
_APPLY_CONTRACT_STATUS: frozenset[str] = frozenset({"blocked", "stale_plan"})

# argparse attribute -> usage message when the flag is used outside `apply`.
_APPLY_ONLY_FLAGS: tuple[tuple[str, str], ...] = (
    ("dry_run", setup_ui.SETUP_DRY_RUN_ONLY_APPLY),
    ("yes", setup_ui.SETUP_YES_ONLY_APPLY),
    ("plan_id", setup_ui.SETUP_PLAN_ID_ONLY_APPLY),
)


def setup_main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    root_path = Path(args.root).expanduser().resolve()
    command = args.command or "status"

    usage_error = _precheck_error(command, root_path, args)
    if usage_error is not None:
        print(usage_error, file=sys.stderr)
        return int(ExitCode.CONTRACT_ERROR)

    try:
        return _dispatch(command, root_path, args)
    except Exception as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL_ERROR)


def _precheck_error(
    command: SetupCommand,
    root_path: Path,
    args: argparse.Namespace,
) -> str | None:
    if not root_path.is_dir():
        return f"Repository root does not exist: {root_path}"
    if command != "apply":
        for attr, message in _APPLY_ONLY_FLAGS:
            if getattr(args, attr):
                return message
    if args.json and command == "wizard":
        return setup_ui.SETUP_WIZARD_JSON_UNSUPPORTED
    return None


def _dispatch(
    command: SetupCommand,
    root_path: Path,
    args: argparse.Namespace,
) -> int:
    if command == "wizard":
        return run_setup_wizard(root_path)
    if command == "apply":
        return _run_apply(root_path, args)

    payload = _PAYLOAD_BUILDERS[command](root_path)
    if args.json:
        _write_json_stdout(payload)
    else:
        _render_payload(command, payload)
    return int(ExitCode.SUCCESS)


def _run_apply(root_path: Path, args: argparse.Namespace) -> int:
    if not args.dry_run and not args.yes:
        gate_exit = _confirmation_gate(root_path)
        if gate_exit is not None:
            return gate_exit

    result = apply_setup_plan(
        root_path,
        dry_run=args.dry_run,
        expected_plan_id=args.plan_id or None,
    )
    status = str(result.get("status", ""))
    if args.json:
        _write_json_stdout(result)
    elif status == "stale_plan":
        print(setup_ui.SETUP_APPLY_STALE_PLAN, file=sys.stderr)
    else:
        _render_payload("apply", result)
    return _exit_code_for_apply(status)


def _confirmation_gate(root_path: Path) -> int | None:
    """Preview the plan and confirm before an interactive apply.

    Returns ``None`` when the caller may proceed with the write; otherwise an exit
    code: refuse without a TTY (``CONTRACT_ERROR``) or an operator decline
    (``SUCCESS``, nothing written).
    """

    confirmed = _confirm_apply(root_path)
    if confirmed:
        return None
    if confirmed is None:
        message, stream, code = (
            setup_ui.SETUP_APPLY_CONFIRM_REQUIRED,
            sys.stderr,
            ExitCode.CONTRACT_ERROR,
        )
    else:
        message, stream, code = (
            setup_ui.SETUP_APPLY_ABORTED,
            sys.stdout,
            ExitCode.SUCCESS,
        )
    print(message, file=stream)
    return int(code)


def _confirm_apply(root_path: Path) -> bool | None:
    """Preview the plan and ask for confirmation on a TTY.

    Returns ``None`` when no interactive terminal is available (caller must refuse
    without ``--yes``), otherwise the operator's yes/no decision.
    """

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    console = make_query_console(no_color=False)
    render_setup_plan(console=console, plan=build_setup_plan(root_path))
    reply = input(f"{setup_ui.SETUP_APPLY_CONFIRM_PROMPT} [y/N] ").strip().lower()
    return reply in {"y", "yes"}


def _exit_code_for_apply(status: str) -> int:
    if status in _APPLY_FAILURE_STATUS:
        return int(ExitCode.INTERNAL_ERROR)
    if status in _APPLY_CONTRACT_STATUS:
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
        help="Readiness view or action (default: status).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit setup projection JSON to stdout (status/doctor/plan/apply).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="For apply: preview writes without modifying files.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="For apply: skip the confirmation prompt (required non-interactively).",
    )
    parser.add_argument(
        "--plan-id",
        default="",
        help="For apply: only proceed if the recomputed plan matches this id.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root path.",
    )
    return parser


_COMMANDS: tuple[SetupCommand, ...] = ("status", "doctor", "plan", "apply", "wizard")

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
