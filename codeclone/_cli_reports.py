# SPDX-License-Identifier: MIT
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


class _OutputPaths(Protocol):
    @property
    def html(self) -> Path | None: ...

    @property
    def json(self) -> Path | None: ...

    @property
    def md(self) -> Path | None: ...

    @property
    def sarif(self) -> Path | None: ...

    @property
    def text(self) -> Path | None: ...


class _ReportArtifacts(Protocol):
    @property
    def html(self) -> str | None: ...

    @property
    def json(self) -> str | None: ...

    @property
    def md(self) -> str | None: ...

    @property
    def sarif(self) -> str | None: ...

    @property
    def text(self) -> str | None: ...


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
    output_paths: _OutputPaths,
    report_artifacts: _ReportArtifacts,
    console: _PrinterLike,
    open_html_report: bool = False,
) -> str | None:
    html_report_path: str | None = None
    saved_reports: list[tuple[str, Path]] = []

    if output_paths.html and report_artifacts.html is not None:
        out = output_paths.html
        _write_report_output(
            out=out,
            content=report_artifacts.html,
            label="HTML",
            console=console,
        )
        html_report_path = str(out)
        saved_reports.append(("HTML", out))

    if output_paths.json and report_artifacts.json is not None:
        out = output_paths.json
        _write_report_output(
            out=out,
            content=report_artifacts.json,
            label="JSON",
            console=console,
        )
        saved_reports.append(("JSON", out))

    if output_paths.md and report_artifacts.md is not None:
        out = output_paths.md
        _write_report_output(
            out=out,
            content=report_artifacts.md,
            label="Markdown",
            console=console,
        )
        saved_reports.append(("Markdown", out))

    if output_paths.sarif and report_artifacts.sarif is not None:
        out = output_paths.sarif
        _write_report_output(
            out=out,
            content=report_artifacts.sarif,
            label="SARIF",
            console=console,
        )
        saved_reports.append(("SARIF", out))

    if output_paths.text and report_artifacts.text is not None:
        out = output_paths.text
        _write_report_output(
            out=out,
            content=report_artifacts.text,
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

    if open_html_report and output_paths.html is not None:
        try:
            _open_html_report_in_browser(path=output_paths.html)
        except Exception as exc:
            console.print(
                ui.fmt_html_report_open_failed(path=output_paths.html, error=exc)
            )

    return html_report_path
