# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...memory.coverage import ScopeCoverageReport
from ...memory.display import format_memory_record_line
from ...memory.models import MemoryRecord
from ...memory.status_report import MemoryStatusReport
from ...memory.vacuum import VacuumReport
from .console import make_query_console, rich_panel_symbols, supports_rich_console
from .types import PrinterLike


def memory_console() -> PrinterLike:
    return make_query_console()


def render_search_results(
    *,
    console: PrinterLike,
    query: str,
    records: Sequence[Mapping[str, object]],
) -> None:
    if supports_rich_console(console):
        _render_record_table_rich(
            console=console,
            command="search",
            subtitle=(
                f"[cyan]{query}[/cyan]  "
                f"[dim]{_count_label(len(records), 'result')}[/dim]"
            ),
            records=records,
            columns=(
                ("#", {"style": "dim", "justify": "right", "no_wrap": True}),
                ("Type", {"style": "cyan", "no_wrap": True}),
                ("Status", {"no_wrap": True}),
                ("Record", {}),
            ),
            row_builder=_search_row,
        )
        return
    console.print(f"Engineering Memory search: {query!r}")
    _print_record_lines(console, records)


def render_path_results(
    *,
    console: PrinterLike,
    rel_path: str,
    records: Sequence[MemoryRecord],
) -> None:
    if supports_rich_console(console):
        mapped = [_record_mapping(record) for record in records]
        _render_record_table_rich(
            console=console,
            command="for-path",
            subtitle=(
                f"[cyan]{rel_path}[/cyan]  "
                f"[dim]{_count_label(len(records), 'record')}[/dim]"
            ),
            records=mapped,
            columns=(
                ("#", {"style": "dim", "justify": "right", "no_wrap": True}),
                ("Type", {"style": "cyan", "no_wrap": True}),
                ("Status", {"no_wrap": True}),
                ("Statement", {}),
            ),
            row_builder=_search_row,
        )
        return
    console.print(f"Engineering Memory for path: {rel_path}")
    _print_record_lines(console, [_record_mapping(record) for record in records])


def render_status_report(*, console: PrinterLike, report: MemoryStatusReport) -> None:
    if supports_rich_console(console):
        _render_status_report_rich(console=console, report=report)
        return
    _render_status_report_plain(console=console, report=report)


def render_init_result(
    *,
    console: PrinterLike,
    dry_run: bool,
    project_id: str,
    db_path: str | None,
    analysis_fingerprint: str | None,
    stats: Mapping[str, int] | None,
    planned_counts: Mapping[str, int] | None,
) -> None:
    if supports_rich_console(console):
        _render_init_result_rich(
            console=console,
            dry_run=dry_run,
            project_id=project_id,
            db_path=db_path,
            analysis_fingerprint=analysis_fingerprint,
            stats=stats,
            planned_counts=planned_counts,
        )
        return
    title = (
        "Engineering Memory init dry-run"
        if dry_run
        else "Engineering Memory initialized"
    )
    console.print(title)
    console.print(f"  project_id: {project_id}")
    if dry_run:
        console.print(f"  analysis_fingerprint:{analysis_fingerprint}")
        _print_count_map(console, "  planned records:", planned_counts)
        return
    if db_path is not None:
        console.print(f"  db:         {db_path}")
    _print_count_map(console, "  upsert stats:", stats)
    _print_count_map(console, "  record types:", planned_counts)


def render_init_note(*, console: PrinterLike, message: str) -> None:
    if supports_rich_console(console):
        _, _, _, _, text_cls = rich_panel_symbols()
        console.print(text_cls(f"  note: {message}", style="dim italic"))
        return
    console.print(f"  note: {message}")


