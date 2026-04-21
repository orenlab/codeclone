# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ...baseline.clone_baseline import Baseline
from ...baseline.trust import current_python_tag
from ...cache.versioning import CacheStatus
from ...contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
)
from ...contracts.schemas import ReportMeta
from .types import CLIArgsLike

if TYPE_CHECKING:
    from pathlib import Path

    from ...baseline.metrics_baseline import MetricsBaseline
    from ...cache.versioning import CacheStatus
    from ...core._types import AnalysisResult
    from ...core._types import ProcessingResult as PipelineProcessingResult
    from .baseline_state import CloneBaselineState, MetricsBaselineState


def _current_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _current_report_timestamp_utc() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _build_report_meta(
    *,
    codeclone_version: str,
    scan_root: Path,
    baseline_path: Path,
    baseline: Baseline,
    baseline_loaded: bool,
    baseline_status: str,
    cache_path: Path,
    cache_used: bool,
    cache_status: str,
    cache_schema_version: str | None,
    files_skipped_source_io: int,
    metrics_baseline_path: Path,
    metrics_baseline: MetricsBaseline,
    metrics_baseline_loaded: bool,
    metrics_baseline_status: str,
    health_score: int | None,
    health_grade: str | None,
    analysis_mode: str,
    metrics_computed: tuple[str, ...],
    min_loc: int,
    min_stmt: int,
    block_min_loc: int,
    block_min_stmt: int,
    segment_min_loc: int,
    segment_min_stmt: int,
    design_complexity_threshold: int = DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    design_coupling_threshold: int = DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
    design_cohesion_threshold: int = DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    analysis_started_at_utc: str | None,
    report_generated_at_utc: str,
) -> ReportMeta:
    project_name = scan_root.name or str(scan_root)
    return {
        "codeclone_version": codeclone_version,
        "project_name": project_name,
        "scan_root": str(scan_root),
        "python_version": _current_python_version(),
        "python_tag": current_python_tag(),
        "baseline_path": str(baseline_path),
        "baseline_fingerprint_version": baseline.fingerprint_version,
        "baseline_schema_version": baseline.schema_version,
        "baseline_python_tag": baseline.python_tag,
        "baseline_generator_name": baseline.generator,
        "baseline_generator_version": baseline.generator_version,
        "baseline_payload_sha256": baseline.payload_sha256,
        "baseline_payload_sha256_verified": (
            baseline_loaded
            and baseline_status == "ok"
            and isinstance(baseline.payload_sha256, str)
        ),
        "baseline_loaded": baseline_loaded,
        "baseline_status": baseline_status,
        "cache_path": str(cache_path),
        "cache_used": cache_used,
        "cache_status": cache_status,
        "cache_schema_version": cache_schema_version,
        "files_skipped_source_io": files_skipped_source_io,
        "metrics_baseline_path": str(metrics_baseline_path),
        "metrics_baseline_loaded": metrics_baseline_loaded,
        "metrics_baseline_status": metrics_baseline_status,
        "metrics_baseline_schema_version": metrics_baseline.schema_version,
        "metrics_baseline_payload_sha256": metrics_baseline.payload_sha256,
        "metrics_baseline_payload_sha256_verified": (
            metrics_baseline_loaded
            and metrics_baseline_status == "ok"
            and isinstance(metrics_baseline.payload_sha256, str)
        ),
        "health_score": health_score,
        "health_grade": health_grade,
        "analysis_mode": analysis_mode,
        "metrics_computed": list(metrics_computed),
        "analysis_profile": {
            "min_loc": min_loc,
            "min_stmt": min_stmt,
            "block_min_loc": block_min_loc,
            "block_min_stmt": block_min_stmt,
            "segment_min_loc": segment_min_loc,
            "segment_min_stmt": segment_min_stmt,
        },
        "design_complexity_threshold": design_complexity_threshold,
        "design_coupling_threshold": design_coupling_threshold,
        "design_cohesion_threshold": design_cohesion_threshold,
        "analysis_started_at_utc": analysis_started_at_utc,
        "report_generated_at_utc": report_generated_at_utc,
    }


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
