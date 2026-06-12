# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

# Profiling requires the optional codeclone[perf] extra (psutil).
pytest.importorskip("psutil")

from codeclone.config.observability import ObservabilityConfig
from codeclone.observability import bootstrap, operation, shutdown, span
from codeclone.observability.profile import (
    build_profile_sample,
    capture_rss_cpu,
    worker_bootstrap_sample,
)
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def test_build_profile_sample_computes_delta_from_baseline() -> None:
    assert build_profile_sample(None) is None
    sample = build_profile_sample((0, 0.0, 0.0))
    assert sample is not None
    # rss_delta vs a zero baseline is the full current RSS — positive and real.
    assert sample.rss_mb is not None and sample.rss_mb > 0
    assert sample.rss_delta_mb is not None and sample.rss_delta_mb > 0
    assert sample.thread_count is not None and sample.thread_count > 0


def test_profile_true_populates_resource_snapshot(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True, profile=True), root=tmp_path)
    with operation(name="job", surface="cli"), span(name="stage"):
        pass
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        op_row = conn.execute(
            "SELECT rss_mb, thread_count FROM platform_operations"
        ).fetchone()
        span_row = conn.execute(
            "SELECT rss_mb, rss_delta_mb, thread_count FROM platform_spans"
        ).fetchone()
    finally:
        conn.close()
    assert op_row[0] is not None
    assert op_row[1] is not None and op_row[1] > 0
    assert span_row[0] is not None
    assert span_row[1] is not None
    assert span_row[2] is not None and span_row[2] > 0


def test_profile_false_leaves_columns_null(tmp_path: Path) -> None:
    bootstrap(ObservabilityConfig(enabled=True, profile=False), root=tmp_path)
    with operation(name="job", surface="cli"), span(name="stage"):
        pass
    shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        op_row = conn.execute(
            "SELECT rss_mb, rss_delta_mb, cpu_user_ms FROM platform_operations"
        ).fetchone()
        span_row = conn.execute("SELECT rss_mb FROM platform_spans").fetchone()
    finally:
        conn.close()
    assert op_row == (None, None, None)
    assert span_row[0] is None


def test_worker_bootstrap_sample_and_capture_rss_cpu_return_values() -> None:
    bootstrap = worker_bootstrap_sample()
    assert bootstrap is not None
    created_iso, elapsed_ms = bootstrap
    assert created_iso.endswith("Z")
    assert elapsed_ms >= 0.0

    snapshot = capture_rss_cpu()
    assert snapshot is not None
    rss, user_cpu, system_cpu = snapshot
    assert rss > 0
    assert user_cpu >= 0.0
    assert system_cpu >= 0.0


def test_profile_helpers_return_none_without_psutil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins
    from collections.abc import Mapping, Sequence

    real_import = builtins.__import__

    def _import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "psutil":
            raise ImportError("psutil unavailable in test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)
    assert worker_bootstrap_sample() is None
    assert capture_rss_cpu() is None
    assert build_profile_sample((0, 0.0, 0.0)) is None


def test_profile_open_fds_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from unittest.mock import MagicMock

    from codeclone.observability.profile import build_profile_sample

    process = MagicMock()
    process.memory_info.return_value = MagicMock(rss=1024 * 1024)
    process.cpu_times.return_value = MagicMock(user=0.1, system=0.2)
    process.num_fds.side_effect = OSError("unsupported")
    process.num_threads.return_value = 3
    mock_psutil = MagicMock()
    mock_psutil.Process.return_value = process
    monkeypatch.setitem(sys.modules, "psutil", mock_psutil)

    sample = build_profile_sample((512 * 1024, 0.0, 0.0))
    assert sample is not None
    assert sample.open_fds is None
