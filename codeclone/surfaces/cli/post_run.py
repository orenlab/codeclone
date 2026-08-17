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
from ...api.comparison import build_comparison_context
from ...core._types import AnalysisResult
from ...models import MetricsDiff, TrustVector
from .baseline_state import CloneBaselineState, MetricsBaselineState
from .changed_scope import ChangedCloneGate
from .summary import ChangedScopeSnapshot
from .types import CLIArgsLike, PrinterLike


@dataclass(frozen=True, slots=True)
class DiffContext:
    new_func: set[str]
    new_block: set[str]
    new_clones_count: int
    #: Whether any clone lane was actually compared against the baseline.
    #: False means the empty ``new_*`` sets are "not compared", never "zero
    #: new" -- the rule WARN_BASELINE_LANES_OPAQUE already states in words.
    clone_novelty_available: bool
    metrics_diff: MetricsDiff | None
    coverage_adoption_diff_available: bool
    api_surface_diff_available: bool


def build_diff_context(
    *,
    analysis: AnalysisResult,
    baseline_path: Path,
    baseline_state: CloneBaselineState,
    metrics_baseline_state: MetricsBaselineState,
    baseline_trust: TrustVector | None = None,
) -> DiffContext:
    """Adapt the sole comparison owner to this surface's local shape.

    The decision itself is not made here. It used to be, and MCP made the same
    decision on different terms, so one degraded lane was enough for the two
    surfaces to publish opposite novelty for one clone in one repository state.
    The R3 door owns it now and both surfaces read the same answer.

    The optional lanes are flattened to sets for this surface's local consumers,
    which count them behind ``clone_novelty_available``; the honest optional
    values travel to the report document from the owner itself.
    """

    _ = baseline_path
    comparison = build_comparison_context(
        func_groups=analysis.func_groups,
        block_groups=analysis.block_groups,
        project_metrics=analysis.project_metrics,
        clone_baseline=baseline_state.baseline,
        clone_trusted_for_diff=baseline_state.trusted_for_diff,
        metrics_baseline=metrics_baseline_state.baseline,
        metrics_trusted_for_diff=metrics_baseline_state.trusted_for_diff,
        baseline_trust=baseline_trust,
    )
    return DiffContext(
        new_func=set(comparison.new_func or ()),
        new_block=set(comparison.new_block or ()),
        new_clones_count=comparison.new_clones_count,
        clone_novelty_available=comparison.clone_novelty_available,
        metrics_diff=comparison.metrics_diff,
        coverage_adoption_diff_available=comparison.coverage_adoption_diff_available,
        api_surface_diff_available=comparison.api_surface_diff_available,
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
