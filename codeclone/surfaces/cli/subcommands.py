# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable


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


_SUBCOMMAND_HANDLERS: dict[str, Callable[[list[str]], int]] = {
    "setup": _run_setup,
    "analytics": _run_analytics,
    "memory": _run_memory,
    "observability": _run_observability,
}


def dispatch_subcommand(argv: list[str]) -> None:
    """Dispatch CLI-owned subcommands without importing them on analysis runs."""
    if len(argv) <= 1:
        return
    handler = _SUBCOMMAND_HANDLERS.get(argv[1])
    if handler is not None:
        raise SystemExit(handler(argv[2:]))


__all__ = ["dispatch_subcommand"]
