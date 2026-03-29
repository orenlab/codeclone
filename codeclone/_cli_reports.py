# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from typing import Protocol

from . import ui_messages as ui
from .contracts import ExitCode

__all__ = ["write_report_outputs"]


class _PrinterLike(Protocol):
    def print(self, *objects: object, **kwargs: object) -> None: ...


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
    console: _PrinterLike,
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
    output_paths: object,
    report_artifacts: object,
    console: _PrinterLike,
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
