# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple, NoReturn

from ... import ui_messages as ui
from ...config.pyproject_loader import ConfigValidationError
from ...contracts import DEFAULT_ROOT, ExitCode
from .attrs import bool_attr, text_attr
from .baseline_state import MetricsBaselineSectionProbe
from .types import CLIArgsLike, ParserWithDefaults, StatusConsole


@dataclass(frozen=True, slots=True)
class ResolvedBaselineInputs:
    baseline_path: Path
    baseline_exists: bool
    metrics_baseline_path: Path
    metrics_baseline_exists: bool
    shared_baseline_payload: dict[str, object] | None


class RepositoryRoots(NamedTuple):
    """The repository root as the user spelled it and as it resolves."""

    spelled: Path
    resolved: Path


def repository_roots(args: object) -> RepositoryRoots:
    """Both forms of the root, so each spelling is compared with its own kind.

    ``os.path.abspath`` anchors and normalises without following links; the
    resolved form is where the scan actually happens, so a checkout that itself
    sits behind a linked ``/var`` or ``/tmp`` is judged by its real location.
    """

    spelled = Path(os.path.abspath(text_attr(args, "root", DEFAULT_ROOT)))
    return RepositoryRoots(spelled=spelled, resolved=spelled.resolve())


def spelled_inside_resolves_outside(
    spelled: Path, resolved: Path, roots: RepositoryRoots
) -> bool:
    """A path the user spelled inside the repository that a link leads out of it.

    A path spelled outside the repository is the user's own word and is left
    alone, linked ancestors included; one spelled inside it that still lands
    outside went through a link the repository planted.
    """

    anchored = Path(os.path.abspath(spelled))
    spelled_inside = anchored.is_relative_to(roots.spelled) or anchored.is_relative_to(
        roots.resolved
    )
    return spelled_inside and not resolved.is_relative_to(roots.resolved)


def resolve_runtime_path_arg(
    *,
    root_path: Path,
    raw_path: str,
    from_cli: bool,
) -> Path:
    return _spelled_runtime_path(
        root_path=root_path, raw_path=raw_path, from_cli=from_cli
    ).resolve()


def _spelled_runtime_path(*, root_path: Path, raw_path: str, from_cli: bool) -> Path:
    candidate_path = Path(raw_path).expanduser()
    if from_cli or candidate_path.is_absolute():
        return candidate_path
    return root_path / candidate_path


#: Why a baseline is not written through a link the repository planted, and
#: what the user can do instead.
_ERR_BASELINE_WRITE_LEAVES_REPOSITORY = (
    "Refusing to write the {label} to {spelled}: the path is inside the "
    "repository, but a symbolic link on the way leads it to {resolved}, outside "
    "the repository. Pass the outside path explicitly with {flag}, or remove the "
    "link. Reading a baseline through such a link is still allowed."
)


def refuse_baseline_write_through_link(
    *,
    args: object,
    root_path: Path,
    raw_path: str,
    from_cli: bool,
    resolved: Path,
    label: str,
    flag: str,
    printer: StatusConsole,
) -> None:
    """Stop a baseline update that a repository's link would carry outside it.

    A repository may commit ``codeclone.baseline.json`` -- or a directory on the
    way to the configured baseline -- as a link to any file the user can write;
    ``--update-baseline`` then replaced that file. Only the write is refused:
    a monorepo that links one shared baseline into each package still reads it.
    """

    spelled = _spelled_runtime_path(
        root_path=root_path, raw_path=raw_path, from_cli=from_cli
    )
    if spelled_inside_resolves_outside(spelled, resolved, repository_roots(args)):
        exit_contract_error(
            _ERR_BASELINE_WRITE_LEAVES_REPOSITORY.format(
                label=label, spelled=spelled, resolved=resolved, flag=flag
            ),
            printer=printer,
        )


def exit_contract_error(
    message: str,
    *,
    printer: StatusConsole,
    cause: BaseException | None = None,
) -> NoReturn:
    printer.print(ui.fmt_contract_error(message))
    if cause is None:
        raise SystemExit(ExitCode.CONTRACT_ERROR)
    raise SystemExit(ExitCode.CONTRACT_ERROR) from cause


def resolve_existing_root_path(*, args: object, printer: StatusConsole) -> Path:
    try:
        root_path = Path(text_attr(args, "root", DEFAULT_ROOT)).resolve()
    except OSError as exc:
        exit_contract_error(
            ui.ERR_INVALID_ROOT_PATH.format(error=exc),
            printer=printer,
            cause=exc,
        )
    if not root_path.exists():
        exit_contract_error(
            ui.ERR_ROOT_NOT_FOUND.format(path=root_path),
            printer=printer,
        )
    return root_path


