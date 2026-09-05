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
from typing import NoReturn

from ... import ui_messages as ui
from ...config.pyproject_loader import ConfigValidationError
from ...contracts import DEFAULT_ROOT, ExitCode
from .attrs import text_attr
from .types import CLIArgsLike, StatusConsole


@dataclass(frozen=True, slots=True)
class ResolvedBaselineInputs:
    baseline_path: Path
    baseline_exists: bool
    metrics_baseline_path: Path
    metrics_baseline_exists: bool


def resolve_runtime_path_arg(
    *,
    root_path: Path,
    raw_path: str,
    from_cli: bool,
) -> Path:
    candidate_path = Path(raw_path).expanduser()
    if from_cli or candidate_path.is_absolute():
        return candidate_path.resolve()
    return (root_path / candidate_path).resolve()


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


def resolve_root_path(args: object) -> Path:
    """Resolve the scan root, absolute, with no policy attached.

    One spelling, one owner. ``resolve_existing_root_path`` layers the
    existence check and the typed exit on top; error paths that only need to
    name a file under the root -- "put this key in <root>/pyproject.toml" --
    call this directly rather than growing a second, quietly divergent
    normalization.
    """

    return Path(text_attr(args, "root", DEFAULT_ROOT)).resolve()


def resolve_existing_root_path(*, args: object, printer: StatusConsole) -> Path:
    try:
        root_path = resolve_root_path(args)
    except OSError as exc:
        exit_contract_error(
            ui.ERR_INVALID_ROOT_PATH.format(error=ui.esc(exc)),
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
        # Through the diagnosed renderer, which is the only thing that carries
        # ``remediation`` onto the terminal: this path used to render
        # ``str(exc)`` alone, so a refusal that had a procedure printed as one
        # that did not. The renderer also escapes -- the diagnosis quotes the
        # user's configuration back at them, and ``[tool.codeclone]`` is
        # exactly what a console reads as a style tag and drops.
        printer.print(ui.fmt_diagnosed_user_error(exc))
        raise SystemExit(ExitCode.CONTRACT_ERROR) from exc


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
    args: CLIArgsLike,
    root_path: Path,
    baseline_path_from_args: bool,
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

    return ResolvedBaselineInputs(
        baseline_path=baseline_path,
        baseline_exists=baseline_exists,
        metrics_baseline_path=baseline_path,
        metrics_baseline_exists=baseline_exists,
    )
