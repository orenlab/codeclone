# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Structural Findings panel — thin wrapper delegating to report/findings.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...report.findings import build_structural_findings_html_panel
from ...structural_findings import normalize_structural_findings

if TYPE_CHECKING:
    from .._context import ReportContext


def render_structural_panel(ctx: ReportContext) -> str:
    sf_groups = list(normalize_structural_findings(ctx.structural_findings))
    sf_files: list[str] = sorted(
        {occ.file_path for group in sf_groups for occ in group.items}
    )
    return build_structural_findings_html_panel(
        sf_groups,
        sf_files,
        scan_root=ctx.scan_root,
        file_cache=ctx.file_cache,
        context_lines=ctx.context_lines,
        max_snippet_lines=ctx.max_snippet_lines,
    )
