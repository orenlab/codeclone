# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from ... import ui_messages as ui
from ...contracts import ExitCode
from ...utils.coerce import as_mapping as _as_mapping
from ...utils.coerce import as_sequence as _as_sequence
from ..mcp._blast_radius import BlastRadiusResult, compute_blast_radius
from .types import PrinterLike

_RISK_STYLES = {
    "low": "green",
    "medium": "yellow",
    "high": "bold red",
    "critical": "bold white on red",
}
_MAX_RENDERED_ITEMS = 20


def _report_run_id(report_document: Mapping[str, object]) -> str:
    integrity = _as_mapping(report_document.get("integrity"))
    digest = _as_mapping(integrity.get("digest"))
    value = str(digest.get("value", "")).strip()
    return value or "cli-blast-radius"


def _inventory_paths(report_document: Mapping[str, object]) -> frozenset[str]:
    inventory = _as_mapping(report_document.get("inventory"))
    file_registry = _as_mapping(inventory.get("file_registry"))
    return frozenset(
        str(item).replace("\\", "/").strip("/")
        for item in _as_sequence(file_registry.get("items"))
        if str(item).strip()
    )


def _normalize_cli_path(raw_path: object) -> str:
    text = str(raw_path).replace("\\", "/").strip()
    if not text:
        raise ValueError("empty path")
    if Path(text).is_absolute():
        raise ValueError("absolute paths are not accepted")
    normalized = str(PurePosixPath(text))
    parts = PurePosixPath(normalized).parts
    if normalized in {"", "."} or any(part == ".." for part in parts):
        raise ValueError("paths must stay inside the scan root")
    return normalized.removeprefix("./").strip("/")


def _validated_origin_paths(
    *,
    report_document: Mapping[str, object],
    files: Sequence[object],
    console: PrinterLike,
    quiet: bool,
) -> tuple[str, ...]:
    known_paths = _inventory_paths(report_document)
    valid: set[str] = set()
    skipped: list[str] = []
    invalid: list[str] = []
    for raw_path in files:
        try:
            relative_path = _normalize_cli_path(raw_path)
        except ValueError as exc:
            invalid.append(f"{raw_path}: {exc}")
            continue
        if relative_path not in known_paths:
            skipped.append(relative_path)
            continue
        valid.add(relative_path)

    if invalid:
        rendered = "\n".join(f"  - {item}" for item in invalid[:10])
        if len(invalid) > 10:
            rendered += f"\n  {ui.BLAST_RADIUS_MORE.format(count=len(invalid) - 10)}"
        console.print(
            ui.fmt_contract_error(
                ui.BLAST_RADIUS_INVALID_SELECTION.format(rendered=rendered)
            )
        )
        sys.exit(ExitCode.CONTRACT_ERROR)

    if skipped and not quiet:
        rendered = ", ".join(skipped[:5])
        if len(skipped) > 5:
            rendered += f", {ui.BLAST_RADIUS_MORE.format(count=len(skipped) - 5)}"
        console.print(
            ui.fmt_cli_runtime_warning(
                ui.BLAST_RADIUS_SKIPPED_INVENTORY.format(rendered=rendered)
            )
        )

    if not valid:
        console.print(ui.fmt_contract_error(ui.BLAST_RADIUS_REQUIRES_INVENTORY_FILE))
        sys.exit(ExitCode.CONTRACT_ERROR)
    return tuple(sorted(valid))


def _style(value: str, *, styles: Mapping[str, str]) -> str:
    style = styles.get(value, "")
    return f"[{style}]{value}[/{style}]" if style else value


def _print_items(
    *,
    console: PrinterLike,
    title: str,
    items: Sequence[str],
) -> None:
    console.print(f"  [bold]{title} ({len(items)}):[/bold]")
    if not items:
        console.print(f"    [dim]{ui.BLAST_RADIUS_NONE}[/dim]")
        return
    for item in items[:_MAX_RENDERED_ITEMS]:
        console.print(f"    {item}")
    if len(items) > _MAX_RENDERED_ITEMS:
        more = ui.BLAST_RADIUS_MORE.format(count=len(items) - _MAX_RENDERED_ITEMS)
        console.print(f"    [dim]{more}[/dim]")


