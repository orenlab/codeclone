"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich import box as rich_box
from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import ui_messages as ui

_CLONE_LABELS = frozenset(
    {
        ui.SUMMARY_LABEL_FUNCTION,
        ui.SUMMARY_LABEL_BLOCK,
        ui.SUMMARY_LABEL_SEGMENT,
    }
)
_STRUCTURE_LABELS = frozenset(
    {
        ui.SUMMARY_LABEL_LINES_ANALYZED,
        ui.SUMMARY_LABEL_FUNCTIONS_ANALYZED,
        ui.SUMMARY_LABEL_METHODS_ANALYZED,
        ui.SUMMARY_LABEL_CLASSES_ANALYZED,
    }
)

_HEALTH_GRADE_STYLE: dict[str, str] = {
    "A": "bold green",
    "B": "green",
    "C": "yellow",
    "D": "bold red",
    "F": "bold red",
}


def _summary_value_style(*, label: str, value: int) -> str:
    if value == 0:
        return "dim"
    if label == ui.SUMMARY_LABEL_NEW_BASELINE:
        return "bold red"
    if label == ui.SUMMARY_LABEL_SUPPRESSED:
        return "yellow"
    if label in _CLONE_LABELS:
        return "bold yellow"
    if label in _STRUCTURE_LABELS:
        return "bold cyan"
    return "bold"


def _build_summary_rows(
    *,
    files_found: int,
    files_analyzed: int,
    cache_hits: int,
    files_skipped: int,
    analyzed_lines: int = 0,
    analyzed_functions: int = 0,
    analyzed_methods: int = 0,
    analyzed_classes: int = 0,
    func_clones_count: int,
    block_clones_count: int,
    segment_clones_count: int,
    suppressed_segment_groups: int,
    new_clones_count: int,
) -> list[tuple[str, int]]:
    return [
        (ui.SUMMARY_LABEL_FILES_FOUND, files_found),
        (ui.SUMMARY_LABEL_FILES_ANALYZED, files_analyzed),
        (ui.SUMMARY_LABEL_CACHE_HITS, cache_hits),
        (ui.SUMMARY_LABEL_FILES_SKIPPED, files_skipped),
        (ui.SUMMARY_LABEL_LINES_ANALYZED, analyzed_lines),
        (ui.SUMMARY_LABEL_FUNCTIONS_ANALYZED, analyzed_functions),
        (ui.SUMMARY_LABEL_METHODS_ANALYZED, analyzed_methods),
        (ui.SUMMARY_LABEL_CLASSES_ANALYZED, analyzed_classes),
        (ui.SUMMARY_LABEL_FUNCTION, func_clones_count),
        (ui.SUMMARY_LABEL_BLOCK, block_clones_count),
        (ui.SUMMARY_LABEL_SEGMENT, segment_clones_count),
        (ui.SUMMARY_LABEL_SUPPRESSED, suppressed_segment_groups),
        (ui.SUMMARY_LABEL_NEW_BASELINE, new_clones_count),
    ]


def _build_summary_table(
    rows: list[tuple[str, int]],
    *,
    width: int | None = None,
) -> Table:
    has_structure = any(v != 0 for label, v in rows if label in _STRUCTURE_LABELS)

    table = Table(
        show_header=False,
        show_edge=True,
        pad_edge=True,
        width=width,
        border_style="dim",
        box=rich_box.ROUNDED,
    )
    table.add_column("Metric", min_width=22)
    table.add_column("Value", justify="right", min_width=6)

    input_rows = rows[:4]
    structure_rows = rows[4:8]
    clone_rows = rows[8:]

    for label, value in input_rows:
        table.add_row(
            label,
            Text(str(value), style=_summary_value_style(label=label, value=value)),
        )

    if has_structure:
        table.add_section()
        for label, value in structure_rows:
            table.add_row(
                label,
                Text(str(value), style=_summary_value_style(label=label, value=value)),
            )

    table.add_section()
    for label, value in clone_rows:
        table.add_row(
            label,
            Text(str(value), style=_summary_value_style(label=label, value=value)),
        )

    return table


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    complexity_avg: float
    complexity_max: int
    high_risk_count: int
    coupling_avg: float
    coupling_max: int
    cohesion_avg: float
    cohesion_max: int
    cycles_count: int
    dead_code_count: int
    health_total: int
    health_grade: str


