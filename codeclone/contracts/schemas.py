# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from typing import TypedDict


class AnalysisProfile(TypedDict):
    min_loc: int
    min_stmt: int
    block_min_loc: int
    block_min_stmt: int
    segment_min_loc: int
    segment_min_stmt: int
    collect_api_surface: bool


class AnalysisProfileMeta(TypedDict):
    min_loc: int
    min_stmt: int
    block_min_loc: int
    block_min_stmt: int
    segment_min_loc: int
    segment_min_stmt: int


class ReportMeta(TypedDict):
    """
    Canonical report metadata contract shared by HTML, JSON, and TXT reports.

    Key semantics:
    - python_version: runtime major.minor string for human readability (e.g. "3.14")
    - python_tag: runtime compatibility tag used by baseline/cache contracts
      (e.g. "cp314")
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
    analysis_profile: AnalysisProfileMeta
    design_complexity_threshold: int
    design_coupling_threshold: int
    design_cohesion_threshold: int
    analysis_started_at_utc: str | None
    report_generated_at_utc: str


__all__ = [
    "AnalysisProfile",
    "AnalysisProfileMeta",
    "ReportMeta",
]
