# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Rich/plain renderers for setup readiness snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, TypeGuard

from ....ui_messages import setup as setup_ui
from ....ui_messages.styling import fmt_bool
from ..console import rich_panel_symbols, supports_rich_console
from ..types import PrinterLike
from .engine.capabilities import GROUP_ORDER

if TYPE_CHECKING:
    from rich.rule import Rule as RichRule
    from rich.table import Table as RichTable


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
    install = _mapping(snapshot.get("install"))
    console.print(setup_ui.SETUP_STATUS_TITLE)
    console.print()
    console.print(
        rule_cls(title="Readiness", style="dim", characters="\u2500"),
    )
    console.print(
        f"  [dim]Root:[/dim] {snapshot.get('root')}  "
        f"[dim]Python:[/dim] {runtime.get('python_tag')}  "
        f"[dim]CodeClone:[/dim] {runtime.get('codeclone_version')}  "
        f"[dim]{setup_ui.SETUP_STATUS_BASE_LABEL}:[/dim] {install.get('base')}"
    )
    commit = snapshot.get("head_commit") or "\u2014"
    console.print(
        f"  [dim]Schema:[/dim] {snapshot.get('schema_version')}  "
        f"[dim]Recomputation:[/dim] {fmt_bool(snapshot.get('recomputation'))}  "
        f"[dim]Commit:[/dim] {commit}"
    )
    maturity = _mapping(snapshot.get("maturity"))
    console.print(
        "  [dim]Maturity:[/dim] "
        f"connected={fmt_bool(maturity.get('connected'))}  "
        f"governed={fmt_bool(maturity.get('governed'))}  "
        f"evidence={fmt_bool(maturity.get('evidence_backed'))}  "
        f"team={fmt_bool(maturity.get('team_ready'))}  "
        f"release={fmt_bool(maturity.get('release_ready'))}"
    )
    console.print()
    for group in GROUP_ORDER:
        rows = [item for item in _capabilities(snapshot) if item.get("group") == group]
        if not rows:
            continue
        console.print(setup_ui.GROUP_LABELS[group])
        table = table_cls(show_header=True, header_style="bold")
        table.add_column("Capability", style="bold")
        table.add_column("Availability")
        table.add_column("Readiness")
        table.add_column("Reason")
        table.add_column("Next step")
        for row in rows:
            table.add_row(
                str(row.get("label", "")),
                _availability_label(row.get("availability")),
                str(row.get("readiness", "")),
                str(row.get("reason", "")) or "-",
                str(row.get("recommended_action", "")) or "-",
            )
        console.print(table)
        console.print()


