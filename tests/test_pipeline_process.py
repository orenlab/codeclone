# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import builtins
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest

import codeclone.core as pipeline
import codeclone.core.parallelism as core_parallelism
import codeclone.core.pipeline as core_pipeline
import codeclone.core.worker as core_worker
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.cache import Cache, CacheEntry, SourceStatsDict, file_stat_signature
from codeclone.core.discovery_cache import usable_cached_source_stats
from codeclone.models import HealthScore, ProjectMetrics


class _FailExec:
    def __init__(self, *args: object, **kwargs: object) -> None:
        return None

    def __enter__(self) -> _FailExec:
        raise RuntimeError("executor unavailable")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> Literal[False]:
        return False


class _UnexpectedExec:
    def __init__(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("ProcessPoolExecutor should not be used for small batches")


def _build_boot(tmp_path: Path, *, processes: int) -> pipeline.BootstrapResult:
    return pipeline.BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(
            processes=processes,
            min_loc=1,
            min_stmt=1,
            block_min_loc=20,
            block_min_stmt=8,
            segment_min_loc=20,
            segment_min_stmt=10,
            skip_metrics=True,
        ),
        output_paths=pipeline.OutputPaths(html=None, json=None, text=None),
        cache_path=tmp_path / "cache.json",
    )


def test_resolve_process_count_defaults_in_runtime() -> None:
    assert pipeline._resolve_process_count(None) == pipeline.DEFAULT_RUNTIME_PROCESSES
    assert pipeline._resolve_process_count(0) == 1
    assert pipeline._resolve_process_count(3) == 3


def _build_discovery(filepaths: tuple[str, ...]) -> pipeline.DiscoveryResult:
    return pipeline.DiscoveryResult(
        files_found=len(filepaths),
        cache_hits=0,
        files_skipped=0,
        all_file_paths=filepaths,
        cached_units=(),
        cached_blocks=(),
        cached_segments=(),
        cached_class_metrics=(),
        cached_module_deps=(),
        cached_dead_candidates=(),
        cached_referenced_names=frozenset(),
        files_to_process=filepaths,
        skipped_warnings=(),
    )


def _ok_result(filepath: str) -> pipeline.FileProcessResult:
    return pipeline.FileProcessResult(
        filepath=filepath,
        success=True,
        units=[],
        blocks=[],
        segments=[],
        lines=2,
        functions=1,
        methods=0,
        classes=0,
        stat=file_stat_signature(filepath),
    )


def _stub_process_file(
    *,
    expected_root: str | None = None,
    expected_filepath: str | None = None,
) -> object:
    def _process_file(
        filepath: str,
        root: str,
        cfg: NormalizationConfig,
        min_loc: int,
        min_stmt: int,
        collect_structural_findings: bool = True,
        block_min_loc: int = 20,
        block_min_stmt: int = 8,
        segment_min_loc: int = 20,
        segment_min_stmt: int = 10,
    ) -> pipeline.FileProcessResult:
        if expected_root is not None:
            assert root == expected_root
        if expected_filepath is not None:
            assert filepath == expected_filepath
        assert min_loc == 1
        assert min_stmt == 1
        assert collect_structural_findings is False
        return _ok_result(filepath)

    return _process_file


