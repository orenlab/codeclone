# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Rich/plain renderers for setup readiness snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from ....ui_messages import setup as setup_ui
from ..console import rich_panel_symbols, supports_rich_console
from ..types import PrinterLike
from .engine.capabilities import GROUP_ORDER


def render_setup_status(
    *, console: PrinterLike, snapshot: Mapping[str, object]
) -> None:
    if supports_rich_console(console):
        _render_status_rich(console=console, snapshot=snapshot)
        return
    _render_status_plain(console=console, snapshot=snapshot)


def render_setup_doctor(
    *, console: PrinterLike, snapshot: Mapping[str, object]
) -> None:
    if supports_rich_console(console):
        _render_doctor_rich(console=console, snapshot=snapshot)
        return
    _render_doctor_plain(console=console, snapshot=snapshot)


def render_setup_plan(*, console: PrinterLike, plan: Mapping[str, object]) -> None:
    if supports_rich_console(console):
        _render_plan_rich(console=console, plan=plan)
        return
    _render_plan_plain(console=console, plan=plan)


def _render_status_rich(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    _, _panel_cls, rule_cls, table_cls, _ = rich_panel_symbols()
    runtime = _mapping(snapshot.get("runtime"))
    console.print(setup_ui.SETUP_STATUS_TITLE)
    console.print()
    console.print(
        rule_cls(title="Readiness", style="dim", characters="\u2500"),
    )
    console.print(
        f"  [dim]Root:[/dim] {snapshot.get('root')}  "
        f"[dim]Python:[/dim] {runtime.get('python_tag')}  "
        f"[dim]CodeClone:[/dim] {runtime.get('codeclone_version')}"
    )
    maturity = _mapping(snapshot.get("maturity"))
    console.print(
        "  [dim]Maturity:[/dim] "
        f"connected={maturity.get('connected')}  "
        f"governed={maturity.get('governed')}  "
        f"evidence={maturity.get('evidence_backed')}  "
        f"team={maturity.get('team_ready')}  "
        f"release={maturity.get('release_ready')}"
    )
    console.print()
    for group in GROUP_ORDER:
        rows = [item for item in _capabilities(snapshot) if item.get("group") == group]
        if not rows:
            continue
        console.print(setup_ui.GROUP_LABELS[group])
        table = table_cls(show_header=True, header_style="bold")
        table.add_column("Capability", style="bold")
        table.add_column("Readiness")
        table.add_column("Reason")
        for row in rows:
            reason = str(row.get("reason", ""))
            table.add_row(
                str(row.get("label", "")),
                str(row.get("readiness", "")),
                reason if reason else "-",
            )
        console.print(table)
        console.print()


def _render_doctor_rich(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    _, panel_cls, rule_cls, _table_cls, _ = rich_panel_symbols()
    _render_status_rich(console, snapshot)
    console.print(rule_cls(title="Probe diagnostics", style="dim", characters="\u2500"))
    for row in _capabilities(snapshot):
        cap_id = str(row.get("id", ""))
        evidence = row.get("evidence")
        evidence_text = ", ".join(evidence) if isinstance(evidence, list) else ""
        action = str(row.get("recommended_action", ""))
        body = (
            f"id={cap_id}\n"
            f"installation={row.get('installation')}  "
            f"configuration={row.get('configuration')}  "
            f"runtime={row.get('runtime')}\n"
            f"evidence={evidence_text or '-'}\n"
            f"action={action or '-'}"
        )
        console.print(panel_cls(body, title=str(row.get("label", cap_id))))


def _render_status_plain(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    runtime = _mapping(snapshot.get("runtime"))
    console.print(setup_ui.SETUP_STATUS_TITLE)
    console.print(f"root: {snapshot.get('root')}")
    console.print(
        f"python: {runtime.get('python_tag')}  "
        f"codeclone: {runtime.get('codeclone_version')}"
    )
    for row in _capabilities(snapshot):
        reason = str(row.get("reason", ""))
        line = f"{row.get('label')}: {row.get('readiness')} ({row.get('availability')})"
        if reason:
            line = f"{line} — {reason}"
        console.print(line)


def _render_doctor_plain(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    console.print(setup_ui.SETUP_DOCTOR_TITLE)
    _render_status_plain(console, snapshot)
    for row in _capabilities(snapshot):
        evidence = row.get("evidence")
        if isinstance(evidence, list) and evidence:
            console.print(f"  evidence[{row.get('id')}]: {', '.join(evidence)}")


def _render_plan_rich(console: PrinterLike, plan: Mapping[str, object]) -> None:
    _, panel_cls, rule_cls, table_cls, _ = rich_panel_symbols()
    console.print(setup_ui.SETUP_PLAN_TITLE)
    console.print()
    console.print(
        rule_cls(title="Plan summary", style="dim", characters="\u2500"),
    )
    console.print(
        f"  [dim]Root:[/dim] {plan.get('root')}  "
        f"[dim]Status:[/dim] {plan.get('status')}  "
        f"[dim]Plan id:[/dim] {plan.get('plan_id')}"
    )
    console.print(f"  [dim]{setup_ui.SETUP_PLAN_READ_ONLY_NOTE}[/dim]")
    console.print()

    blockers = plan.get("blockers")
    if isinstance(blockers, list) and blockers:
        console.print(setup_ui.SETUP_PLAN_BLOCKED)
        for blocker in blockers:
            if isinstance(blocker, Mapping):
                console.print(f"  - {blocker.get('kind')}: {blocker.get('reason', '')}")
        console.print()

    actions = _plan_actions(plan)
    if not actions:
        console.print(setup_ui.SETUP_PLAN_EMPTY)
        return

    table = table_cls(show_header=True, header_style="bold")
    table.add_column("Action")
    table.add_column("Target")
    table.add_column("Status")
    for action in actions:
        table.add_row(
            str(action.get("kind", "")),
            str(action.get("path", "")),
            str(action.get("status", "")),
        )
    console.print(table)
    console.print()

    for action in actions:
        preview = action.get("preview")
        diff = ""
        if isinstance(preview, Mapping):
            diff = str(preview.get("unified_diff", ""))
        if not diff:
            continue
        title = f"{action.get('kind')} → {action.get('path')}"
        console.print(panel_cls(diff.rstrip(), title=title))


def _render_plan_plain(console: PrinterLike, plan: Mapping[str, object]) -> None:
    console.print(setup_ui.SETUP_PLAN_TITLE)
    console.print(f"status: {plan.get('status')}  plan_id: {plan.get('plan_id')}")
    console.print(setup_ui.SETUP_PLAN_READ_ONLY_NOTE)
    actions = _plan_actions(plan)
    if not actions:
        console.print(setup_ui.SETUP_PLAN_EMPTY)
        return
    for action in actions:
        console.print(
            f"{action.get('kind')} {action.get('path')}: {action.get('status')}"
        )
        preview = action.get("preview")
        if isinstance(preview, Mapping):
            diff = str(preview.get("unified_diff", "")).strip()
            if diff:
                console.print(diff)


def _plan_actions(plan: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = plan.get("actions")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _capabilities(snapshot: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = snapshot.get("capabilities")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


__all__ = ["render_setup_doctor", "render_setup_plan", "render_setup_status"]
