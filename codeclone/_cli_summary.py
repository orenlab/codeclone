"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

from rich.console import Console
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


def _summary_value_style(*, label: str, value: int) -> str:
    if value == 0:
        return "dim"
    if label == ui.SUMMARY_LABEL_NEW_BASELINE:
        return "bold red"
    if label == ui.SUMMARY_LABEL_SUPPRESSED:
        return "yellow"
    if label in _CLONE_LABELS:
        return "bold yellow"
    return "bold"


def _build_summary_rows(
    *,
    files_found: int,
    files_analyzed: int,
    cache_hits: int,
    files_skipped: int,
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
        (ui.SUMMARY_LABEL_FUNCTION, func_clones_count),
        (ui.SUMMARY_LABEL_BLOCK, block_clones_count),
        (ui.SUMMARY_LABEL_SEGMENT, segment_clones_count),
        (ui.SUMMARY_LABEL_SUPPRESSED, suppressed_segment_groups),
        (ui.SUMMARY_LABEL_NEW_BASELINE, new_clones_count),
    ]


def _build_summary_table(rows: list[tuple[str, int]]) -> Table:
    summary_table = Table(
        title=ui.SUMMARY_TITLE,
        show_header=True,
        width=ui.CLI_LAYOUT_WIDTH,
    )
    summary_table.add_column("Metric")
    summary_table.add_column("Value", justify="right")
    for label, value in rows:
        summary_table.add_row(
            label,
            Text(str(value), style=_summary_value_style(label=label, value=value)),
        )
    return summary_table


def _print_summary(
    *,
    console: Console,
    quiet: bool,
    files_found: int,
    files_analyzed: int,
    cache_hits: int,
    files_skipped: int,
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
        func_clones_count=func_clones_count,
        block_clones_count=block_clones_count,
        segment_clones_count=segment_clones_count,
        suppressed_segment_groups=suppressed_segment_groups,
        new_clones_count=new_clones_count,
    )

    if quiet:
        console.print(ui.SUMMARY_TITLE)
        console.print(
            ui.fmt_summary_compact_input(
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
        console.print(_build_summary_table(rows))

    if not invariant_ok:
        console.print(f"[warning]{ui.WARN_SUMMARY_ACCOUNTING_MISMATCH}[/warning]")
