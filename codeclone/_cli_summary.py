# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import ui_messages as ui


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


class _Printer(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def _print_summary(
    *,
    console: _Printer,
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
        from rich.rule import Rule

        console.print()
        console.print(Rule(title=ui.SUMMARY_TITLE, style="dim", characters="\u2500"))
        console.print(
            ui.fmt_summary_files(
                found=files_found,
                analyzed=files_analyzed,
                cached=cache_hits,
                skipped=files_skipped,
            )
        )
        parsed_line = ui.fmt_summary_parsed(
            lines=analyzed_lines,
            functions=analyzed_functions,
            methods=analyzed_methods,
            classes=analyzed_classes,
        )
        if parsed_line is not None:
            console.print(parsed_line)
        console.print(
            ui.fmt_summary_clones(
                func=func_clones_count,
                block=block_clones_count,
                segment=segment_clones_count,
                suppressed=suppressed_segment_groups,
                new=new_clones_count,
            )
        )

    if not invariant_ok:
        console.print(f"[warning]{ui.WARN_SUMMARY_ACCOUNTING_MISMATCH}[/warning]")


def _print_metrics(
    *,
    console: _Printer,
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
        from rich.rule import Rule

        console.print()
        console.print(Rule(title=ui.METRICS_TITLE, style="dim", characters="\u2500"))
        console.print(ui.fmt_metrics_health(metrics.health_total, metrics.health_grade))
        console.print(
            ui.fmt_metrics_cc(
                metrics.complexity_avg,
                metrics.complexity_max,
                metrics.high_risk_count,
            )
        )
        console.print(
            ui.fmt_metrics_coupling(metrics.coupling_avg, metrics.coupling_max)
        )
        console.print(
            ui.fmt_metrics_cohesion(metrics.cohesion_avg, metrics.cohesion_max)
        )
        console.print(ui.fmt_metrics_cycles(metrics.cycles_count))
        console.print(ui.fmt_metrics_dead_code(metrics.dead_code_count))
