# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from . import ui_messages as ui
from .baseline import (
    BASELINE_UNTRUSTED_STATUSES,
    Baseline,
    BaselineStatus,
    coerce_baseline_status,
    current_python_tag,
)
from .contracts import (
    BASELINE_FINGERPRINT_VERSION,
    BASELINE_SCHEMA_VERSION,
    ExitCode,
)
from .errors import BaselineValidationError
from .metrics_baseline import (
    METRICS_BASELINE_UNTRUSTED_STATUSES,
    MetricsBaseline,
    MetricsBaselineStatus,
    coerce_metrics_baseline_status,
)

if TYPE_CHECKING:
    from .models import GroupMapLike, ProjectMetrics

__all__ = [
    "CloneBaselineState",
    "MetricsBaselineSectionProbe",
    "MetricsBaselineState",
    "probe_metrics_baseline_section",
    "resolve_clone_baseline_state",
    "resolve_metrics_baseline_state",
]


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


class _BaselineArgs(Protocol):
    max_baseline_size_mb: int
    update_baseline: bool
    fail_on_new: bool
    skip_metrics: bool
    update_metrics_baseline: bool
    fail_on_new_metrics: bool
    ci: bool


@dataclass(frozen=True, slots=True)
class CloneBaselineState:
    baseline: Baseline
    loaded: bool
    status: BaselineStatus
    failure_code: ExitCode | None
    trusted_for_diff: bool
    updated_path: Path | None


@dataclass(frozen=True, slots=True)
class MetricsBaselineState:
    baseline: MetricsBaseline
    loaded: bool
    status: MetricsBaselineStatus
    failure_code: ExitCode | None
    trusted_for_diff: bool


@dataclass(slots=True)
class _MetricsBaselineRuntime:
    baseline: MetricsBaseline
    loaded: bool = False
    status: MetricsBaselineStatus = MetricsBaselineStatus.MISSING
    failure_code: ExitCode | None = None
    trusted_for_diff: bool = False


@dataclass(frozen=True, slots=True)
class MetricsBaselineSectionProbe:
    has_metrics_section: bool
    payload: dict[str, object] | None


def probe_metrics_baseline_section(path: Path) -> MetricsBaselineSectionProbe:
    if not path.exists():
        return MetricsBaselineSectionProbe(
            has_metrics_section=False,
            payload=None,
        )
    try:
        raw_payload = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return MetricsBaselineSectionProbe(
            has_metrics_section=True,
            payload=None,
        )
    if not isinstance(raw_payload, dict):
        return MetricsBaselineSectionProbe(
            has_metrics_section=True,
            payload=None,
        )
    payload = dict(raw_payload)
    return MetricsBaselineSectionProbe(
        has_metrics_section=("metrics" in payload),
        payload=payload,
    )


def resolve_clone_baseline_state(
    *,
    args: _BaselineArgs,
    baseline_path: Path,
    baseline_exists: bool,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    codeclone_version: str,
    console: _PrinterLike,
    shared_baseline_payload: dict[str, object] | None = None,
) -> CloneBaselineState:
    baseline = Baseline(baseline_path)
    baseline_loaded = False
    baseline_status = BaselineStatus.MISSING
    baseline_failure_code: ExitCode | None = None
    baseline_trusted_for_diff = False
    baseline_updated_path: Path | None = None

    if baseline_exists:
        try:
            if shared_baseline_payload is None:
                baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
            else:
                baseline.load(
                    max_size_bytes=args.max_baseline_size_mb * 1024 * 1024,
                    preloaded_payload=shared_baseline_payload,
                )
        except BaselineValidationError as exc:
            baseline_status = coerce_baseline_status(exc.status)
            if not args.update_baseline:
                console.print(ui.fmt_invalid_baseline(exc))
                if args.fail_on_new:
                    baseline_failure_code = ExitCode.CONTRACT_ERROR
                else:
                    console.print(ui.WARN_BASELINE_IGNORED)
        else:
            if not args.update_baseline:
                try:
                    baseline.verify_compatibility(
                        current_python_tag=current_python_tag()
                    )
                except BaselineValidationError as exc:
                    baseline_status = coerce_baseline_status(exc.status)
                    console.print(ui.fmt_invalid_baseline(exc))
                    if args.fail_on_new:
                        baseline_failure_code = ExitCode.CONTRACT_ERROR
                    else:
                        console.print(ui.WARN_BASELINE_IGNORED)
                else:
                    baseline_loaded = True
                    baseline_status = BaselineStatus.OK
                    baseline_trusted_for_diff = True
    elif not args.update_baseline:
        console.print(ui.fmt_path(ui.WARN_BASELINE_MISSING, baseline_path))

    if baseline_status in BASELINE_UNTRUSTED_STATUSES:
        baseline_loaded = False
        baseline_trusted_for_diff = False
        if args.fail_on_new and not args.update_baseline:
            baseline_failure_code = ExitCode.CONTRACT_ERROR

    if args.update_baseline:
        new_baseline = Baseline.from_groups(
            func_groups,
            block_groups,
            path=baseline_path,
            python_tag=current_python_tag(),
            fingerprint_version=BASELINE_FINGERPRINT_VERSION,
            schema_version=BASELINE_SCHEMA_VERSION,
            generator_version=codeclone_version,
        )
        try:
            new_baseline.save()
        except OSError as exc:
            console.print(
                ui.fmt_contract_error(
                    ui.fmt_baseline_write_failed(path=baseline_path, error=exc)
                )
            )
            sys.exit(ExitCode.CONTRACT_ERROR)
        console.print(ui.fmt_path(ui.SUCCESS_BASELINE_UPDATED, baseline_path))
        baseline = new_baseline
        baseline_loaded = True
        baseline_status = BaselineStatus.OK
        baseline_trusted_for_diff = True
        baseline_updated_path = baseline_path

    return CloneBaselineState(
        baseline=baseline,
        loaded=baseline_loaded,
        status=baseline_status,
        failure_code=baseline_failure_code,
        trusted_for_diff=baseline_trusted_for_diff,
        updated_path=baseline_updated_path,
    )


