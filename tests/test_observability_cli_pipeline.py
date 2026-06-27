# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import orjson
import pytest

import codeclone.surfaces.cli.workflow as cli
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.phase_ledger import (
    PHASE_US_COUNTER_SUFFIXES,
    PHASE_VOLUME_COUNTER_SUFFIXES,
    AnalysisVolumeKey,
    PhaseSnapshot,
    PhaseTotals,
)
from codeclone.cache.store import Cache
from codeclone.config.observability import ObservabilityConfig
from codeclone.contracts import ExitCode
from codeclone.core._types import (
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    OutputPaths,
    ProcessingResult,
)
from codeclone.observability import bootstrap, operation, shutdown
from codeclone.observability.models import OperationRecord
from codeclone.observability.store.schema import (
    observability_store_path,
    open_observability_store,
)
from codeclone.observability.store.writer import write_operation
from codeclone.surfaces.cli.observability import observability_main


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
        phase_snapshot=PhaseSnapshot(
            totals=PhaseTotals(parse_ns=1_500_000, unit_cfg_ns=2_000_000),
            volumes=(
                (AnalysisVolumeKey.FILES_TIMED.value, 2),
                (AnalysisVolumeKey.UNITS_ELIGIBLE.value, 3),
            ),
        ),
    )


def _processing_without_phase_snapshot() -> ProcessingResult:
    return ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
        referenced_names=frozenset(),
        files_analyzed=0,
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


def _run_observed_pipeline(
    tmp_path: Path,
    args: Namespace,
) -> None:
    cli._run_analysis_stages(
        args=args,
        boot=_boot(tmp_path, args),
        cache=cast(Cache, _FakeCache()),
    )


def _read_span_rows(tmp_path: Path) -> tuple[list[Any], dict[str, object]]:
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        rows = conn.execute(
            "SELECT name, counters_json, operation_id FROM platform_spans"
        ).fetchall()
    finally:
        conn.close()
    return (
        rows,
        {
            "process_counters": orjson.loads(
                next(row[1] for row in rows if row[0] == "pipeline.process")
            ),
        },
    )


def _boot(tmp_path: Path, args: Namespace) -> BootstrapResult:
    return BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=args,
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )


def test_cli_pipeline_emits_stage_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = ("a.py", "b.py")
    processing = _processing()
    monkeypatch.setattr(cli, "discover", lambda **_kw: _discovery(files))
    monkeypatch.setattr(cli, "process", lambda **_kw: processing)
    monkeypatch.setattr(cli, "analyze", lambda **_kw: _analysis())
    args = Namespace(
        quiet=True, no_progress=True, blast_radius=False, patch_verify=False
    )

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="cli.analyze", surface="cli"):
            _run_observed_pipeline(tmp_path, args)
    finally:
        shutdown()
    span_rows, _ = _read_span_rows(tmp_path)

    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        op_row = conn.execute(
            "SELECT name, surface FROM platform_operations"
        ).fetchone()
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
    process_counters = orjson.loads(by_name["pipeline.process"][1])
    expected_keys = frozenset(
        {"files_analyzed", "failed_files"}
        | set(PHASE_US_COUNTER_SUFFIXES)
        | set(PHASE_VOLUME_COUNTER_SUFFIXES)
    )
    assert frozenset(process_counters) == expected_keys
    expected_values = {
        "files_analyzed": 2,
        "failed_files": 0,
        "phase_parse_us": 1500,
        "phase_unit_cfg_us": 2000,
        "files_timed": 2,
        "units_eligible": 3,
        "blocks_emitted": 0,
    }
    assert {key: process_counters[key] for key in expected_values} == expected_values


def test_cli_pipeline_cache_only_keeps_legacy_process_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processing = _processing_without_phase_snapshot()
    monkeypatch.setattr(cli, "discover", lambda **_kw: _discovery(()))
    monkeypatch.setattr(cli, "process", lambda **_kw: processing)
    monkeypatch.setattr(cli, "analyze", lambda **_kw: _analysis())
    args = Namespace(
        quiet=True, no_progress=True, blast_radius=False, patch_verify=False
    )

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="cli.analyze", surface="cli"):
            _run_observed_pipeline(tmp_path, args)
    finally:
        shutdown()
    _, observed = _read_span_rows(tmp_path)

    assert observed["process_counters"] == {
        "files_analyzed": 0,
        "failed_files": 0,
    }


def test_observability_cli_help_and_stdout_trace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert observability_main([]) == int(ExitCode.CONTRACT_ERROR)
    assert "trace" in capsys.readouterr().out

    bootstrap(ObservabilityConfig(enabled=True), root=tmp_path)
    try:
        with operation(name="cli.analyze", surface="cli"):
            pass
    finally:
        shutdown()
    conn = open_observability_store(observability_store_path(tmp_path))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="op-1",
                correlation_id="corr",
                surface="cli",
                name="cli.analyze",
                started_at_utc="2026-01-01T00:00:00Z",
                duration_ms=1.0,
                status="ok",
                spans=(),
            ),
        )
    finally:
        conn.close()

    code = observability_main(["trace", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == int(ExitCode.SUCCESS)
    assert '"operation_tree"' in out


def test_observability_cli_missing_store_and_file_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    code = observability_main(["trace", "--root", str(empty_root)])
    assert code == int(ExitCode.SUCCESS)
    assert "No observability store" in capsys.readouterr().out

    repo = tmp_path / "repo"
    repo.mkdir()
    conn = open_observability_store(observability_store_path(repo))
    try:
        write_operation(
            conn,
            OperationRecord(
                operation_id="op-cli",
                correlation_id="op-cli",
                surface="cli",
                name="cli.analyze",
                started_at_utc="2026-01-01T00:00:00Z",
                duration_ms=1.0,
                status="ok",
                spans=(),
            ),
        )
    finally:
        conn.close()

    json_path = tmp_path / "trace.json"
    html_path = tmp_path / "trace.html"
    code = observability_main(
        [
            "trace",
            "--root",
            str(repo),
            "--json",
            str(json_path),
            "--html",
            str(html_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == int(ExitCode.SUCCESS)
    assert json_path.is_file()
    assert html_path.is_file()
    assert f"Wrote {json_path}" in out
    assert f"Wrote {html_path}" in out