def _build_large_batch_case(
    tmp_path: Path,
) -> tuple[pipeline.BootstrapResult, pipeline.DiscoveryResult, Cache, list[str]]:
    filepaths: list[str] = []
    for idx in range(pipeline._parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
        filepaths.append(str(src))

    boot = _build_boot(tmp_path, processes=2)
    discovery = _build_discovery(tuple(filepaths))
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    return boot, discovery, cache, filepaths


def _build_single_file_process_case(
    tmp_path: Path,
) -> tuple[str, pipeline.BootstrapResult, pipeline.DiscoveryResult]:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    filepath = str(src)
    return filepath, _build_boot(tmp_path, processes=1), _build_discovery((filepath,))


def _build_report_case(
    tmp_path: Path,
    *,
    json_out: bool = True,
    md_out: bool = False,
    sarif_out: bool = False,
) -> tuple[
    pipeline.BootstrapResult,
    pipeline.DiscoveryResult,
    pipeline.ProcessingResult,
    pipeline.AnalysisResult,
]:
    boot = pipeline.BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(),
        output_paths=pipeline.OutputPaths(
            json=tmp_path / "report.json" if json_out else None,
            md=tmp_path / "report.md" if md_out else None,
            sarif=tmp_path / "report.sarif" if sarif_out else None,
        ),
        cache_path=tmp_path / "cache.json",
    )
    discovery = _build_discovery(())
    processing = pipeline.ProcessingResult(
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
    analysis = pipeline.AnalysisResult(
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
    )
    return boot, discovery, processing, analysis


def test_process_parallel_fallback_without_callback_uses_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot, discovery, cache, filepaths = _build_large_batch_case(tmp_path)

    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _FailExec)
    monkeypatch.setattr(
        core_worker,
        "process_file",
        _stub_process_file(
            expected_root=str(tmp_path),
        ),
    )

    result = pipeline.process(
        boot=boot,
        discovery=discovery,
        cache=cache,
        on_parallel_fallback=None,
    )

    assert result.files_analyzed == len(filepaths)
    assert result.files_skipped == 0
    assert result.analyzed_functions == len(filepaths)


def test_process_small_batch_skips_parallel_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")

    boot = _build_boot(tmp_path, processes=4)
    discovery = _build_discovery((str(src),))
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    callbacks: list[str] = []

    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _UnexpectedExec)
    monkeypatch.setattr(
        core_worker,
        "process_file",
        _stub_process_file(expected_root=str(tmp_path)),
    )
    result = pipeline.process(
        boot=boot,
        discovery=discovery,
        cache=cache,
        on_parallel_fallback=lambda exc: callbacks.append(str(exc)),
    )

    assert callbacks == []
    assert result.files_analyzed == 1
    assert result.files_skipped == 0


def test_process_parallel_failure_large_batch_invokes_fallback_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot, discovery, cache, filepaths = _build_large_batch_case(tmp_path)
    callbacks: list[str] = []

    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _FailExec)
    monkeypatch.setattr(
        core_worker,
        "process_file",
        _stub_process_file(expected_root=str(tmp_path)),
    )
    result = pipeline.process(
        boot=boot,
        discovery=discovery,
        cache=cache,
        on_parallel_fallback=lambda exc: callbacks.append(type(exc).__name__),
    )

    assert callbacks == ["RuntimeError"]
    assert result.files_analyzed == len(filepaths)
    assert result.files_skipped == 0


def test_process_parallel_executor_analyzes_real_files(tmp_path: Path) -> None:
    boot, discovery, cache, filepaths = _build_large_batch_case(tmp_path)

    result = pipeline.process(
        boot=boot,
        discovery=discovery,
        cache=cache,
    )

    assert result.files_analyzed == len(filepaths)
    assert result.files_skipped == 0
    assert result.failed_files == ()
    assert cache.get_file_entry(filepaths[0]) is not None


