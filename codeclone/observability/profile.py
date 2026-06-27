# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""psutil resource sampling for observability profiling.

psutil is an optional dependency (``codeclone[perf]``) imported lazily inside the
capture functions, so a disabled or non-profiling process never loads it. Every
function degrades to ``None`` when psutil is unavailable — profiling is best
effort and must never break the work it measures.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

from .models import ProfileSample

_BYTES_PER_MB = 1024 * 1024
ProfileBaseline = tuple[int, float, float, int | None]


def worker_bootstrap_sample() -> tuple[str, float] | None:
    """Process cold-start as ``(creation_timestamp_iso, ms_elapsed_to_now)``.

    The elapsed time spans process spawn, interpreter startup, imports and setup
    up to this call — the part of the spawn->job handoff a worker cannot wrap
    with a normal span. Returns ``None`` when psutil is unavailable.
    """
    try:
        import psutil
    except ImportError:
        return None
    created = psutil.Process().create_time()  # epoch seconds
    elapsed_ms = max(0.0, (time.time() - created) * 1000.0)
    created_iso = datetime.fromtimestamp(created, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    return created_iso, elapsed_ms


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


def capture_process_peak_rss() -> int | None:
    """Process high-water RSS via ``getrusage`` (monotonic since process start).

    Returns ``None`` when ``resource.getrusage`` is unavailable.
    """
    try:
        import resource
    except ImportError:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return peak
    return peak * 1024


def capture_profile_baseline() -> ProfileBaseline | None:
    """Capture RSS/CPU plus the process peak-RSS watermark at span/operation start."""
    snapshot = capture_rss_cpu()
    if snapshot is None:
        return None
    base_rss, base_user, base_system = snapshot
    return base_rss, base_user, base_system, capture_process_peak_rss()


def build_profile_sample(baseline: ProfileBaseline | None) -> ProfileSample | None:
    """Build a ``ProfileSample`` as the delta from ``baseline`` to now.

    Returns ``None`` when no baseline was captured or psutil is unavailable.
    """
    if baseline is None:
        return None
    try:
        import psutil
    except ImportError:
        return None
    base_rss, base_user, base_system, base_peak = baseline
    process = psutil.Process()
    memory = process.memory_info()
    cpu = process.cpu_times()
    end_peak = capture_process_peak_rss()
    peak_rss_mb: float | None = None
    peak_rss_delta_mb: float | None = None
    if end_peak is not None:
        peak_rss_mb = end_peak / _BYTES_PER_MB
        if base_peak is not None:
            peak_rss_delta_mb = max(0, end_peak - base_peak) / _BYTES_PER_MB
    try:
        open_fds: int | None = process.num_fds()
    except (AttributeError, NotImplementedError, OSError):
        # num_fds() is Unix-only; degrade gracefully elsewhere.
        open_fds = None
    return ProfileSample(
        rss_mb=memory.rss / _BYTES_PER_MB,
        rss_delta_mb=(memory.rss - base_rss) / _BYTES_PER_MB,
        peak_rss_mb=peak_rss_mb,
        peak_rss_delta_mb=peak_rss_delta_mb,
        cpu_user_ms=(cpu.user - base_user) * 1000.0,
        cpu_system_ms=(cpu.system - base_system) * 1000.0,
        open_fds=open_fds,
        thread_count=process.num_threads(),
    )


__all__ = [
    "ProfileBaseline",
    "build_profile_sample",
    "capture_process_peak_rss",
    "capture_profile_baseline",
    "capture_rss_cpu",
    "worker_bootstrap_sample",
]
