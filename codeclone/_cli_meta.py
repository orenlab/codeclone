"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

from .baseline import Baseline, current_python_tag
from .contracts import REPORT_SCHEMA_VERSION


def _current_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


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

    report_schema_version: str
    codeclone_version: str
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


def _build_report_meta(
    *,
    codeclone_version: str,
    baseline_path: Path,
    baseline: Baseline,
    baseline_loaded: bool,
    baseline_status: str,
    cache_path: Path,
    cache_used: bool,
    cache_status: str,
    cache_schema_version: str | None,
    files_skipped_source_io: int,
) -> ReportMeta:
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "codeclone_version": codeclone_version,
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
    }
