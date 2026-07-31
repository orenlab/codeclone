# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Final

from ..baseline.clone_baseline import Baseline
from ..baseline.trust import current_python_tag
from ..contracts import (
    DEFAULT_REPORT_DESIGN_COHESION_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COMPLEXITY_THRESHOLD,
    DEFAULT_REPORT_DESIGN_COUPLING_THRESHOLD,
)
from ..contracts.schemas import ReportMeta

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from ..baseline.metrics_baseline import MetricsBaseline


def current_report_timestamp_utc() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


#: Families the metrics payload always carries a key for, so their presence says
#: nothing about whether the run computed them -- a switch does. Every other
#: family is payload-decided: it appears only when the analysis produced it, so
#: it needs no entry here and a new one is declared the moment it is emitted.
_SKIPPABLE_METRIC_FAMILIES: Final = {
    "dependencies": "skip_dependencies",
    "dead_code": "skip_dead_code",
}
_OPT_IN_METRIC_FAMILIES: Final = ("api_surface",)


def computed_metric_families(
    *,
    metrics_payload: Mapping[str, object] | None,
    skip_dependencies: bool = False,
    skip_dead_code: bool = False,
    api_surface: bool = False,
) -> tuple[str, ...]:
    """Declare which metric families this run computed.

    The emitted payload is the source of truth: it already states what the
    analysis produced, including the families no switch can predict such as
    ``semantic_authority``. Re-listing families by hand is what left
    ``semantic_authority`` out of the declaration while the document carried it,
    and consumers filter the report by this declaration -- so the only thing the
    run switches still do here is subtract what they explicitly turned off.
    """

    if metrics_payload is None:
        return ()
    families = {str(name) for name in metrics_payload}
    if skip_dependencies:
        families.discard("dependencies")
    if skip_dead_code:
        families.discard("dead_code")
    if not api_surface:
        families.difference_update(_OPT_IN_METRIC_FAMILIES)
    return tuple(sorted(families))


def build_report_meta(
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


def _current_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"
