# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from ...core._types import (
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    OutputPaths,
    ReportArtifacts,
)
from ...core._types import (
    FileProcessResult as ProcessingResult,
)

ReportPathOrigin = Literal["default", "explicit"]


@dataclass(frozen=True, slots=True)
class ChangedCloneGate:
    """Changed-scope clone summary used by CLI post-run gating."""

    changed_paths: tuple[str, ...]
    new_func: frozenset[str]
    new_block: frozenset[str]
    total_clone_groups: int
    findings_total: int
    findings_new: int
    findings_known: int


@runtime_checkable
class PrinterLike(Protocol):
    """Minimal console surface that supports plain text output."""

    def print(self, *objects: object, **kwargs: object) -> None: ...


@runtime_checkable
class StatusConsole(PrinterLike, Protocol):
    """Console surface that can open rich status contexts."""

    def status(
        self,
        *objects: object,
        **kwargs: object,
    ) -> AbstractContextManager[object]: ...


class CLIArgsLike(Protocol):
    """Typed attribute view over the CLI namespace used by the workflow."""

    root: str | Path
    baseline: str | Path
    metrics_baseline: str | Path
    cache_path: str | Path | None
    html_out: str | None
    json_out: str | None
    md_out: str | None
    sarif_out: str | None
    text_out: str | None
    debug: bool
    ci: bool
    quiet: bool
    no_color: bool
    no_progress: bool
    open_html_report: bool
    timestamped_report_paths: bool
    changed_only: bool
    diff_against: str | None
    paths_from_git_diff: str | None
    skip_metrics: bool
    skip_dead_code: bool
    skip_dependencies: bool
    update_baseline: bool
    update_metrics_baseline: bool
    fail_on_new: bool
    fail_threshold: int
    fail_complexity: int
    fail_coupling: int
    fail_cohesion: int
    fail_cycles: bool
    fail_dead_code: bool
    fail_health: int
    fail_on_new_metrics: bool
    fail_on_typing_regression: bool
    fail_on_docstring_regression: bool
    fail_on_api_break: bool
    fail_on_untested_hotspots: bool
    min_typing_coverage: int
    min_docstring_coverage: int
    coverage_min: int
    coverage_xml: str | None
    api_surface: bool
    verbose: bool
    max_baseline_size_mb: int
    max_cache_size_mb: int
    min_loc: int
    min_stmt: int
    block_min_loc: int
    block_min_stmt: int
    segment_min_loc: int
    segment_min_stmt: int


class ParserWithDefaults(Protocol):
    """Argparse-compatible parser surface for default lookups."""

    def get_default(self, dest: str) -> object: ...


def require_status_console(value: object) -> StatusConsole:
    """Return a status-capable console or raise a precise type error."""

    if not isinstance(value, StatusConsole):
        raise TypeError("CLI console does not provide print/status methods.")
    return value


__all__ = [
    "AnalysisResult",
    "BootstrapResult",
    "CLIArgsLike",
    "ChangedCloneGate",
    "DiscoveryResult",
    "OutputPaths",
    "ParserWithDefaults",
    "PrinterLike",
    "ProcessingResult",
    "ReportArtifacts",
    "ReportPathOrigin",
    "StatusConsole",
    "require_status_console",
]