def render_stale_records(
    *,
    console: PrinterLike,
    records: Sequence[Mapping[str, object]],
) -> None:
    if supports_rich_console(console):
        _render_record_table_rich(
            console=console,
            command="stale",
            subtitle=f"[dim]{_count_label(len(records), 'record')}[/dim]",
            border_style="yellow",
            records=records,
            columns=(
                ("#", {"style": "dim", "justify": "right", "no_wrap": True}),
                ("Type", {"style": "cyan", "no_wrap": True}),
                ("Reason", {"style": "yellow", "no_wrap": True}),
                ("Record", {}),
            ),
            row_builder=_stale_row,
            empty_message="(none)",
        )
        return
    console.print("Stale engineering memory records")
    if not records:
        console.print("  (none)")
        return
    for item in records:
        reason = item.get("stale_reason", "")
        line = format_memory_record_line(item)
        console.print(f"  - [{item.get('type')}] {line} ({reason})")


def render_vacuum_report(*, console: PrinterLike, report: VacuumReport) -> None:
    if supports_rich_console(console):
        _render_vacuum_report_rich(console=console, report=report)
        return
    console.print("Engineering Memory vacuum complete")
    console.print(f"  deleted: {report.total_deleted}")
    _print_count_map(console, "  ", report.deleted_by_status, indent="    ")


def render_coverage_report(
    *, console: PrinterLike, report: ScopeCoverageReport
) -> None:
    if supports_rich_console(console):
        _render_coverage_report_rich(console=console, report=report)
        return
    console.print("Engineering Memory coverage")
    covered = report.scope_paths_with_memory
    total = report.scope_paths_total
    console.print(f"  covered: {covered}/{total} ({report.scope_coverage_percent}%)")
    if report.uncovered_paths:
        console.print("  uncovered:")
        for path in report.uncovered_paths:
            console.print(f"    - {path}")


def render_draft_candidates(
    *,
    console: PrinterLike,
    records: Sequence[MemoryRecord],
) -> None:
    if supports_rich_console(console):
        _render_record_table_rich(
            console=console,
            command="review candidates",
            subtitle=f"[dim]{_count_label(len(records), 'draft')}[/dim]",
            border_style="magenta",
            records=records,
            columns=(
                ("#", {"style": "dim", "justify": "right", "no_wrap": True}),
                ("ID", {"style": "dim", "no_wrap": True}),
                ("Type", {"style": "cyan", "no_wrap": True}),
                ("Statement", {}),
            ),
            row_builder=_draft_row,
            empty_message="(none)",
        )
        return
    console.print("Draft memory candidates")
    if not records:
        console.print("  (none)")
        return
    for record in records:
        console.print(f"  - {record.id} [{record.type}] {record.statement}")


def render_governance_result(
    *,
    console: PrinterLike,
    action: str,
    record_id: str,
    detail: str | None = None,
) -> None:
    message = detail or f"{action} {record_id}"
    if supports_rich_console(console):
        _, panel_cls, _, _, text_cls = rich_panel_symbols()
        style = "green" if action == "approved" else "yellow"
        console.print(
            panel_cls(
                text_cls(message, style=style),
                border_style=style,
                padding=(0, 1),
            )
        )
        return
    console.print(message)


def _render_record_table_rich(
    *,
    console: PrinterLike,
    command: str,
    subtitle: str,
    records: Sequence[object],
    columns: Sequence[tuple[str, dict[str, object]]],
    row_builder: Any,
    border_style: str = "blue",
    empty_message: str = "(no records)",
) -> None:
    box, panel_cls, rule_cls, table_cls, text_cls = rich_panel_symbols()
    console.print(rule_cls("Engineering Memory", style="dim", characters="─"))
    console.print(
        panel_cls(
            text_cls.from_markup(f"[bold]{command}[/bold]  {subtitle}"),
            border_style=border_style,
            padding=(0, 1),
        )
    )
    if not records:
        console.print(f"  [dim]{empty_message}[/dim]")
        return
    table = table_cls(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
        padding=(0, 1),
    )
    for title, kwargs in columns:
        table.add_column(title, **kwargs)
    for index, item in enumerate(records, start=1):
        table.add_row(*row_builder(index, item, text_cls))
    console.print(table)


