# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, TypedDict

from .baseline import Baseline, current_python_tag

if TYPE_CHECKING:
    from pathlib import Path

    from .metrics_baseline import MetricsBaseline


def _current_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _current_report_timestamp_utc() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


class ReportMeta(TypedDict):
    """
    Canonical report metadata contract shared by HTML, JSON, and TXT reports.

    Key semantics:
    - python_version: runtime major.minor string for human readability (e.g. "3.13")
    - python_tag: runtime compatibility tag used by baseline/cache contracts
      (e.g. "cp313")
    - baseline_*: values loaded from baseline metadata for audit/provenance
    - cache_*: cache status/provenance for run transparency
    """

    codeclone_version: str
    project_name: str
    scan_root: str
    python_version: str
    python_tag: str
    baseline_path: str
    baseline_fingerprint_version: str | None
    baseline_schema_version: str | None
    baseline_python_tag: str | None
    baseline_generator_name: str | None
    baseline_generator_version: str | None
    baseline_payload_sha256: str | None
    baseline_payload_sha256_verified: bool
    baseline_loaded: bool
    baseline_status: str
    cache_path: str
    cache_used: bool
    cache_status: str
    cache_schema_version: str | None
    files_skipped_source_io: int
    metrics_baseline_path: str
    metrics_baseline_loaded: bool
    metrics_baseline_status: str
    metrics_baseline_schema_version: str | None
    metrics_baseline_payload_sha256: str | None
    metrics_baseline_payload_sha256_verified: bool
    health_score: int | None
    health_grade: str | None
    analysis_mode: str
    metrics_computed: list[str]
    analysis_started_at_utc: str | None
    report_generated_at_utc: str


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
        "analysis_started_at_utc": analysis_started_at_utc,
        "report_generated_at_utc": report_generated_at_utc,
    }
