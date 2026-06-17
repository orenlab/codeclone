# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from .spawn import SpawnWorkerResult, spawn_projection_jobs_worker
from .staleness import (
    compute_projection_stimulus,
    last_applied_stimulus,
    projection_is_stale,
    stimulus_digest,
)
from .store import (
    EnqueueProjectionJobResult,
    enqueue_projection_job,
    list_projection_jobs,
    pending_projection_job,
)
from .worker import ProjectionWorkerResult, run_projection_jobs_once
from .workflow import (
    execute_enqueue_projection_rebuild,
    execute_projection_rebuild_status,
    execute_run_projection_jobs_once,
    is_ci_environment,
    maybe_auto_enqueue_projection_rebuild,
)

__all__ = [
    "EnqueueProjectionJobResult",
    "ProjectionWorkerResult",
    "SpawnWorkerResult",
    "compute_projection_stimulus",
    "enqueue_projection_job",
    "execute_enqueue_projection_rebuild",
    "execute_projection_rebuild_status",
    "execute_run_projection_jobs_once",
    "is_ci_environment",
    "last_applied_stimulus",
    "list_projection_jobs",
    "maybe_auto_enqueue_projection_rebuild",
    "pending_projection_job",
    "projection_is_stale",
    "run_projection_jobs_once",
    "spawn_projection_jobs_worker",
    "stimulus_digest",
]