def _search_row(
    index: int,
    item: Mapping[str, object],
    text_cls: Any,
) -> tuple[str, str, Any, str]:
    record_type = str(item.get("type", "?"))
    status = str(item.get("status", "?"))
    return (
        str(index),
        record_type,
        text_cls(status, style=_status_style(status)),
        format_memory_record_line(item),
    )


def _stale_row(
    index: int,
    item: Mapping[str, object],
    _text_cls: Any,
) -> tuple[str, str, str, str]:
    return (
        str(index),
        str(item.get("type", "?")),
        str(item.get("stale_reason", "")),
        format_memory_record_line(item),
    )


def _draft_row(
    index: int,
    record: MemoryRecord,
    _text_cls: Any,
) -> tuple[str, str, str, str]:
    return (str(index), record.id, record.type, record.statement)


def _render_status_report_rich(
    *, console: PrinterLike, report: MemoryStatusReport
) -> None:
    box, panel_cls, rule_cls, table_cls, text_cls = rich_panel_symbols()
    console.print(rule_cls("Engineering Memory", style="dim", characters="─"))
    console.print(
        panel_cls(
            text_cls.from_markup("[bold]status[/bold]"),
            border_style="blue",
            padding=(0, 1),
        )
    )
    meta = table_cls.grid(padding=(0, 2))
    meta.add_column(style="dim", no_wrap=True)
    meta.add_column()
    for label, value in _status_rows(report):
        meta.add_row(label, value)
    console.print(meta)
    if report.records_by_type:
        type_table = table_cls(box=box.SIMPLE, show_header=True, header_style="bold")
        type_table.add_column("Type", style="cyan")
        type_table.add_column("Count", justify="right")
        for key, count in sorted(report.records_by_type.items()):
            type_table.add_row(key, str(count))
        console.print(type_table)


def _render_init_result_rich(
    *,
    console: PrinterLike,
    dry_run: bool,
    project_id: str,
    db_path: str | None,
    analysis_fingerprint: str | None,
    stats: Mapping[str, int] | None,
    planned_counts: Mapping[str, int] | None,
) -> None:
    _box, panel_cls, rule_cls, table_cls, text_cls = rich_panel_symbols()
    title = "init dry-run" if dry_run else "initialized"
    console.print(rule_cls("Engineering Memory", style="dim", characters="─"))
    console.print(
        panel_cls(
            text_cls.from_markup(f"[bold]{title}[/bold]  [cyan]{project_id}[/cyan]"),
            border_style="green" if not dry_run else "yellow",
            padding=(0, 1),
        )
    )
    meta = table_cls.grid(padding=(0, 2))
    meta.add_column(style="dim", no_wrap=True)
    meta.add_column()
    if dry_run:
        meta.add_row("analysis_fp", analysis_fingerprint or "n/a")
    elif db_path is not None:
        meta.add_row("db", db_path)
    console.print(meta)
    _render_count_table(console, title="Upsert stats", counts=stats)
    _render_count_table(
        console,
        title="Record types" if not dry_run else "Planned records",
        counts=planned_counts,
    )


def _render_vacuum_report_rich(*, console: PrinterLike, report: VacuumReport) -> None:
    _, panel_cls, rule_cls, _, text_cls = rich_panel_symbols()
    console.print(rule_cls("Engineering Memory", style="dim", characters="─"))
    console.print(
        panel_cls(
            text_cls.from_markup(
                f"[bold]vacuum complete[/bold]  "
                f"[dim](deleted {report.total_deleted})[/dim]"
            ),
            border_style="green" if report.total_deleted else "blue",
            padding=(0, 1),
        )
    )
    if not report.deleted_by_status:
        console.print("  [dim](nothing to purge)[/dim]")
        return
    _render_count_table(
        console,
        title="Deleted by status",
        counts=report.deleted_by_status,
    )


