# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from ... import ui_messages as ui
from ...contracts import ExitCode
from ...core._types import AnalysisResult
from . import baseline_state as cli_baseline_state
from . import post_run as cli_post_run
from .attrs import bool_attr
from .patch_verify import VALID_STRICTNESS_PROFILES
from .types import CLIArgsLike, StatusConsole


def _contract_error(printer: StatusConsole, message: str) -> NoReturn:
    printer.print(ui.fmt_contract_error(message))
    raise SystemExit(ExitCode.CONTRACT_ERROR)


def controller_query_mode(args: object) -> bool:
    return (
        bool_attr(args, "blast_radius")
        or bool_attr(args, "patch_verify")
        or bool_attr(args, "session_stats")
        or bool_attr(args, "audit")
        or bool_attr(args, "audit_json")
    )


def validate_controller_query_flags(
    *,
    args: object,
    printer: StatusConsole,
    report_outputs_requested: bool = False,
    strictness_explicit: bool = False,
) -> None:
    blast_radius = bool_attr(args, "blast_radius")
    patch_verify = bool_attr(args, "patch_verify")
    strictness = str(getattr(args, "strictness", "ci") or "ci")
    if strictness not in VALID_STRICTNESS_PROFILES:
        expected = ", ".join(sorted(VALID_STRICTNESS_PROFILES))
        _contract_error(
            printer,
            f"Invalid --strictness value: {strictness!r}. Expected {expected}.",
        )
    if strictness_explicit and not patch_verify:
        _contract_error(printer, ui.ERR_STRICTNESS_PATCH_VERIFY_ONLY)
    session_stats = bool_attr(args, "session_stats")
    audit = bool_attr(args, "audit")
    if session_stats and (blast_radius or patch_verify or audit):
        _contract_error(printer, ui.ERR_SESSION_STATS_COMBINED)
    if audit and (blast_radius or patch_verify):
        _contract_error(printer, ui.ERR_AUDIT_COMBINED)
    if blast_radius and patch_verify:
        _contract_error(printer, ui.ERR_BLAST_PATCH_BOTH)
    if not (blast_radius or patch_verify or session_stats or audit):
        return
    if bool_attr(args, "update_baseline"):
        _contract_error(printer, ui.ERR_CONTROLLER_NO_BASELINE_UPDATE)
    if (
        bool_attr(args, "changed_only")
        or getattr(args, "diff_against", None)
        or getattr(args, "paths_from_git_diff", None)
    ):
        _contract_error(printer, ui.ERR_CONTROLLER_NO_CHANGED_SCOPE)
    if report_outputs_requested:
        _contract_error(printer, ui.ERR_CONTROLLER_TERMINAL_ONLY)


def run_post_analysis_controller_query(
    *,
    args: CLIArgsLike,
    report_document: dict[str, object] | None,
    root_path: Path,
    analysis_result: AnalysisResult,
    diff_context: cli_post_run.DiffContext,
    baseline_state: cli_baseline_state.CloneBaselineState,
    console_factory: Callable[[], StatusConsole],
) -> int | None:
    if bool_attr(args, "blast_radius"):
        from .blast_radius import render_blast_radius

        return render_blast_radius(
            console=console_factory(),
            report_document=report_document,
            files=tuple(getattr(args, "blast_radius", ()) or ()),
            root_path=root_path,
            quiet=args.quiet,
        )
    if not bool_attr(args, "patch_verify"):
        return None
    from .patch_verify import render_patch_verify

    assert report_document is not None
    return render_patch_verify(
        console=console_factory(),
        args=args,
        strictness=str(getattr(args, "strictness", "ci") or "ci"),
        report_document=report_document,
        analysis=analysis_result,
        diff_context=diff_context,
        baseline_state=baseline_state,
        quiet=args.quiet,
    )


def run_pre_analysis_controller_query(
    *,
    args: CLIArgsLike,
    root_path: Path,
    query_console_factory: Callable[[CLIArgsLike], StatusConsole],
) -> int | None:
    if bool_attr(args, "session_stats"):
        from .session_stats import render_session_stats

        return render_session_stats(
            console=query_console_factory(args),
            root_path=root_path,
            quiet=args.quiet,
        )
    if bool_attr(args, "audit") or bool_attr(args, "audit_json"):
        from .audit import render_audit

        return render_audit(
            console=query_console_factory(args),
            root_path=root_path,
            audit_enabled=bool(getattr(args, "audit_enabled", False)),
            audit_path=str(getattr(args, "audit_path", "")),
            quiet=args.quiet,
            json_summary=bool_attr(args, "audit_json"),
        )
    return None


__all__ = [
    "controller_query_mode",
    "run_post_analysis_controller_query",
    "run_pre_analysis_controller_query",
    "validate_controller_query_flags",
]