def _print_entries(
    *,
    console: PrinterLike,
    title: str,
    entries: Sequence[Mapping[str, str]],
) -> None:
    console.print(f"  [bold]{title} ({len(entries)}):[/bold]")
    if not entries:
        console.print(f"    [dim]{ui.BLAST_RADIUS_NONE}[/dim]")
        return
    for entry in entries[:_MAX_RENDERED_ITEMS]:
        path = str(entry.get("path", "")).strip()
        reason = str(entry.get("reason", "")).strip()
        severity = str(entry.get("severity", "")).strip()
        suffix = f" [{severity}]" if severity else ""
        console.print(f"    {path}  [dim]{reason}{suffix}[/dim]")
    if len(entries) > _MAX_RENDERED_ITEMS:
        more = ui.BLAST_RADIUS_MORE.format(count=len(entries) - _MAX_RENDERED_ITEMS)
        console.print(f"    [dim]{more}[/dim]")


def _contract_error_result(*, console: PrinterLike, message: str) -> int:
    console.print(ui.fmt_contract_error(message))
    return int(ExitCode.CONTRACT_ERROR)


def _render_quiet_result(*, console: PrinterLike, result: BlastRadiusResult) -> int:
    console.print(
        ui.fmt_blast_radius_compact(
            level=result.radius_level,
            dependents=len(result.direct_dependents),
            cohorts=len(result.clone_cohort_members),
            cycles=len(result.in_dependency_cycle),
            do_not_touch=len(result.do_not_touch),
        )
    )
    return int(ExitCode.SUCCESS)


def render_blast_radius(
    *,
    console: PrinterLike,
    report_document: Mapping[str, object] | None,
    files: Sequence[object],
    root_path: Path,
    quiet: bool,
) -> int:
    _ = root_path
    if report_document is None:
        return _contract_error_result(
            console=console,
            message=ui.BLAST_RADIUS_REQUIRES_REPORT,
        )

    origin_paths = _validated_origin_paths(
        report_document=report_document,
        files=files,
        console=console,
        quiet=quiet,
    )
    result = compute_blast_radius(
        run_id=_report_run_id(report_document),
        report_document=report_document,
        files=origin_paths,
    )

    if quiet:
        return _render_quiet_result(console=console, result=result)

    console.print()
    console.print(f"[bold]{ui.BLAST_RADIUS_TITLE}[/bold]")
    console.print()
    console.print(f"  [bold]{ui.BLAST_RADIUS_FILES}[/bold] {', '.join(result.origin)}")
    console.print(
        f"  [bold]{ui.BLAST_RADIUS_RISK_LEVEL}[/bold] "
        f"{_style(result.radius_level, styles=_RISK_STYLES)}"
    )
    console.print()
    _print_items(
        console=console,
        title=ui.BLAST_RADIUS_DIRECT_DEPENDENTS,
        items=result.direct_dependents,
    )
    _print_items(
        console=console,
        title=ui.BLAST_RADIUS_CLONE_COHORT,
        items=result.clone_cohort_members,
    )
    _print_items(
        console=console,
        title=ui.BLAST_RADIUS_DEPENDENCY_CYCLES,
        items=result.in_dependency_cycle,
    )
    _print_entries(
        console=console,
        title=ui.BLAST_RADIUS_DO_NOT_TOUCH,
        entries=result.do_not_touch,
    )
    _print_entries(
        console=console,
        title=ui.BLAST_RADIUS_REVIEW_CONTEXT,
        entries=result.review_context,
    )
    if result.guardrails:
        console.print(f"  [bold]{ui.BLAST_RADIUS_GUARDRAILS}[/bold]")
        for guardrail in result.guardrails:
            console.print(f"    - {guardrail}")
    return int(ExitCode.SUCCESS)


__all__ = ["render_blast_radius"]
