"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .baseline import Baseline


def _current_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _build_report_meta(
    *,
    codeclone_version: str,
    baseline_path: Path,
    baseline: Baseline,
    baseline_loaded: bool,
    baseline_status: str,
    cache_path: Path,
    cache_used: bool,
) -> dict[str, Any]:
    return {
        "codeclone_version": codeclone_version,
        "python_version": _current_python_version(),
        "baseline_path": str(baseline_path),
        "baseline_version": baseline.baseline_version,
        "baseline_schema_version": baseline.schema_version,
        "baseline_python_version": baseline.python_version,
        "baseline_loaded": baseline_loaded,
        "baseline_status": baseline_status,
        "cache_path": str(cache_path),
        "cache_used": cache_used,
    }
