# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProjectionJobKind = Literal["projection_bundle"]
ProjectionJobStatus = Literal[
    "pending",
    "running",
    "done",
    "failed",
    "skipped",
]
ProjectionJobTrigger = Literal["auto", "explicit", "mcp_finish", "cli"]


@dataclass(frozen=True, slots=True)
class ProjectionJobRecord:
    id: str
    project_id: str
    job_kind: ProjectionJobKind
    status: ProjectionJobStatus
    trigger: ProjectionJobTrigger
    requested_at_utc: str
    started_at_utc: str | None
    finished_at_utc: str | None
    claimed_by: str | None
    attempt: int
    stimulus_json: str
    result_json: str | None
    error_message: str | None
    # PID@host of the single scheduled delayed-flush worker holding the coalesce
    # slot for this pending job (None when no flush is scheduled). See
    # try_claim_flush_slot in store.py.
    flush_claimed_by: str | None = None


__all__ = [
    "ProjectionJobKind",
    "ProjectionJobRecord",
    "ProjectionJobStatus",
    "ProjectionJobTrigger",
]
