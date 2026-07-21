# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

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
) -> CloneBaselineState:
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
        warning_message=None,
    )


def resolve_metrics_baseline_state(
    *,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    max_baseline_size_mb: int,
    skip_metrics: bool,
    baseline_scope_id: UUID | None,
) -> MetricsBaselineState:
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
