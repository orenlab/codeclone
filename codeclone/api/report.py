# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal R3 door for bounded stored-report ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..models import ReportReadFailure, ReportReadSuccess
from ..report.document.reader import read_report_document_v3
from ..utils.json_io import DEFAULT_MAX_JSON_BYTES


@dataclass(frozen=True, kw_only=True, slots=True)
class ReportArtifactRef:
    document: dict[str, object]


@dataclass(frozen=True, kw_only=True, slots=True)
class ReportArtifactFailure:
    reason: str
    detail: str


ReportArtifactResult = ReportArtifactRef | ReportArtifactFailure


def load_report_artifact(
    path: Path,
    *,
    limit_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> ReportArtifactResult:
    """Load one stored report through the sole bounded R2 reader."""

    result = read_report_document_v3(path, limit_bytes=limit_bytes)
    if isinstance(result, ReportReadFailure):
        return ReportArtifactFailure(reason=result.reason, detail=result.detail)
    if not isinstance(result, ReportReadSuccess):
        raise TypeError("stored report reader returned an unknown result")
    return ReportArtifactRef(document=result.document)


__all__ = [
    "ReportArtifactFailure",
    "ReportArtifactRef",
    "ReportArtifactResult",
    "load_report_artifact",
]
