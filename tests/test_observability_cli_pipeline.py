# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import orjson
import pytest

import codeclone.surfaces.cli.workflow as cli
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.cache.store import Cache
from codeclone.config.observability import ObservabilityConfig
from codeclone.core._types import (
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    OutputPaths,
    ProcessingResult,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    yield
    shutdown()


def _discovery(files: tuple[str, ...]) -> DiscoveryResult:
    return DiscoveryResult(
        files_found=len(files),
        cache_hits=3,
        files_skipped=0,
        all_file_paths=(),
        cached_units=(),
        cached_blocks=(),
        cached_segments=(),
        cached_class_metrics=(),
        cached_module_deps=(),
        cached_dead_candidates=(),
        cached_referenced_names=frozenset(),
        files_to_process=files,
        skipped_warnings=(),
    )


def _processing() -> ProcessingResult:
    return ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
        referenced_names=frozenset(),
        files_analyzed=2,
        files_skipped=0,
        analyzed_lines=0,
        analyzed_functions=0,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
    )


def _analysis() -> AnalysisResult:
    return AnalysisResult(
        func_groups={},
        block_groups={},
        block_groups_report={},
        segment_groups={},
        suppressed_segment_groups=0,
        block_group_facts={},
        func_clones_count=0,
        block_clones_count=0,
        segment_clones_count=0,
        files_analyzed_or_cached=0,
        project_metrics=None,
        metrics_payload=None,
        suggestions=(),
        segment_groups_raw_digest="",
        structural_findings=(),
    )


class _FakeCache:
    load_warning: str | None = None

    def save(self) -> None:
        return None


def test_cli_pipeline_emits_stage_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = ("a.py", "b.py")
    monkeypatch.setattr(cli, "discover", lambda **_kw: _discovery(files))
    monkeypatch.setattr(cli, "process", lambda **_kw: _processing())
    monkeypatch.setattr(cli, "analyze", lambda **_kw: _analysis())
    args = Namespace(
        quiet=True, no_progress=True, blast_radius=False, patch_verify=False
    )
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=args,
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="cli.analyze", surface="cli"):
            cli._run_analysis_stages(
                args=args, boot=boot, cache=cast(Cache, _FakeCache())
            )
    finally:
        shutdown()

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        op_row = conn.execute(
            "SELECT name, surface FROM platform_operations"
        ).fetchone()
        span_rows = conn.execute(
            "SELECT name, counters_json, operation_id FROM platform_spans"
        ).fetchall()
    finally:
        conn.close()

    assert op_row == ("cli.analyze", "cli")
    by_name = {row[0]: row for row in span_rows}
    assert set(by_name) == {
        "pipeline.discover",
        "pipeline.process",
        "pipeline.analyze",
    }
    # All stage spans hang off the single cli.analyze operation.
    assert len({row[2] for row in span_rows}) == 1
    assert orjson.loads(by_name["pipeline.discover"][1]) == {
        "files_to_process": 2,
        "cache_hits": 3,
    }
    assert orjson.loads(by_name["pipeline.process"][1]) == {
        "files_analyzed": 2,
        "failed_files": 0,
    }
