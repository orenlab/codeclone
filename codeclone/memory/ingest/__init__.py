# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..models import RecordBatch
from ..project import GitProvenance


@dataclass(frozen=True, slots=True)
class InitOptions:
    dry_run: bool = False
    refresh: bool = False
    from_report: Path | None = None
    include_docs: bool = True
    include_tests: bool = True


@dataclass
class InitReport:
    project_id: str
    db_path: Path | None
    dry_run: bool
    analysis_fingerprint: str | None
    stats: dict[str, int] = field(default_factory=dict)
    planned_counts: dict[str, int] = field(default_factory=dict)
    git: GitProvenance | None = None
    warnings: list[str] = field(default_factory=list)
    ingestion_mode: str = "init"
    records_marked_stale: int = 0
    vacuum_deleted: int = 0


__all__ = ["InitOptions", "InitReport", "RecordBatch"]
