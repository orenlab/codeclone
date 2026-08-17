# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from ...api.comparison import blocking_lanes, lane_opacity_warning
from ...baseline import (
    Baseline,
    BaselineStatus,
    MetricsBaseline,
    MetricsBaselineStatus,
    coerce_baseline_status,
    coerce_metrics_baseline_status,
    current_python_tag,
)
from ...contracts import ExitCode
from ...contracts.errors import BaselineValidationError


@dataclass(frozen=True, slots=True)
class CloneBaselineState:
    baseline: Baseline
    loaded: bool
    status: BaselineStatus
    failure_code: ExitCode | None
    trusted_for_diff: bool
    updated_path: Path | None
    warning_message: str | None = None


@dataclass(frozen=True, slots=True)
class MetricsBaselineState:
    baseline: MetricsBaseline
    loaded: bool
    status: MetricsBaselineStatus
    failure_code: ExitCode | None
    trusted_for_diff: bool
    warning_message: str | None = None


def resolve_clone_baseline_state(
    *,
    baseline_path: Path,
    baseline_exists: bool,
    max_baseline_size_mb: int,
    baseline_scope_id: UUID | None,
    required_lanes: frozenset[str],
) -> CloneBaselineState:
    """Resolve clone-baseline trust per lane, as the CLI already did.

    This used to call the all-or-nothing ``verify_compatibility``, so a single
    stale lane -- ``api_surface``, say -- made the whole container untrusted for
    diffing while it stayed attached to the report. The comparison then never
    ran, and the report document, looking at the attached container and an empty
    difference set, answered ``known`` for clones nothing had compared. One
    incompatible lane MUST be reported unavailable and MUST NOT condemn the
    container (`B5`); a lane an active gate depends on still fails closed, and so
    does a container that does not describe this run at all.
    """

    baseline = Baseline(baseline_path)
    if not baseline_exists:
        return CloneBaselineState(
            baseline=baseline,
            loaded=False,
            status=BaselineStatus.MISSING,
            failure_code=None,
            trusted_for_diff=False,
            updated_path=None,
            warning_message=None,
        )

    try:
        baseline.load(max_size_bytes=max_baseline_size_mb * 1024 * 1024)
        if baseline_scope_id is None:
            raise BaselineValidationError(
                "baseline_scope_id is required for baseline trust.",
                status=BaselineStatus.MISMATCH_SCOPE_ID,
            )
        # Container-level trust stays fail-closed inside this reader: a missing
        # container, a root digest mismatch, and schema or fingerprint drift all
        # still raise. Only per-lane staleness comes back as data.
        opaque_lanes = baseline.unavailable_lanes(
            current_python_tag=current_python_tag(),
            baseline_scope_id=baseline_scope_id,
        )
        if blocking_lanes(opaque_lanes, required_lanes=required_lanes):
            # Raising is delegated so a gate-relevant or context-incompatible
            # container fails closed with exactly the wording operators know.
            baseline.verify_compatibility(
                current_python_tag=current_python_tag(),
                baseline_scope_id=baseline_scope_id,
            )
    except BaselineValidationError as exc:
        status = coerce_baseline_status(exc.status)
        return CloneBaselineState(
            baseline=baseline,
            loaded=False,
            status=status,
            failure_code=None,
            trusted_for_diff=False,
            updated_path=None,
            warning_message=str(exc),
        )

    return CloneBaselineState(
        baseline=baseline,
        loaded=True,
        status=BaselineStatus.OK,
        failure_code=None,
        trusted_for_diff=True,
        updated_path=None,
        warning_message=lane_opacity_warning(opaque_lanes) if opaque_lanes else None,
    )


def resolve_metrics_baseline_state(
    *,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    max_baseline_size_mb: int,
    skip_metrics: bool,
    baseline_scope_id: UUID | None,
    required_lanes: frozenset[str],
) -> MetricsBaselineState:
    """Resolve metrics-baseline trust per lane, as the CLI already did.

    The metrics lanes live in the same v3 container as the clone lanes, so the
    all-or-nothing check here took six metric families' legitimately available
    comparison away over one stale lane -- the same `B5` violation as the clone
    side, pointing the other way: novelty too optimistic, metrics too
    pessimistic, both from one condemned container.
    """

    baseline = MetricsBaseline(metrics_baseline_path)
    if skip_metrics or not metrics_baseline_exists:
        return MetricsBaselineState(
            baseline=baseline,
            loaded=False,
            status=MetricsBaselineStatus.MISSING,
            failure_code=None,
            trusted_for_diff=False,
            warning_message=None,
        )

    try:
        baseline.load(max_size_bytes=max_baseline_size_mb * 1024 * 1024)
        if baseline_scope_id is None:
            raise BaselineValidationError(
                "baseline_scope_id is required for metrics baseline trust.",
                status=MetricsBaselineStatus.MISMATCH_SCOPE_ID,
            )
        if blocking_lanes(
            baseline.unavailable_lanes(
                runtime_python_tag=current_python_tag(),
                baseline_scope_id=baseline_scope_id,
            ),
            required_lanes=required_lanes,
        ):
            baseline.verify_compatibility(
                runtime_python_tag=current_python_tag(),
                baseline_scope_id=baseline_scope_id,
            )
    except BaselineValidationError as exc:
        status = coerce_metrics_baseline_status(exc.status)
        return MetricsBaselineState(
            baseline=baseline,
            loaded=False,
            status=status,
            failure_code=None,
            trusted_for_diff=False,
            warning_message=str(exc),
        )

    return MetricsBaselineState(
        baseline=baseline,
        loaded=True,
        status=MetricsBaselineStatus.OK,
        failure_code=None,
        trusted_for_diff=True,
        warning_message=None,
    )
