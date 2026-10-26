# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A worker entry point that kills its own process for one marked file.

It stands in for ``codeclone.core.parallelism._invoke_process_file`` and is
pickled by reference into real ``ProcessPoolExecutor`` children, so it must
live in an importable module rather than in a test body. Inside a child it
dies with ``os._exit`` -- the same abrupt death a segfault or the OOM killer
gives, which surfaces in the parent as ``BrokenProcessPool``. In the parent
process (the sequential retry) it delegates to the real worker, so the file
the pool lost is analysable once it is retried.
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

from codeclone.core import worker as _worker

WORKER_KILLER_PREFIX = "worker_killer"


def die_in_worker_on_marked_file(
    filepath: str,
    *args: object,
    **kwargs: object,
) -> object:
    in_child = multiprocessing.parent_process() is not None
    if in_child and Path(filepath).name.startswith(WORKER_KILLER_PREFIX):
        os._exit(13)
    return _worker._invoke_process_file(filepath, *args, **kwargs)  # type: ignore[arg-type]
