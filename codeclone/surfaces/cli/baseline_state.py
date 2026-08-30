# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from ... import ui_messages as ui
from ...api.comparison import foreign_interpreter_provenance
from ...api.config_delivery import tool_codeclone_table_state
from ...baseline import (
    BASELINE_UNTRUSTED_STATUSES,
    Baseline,
    BaselinePublicationError,
    BaselineStatus,
    MetricsBaseline,
    MetricsBaselineSectionProbe,
    MetricsBaselineStatus,
    coerce_baseline_status,
    coerce_metrics_baseline_status,
    current_python_tag,
    probe_metrics_baseline_section,
    publish_baseline,
    recover_publish_lock,
)
from ...contracts import ExitCode, HealthPopulation
from ...contracts.errors import BaselineValidationError
from . import state as cli_state
from .startup import resolve_root_path
from .types import CLIArgsLike, require_status_console

if TYPE_CHECKING:
    from ...core._types import AnalysisResult
    from ...models import LaneTrust, ObservationBundle

__all__ = [
    "CloneBaselineState",
    "MetricsBaselineSectionProbe",
    "MetricsBaselineState",
    "_CloneBaselineState",
    "_MetricsBaselineSectionProbe",
    "_MetricsBaselineState",
    "_probe_metrics_baseline_section",
    "_resolve_clone_baseline_state",
    "_resolve_metrics_baseline_state",
    "gate_blocking_lanes",
    "probe_metrics_baseline_section",
    "recover_baseline_publish_lock",
    "resolve_clone_baseline_state",
    "resolve_metrics_baseline_state",
]


def recover_baseline_publish_lock(
    *,
    target: Path,
    expected_token: str,
    force: bool,
) -> str | None:
    """Run the sole publisher recovery owner behind the CLI orchestration seam."""

    try:
        recover_publish_lock(
            target=target,
            expected_token=expected_token,
            force=force,
        )
    except (BaselinePublicationError, OSError) as exc:
        return str(exc)
    return None


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


def _print_scope_id_required(console: _PrinterLike, *, root_path: Path) -> None:
    """Print the missing-scope-id contract error with its body left literal.

    The message names the ``[tool.codeclone]`` config table, which every
    console in this codebase treats as a markup tag and strips — deleting the
    only actionable detail. The marker keeps its styling; the body is printed
    with ``markup=False`` so the table name survives.

    The body also carries a ready-to-paste key line and the absolute file it
    belongs in. ``codeclone setup`` would write it, but not every project runs
    setup, and a refusal that only names a requirement is not a procedure.
    """
    console.print(ui.MARKER_CONTRACT_ERROR)
    console.print(
        ui.fmt_baseline_scope_id_required(
            table_state=tool_codeclone_table_state(root_path),
            config_path=root_path / "pyproject.toml",
            # ``uuid4``, never a name-derived ``uuid5``: a deterministic id
            # would reproduce the very failure this key prevents. Two checkouts
            # that happen to share a project name would be handed one
            # ``baseline_scope_id``, and the guard would again be unable to
            # tell this project's baseline from a stranger's. The field is a
            # discriminator, so it must be unique by construction and not by
            # the user's choice of name.
            scope_id=uuid4(),
        ),
        markup=False,
    )


def gate_blocking_lanes(
    unavailable: tuple[LaneTrust, ...],
    *,
    required_lanes: frozenset[str],
) -> tuple[str, ...]:
    """Return the untrusted lanes that an active gate actually reads.

    ``required_lanes`` is resolved once by the gate layer, behind the versioned
    gate-to-lane matrix, so this surface never re-derives gate policy — it only
    intersects. A non-empty answer means the run must stay fail-closed.
    """

    return tuple(sorted({item.name for item in unavailable} & required_lanes))


