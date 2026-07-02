# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Interactive setup wizard: hub navigation and guided plan/apply."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ....contracts import ExitCode
from ....ui_messages import setup as setup_ui
from ..console import make_query_console, rich_panel_symbols, supports_rich_console
from ..types import PrinterLike
from .engine.apply import apply_setup_plan
from .engine.capabilities import GROUP_ORDER, CapabilityGroup
from .engine.discover import build_setup_snapshot
from .engine.plan import build_setup_plan
from .render import (
    render_setup_apply,
    render_setup_capability_table,
    render_setup_doctor,
    render_setup_plan,
    render_setup_status,
    snapshot_capabilities,
)

_HUB_QUIT: Final = "0"
_HUB_GUIDED: Final = "g"
_HUB_DOCTOR: Final = "d"
_GROUP_CHOICES: Final[tuple[str, ...]] = tuple(
    str(index + 1) for index in range(len(GROUP_ORDER))
)
_PLAN_GUIDANCE: Final[dict[str, tuple[str, ExitCode]]] = {
    "blocked": (setup_ui.SETUP_WIZARD_GUIDED_BLOCKED, ExitCode.CONTRACT_ERROR),
    "empty": (setup_ui.SETUP_WIZARD_GUIDED_EMPTY, ExitCode.SUCCESS),
}
_APPLY_FAILURE_STATUS: Final[frozenset[str]] = frozenset({"failed", "partial"})


@dataclass(frozen=True, slots=True)
class WizardPrompts:
    ask_choice: Callable[[str, list[str]], str]
    confirm: Callable[[str, bool], bool]


def run_setup_wizard(
    root_path: Path,
    *,
    console: PrinterLike | None = None,
    prompts: WizardPrompts | None = None,
) -> int:
    """Run the interactive hub session until the operator quits."""

    if not _interactive_terminal_available():
        print(setup_ui.SETUP_WIZARD_TTY_REQUIRED, file=sys.stderr)
        return int(ExitCode.CONTRACT_ERROR)

    resolved_console = console or make_query_console(no_color=False)
    if not supports_rich_console(resolved_console):
        print(setup_ui.SETUP_WIZARD_RICH_REQUIRED, file=sys.stderr)
        return int(ExitCode.CONTRACT_ERROR)

    resolved_prompts = prompts or _default_wizard_prompts(resolved_console)
    while True:
        snapshot = build_setup_snapshot(root_path)
        _render_hub_header(resolved_console, snapshot)
        choice = resolved_prompts.ask_choice(
            setup_ui.SETUP_WIZARD_PROMPT,
            list(_hub_choices()),
        )
        exit_code = _process_hub_choice(
            choice,
            root_path=root_path,
            console=resolved_console,
            snapshot=snapshot,
            prompts=resolved_prompts,
        )
        if exit_code is not None:
            return exit_code


def _process_hub_choice(
    choice: str,
    *,
    root_path: Path,
    console: PrinterLike,
    snapshot: Mapping[str, object],
    prompts: WizardPrompts,
) -> int | None:
    if choice == _HUB_QUIT:
        return int(ExitCode.SUCCESS)
    if choice == _HUB_GUIDED:
        guided_exit = _run_guided_setup(
            root_path,
            console=console,
            prompts=prompts,
        )
        return None if guided_exit == int(ExitCode.SUCCESS) else guided_exit
    if choice == _HUB_DOCTOR:
        render_setup_doctor(console=console, snapshot=snapshot)
        return None
    group = _group_for_choice(choice)
    if group is not None:
        _render_sphere(console, snapshot, group=group)
    return None


def _run_guided_setup(
    root_path: Path,
    *,
    console: PrinterLike,
    prompts: WizardPrompts,
) -> int:
    plan = build_setup_plan(root_path)
    console.print()
    render_setup_plan(console=console, plan=plan)
    plan_exit = _guided_plan_exit(console, str(plan.get("status", "")))
    if plan_exit is not None:
        return plan_exit
    if not prompts.confirm(setup_ui.SETUP_WIZARD_CONFIRM_APPLY, False):
        console.print(setup_ui.SETUP_WIZARD_APPLY_SKIPPED)
        return int(ExitCode.SUCCESS)

    # Bind apply to the plan the operator just confirmed so a concurrent repo
    # change between preview and apply is refused rather than silently applied.
    result = apply_setup_plan(
        root_path,
        expected_plan_id=str(plan.get("plan_id", "")),
    )
    console.print()
    render_setup_apply(console=console, result=result)
    apply_exit = _apply_result_exit(str(result.get("status", "")))
    if apply_exit is not None:
        return apply_exit

    console.print()
    console.print(setup_ui.SETUP_WIZARD_UPDATED_READINESS)
    render_setup_status(
        console=console,
        snapshot=build_setup_snapshot(root_path),
    )
    return int(ExitCode.SUCCESS)


