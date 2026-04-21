# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from ... import ui_messages as ui
from ...baseline import Baseline
from ...core._types import AnalysisResult
from ...models import MetricsDiff
from .baseline_state import CloneBaselineState, MetricsBaselineState
from .changed_scope import ChangedCloneGate
from .summary import ChangedScopeSnapshot
from .types import CLIArgsLike, PrinterLike


@dataclass(frozen=True, slots=True)
class DiffContext:
    new_func: set[str]
    new_block: set[str]
    new_clones_count: int
    metrics_diff: MetricsDiff | None
    coverage_adoption_diff_available: bool
    api_surface_diff_available: bool


def build_diff_context(
    *,
    analysis: AnalysisResult,
    baseline_path: Path,
    baseline_state: CloneBaselineState,
    metrics_baseline_state: MetricsBaselineState,
) -> DiffContext:
    baseline_for_diff = (
        baseline_state.baseline
        if baseline_state.trusted_for_diff
        else Baseline(baseline_path)
    )
    raw_new_func, raw_new_block = baseline_for_diff.diff(
        analysis.func_groups,
        analysis.block_groups,
    )
    metrics_diff = None
    if analysis.project_metrics is not None and metrics_baseline_state.trusted_for_diff:
        metrics_diff = metrics_baseline_state.baseline.diff(analysis.project_metrics)
    return DiffContext(
        new_func=set(raw_new_func),
        new_block=set(raw_new_block),
        new_clones_count=len(raw_new_func) + len(raw_new_block),
        metrics_diff=metrics_diff,
        coverage_adoption_diff_available=bool(
            metrics_baseline_state.trusted_for_diff
            and getattr(
                metrics_baseline_state.baseline,
                "has_coverage_adoption_snapshot",
                False,
            )
        ),
        api_surface_diff_available=bool(
            metrics_baseline_state.trusted_for_diff
            and getattr(metrics_baseline_state.baseline, "api_surface_snapshot", None)
            is not None
        ),
    )


def print_metrics_if_available(
    *,
    args: CLIArgsLike,
    analysis: AnalysisResult,
    metrics_diff: MetricsDiff | None,
    api_surface_diff_available: bool,
    console: PrinterLike,
    build_metrics_snapshot_fn: Callable[..., object],
    print_metrics_fn: Callable[..., None],
) -> None:
    if analysis.project_metrics is None:
        return
    print_metrics_fn(
        console=console,
        quiet=args.quiet,
        metrics=build_metrics_snapshot_fn(
            analysis_result=analysis,
            metrics_diff=metrics_diff,
            api_surface_diff_available=api_surface_diff_available,
        ),
    )


def resolve_changed_clone_gate(
    *,
    args: CLIArgsLike,
    report_document: Mapping[str, object] | None,
    changed_paths: Collection[str],
    changed_clone_gate_from_report_fn: Callable[..., ChangedCloneGate],
) -> ChangedCloneGate | None:
    if not args.changed_only or report_document is None:
        return None
    return changed_clone_gate_from_report_fn(
        report_document,
        changed_paths=tuple(changed_paths),
    )


def maybe_print_changed_scope_snapshot(
    *,
    args: CLIArgsLike,
    changed_clone_gate: ChangedCloneGate | None,
    console: PrinterLike,
    print_changed_scope_fn: Callable[..., None],
) -> None:
    if changed_clone_gate is None:
        return
    print_changed_scope_fn(
        console=console,
        quiet=args.quiet,
        changed_scope=ChangedScopeSnapshot(
            paths_count=len(changed_clone_gate.changed_paths),
            findings_total=changed_clone_gate.findings_total,
            findings_new=changed_clone_gate.findings_new,
            findings_known=changed_clone_gate.findings_known,
        ),
    )


def warn_new_clones_without_fail(
    *,
    args: CLIArgsLike,
    notice_new_clones_count: int,
    console: PrinterLike,
) -> None:
    if args.update_baseline or args.fail_on_new or notice_new_clones_count <= 0:
        return
    console.print(ui.WARN_NEW_CLONES_WITHOUT_FAIL)