def _print_foreign_interpreter_note(
    baseline: Baseline,
    *,
    console: _PrinterLike,
) -> None:
    """Say where a usable baseline came from, when it came from elsewhere.

    Only reached once the container is loaded and trusted, so the note can never
    read as a reason to distrust it. The decision is the shared owner's
    (``api.comparison``); this surface renders and does not re-derive it (`P3`).
    Silence when the interpreters agree is correct: there is no difference to
    report, which is a different thing from having nothing to say about trust.
    """

    runtime_tag = current_python_tag()
    foreign = foreign_interpreter_provenance(
        baseline_python_tag=baseline.python_tag,
        runtime_python_tag=runtime_tag,
    )
    if foreign is None:
        return
    console.print(
        ui.fmt_baseline_foreign_interpreter(
            baseline_tag=foreign,
            runtime_tag=runtime_tag,
        )
    )


def _clone_opaque_lanes(
    baseline: Baseline,
    *,
    scope_id: UUID | None,
    required_lanes: frozenset[str],
) -> tuple[LaneTrust, ...]:
    """Return lanes safe to degrade, or raise the canonical compatibility error.

    Raising is delegated to ``verify_compatibility`` so a gate-relevant opaque
    lane fails closed with exactly the wording operators already know.
    """

    if scope_id is None:
        raise BaselineValidationError(
            "baseline_scope_id is required for baseline gating.",
            status=BaselineStatus.MISMATCH_SCOPE_ID,
        )
    opaque_lanes = baseline.unavailable_lanes(
        current_python_tag=current_python_tag(),
        baseline_scope_id=scope_id,
    )
    if gate_blocking_lanes(opaque_lanes, required_lanes=required_lanes):
        baseline.verify_compatibility(
            current_python_tag=current_python_tag(),
            baseline_scope_id=scope_id,
        )
    return opaque_lanes


class _BaselineArgs(Protocol):
    root: str | Path
    max_baseline_size_mb: int
    update_baseline: bool
    baseline_scope_id: str | None
    project_label: str | None
    fail_on_new: bool
    skip_metrics: bool
    fail_on_new_metrics: bool
    fail_on_typing_regression: bool
    fail_on_docstring_regression: bool
    fail_on_api_break: bool
    api_surface: bool
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


_CloneBaselineState = CloneBaselineState
_MetricsBaselineSectionProbe = MetricsBaselineSectionProbe
_MetricsBaselineState = MetricsBaselineState