def _guided_plan_exit(console: PrinterLike, status: str) -> int | None:
    guidance = _PLAN_GUIDANCE.get(status)
    if guidance is None:
        return None
    message, exit_code = guidance
    console.print(message)
    return int(exit_code)


def _apply_result_exit(status: str) -> int | None:
    if status in _APPLY_FAILURE_STATUS:
        return int(ExitCode.INTERNAL_ERROR)
    if status in {"blocked", "stale_plan"}:
        return int(ExitCode.CONTRACT_ERROR)
    return None


def _interactive_terminal_available() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _default_wizard_prompts(console: PrinterLike) -> WizardPrompts:
    from rich.console import Console
    from rich.prompt import Confirm, Prompt

    if not isinstance(console, Console):
        raise RuntimeError(setup_ui.SETUP_WIZARD_RICH_REQUIRED)

    rich_console = console

    def ask_choice(message: str, choices: list[str]) -> str:
        return str(
            Prompt.ask(
                message,
                choices=choices,
                show_choices=False,
                console=rich_console,
            )
        )

    def confirm(message: str, default: bool) -> bool:
        return bool(
            Confirm.ask(
                message,
                default=default,
                console=rich_console,
            )
        )

    return WizardPrompts(ask_choice=ask_choice, confirm=confirm)


def _hub_choices() -> tuple[str, ...]:
    return (*_GROUP_CHOICES, _HUB_GUIDED, _HUB_DOCTOR, _HUB_QUIT)


def _group_for_choice(choice: str) -> CapabilityGroup | None:
    if choice not in _GROUP_CHOICES:
        return None
    return GROUP_ORDER[int(choice) - 1]


def _render_hub_header(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    _, _panel_cls, rule_cls, table_cls, _ = rich_panel_symbols()
    console.print()
    console.print(setup_ui.SETUP_WIZARD_TITLE)
    console.print(
        rule_cls(
            title=setup_ui.SETUP_WIZARD_HUB_RULE, style="dim", characters="\u2500"
        ),
    )
    maturity = _mapping(snapshot.get("maturity"))
    console.print(
        "  [dim]Root:[/dim] "
        f"{snapshot.get('root')}  "
        "[dim]Maturity:[/dim] "
        f"connected={maturity.get('connected')}  "
        f"governed={maturity.get('governed')}  "
        f"evidence={maturity.get('evidence_backed')}  "
        f"team={maturity.get('team_ready')}  "
        f"release={maturity.get('release_ready')}"
    )
    console.print()
    table = table_cls(show_header=True, header_style="bold")
    table.add_column("#")
    table.add_column("Sphere")
    table.add_column("Summary")
    for index, group in enumerate(GROUP_ORDER, start=1):
        table.add_row(
            str(index), setup_ui.GROUP_LABELS[group], _group_summary(snapshot, group)
        )
    table.add_row(
        _HUB_GUIDED,
        setup_ui.SETUP_WIZARD_GUIDED_LABEL,
        setup_ui.SETUP_WIZARD_GUIDED_HINT,
    )
    table.add_row(
        _HUB_DOCTOR,
        setup_ui.SETUP_WIZARD_DOCTOR_LABEL,
        setup_ui.SETUP_WIZARD_DOCTOR_HINT,
    )
    table.add_row(
        _HUB_QUIT, setup_ui.SETUP_WIZARD_QUIT_LABEL, setup_ui.SETUP_WIZARD_QUIT_HINT
    )
    console.print(table)


def _render_sphere(
    console: PrinterLike,
    snapshot: Mapping[str, object],
    *,
    group: CapabilityGroup,
) -> None:
    _, _panel_cls, rule_cls, _table_cls, _ = rich_panel_symbols()
    console.print()
    sphere_title = (
        f"{setup_ui.GROUP_LABELS[group]} — {setup_ui.SETUP_WIZARD_SPHERE_RULE}"
    )
    console.print(
        rule_cls(
            title=sphere_title,
            style="dim",
            characters="\u2500",
        ),
    )
    rows = [
        item for item in snapshot_capabilities(snapshot) if item.get("group") == group
    ]
    if not rows:
        console.print(setup_ui.SETUP_WIZARD_SPHERE_EMPTY)
        return
    render_setup_capability_table(console, rows)


def _group_summary(snapshot: Mapping[str, object], group: CapabilityGroup) -> str:
    rows = [
        item for item in snapshot_capabilities(snapshot) if item.get("group") == group
    ]
    if not rows:
        return setup_ui.SETUP_WIZARD_SPHERE_EMPTY
    counts: dict[str, int] = {}
    for row in rows:
        readiness = str(row.get("readiness", "unknown"))
        counts[readiness] = counts.get(readiness, 0) + 1
    parts = [
        f"{readiness}={count}"
        for readiness, count in sorted(counts.items(), key=lambda item: item[0])
    ]
    return ", ".join(parts)


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


__all__ = ["WizardPrompts", "run_setup_wizard"]
