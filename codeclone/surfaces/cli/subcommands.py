# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable
from pathlib import Path

from ... import ui_messages as ui
from ...contracts import ExitCode


def _run_setup(argv: list[str]) -> int:
    from .setup import setup_main

    return setup_main(argv)


def _run_analytics(argv: list[str]) -> int:
    from .analytics import analytics_main

    return analytics_main(argv)


def _run_memory(argv: list[str]) -> int:
    from .memory import memory_main

    return memory_main(argv)


def _run_observability(argv: list[str]) -> int:
    from .observability import observability_main

    return observability_main(argv)


def _run_baseline(argv: list[str]) -> int:
    from .baseline_state import recover_baseline_publish_lock

    parser = argparse.ArgumentParser(
        prog="codeclone baseline",
        description=ui.HELP_BASELINE_COMMAND,
    )
    actions = parser.add_subparsers(dest="action", required=True)
    recover = actions.add_parser(
        "recover-lock",
        help=ui.HELP_BASELINE_RECOVER_LOCK,
    )
    recover.add_argument(
        "--path",
        required=True,
        help=ui.HELP_BASELINE_RECOVER_PATH,
    )
    recover.add_argument(
        "--expected-token",
        required=True,
        help=ui.HELP_BASELINE_RECOVER_TOKEN,
    )
    recover.add_argument(
        "--force",
        action="store_true",
        help=ui.HELP_BASELINE_RECOVER_FORCE,
    )
    args = parser.parse_args(argv)
    target = Path(args.path).expanduser().resolve()
    failure = recover_baseline_publish_lock(
        target=target,
        expected_token=args.expected_token,
        force=args.force,
    )
    if failure is not None:
        print(ui.fmt_baseline_lock_recovery_failed(path=target, reason=failure))
        return int(ExitCode.CONTRACT_ERROR)
    print(ui.fmt_baseline_lock_recovered(path=target))
    return int(ExitCode.SUCCESS)


def _run_run_store(argv: list[str]) -> int:
    """``codeclone run-store migrate --path PATH``: the run store's one
    explicit schema migration -- the command an open's refusal names."""
    parser = argparse.ArgumentParser(
        prog="codeclone run-store",
        description=ui.HELP_RUN_STORE_COMMAND,
    )
    actions = parser.add_subparsers(dest="action", required=True)
    migrate = actions.add_parser("migrate", help=ui.HELP_RUN_STORE_MIGRATE)
    migrate.add_argument("--path", required=True, help=ui.HELP_RUN_STORE_MIGRATE_PATH)
    args = parser.parse_args(argv)
    target = Path(args.path).expanduser()
    from ...api.run_store_migration import RunStoreError, migrate_run_store_schema

    try:
        added = migrate_run_store_schema(target)
    except (RunStoreError, sqlite3.DatabaseError) as refusal:
        print(refusal)
        return int(ExitCode.CONTRACT_ERROR)
    if not added:
        print(f"Run store schema at {target} is complete; nothing to migrate.")
        return int(ExitCode.SUCCESS)
    spelled = ", ".join(f"{kind} {name}" for kind, name in added)
    print(
        f"Run store schema at {target}: added {spelled}. The witness, the "
        "storage revision and every stored run are unchanged."
    )
    return int(ExitCode.SUCCESS)


_SUBCOMMAND_HANDLERS: dict[str, Callable[[list[str]], int]] = {
    "setup": _run_setup,
    "analytics": _run_analytics,
    "baseline": _run_baseline,
    "memory": _run_memory,
    "observability": _run_observability,
    "run-store": _run_run_store,
}


def dispatch_subcommand(argv: list[str]) -> None:
    """Dispatch CLI-owned subcommands without importing them on analysis runs."""
    if len(argv) <= 1:
        return
    handler = _SUBCOMMAND_HANDLERS.get(argv[1])
    if handler is not None:
        raise SystemExit(handler(argv[2:]))


__all__ = ["dispatch_subcommand"]