def _render_coverage_report_rich(
    *, console: PrinterLike, report: ScopeCoverageReport
) -> None:
    box, panel_cls, rule_cls, table_cls, text_cls = rich_panel_symbols()
    covered = report.scope_paths_with_memory
    total = report.scope_paths_total
    percent = report.scope_coverage_percent
    console.print(rule_cls("Engineering Memory", style="dim", characters="─"))
    console.print(
        panel_cls(
            text_cls.from_markup(
                f"[bold]coverage[/bold]  [cyan]{covered}/{total}[/cyan] "
                f"[dim]({percent}%)[/dim]"
            ),
            border_style="blue",
            padding=(0, 1),
        )
    )
    if not report.uncovered_paths:
        console.print("  [dim](all scoped paths covered)[/dim]")
        return
    table = table_cls(box=box.SIMPLE, show_header=True, header_style="bold")
    table.add_column("Uncovered path", style="yellow")
    for path in report.uncovered_paths:
        table.add_row(path)
    console.print(table)


def _render_count_table(
    console: PrinterLike,
    *,
    title: str,
    counts: Mapping[str, int] | None,
) -> None:
    if not counts:
        return
    box, _, _, table_cls, _ = rich_panel_symbols()
    table = table_cls(
        title=title,
        box=box.SIMPLE,
        show_header=True,
        header_style="bold",
    )
    table.add_column("Key", style="cyan")
    table.add_column("Count", justify="right")
    for key, count in sorted(counts.items()):
        table.add_row(key, str(count))
    console.print(table)


def _render_status_report_plain(
    *, console: PrinterLike, report: MemoryStatusReport
) -> None:
    console.print("Engineering Memory status")
    for label, value in _status_rows(report):
        console.print(f"  {label + ':':18} {value}")
    if report.records_by_type:
        console.print("  records_by_type:")
        for key, count in sorted(report.records_by_type.items()):
            console.print(f"    {key}: {count}")


def _status_rows(report: MemoryStatusReport) -> tuple[tuple[str, str], ...]:
    return (
        ("root", str(report.project_root)),
        ("backend", report.backend),
        ("db", str(report.db_path)),
        ("db_exists", str(report.db_exists)),
        ("schema", report.schema_version or "n/a"),
        ("project_id", report.project_id or "n/a"),
        ("analysis_fp", report.last_analysis_fingerprint or "n/a"),
        ("last_init_run", report.last_init_run_id or "n/a"),
        ("records", str(report.record_count)),
    )


def _record_mapping(record: MemoryRecord) -> dict[str, object]:
    return {
        "type": record.type,
        "status": record.status,
        "statement": record.statement,
        "payload": record.payload,
    }


def _print_record_lines(
    console: PrinterLike,
    records: Sequence[Mapping[str, object]],
) -> None:
    if not records:
        console.print("  (no records)")
        return
    for item in records:
        record_type = item.get("type", "?")
        status = item.get("status", "?")
        line = format_memory_record_line(item)
        console.print(f"  - [{record_type}/{status}] {line}")


def _print_count_map(
    console: PrinterLike,
    heading: str,
    counts: Mapping[str, int] | None,
    *,
    indent: str = "    ",
) -> None:
    if not counts:
        return
    console.print(heading)
    for key, count in sorted(counts.items()):
        console.print(f"{indent}{key}: {count}")


def _count_label(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"({count} {noun}{suffix})"


def _status_style(status: str) -> str:
    if status == "active":
        return "green"
    if status == "stale":
        return "yellow"
    if status == "draft":
        return "magenta"
    return "dim"


__all__ = [
    "memory_console",
    "render_coverage_report",
    "render_draft_candidates",
    "render_governance_result",
    "render_init_note",
    "render_init_result",
    "render_path_results",
    "render_search_results",
    "render_stale_records",
    "render_status_report",
    "render_vacuum_report",
]
