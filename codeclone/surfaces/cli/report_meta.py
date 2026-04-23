# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TYPE_CHECKING

from ...cache.versioning import CacheStatus
from ...contracts.schemas import ReportMeta
from ...report import meta as _report_meta
from ...report.meta import build_report_meta as _build_report_meta
from .types import CLIArgsLike

if TYPE_CHECKING:
    from pathlib import Path

    from ...core._types import AnalysisResult
    from ...core._types import ProcessingResult as PipelineProcessingResult
    from .baseline_state import CloneBaselineState, MetricsBaselineState


_current_report_timestamp_utc = _report_meta.current_report_timestamp_utc


def build_cli_report_meta(
    *,
    codeclone_version: str,
    scan_root: Path,
    baseline_path: Path,
    baseline_state: CloneBaselineState,
    cache_path: Path,
    cache_status: CacheStatus,
    cache_schema_version: str | None,
    processing_result: PipelineProcessingResult,
    metrics_baseline_path: Path,
    metrics_baseline_state: MetricsBaselineState,
    analysis_result: AnalysisResult,
    args: CLIArgsLike,
    metrics_computed: tuple[str, ...],
    analysis_started_at_utc: str | None,
    report_generated_at_utc: str,
) -> ReportMeta:
    project_metrics = analysis_result.project_metrics
    return _build_report_meta(
        codeclone_version=codeclone_version,
        scan_root=scan_root,
        baseline_path=baseline_path,
        baseline=baseline_state.baseline,
        baseline_loaded=baseline_state.loaded,
        baseline_status=baseline_state.status.value,
        cache_path=cache_path,
        cache_used=cache_status == CacheStatus.OK,
        cache_status=cache_status.value,
        cache_schema_version=cache_schema_version,
        files_skipped_source_io=len(processing_result.source_read_failures),
        metrics_baseline_path=metrics_baseline_path,
        metrics_baseline=metrics_baseline_state.baseline,
        metrics_baseline_loaded=metrics_baseline_state.loaded,
        metrics_baseline_status=metrics_baseline_state.status.value,
        health_score=(project_metrics.health.total if project_metrics else None),
        health_grade=(project_metrics.health.grade if project_metrics else None),
        analysis_mode=("clones_only" if args.skip_metrics else "full"),
        metrics_computed=metrics_computed,
        min_loc=args.min_loc,
        min_stmt=args.min_stmt,
        block_min_loc=args.block_min_loc,
        block_min_stmt=args.block_min_stmt,
        segment_min_loc=args.segment_min_loc,
        segment_min_stmt=args.segment_min_stmt,
        analysis_started_at_utc=analysis_started_at_utc,
        report_generated_at_utc=report_generated_at_utc,
    )
