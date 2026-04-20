# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0

from ._types import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RUNTIME_PROCESSES,
    MAX_FILE_SIZE,
    PARALLEL_MIN_FILES_FLOOR,
    PARALLEL_MIN_FILES_PER_WORKER,
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    FileProcessResult,
    OutputPaths,
    ProcessingResult,
    ReportArtifacts,
)
from .bootstrap import _resolve_optional_runtime_path, bootstrap
from .discovery import discover
from .parallelism import (
    _parallel_min_files,
    _resolve_process_count,
    _should_use_parallel,
    process,
)
from .pipeline import analyze, compute_project_metrics, compute_suggestions
from .reporting import GatingResult, MetricGateConfig, gate, report
from .worker import _invoke_process_file, process_file

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_RUNTIME_PROCESSES",
    "MAX_FILE_SIZE",
    "PARALLEL_MIN_FILES_FLOOR",
    "PARALLEL_MIN_FILES_PER_WORKER",
    "AnalysisResult",
    "BootstrapResult",
    "DiscoveryResult",
    "FileProcessResult",
    "GatingResult",
    "MetricGateConfig",
    "OutputPaths",
    "ProcessingResult",
    "ReportArtifacts",
    "_invoke_process_file",
    "_parallel_min_files",
    "_resolve_optional_runtime_path",
    "_resolve_process_count",
    "_should_use_parallel",
    "analyze",
    "bootstrap",
    "compute_project_metrics",
    "compute_suggestions",
    "discover",
    "gate",
    "process",
    "process_file",
    "report",
]