def _render_doctor_rich(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    _, panel_cls, rule_cls, _table_cls, _ = rich_panel_symbols()
    _render_status_rich(console, snapshot)
    console.print(
        rule_cls(
            title=setup_ui.SETUP_DOCTOR_PROBES_HEADER,
            style="dim",
            characters="\u2500",
        )
    )
    for row in _capabilities(snapshot):
        console.print(
            panel_cls(
                _doctor_body(row),
                title=str(row.get("label", row.get("id", ""))),
            )
        )


def _doctor_body(row: Mapping[str, object]) -> str:
    evidence = row.get("evidence")
    evidence_text = ", ".join(evidence) if _is_string_list(evidence) else ""
    reason = str(row.get("reason", ""))
    action = str(row.get("recommended_action", ""))
    return (
        f"id={row.get('id')}  availability={row.get('availability')}  "
        f"readiness={row.get('readiness')}\n"
        f"installation={row.get('installation')}  "
        f"configuration={row.get('configuration')}  "
        f"runtime={row.get('runtime')}\n"
        f"cause={reason or '-'}\n"
        f"{setup_ui.SETUP_DOCTOR_PROBES_LABEL}={evidence_text or '-'}\n"
        f"action={action or '-'}"
    )


def _render_status_plain(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    runtime = _mapping(snapshot.get("runtime"))
    install = _mapping(snapshot.get("install"))
    console.print(setup_ui.SETUP_STATUS_TITLE)
    console.print(f"root: {snapshot.get('root')}")
    console.print(
        f"python: {runtime.get('python_tag')}  "
        f"codeclone: {runtime.get('codeclone_version')}  "
        f"base: {install.get('base')}  "
        f"schema: {snapshot.get('schema_version')}"
    )
    for row in _capabilities(snapshot):
        reason = str(row.get("reason", ""))
        action = str(row.get("recommended_action", ""))
        availability = _availability_label(row.get("availability"))
        line = f"{row.get('label')}: {row.get('readiness')} ({availability})"
        if reason:
            line = f"{line} — {reason}"
        if action:
            line = f"{line} → {action}"
        console.print(line)


def _render_doctor_plain(console: PrinterLike, snapshot: Mapping[str, object]) -> None:
    console.print(setup_ui.SETUP_DOCTOR_TITLE)
    _render_status_plain(console, snapshot)
    for row in _capabilities(snapshot):
        evidence = row.get("evidence")
        if _is_string_list(evidence) and evidence:
            label = setup_ui.SETUP_DOCTOR_PROBES_LABEL
            console.print(f"  {label}[{row.get('id')}]: {', '.join(evidence)}")


def _availability_label(availability: object) -> str:
    return setup_ui.AVAILABILITY_LABELS.get(str(availability), str(availability))


def _render_plan_rich(console: PrinterLike, plan: Mapping[str, object]) -> None:
    _, panel_cls, rule_cls, table_cls, _ = rich_panel_symbols()
    _print_setup_rich_header(
        console,
        title=setup_ui.SETUP_PLAN_TITLE,
        rule_title="Plan summary",
        rule_cls=rule_cls,
        root=plan.get("root"),
        status=plan.get("status"),
        plan_id=plan.get("plan_id"),
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

    _print_kind_path_status_table(
        console,
        table_cls,
        actions,
        status_column="Status",
    )
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


def render_setup_apply(*, console: PrinterLike, result: Mapping[str, object]) -> None:
    if supports_rich_console(console):
        _render_apply_rich(console=console, result=result)
        return
    _render_apply_plain(console=console, result=result)


def _render_apply_rich(console: PrinterLike, result: Mapping[str, object]) -> None:
    _, _panel_cls, rule_cls, table_cls, _ = rich_panel_symbols()
    _print_setup_rich_header(
        console,
        title=setup_ui.SETUP_APPLY_TITLE,
        rule_title="Apply summary",
        rule_cls=rule_cls,
        root=result.get("root"),
        status=result.get("status"),
        plan_id=result.get("plan_id"),
    )
    if result.get("dry_run"):
        console.print("  [dim]Dry run — no files were modified.[/dim]")
    console.print()

    status = str(result.get("status", ""))
    if status == "blocked":
        console.print(setup_ui.SETUP_APPLY_BLOCKED)
        return
    results = _apply_results(result)
    if not results:
        console.print(setup_ui.SETUP_APPLY_NOOP)
        return

    _print_kind_path_status_table(
        console,
        table_cls,
        results,
        status_column="Result",
    )


def _render_apply_plain(console: PrinterLike, result: Mapping[str, object]) -> None:
    console.print(setup_ui.SETUP_APPLY_TITLE)
    console.print(
        f"status: {result.get('status')}  plan_id: {result.get('plan_id')}  "
        f"dry_run: {result.get('dry_run')}"
    )
    if str(result.get("status", "")) == "blocked":
        console.print(setup_ui.SETUP_APPLY_BLOCKED)
        return
    for row in _apply_results(result):
        message = str(row.get("message", ""))
        suffix = f" — {message}" if message else ""
        console.print(
            f"{row.get('kind')} {row.get('path')}: {row.get('status')}{suffix}"
        )


def _print_setup_rich_header(
    console: PrinterLike,
    *,
    title: str,
    rule_title: str,
    rule_cls: type[RichRule],
    root: object,
    status: object,
    plan_id: object,
) -> None:
    console.print(title)
    console.print()
    console.print(
        rule_cls(title=rule_title, style="dim", characters="\u2500"),
    )
    console.print(
        f"  [dim]Root:[/dim] {root}  "
        f"[dim]Status:[/dim] {status}  "
        f"[dim]Plan id:[/dim] {plan_id}"
    )


def _print_kind_path_status_table(
    console: PrinterLike,
    table_cls: type[RichTable],
    rows: list[Mapping[str, object]],
    *,
    status_column: str,
) -> None:
    table = table_cls(show_header=True, header_style="bold")
    table.add_column("Action")
    table.add_column("Target")
    table.add_column(status_column)
    for row in rows:
        table.add_row(
            str(row.get("kind", "")),
            str(row.get("path", "")),
            str(row.get("status", "")),
        )
    console.print(table)


def _apply_results(result: Mapping[str, object]) -> list[Mapping[str, object]]:
    return _mapping_rows(result.get("results"))


def _plan_actions(plan: Mapping[str, object]) -> list[Mapping[str, object]]:
    return _mapping_rows(plan.get("actions"))


def snapshot_capabilities(
    snapshot: Mapping[str, object],
) -> list[Mapping[str, object]]:
    return _mapping_rows(snapshot.get("capabilities"))


def render_setup_capability_table(
    console: PrinterLike,
    rows: list[Mapping[str, object]],
) -> None:
    if supports_rich_console(console):
        _, _panel_cls, _rule_cls, table_cls, _ = rich_panel_symbols()
        table = table_cls(show_header=True, header_style="bold")
        table.add_column("Capability")
        table.add_column("Readiness")
        table.add_column("Reason")
        for row in rows:
            reason = str(row.get("reason", ""))
            table.add_row(
                str(row.get("label", "")),
                str(row.get("readiness", "")),
                reason or "-",
            )
        console.print(table)
        return
    for row in rows:
        reason = str(row.get("reason", ""))
        line = f"{row.get('label')}: {row.get('readiness')}"
        if reason:
            line = f"{line} — {reason}"
        console.print(line)


def _capabilities(snapshot: Mapping[str, object]) -> list[Mapping[str, object]]:
    return snapshot_capabilities(snapshot)


def _mapping(value: object) -> Mapping[str, object]:
    if _is_mapping(value):
        return value
    return {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if _is_mapping(item)]


def _is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _is_string_list(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


__all__ = [
    "render_setup_apply",
    "render_setup_capability_table",
    "render_setup_doctor",
    "render_setup_plan",
    "render_setup_status",
    "snapshot_capabilities",
]