def resolve_metrics_baseline_state(
    *,
    args: _BaselineArgs,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    baseline_updated_path: Path | None,
    project_metrics: ProjectMetrics | None,
    console: _PrinterLike,
    shared_baseline_payload: dict[str, object] | None = None,
) -> MetricsBaselineState:
    state = _MetricsBaselineRuntime(baseline=MetricsBaseline(metrics_baseline_path))

    if _metrics_mode_short_circuit(args=args, console=console):
        return MetricsBaselineState(
            baseline=state.baseline,
            loaded=state.loaded,
            status=state.status,
            failure_code=state.failure_code,
            trusted_for_diff=state.trusted_for_diff,
        )

    _load_metrics_baseline_for_diff(
        args=args,
        metrics_baseline_exists=metrics_baseline_exists,
        state=state,
        console=console,
        shared_baseline_payload=shared_baseline_payload,
    )
    _apply_metrics_baseline_untrusted_policy(args=args, state=state)
    _update_metrics_baseline_if_requested(
        args=args,
        metrics_baseline_path=metrics_baseline_path,
        baseline_updated_path=baseline_updated_path,
        project_metrics=project_metrics,
        state=state,
        console=console,
    )
    if args.ci and state.loaded:
        args.fail_on_new_metrics = True

    return MetricsBaselineState(
        baseline=state.baseline,
        loaded=state.loaded,
        status=state.status,
        failure_code=state.failure_code,
        trusted_for_diff=state.trusted_for_diff,
    )


def _metrics_mode_short_circuit(
    *,
    args: _BaselineArgs,
    console: _PrinterLike,
) -> bool:
    if not args.skip_metrics:
        return False
    if args.update_metrics_baseline or args.fail_on_new_metrics:
        console.print(
            ui.fmt_contract_error(
                "Metrics baseline operations require metrics analysis. "
                "Remove --skip-metrics."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    return True


def _load_metrics_baseline_for_diff(
    *,
    args: _BaselineArgs,
    metrics_baseline_exists: bool,
    state: _MetricsBaselineRuntime,
    console: _PrinterLike,
    shared_baseline_payload: dict[str, object] | None = None,
) -> None:
    if not metrics_baseline_exists:
        if args.fail_on_new_metrics and not args.update_metrics_baseline:
            state.failure_code = ExitCode.CONTRACT_ERROR
            console.print(
                ui.fmt_contract_error(
                    "Metrics baseline file is required for --fail-on-new-metrics. "
                    "Run codeclone . --update-metrics-baseline first."
                )
            )
        return

    try:
        if shared_baseline_payload is None:
            state.baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
        else:
            state.baseline.load(
                max_size_bytes=args.max_baseline_size_mb * 1024 * 1024,
                preloaded_payload=shared_baseline_payload,
            )
    except BaselineValidationError as exc:
        state.status = coerce_metrics_baseline_status(exc.status)
        if not args.update_metrics_baseline:
            console.print(ui.fmt_invalid_baseline(exc))
            if args.fail_on_new_metrics:
                state.failure_code = ExitCode.CONTRACT_ERROR
        return

    if args.update_metrics_baseline:
        return

    try:
        state.baseline.verify_compatibility(runtime_python_tag=current_python_tag())
    except BaselineValidationError as exc:
        state.status = coerce_metrics_baseline_status(exc.status)
        console.print(ui.fmt_invalid_baseline(exc))
        if args.fail_on_new_metrics:
            state.failure_code = ExitCode.CONTRACT_ERROR
    else:
        state.loaded = True
        state.status = MetricsBaselineStatus.OK
        state.trusted_for_diff = True


def _apply_metrics_baseline_untrusted_policy(
    *,
    args: _BaselineArgs,
    state: _MetricsBaselineRuntime,
) -> None:
    if state.status not in METRICS_BASELINE_UNTRUSTED_STATUSES:
        return
    state.loaded = False
    state.trusted_for_diff = False
    if args.fail_on_new_metrics and not args.update_metrics_baseline:
        state.failure_code = ExitCode.CONTRACT_ERROR


def _update_metrics_baseline_if_requested(
    *,
    args: _BaselineArgs,
    metrics_baseline_path: Path,
    baseline_updated_path: Path | None,
    project_metrics: ProjectMetrics | None,
    state: _MetricsBaselineRuntime,
    console: _PrinterLike,
) -> None:
    if not args.update_metrics_baseline:
        return
    if project_metrics is None:
        console.print(
            ui.fmt_contract_error(
                "Cannot update metrics baseline: metrics were not computed."
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    new_metrics_baseline = MetricsBaseline.from_project_metrics(
        project_metrics=project_metrics,
        path=metrics_baseline_path,
    )
    try:
        new_metrics_baseline.save()
    except OSError as exc:
        console.print(
            ui.fmt_contract_error(
                ui.fmt_baseline_write_failed(
                    path=metrics_baseline_path,
                    error=exc,
                )
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    if baseline_updated_path != metrics_baseline_path:
        console.print(ui.fmt_path(ui.SUCCESS_BASELINE_UPDATED, metrics_baseline_path))

    state.baseline = new_metrics_baseline
    state.loaded = True
    state.status = MetricsBaselineStatus.OK
    state.trusted_for_diff = True