def load_pyproject_config_or_exit(
    *,
    root_path: Path,
    load_pyproject_config_fn: Callable[[Path], dict[str, object]],
    printer: StatusConsole,
) -> dict[str, object]:
    try:
        return load_pyproject_config_fn(root_path)
    except ConfigValidationError as exc:
        exit_contract_error(str(exc), printer=printer, cause=exc)


def configure_runtime_flags(args: CLIArgsLike) -> None:
    if args.debug:
        os.environ["CODECLONE_DEBUG"] = "1"
    if args.ci:
        args.fail_on_new = True
        args.no_color = True
        args.quiet = True


def configure_runtime_console(
    *,
    args: CLIArgsLike,
    make_plain_console: Callable[[], object],
    make_console: Callable[..., object],
    set_console: Callable[[object], None],
) -> object:
    console = (
        make_plain_console() if args.quiet else make_console(no_color=args.no_color)
    )
    set_console(console)
    return console


def validate_numeric_args_or_exit(
    *,
    args: CLIArgsLike,
    validate_numeric_args_fn: Callable[[CLIArgsLike], bool],
    printer: StatusConsole,
) -> None:
    if validate_numeric_args_fn(args):
        return
    exit_contract_error(
        "Size limits must be non-negative integers (MB), "
        "threshold flags must be >= 0 or -1, and coverage thresholds "
        "must be between 0 and 100.",
        printer=printer,
    )


def resolve_baseline_inputs(
    *,
    ap: ParserWithDefaults,
    args: CLIArgsLike,
    root_path: Path,
    baseline_path_from_args: bool,
    metrics_path_from_args: bool,
    probe_metrics_baseline_section_fn: Callable[[Path], MetricsBaselineSectionProbe],
    printer: StatusConsole,
) -> ResolvedBaselineInputs:
    baseline_arg_path = Path(text_attr(args, "baseline")).expanduser()
    try:
        baseline_path = resolve_runtime_path_arg(
            root_path=root_path,
            raw_path=text_attr(args, "baseline"),
            from_cli=baseline_path_from_args,
        )
        baseline_exists = baseline_path.exists()
    except OSError as exc:
        exit_contract_error(
            ui.fmt_invalid_baseline_path(path=baseline_arg_path, error=exc),
            printer=printer,
            cause=exc,
        )

    shared_baseline_payload: dict[str, object] | None = None
    default_metrics_baseline = ap.get_default("metrics_baseline")
    metrics_baseline_value = text_attr(args, "metrics_baseline")
    metrics_path_overridden = metrics_path_from_args or (
        metrics_baseline_value != str(default_metrics_baseline)
    )
    metrics_baseline_raw_path = (
        metrics_baseline_value
        if metrics_path_overridden
        else text_attr(args, "baseline")
    )
    metrics_baseline_arg_path = Path(metrics_baseline_raw_path).expanduser()
    try:
        metrics_baseline_path = resolve_runtime_path_arg(
            root_path=root_path,
            raw_path=metrics_baseline_raw_path,
            from_cli=metrics_path_from_args,
        )
        if metrics_baseline_path == baseline_path:
            probe = probe_metrics_baseline_section_fn(metrics_baseline_path)
            metrics_baseline_exists = probe.has_metrics_section
            shared_baseline_payload = probe.payload
        else:
            metrics_baseline_exists = metrics_baseline_path.exists()
    except OSError as exc:
        exit_contract_error(
            ui.fmt_invalid_baseline_path(
                path=metrics_baseline_arg_path,
                error=exc,
            ),
            printer=printer,
            cause=exc,
        )

    if bool_attr(args, "update_baseline") or bool_attr(args, "update_metrics_baseline"):
        for raw_path, from_cli, resolved, label, flag in (
            (
                text_attr(args, "baseline"),
                baseline_path_from_args,
                baseline_path,
                "baseline",
                "--baseline",
            ),
            (
                metrics_baseline_raw_path,
                metrics_path_from_args,
                metrics_baseline_path,
                "metrics baseline",
                "--metrics-baseline",
            ),
        ):
            refuse_baseline_write_through_link(
                args=args,
                root_path=root_path,
                raw_path=raw_path,
                from_cli=from_cli,
                resolved=resolved,
                label=label,
                flag=flag,
                printer=printer,
            )

    return ResolvedBaselineInputs(
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline_exists=metrics_baseline_exists,
        shared_baseline_payload=shared_baseline_payload,
    )
