# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import sys
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import NamedTuple, NoReturn, Protocol

from ... import ui_messages as ui
from ...contracts import DEFAULT_ROOT, ExitCode
from . import state as cli_state
from .attrs import bool_attr, optional_text_attr, text_attr
from .startup import resolve_root_path
from .types import (
    CLIArgsLike,
    OutputPaths,
    PrinterLike,
    ReportArtifacts,
    ReportPathOrigin,
    require_status_console,
)


class _QuietArgs(Protocol):
    quiet: bool


def _path_attr(obj: object, name: str) -> Path | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, Path) else None


def _rendered_attr(obj: object, name: str) -> bytes | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, bytes) else None


def _write_report_output(
    *,
    out: Path,
    content: bytes,
    label: str,
    console: PrinterLike,
) -> None:
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
    except OSError as exc:
        console.print(
            ui.fmt_contract_error(
                ui.fmt_report_write_failed(label=label, path=out, error=exc)
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)


def _open_html_report_in_browser(*, path: Path) -> None:
    if not webbrowser.open_new_tab(path.as_uri()):
        raise OSError("no browser handler available")


def write_report_outputs(
    *,
    args: _QuietArgs,
    output_paths: OutputPaths,
    report_artifacts: ReportArtifacts,
    console: PrinterLike,
    open_html_report: bool = False,
) -> str | None:
    html_report_path: str | None = None
    saved_reports: list[tuple[str, Path]] = []
    html_path = _path_attr(output_paths, "html")
    json_path = _path_attr(output_paths, "json")
    md_path = _path_attr(output_paths, "md")
    sarif_path = _path_attr(output_paths, "sarif")
    text_path = _path_attr(output_paths, "text")
    html_report = _rendered_attr(report_artifacts, "html")
    json_report = _rendered_attr(report_artifacts, "json")
    md_report = _rendered_attr(report_artifacts, "md")
    sarif_report = _rendered_attr(report_artifacts, "sarif")
    text_report = _rendered_attr(report_artifacts, "text")

    if html_path and html_report is not None:
        out = html_path
        _write_report_output(
            out=out,
            content=html_report,
            label="HTML",
            console=console,
        )
        html_report_path = str(out)
        saved_reports.append(("HTML", out))

    if json_path and json_report is not None:
        out = json_path
        _write_report_output(
            out=out,
            content=json_report,
            label="JSON",
            console=console,
        )
        saved_reports.append(("JSON", out))

    if md_path and md_report is not None:
        out = md_path
        _write_report_output(
            out=out,
            content=md_report,
            label="Markdown",
            console=console,
        )
        saved_reports.append(("Markdown", out))

    if sarif_path and sarif_report is not None:
        out = sarif_path
        _write_report_output(
            out=out,
            content=sarif_report,
            label="SARIF",
            console=console,
        )
        saved_reports.append(("SARIF", out))

    if text_path and text_report is not None:
        out = text_path
        _write_report_output(
            out=out,
            content=text_report,
            label="text",
            console=console,
        )
        saved_reports.append(("Text", out))

    if saved_reports and not args.quiet:
        cwd = Path.cwd()
        console.print()
        for label, path in saved_reports:
            try:
                display = path.relative_to(cwd)
            except ValueError:
                display = path
            console.print(f"  [bold]{label} report saved:[/bold] [dim]{display}[/dim]")

    if open_html_report and html_path is not None:
        try:
            _open_html_report_in_browser(path=html_path)
        except Exception as exc:
            console.print(
                ui.fmt_cli_runtime_warning(
                    ui.fmt_html_report_open_failed(path=html_path, error=exc)
                )
            )

    return html_report_path


#: Why a report is not written to a path whose last component is a link.
_REASON_OUTPUT_IS_SYMLINK = (
    "it is a symbolic link, and a report is never written through one"
)


#: Why a report is not written to a path spelled inside the repository that a
#: linked directory leads out of it, and what the user can do instead.
_REASON_OUTPUT_LEAVES_REPOSITORY = (
    "a directory on the way to it is a symbolic link that leads outside the "
    "repository; pass the real outside path explicitly, or remove the link"
)


class _OutputPathIsSymlinkError(OSError):
    """A report path whose last component is a symbolic link."""


class _OutputPathLeavesRepositoryError(OSError):
    """A report path spelled inside the repository that resolves outside it."""


class _RepositoryRoots(NamedTuple):
    """The repository root as the user spelled it and as it resolves."""

    spelled: Path
    resolved: Path


def _repository_roots(args: object) -> _RepositoryRoots:
    """Both forms of the root, so each spelling is compared with its own kind.

    ``os.path.abspath`` anchors and normalises without following links; the
    resolved form is the scan root's one owner, so a checkout that itself sits
    behind a linked ``/var`` or ``/tmp`` is judged against its real location.
    """

    return _RepositoryRoots(
        spelled=Path(os.path.abspath(text_attr(args, "root", DEFAULT_ROOT))),
        resolved=resolve_root_path(args),
    )


def _spelled_inside(out: Path, roots: _RepositoryRoots) -> bool:
    """Whether the user spelled *out* inside the repository, links unfollowed."""

    spelled = Path(os.path.abspath(out))
    return spelled.is_relative_to(roots.spelled) or spelled.is_relative_to(
        roots.resolved
    )


def _refuse_link_leading_outside(
    out: Path, resolved: Path, roots: _RepositoryRoots
) -> None:
    """Refuse a path spelled inside the repository that resolves outside it.

    A path the user spelled outside the repository is their own word and is
    left alone, linked ancestors included; one spelled inside it that still
    lands outside went through a directory link the repository planted.
    """

    if _spelled_inside(out, roots) and not resolved.is_relative_to(roots.resolved):
        raise _OutputPathLeavesRepositoryError(_REASON_OUTPUT_LEAVES_REPOSITORY)


def _resolve_report_target(out: Path, roots: _RepositoryRoots) -> Path:
    """The path a report would be written to, unless a link would redirect it."""

    if out.is_symlink():
        raise _OutputPathIsSymlinkError(_REASON_OUTPUT_IS_SYMLINK)
    resolved = out.resolve()
    _refuse_link_leading_outside(out, resolved, roots)
    return resolved


def _validate_output_path(
    path: str,
    *,
    expected_suffix: str,
    label: str,
    console: PrinterLike,
    invalid_message: Callable[..., str],
    invalid_path_message: Callable[..., str],
    roots: _RepositoryRoots,
) -> Path:
    """Resolve a report path first, then decide whether it may be written.

    The suffix used to be checked on the path as spelled and the write went
    to the path as resolved, so ``reports/out.txt`` committed as a link to a
    dotfile passed the ``.txt`` check and overwrote the dotfile (security
    review 2026-10, A-02). A path whose last component is a symbolic link is
    refused outright, whether the repository's configuration or the user's
    command line named it: the user typed a path inside their checkout, not
    the link's target. A path spelled inside the repository that a linked
    directory leads out of it is refused for the same reason. The suffix is
    then checked on the resolved path, the one the report is actually written
    to.
    """

    out = Path(path).expanduser()
    try:
        resolved = _resolve_report_target(out, roots)
    except OSError as exc:
        _exit_contract_error(
            console, invalid_path_message(label=label, path=out, error=exc)
        )
    if resolved.suffix.lower() != expected_suffix:
        _exit_contract_error(
            console,
            invalid_message(label=label, path=out, expected_suffix=expected_suffix),
        )
    return resolved


def _exit_contract_error(console: PrinterLike, message: str) -> NoReturn:
    """Print *message* as a contract error and exit with its code."""

    console.print(ui.fmt_contract_error(message))
    sys.exit(ExitCode.CONTRACT_ERROR)


def _report_path_origins(argv: Sequence[str]) -> dict[str, ReportPathOrigin | None]:
    origins: dict[str, ReportPathOrigin | None] = {
        "html": None,
        "json": None,
        "md": None,
        "sarif": None,
        "text": None,
    }
    flag_to_field = {
        "--html": "html",
        "--json": "json",
        "--md": "md",
        "--sarif": "sarif",
        "--text": "text",
    }
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            break
        if "=" in token:
            flag, _value = token.split("=", maxsplit=1)
            field_name = flag_to_field.get(flag)
            if field_name is not None:
                origins[field_name] = "explicit"
            index += 1
            continue
        field_name = flag_to_field.get(token)
        if field_name is None:
            index += 1
            continue
        next_token = argv[index + 1] if index + 1 < len(argv) else None
        if next_token is None or next_token.startswith("-"):
            origins[field_name] = "default"
            index += 1
            continue
        origins[field_name] = "explicit"
        index += 2
    return origins


def _report_path_timestamp_slug(report_generated_at_utc: str) -> str:
    return report_generated_at_utc.replace("-", "").replace(":", "")


def _timestamped_report_path(path: Path, *, report_generated_at_utc: str) -> Path:
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    return path.with_name(
        f"{stem}-{_report_path_timestamp_slug(report_generated_at_utc)}{suffix}"
    )


def _resolve_output_paths(
    args: CLIArgsLike,
    *,
    report_path_origins: Mapping[str, ReportPathOrigin | None],
    report_generated_at_utc: str,
) -> OutputPaths:
    printer = require_status_console(cli_state.get_console())
    resolved: dict[str, Path | None] = {
        "html": None,
        "json": None,
        "md": None,
        "sarif": None,
        "text": None,
    }
    output_specs = (
        ("html", "html_out", ".html", "HTML"),
        ("json", "json_out", ".json", "JSON"),
        ("md", "md_out", ".md", "Markdown"),
        ("sarif", "sarif_out", ".sarif", "SARIF"),
        ("text", "text_out", ".txt", "text"),
    )

    roots = _repository_roots(args)
    for field_name, arg_name, expected_suffix, label in output_specs:
        raw_value = optional_text_attr(args, arg_name)
        if not raw_value:
            continue
        validate = partial(
            _validate_output_path,
            expected_suffix=expected_suffix,
            label=label,
            console=printer,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
            roots=roots,
        )
        path = validate(raw_value)
        if (
            args.timestamped_report_paths
            and report_path_origins.get(field_name) == "default"
        ):
            # The timestamped name is a new last component: judged the same way.
            path = validate(
                str(
                    _timestamped_report_path(
                        path,
                        report_generated_at_utc=report_generated_at_utc,
                    )
                )
            )
        resolved[field_name] = path

    return OutputPaths(
        html=resolved["html"],
        json=resolved["json"],
        text=resolved["text"],
        md=resolved["md"],
        sarif=resolved["sarif"],
    )


def _validate_report_ui_flags(*, args: object, output_paths: OutputPaths) -> None:
    console = require_status_console(cli_state.get_console())
    if bool_attr(args, "open_html_report") and output_paths.html is None:
        console.print(ui.fmt_contract_error(ui.ERR_OPEN_HTML_REPORT_REQUIRES_HTML))
        sys.exit(ExitCode.CONTRACT_ERROR)

    if bool_attr(args, "timestamped_report_paths") and not any(
        (
            output_paths.html,
            output_paths.json,
            output_paths.md,
            output_paths.sarif,
            output_paths.text,
        )
    ):
        console.print(
            ui.fmt_contract_error(ui.ERR_TIMESTAMPED_REPORT_PATHS_REQUIRES_REPORT)
        )
        sys.exit(ExitCode.CONTRACT_ERROR)


def _write_report_outputs(
    *,
    args: CLIArgsLike,
    output_paths: OutputPaths,
    report_artifacts: ReportArtifacts,
    open_html_report: bool = False,
) -> str | None:
    return write_report_outputs(
        args=args,
        output_paths=output_paths,
        report_artifacts=report_artifacts,
        console=require_status_console(cli_state.get_console()),
        open_html_report=open_html_report,
    )