def _build_metrics_table(
    m: MetricsSnapshot,
    *,
    width: int | None = None,
) -> Table:
    table = Table(
        show_header=True,
        show_edge=True,
        pad_edge=True,
        width=width,
        border_style="dim",
        box=rich_box.ROUNDED,
    )
    table.add_column("Metric", min_width=12)
    table.add_column("Avg", justify="right", min_width=6)
    table.add_column("Max", justify="right", min_width=6)
    table.add_column("Status")

    hr_style = "bold red" if m.high_risk_count > 0 else "dim"
    hr_text = (
        f"[{hr_style}]{m.high_risk_count} high-risk[/{hr_style}]"
        if m.high_risk_count > 0
        else "[dim]0 high-risk[/dim]"
    )
    table.add_row(
        "Complexity",
        f"{m.complexity_avg:.1f}",
        str(m.complexity_max),
        hr_text,
    )
    table.add_row(
        "Coupling",
        f"{m.coupling_avg:.1f}",
        str(m.coupling_max),
        "",
    )
    table.add_row(
        "Cohesion",
        f"{m.cohesion_avg:.1f}",
        str(m.cohesion_max),
        "",
    )

    cycles_status = (
        f"[bold red]{m.cycles_count} detected[/bold red]"
        if m.cycles_count > 0
        else "[green]✔ clean[/green]"
    )
    table.add_row("Cycles", "—", str(m.cycles_count), cycles_status)

    dead_status = (
        f"[bold red]{m.dead_code_count} found[/bold red]"
        if m.dead_code_count > 0
        else "[green]✔ clean[/green]"
    )
    table.add_row("Dead code", "—", str(m.dead_code_count), dead_status)

    table.add_section()
    grade_style = _HEALTH_GRADE_STYLE.get(m.health_grade, "bold")
    table.add_row(
        "Health",
        "",
        Text(f"{m.health_total}/100", style=grade_style),
        Text(m.health_grade, style=grade_style),
    )

    return table


def _print_summary(
    *,
    console: Console,
    quiet: bool,
    files_found: int,
    files_analyzed: int,
    cache_hits: int,
    files_skipped: int,
    analyzed_lines: int = 0,
    analyzed_functions: int = 0,
    analyzed_methods: int = 0,
    analyzed_classes: int = 0,
    func_clones_count: int,
    block_clones_count: int,
    segment_clones_count: int,
    suppressed_segment_groups: int,
    new_clones_count: int,
) -> None:
    invariant_ok = files_found == (files_analyzed + cache_hits + files_skipped)
    rows = _build_summary_rows(
        files_found=files_found,
        files_analyzed=files_analyzed,
        cache_hits=cache_hits,
        files_skipped=files_skipped,
        analyzed_lines=analyzed_lines,
        analyzed_functions=analyzed_functions,
        analyzed_methods=analyzed_methods,
        analyzed_classes=analyzed_classes,
        func_clones_count=func_clones_count,
        block_clones_count=block_clones_count,
        segment_clones_count=segment_clones_count,
        suppressed_segment_groups=suppressed_segment_groups,
        new_clones_count=new_clones_count,
    )

    if quiet:
        console.print(
            ui.fmt_summary_compact(
                found=files_found,
                analyzed=files_analyzed,
                cache_hits=cache_hits,
                skipped=files_skipped,
            )
        )
        console.print(
            ui.fmt_summary_compact_clones(
                function=func_clones_count,
                block=block_clones_count,
                segment=segment_clones_count,
                suppressed=suppressed_segment_groups,
                new=new_clones_count,
            )
        )
    else:
        w = ui.cli_layout_width(console.width)
        console.print(Rule(title=ui.SUMMARY_TITLE, style="dim", characters="─"))
        console.print(_build_summary_table(rows, width=w))

    if not invariant_ok:
        console.print(f"[warning]{ui.WARN_SUMMARY_ACCOUNTING_MISMATCH}[/warning]")


def _print_metrics(
    *,
    console: Console,
    quiet: bool,
    metrics: MetricsSnapshot,
) -> None:
    if quiet:
        console.print(
            ui.fmt_summary_compact_metrics(
                cc_avg=metrics.complexity_avg,
                cc_max=metrics.complexity_max,
                cbo_avg=metrics.coupling_avg,
                cbo_max=metrics.coupling_max,
                lcom_avg=metrics.cohesion_avg,
                lcom_max=metrics.cohesion_max,
                cycles=metrics.cycles_count,
                dead=metrics.dead_code_count,
                health=metrics.health_total,
                grade=metrics.health_grade,
            )
        )
    else:
        w = ui.cli_layout_width(console.width)
        console.print(Rule(title=ui.METRICS_TITLE, style="dim", characters="─"))
        console.print(_build_metrics_table(metrics, width=w))