def test_process_cache_put_file_entry_fallback_without_source_stats_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filepath, boot, discovery = _build_single_file_process_case(tmp_path)

    class _LegacyCache:
        def __init__(self) -> None:
            self.calls = 0

        def put_file_entry(
            self,
            _filepath: str,
            _stat_sig: object,
            _units: object,
            _blocks: object,
            _segments: object,
            *,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            self.calls += 1

        def save(self) -> None:
            return None

    cache = _LegacyCache()
    monkeypatch.setattr(
        pipeline,
        "process_file",
        _stub_process_file(
            expected_root=str(tmp_path),
            expected_filepath=filepath,
        ),
    )

    result = pipeline.process(
        boot=boot,
        discovery=discovery,
        cache=cache,  # type: ignore[arg-type]
    )

    assert result.files_analyzed == 1
    assert result.files_skipped == 0
    assert cache.calls == 1


def test_process_cache_put_file_entry_type_error_is_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filepath, boot, discovery = _build_single_file_process_case(tmp_path)

    class _BrokenCache:
        def put_file_entry(
            self,
            _filepath: str,
            _stat_sig: object,
            _units: object,
            _blocks: object,
            _segments: object,
            *,
            source_stats: object | None = None,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            raise TypeError("broken cache write")

    monkeypatch.setattr(
        pipeline,
        "process_file",
        _stub_process_file(
            expected_root=str(tmp_path),
            expected_filepath=filepath,
        ),
    )

    with pytest.raises(TypeError, match="broken cache write"):
        pipeline.process(
            boot=boot,
            discovery=discovery,
            cache=_BrokenCache(),  # type: ignore[arg-type]
        )


def test_usable_cached_source_stats_respects_required_sections() -> None:
    source_stats: SourceStatsDict = {
        "lines": 5,
        "functions": 2,
        "methods": 1,
        "classes": 1,
    }
    base_entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 1},
        "units": [],
        "blocks": [],
        "segments": [],
        "source_stats": source_stats,
    }
    complete_entry: CacheEntry = {
        **base_entry,
        "source_stats": source_stats,
        "class_metrics": [],
        "module_deps": [],
        "dead_candidates": [],
        "referenced_names": [],
        "referenced_qualnames": [],
        "import_names": [],
        "class_names": [],
        "structural_findings": [],
    }
    assert usable_cached_source_stats(
        complete_entry,
        skip_metrics=False,
        collect_structural_findings=True,
    ) == (5, 2, 1, 1)
    assert (
        usable_cached_source_stats(
            base_entry,
            skip_metrics=False,
            collect_structural_findings=False,
        )
        is None
    )
    assert (
        usable_cached_source_stats(
            {
                **base_entry,
                "class_metrics": [],
                "module_deps": [],
                "dead_candidates": [],
                "referenced_names": [],
                "referenced_qualnames": [],
                "import_names": [],
                "class_names": [],
            },
            skip_metrics=False,
            collect_structural_findings=True,
        )
        is None
    )


def test_report_json_only_does_not_import_markdown_or_sarif(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot, discovery, processing, analysis = _build_report_case(tmp_path, json_out=True)
    original_import: Callable[..., object] = builtins.__import__

    def _guard_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name in {"codeclone.report.markdown", "codeclone.report.sarif"}:
            raise AssertionError(f"unexpected import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guard_import)

    artifacts = pipeline.report(
        boot=boot,
        discovery=discovery,
        processing=processing,
        analysis=analysis,
        report_meta={},
        new_func=(),
        new_block=(),
        html_builder=None,
        metrics_diff=None,
    )

    assert artifacts.json is not None
    assert artifacts.md is None
    assert artifacts.sarif is None


def test_analyze_skips_suppressed_dead_code_scan_when_dead_code_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = pipeline.BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(
            processes=None,
            skip_metrics=False,
            skip_dead_code=True,
            skip_dependencies=True,
        ),
        output_paths=pipeline.OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    discovery = _build_discovery(())
    processing = pipeline.ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset(),
        structural_findings=(),
        files_analyzed=0,
        files_skipped=0,
        analyzed_lines=0,
        analyzed_functions=0,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
    )
    project_metrics = ProjectMetrics(
        complexity_avg=0.0,
        complexity_max=0,
        high_risk_functions=(),
        coupling_avg=0.0,
        coupling_max=0,
        high_risk_classes=(),
        cohesion_avg=0.0,
        cohesion_max=0,
        low_cohesion_classes=(),
        dependency_modules=0,
        dependency_edges=0,
        dependency_edge_list=(),
        dependency_cycles=(),
        dependency_max_depth=0,
        dependency_longest_chains=(),
        dead_code=(),
        health=HealthScore(total=100, grade="A", dimensions={"overall": 100}),
    )

    monkeypatch.setattr(
        core_pipeline,
        "compute_project_metrics",
        lambda **kwargs: (project_metrics, None, ()),
    )
    monkeypatch.setattr(
        core_pipeline,
        "find_suppressed_unused",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("should not compute suppressed dead-code items")
        ),
    )
    monkeypatch.setattr(core_pipeline, "compute_suggestions", lambda **kwargs: ())
    monkeypatch.setattr(
        core_pipeline,
        "build_metrics_report_payload",
        lambda **kwargs: {"health": {"score": 100, "grade": "A", "dimensions": {}}},
    )

    analysis = pipeline.analyze(boot=boot, discovery=discovery, processing=processing)
    assert analysis.project_metrics == project_metrics
    assert analysis.suppressed_dead_code_items == 0