def resolve_clone_baseline_state(
    *,
    args: _BaselineArgs,
    baseline_path: Path,
    baseline_exists: bool,
    observation_bundle: ObservationBundle,
    console: _PrinterLike,
    required_lanes: frozenset[str],
    files_skipped: int = 0,
    analysis_population: HealthPopulation = "complete_nonempty",
) -> CloneBaselineState:
    baseline = Baseline(baseline_path)
    baseline_loaded = False
    baseline_status = BaselineStatus.MISSING
    baseline_failure_code: ExitCode | None = None
    baseline_trusted_for_diff = False
    baseline_updated_path: Path | None = None
    scope_id = _required_scope_id(
        args=args,
        baseline_path=baseline_path,
        console=console,
    )

    if baseline_exists:
        try:
            baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
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
                    opaque_lanes = _clone_opaque_lanes(
                        baseline,
                        scope_id=scope_id,
                        required_lanes=required_lanes,
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
                    if opaque_lanes:
                        console.print(ui.fmt_baseline_lanes_opaque(opaque_lanes))
                    _print_foreign_interpreter_note(baseline, console=console)
    elif not args.update_baseline:
        console.print(ui.fmt_path(ui.WARN_BASELINE_MISSING, baseline_path))

    if baseline_status in BASELINE_UNTRUSTED_STATUSES:
        baseline_loaded = False
        baseline_trusted_for_diff = False
        if args.fail_on_new and not args.update_baseline:
            baseline_failure_code = ExitCode.CONTRACT_ERROR

    if args.update_baseline:
        if scope_id is None:
            # ``_required_scope_id`` has already announced this refusal, with
            # the paste-ready hint attached. Repeating it handed the operator
            # two copies of one failure -- and, when the value was present but
            # malformed, the second copy claimed the key was missing, which is
            # a different and wrong diagnosis.
            sys.exit(ExitCode.CONTRACT_ERROR)
        try:
            publish_baseline(
                target=baseline_path,
                bundle=observation_bundle,
                scope_id=scope_id,
                max_size_bytes=args.max_baseline_size_mb * 1024 * 1024,
                project_label=args.project_label,
                files_skipped=files_skipped,
                # Consulted, never re-derived: the publisher owns the
                # empty-scope rule, and this layer only carries the fact the
                # single computer produced.
                analysis_population=analysis_population,
            )
            new_baseline = Baseline(baseline_path)
            new_baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
            new_baseline.verify_compatibility(
                current_python_tag=current_python_tag(),
                baseline_scope_id=scope_id,
            )
        except (BaselinePublicationError, BaselineValidationError, OSError) as exc:
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


def _required_scope_id(
    *,
    args: _BaselineArgs,
    baseline_path: Path,
    console: _PrinterLike,
    announce: bool = True,
) -> UUID | None:
    """Read the configured scope id, announcing its absence at most once.

    ``announce=False`` is for the second resolver in a run. Both resolvers need
    the value and both would refuse on the same predicate, so the later one
    would repeat a refusal the operator has already read, hint and all.
    """

    raw = args.baseline_scope_id
    if raw is None:
        if announce and (args.update_baseline or args.fail_on_new):
            _print_scope_id_required(console, root_path=resolve_root_path(args))
        return None
    try:
        return UUID(str(raw))
    except ValueError as exc:
        console.print(
            ui.fmt_contract_error(
                ui.fmt_invalid_baseline_scope_id(path=baseline_path, error=exc)
            )
        )
        return None


def resolve_metrics_baseline_state(
    *,
    args: _BaselineArgs,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    clone_baseline_state: CloneBaselineState,
    console: _PrinterLike,
    required_lanes: frozenset[str],
) -> MetricsBaselineState:
    state = _MetricsBaselineRuntime(baseline=MetricsBaseline(metrics_baseline_path))
    # Silent by construction: the clone resolver runs first -- its result is a
    # required argument here -- and it refuses on the same predicate, so this
    # call reads the value without saying anything the operator has not read.
    scope_id = _required_scope_id(
        args=args,
        baseline_path=metrics_baseline_path,
        console=console,
        announce=False,
    )

    if _metrics_mode_short_circuit(args=args, console=console):
        return MetricsBaselineState(
            baseline=state.baseline,
            loaded=state.loaded,
            status=state.status,
            failure_code=state.failure_code,
            trusted_for_diff=state.trusted_for_diff,
        )

    if args.ci:
        args.fail_on_new_metrics = True

    if (
        not metrics_baseline_exists
        or not clone_baseline_state.trusted_for_diff
        or scope_id is None
    ):
        if metrics_baseline_exists and scope_id is None:
            state.status = MetricsBaselineStatus.MISMATCH_SCOPE_ID
        if _metrics_baseline_gate_requested(args) and not args.update_baseline:
            state.failure_code = ExitCode.CONTRACT_ERROR
            console.print(
                ui.fmt_contract_error(ui.ERR_METRICS_BASELINE_REQUIRED_FOR_GATES)
            )
    else:
        try:
            state.baseline.load(max_size_bytes=args.max_baseline_size_mb * 1024 * 1024)
            if gate_blocking_lanes(
                state.baseline.unavailable_lanes(
                    runtime_python_tag=current_python_tag(),
                    baseline_scope_id=scope_id,
                ),
                required_lanes=required_lanes,
            ):
                # An active gate reads one of these lanes, so the run must
                # fail closed with the established wording.
                state.baseline.verify_compatibility(
                    runtime_python_tag=current_python_tag(),
                    baseline_scope_id=scope_id,
                )
        except BaselineValidationError as exc:
            state.status = coerce_metrics_baseline_status(exc.status)
            console.print(ui.fmt_invalid_baseline(exc))
            if _metrics_baseline_gate_requested(args):
                state.failure_code = ExitCode.CONTRACT_ERROR
        else:
            state.loaded = True
            state.status = MetricsBaselineStatus.OK
            state.trusted_for_diff = True
            # Metrics lanes live in the same v3 container as the clone lanes,
            # so the clone resolver has already named any opaque lane; saying
            # it twice would read as two separate defects.
            _enforce_metrics_gate_schema_requirements(
                args=args,
                state=state,
                console=console,
            )
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
    if (
        args.update_baseline
        or args.fail_on_new_metrics
        or args.fail_on_typing_regression
        or args.fail_on_docstring_regression
        or args.fail_on_api_break
    ):
        console.print(ui.fmt_contract_error(ui.ERR_METRICS_BASELINE_REQUIRES_ANALYSIS))
        sys.exit(ExitCode.CONTRACT_ERROR)
    return True


def _metrics_baseline_gate_requested(args: _BaselineArgs) -> bool:
    return bool(
        args.fail_on_new_metrics
        or args.fail_on_typing_regression
        or args.fail_on_docstring_regression
        or args.fail_on_api_break
    )


def _enforce_metrics_gate_schema_requirements(
    *,
    args: _BaselineArgs,
    state: _MetricsBaselineRuntime,
    console: _PrinterLike,
) -> None:
    baseline = state.baseline
    needs_adoption_snapshot = bool(
        args.fail_on_typing_regression or args.fail_on_docstring_regression
    )
    if needs_adoption_snapshot and not getattr(
        baseline, "has_coverage_adoption_snapshot", False
    ):
        state.loaded = False
        state.trusted_for_diff = False
        state.status = MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION
        state.failure_code = ExitCode.CONTRACT_ERROR
        console.print(ui.fmt_contract_error(ui.ERR_METRICS_BASELINE_TYPING_GATES))
        return
    if args.fail_on_api_break and baseline.api_surface_snapshot is None:
        state.loaded = False
        state.trusted_for_diff = False
        state.status = MetricsBaselineStatus.MISMATCH_SCHEMA_VERSION
        state.failure_code = ExitCode.CONTRACT_ERROR
        console.print(ui.fmt_contract_error(ui.ERR_METRICS_BASELINE_API_GATES))


def _probe_metrics_baseline_section(path: Path) -> _MetricsBaselineSectionProbe:
    return probe_metrics_baseline_section(path)


def _resolve_clone_baseline_state(
    *,
    args: CLIArgsLike,
    baseline_path: Path,
    baseline_exists: bool,
    analysis: AnalysisResult,
    required_lanes: frozenset[str],
    files_skipped: int = 0,
    analysis_population: HealthPopulation = "complete_nonempty",
) -> _CloneBaselineState:
    return resolve_clone_baseline_state(
        args=args,
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        observation_bundle=analysis.observation_bundle,
        console=require_status_console(cli_state.get_console()),
        required_lanes=required_lanes,
        files_skipped=files_skipped,
        analysis_population=analysis_population,
    )


def _resolve_metrics_baseline_state(
    *,
    args: CLIArgsLike,
    metrics_baseline_path: Path,
    metrics_baseline_exists: bool,
    clone_baseline_state: CloneBaselineState,
    required_lanes: frozenset[str],
) -> _MetricsBaselineState:
    return resolve_metrics_baseline_state(
        args=args,
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline_exists=metrics_baseline_exists,
        clone_baseline_state=clone_baseline_state,
        console=require_status_console(cli_state.get_console()),
        required_lanes=required_lanes,
    )
