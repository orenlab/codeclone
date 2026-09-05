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
from .baseline_state import (
    CloneBaselineState,
    MetricsBaselineState,
    display_path,
    novelty_reason,
)
from .changed_scope import ChangedCloneGate
from .summary import ChangedScopeSnapshot, build_metrics_snapshot
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
            findings_unavailable=changed_clone_gate.findings_unavailable,
        ),
    )


def summary_novelty(
    *,
    diff_context: DiffContext,
    baseline_state: CloneBaselineState,
    baseline_path: Path,
    root_path: Path,
) -> tuple[int | None, str, str]:
    """Compose the ``New`` row from the comparison owner's answer.

    Returns ``(count, reason, detail)``. A compared run carries its count and
    nothing else. An uncompared run carries ``None``, the reason in the row's
    own words and, when the reason is a missing file, the file -- so a reader
    who passed ``--baseline`` sees which one was looked for. A plain triple
    rather than a record type: the model store owns record types, and this is
    three values one caller unpacks.
    """

    if diff_context.clone_novelty_available:
        return diff_context.new_clones_count, "", ""
    reason = novelty_reason(baseline_state)
    detail = (
        display_path(baseline_path, root=root_path)
        if reason == ui.NOVELTY_REASON_NO_BASELINE
        else ""
    )
    return None, reason, detail


def metrics_skipped_state(
    *, analysis: AnalysisResult, skip_requested: bool
) -> str | None:
    """Which absence the summary prints for a run without metrics, if any.

    ``skip_requested`` is the flag as it stood before the metrics mode was
    configured: that step turns it on for a run with no baseline, and the
    reader is owed the difference between "you asked" and "nothing to compare".
    """

    if analysis.project_metrics is not None:
        return None
    return "requested" if skip_requested else "no_baseline"


def has_locatable_findings(
    *, analysis: AnalysisResult, diff_context: DiffContext
) -> bool:
    """Whether anything on screen is worth a report with file locations."""

    if (
        analysis.func_clones_count
        or analysis.block_clones_count
        or analysis.segment_clones_count
    ):
        return True
    if analysis.project_metrics is None:
        return False
    # The same snapshot the Metrics section printed, read again for one
    # boolean rather than counted a second time here.
    snapshot = build_metrics_snapshot(
        analysis_result=analysis,
        metrics_diff=diff_context.metrics_diff,
        api_surface_diff_available=diff_context.api_surface_diff_available,
    )
    return bool(snapshot.dead_code_count or snapshot.high_risk_count)


def print_run_outcome(
    *,
    args: CLIArgsLike,
    console: PrinterLike,
    elapsed: float,
    notice_new_clones_count: int,
    clone_novelty_available: bool,
    baseline_state: CloneBaselineState,
    baseline_display: str,
    gating_enabled: bool,
    html_report_path: str | None,
    has_findings: bool,
    api_surface_enabled: bool,
    api_surface_diff_available: bool,
    files_found: int,
) -> None:
    """Close the run with its verdict and the commands that apply to it.

    Reached only when no gate refused, so every branch here is a run that
    exits 0. The block composes facts the run already established -- the
    baseline state, the new-clone count, whether a report was written -- and
    adds nothing to them.
    """

    if files_found == 0:
        kind: ui.RunOutcomeKind = "empty_scope"
    elif args.update_baseline and baseline_state.updated_path is not None:
        kind = "baseline_written"
    elif not clone_novelty_available:
        kind = "not_compared"
    elif notice_new_clones_count > 0:
        kind = "new_clones"
    elif gating_enabled:
        kind = "gate_passed"
    else:
        kind = "clean"

    if args.quiet:
        if kind == "new_clones":
            console.print(ui.fmt_run_outcome_quiet(new_clones=notice_new_clones_count))
        return

    console.print(
        ui.fmt_run_outcome(
            kind=kind,
            elapsed=elapsed,
            baseline_display=baseline_display,
            reason=novelty_reason(baseline_state) if kind == "not_compared" else "",
            new_clones=notice_new_clones_count,
            show_locations=has_findings and html_report_path is None,
            api_not_compared=api_surface_enabled and not api_surface_diff_available,
        )
    )
