# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from ... import ui_messages as ui
from ...contracts import ExitCode
from . import state as cli_state
from .attrs import bool_attr, optional_text_attr
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


def _text_attr(obj: object, name: str) -> str | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, str) else None


def _write_report_output(
    *,
    out: Path,
    content: str,
    label: str,
    console: PrinterLike,
) -> None:
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, "utf-8")
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
    html_report = _text_attr(report_artifacts, "html")
    json_report = _text_attr(report_artifacts, "json")
    md_report = _text_attr(report_artifacts, "md")
    sarif_report = _text_attr(report_artifacts, "sarif")
    text_report = _text_attr(report_artifacts, "text")

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
            console.print(ui.fmt_html_report_open_failed(path=html_path, error=exc))

    return html_report_path


def _validate_output_path(
    path: str,
    *,
    expected_suffix: str,
    label: str,
    console: PrinterLike,
    invalid_message: Callable[..., str],
    invalid_path_message: Callable[..., str],
) -> Path:
    out = Path(path).expanduser()
    if out.suffix.lower() != expected_suffix:
        console.print(
            ui.fmt_contract_error(
                invalid_message(label=label, path=out, expected_suffix=expected_suffix)
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)
    try:
        return out.resolve()
    except OSError as exc:
        console.print(
            ui.fmt_contract_error(
                invalid_path_message(label=label, path=out, error=exc)
            )
        )
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

    for field_name, arg_name, expected_suffix, label in output_specs:
        raw_value = optional_text_attr(args, arg_name)
        if not raw_value:
            continue
        path = _validate_output_path(
            raw_value,
            expected_suffix=expected_suffix,
            label=label,
            console=printer,
            invalid_message=ui.fmt_invalid_output_extension,
            invalid_path_message=ui.fmt_invalid_output_path,
        )
        if (
            args.timestamped_report_paths
            and report_path_origins.get(field_name) == "default"
        ):
            path = _timestamped_report_path(
                path,
                report_generated_at_utc=report_generated_at_utc,
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
