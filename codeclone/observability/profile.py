# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""psutil resource sampling for observability profiling (Phase 29, profile=true).

psutil is an optional dependency (``codeclone[perf]``) imported lazily inside the
capture functions, so a disabled or non-profiling process never loads it. Every
function degrades to ``None`` when psutil is unavailable — profiling is best
effort and must never break the work it measures.
"""

from __future__ import annotations

from .models import ProfileSample

_BYTES_PER_MB = 1024 * 1024


def capture_rss_cpu() -> tuple[int, float, float] | None:
    """Snapshot ``(rss_bytes, cpu_user_s, cpu_system_s)`` for this process.

    Returns ``None`` when psutil is not installed.
    """
    try:
        import psutil
    except ImportError:
        return None
    process = psutil.Process()
    memory = process.memory_info()
    cpu = process.cpu_times()
    return memory.rss, cpu.user, cpu.system


def build_profile_sample(
    baseline: tuple[int, float, float] | None,
) -> ProfileSample | None:
    """Build a ``ProfileSample`` as the delta from ``baseline`` to now.

    Returns ``None`` when no baseline was captured or psutil is unavailable.
    """
    if baseline is None:
        return None
    try:
        import psutil
    except ImportError:
        return None
    base_rss, base_user, base_system = baseline
    process = psutil.Process()
    memory = process.memory_info()
    cpu = process.cpu_times()
    try:
        open_fds: int | None = process.num_fds()
    except (AttributeError, NotImplementedError, OSError):
        # num_fds() is Unix-only; degrade gracefully elsewhere.
        open_fds = None
    return ProfileSample(
        rss_mb=memory.rss / _BYTES_PER_MB,
        rss_delta_mb=(memory.rss - base_rss) / _BYTES_PER_MB,
        cpu_user_ms=(cpu.user - base_user) * 1000.0,
        cpu_system_ms=(cpu.system - base_system) * 1000.0,
        open_fds=open_fds,
        thread_count=process.num_threads(),
    )


__all__ = ["build_profile_sample", "capture_rss_cpu"]
