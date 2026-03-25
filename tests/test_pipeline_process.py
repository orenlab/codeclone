from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Literal

import pytest

import codeclone.pipeline as pipeline
from codeclone.cache import Cache, CacheEntry, SourceStatsDict, file_stat_signature
from codeclone.normalize import NormalizationConfig


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


def test_process_parallel_fallback_without_callback_uses_sequential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot, discovery, cache, filepaths = _build_large_batch_case(tmp_path)

    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", _FailExec)
    monkeypatch.setattr(
        pipeline,
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

    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", _UnexpectedExec)
    monkeypatch.setattr(
        pipeline,
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

    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", _FailExec)
    monkeypatch.setattr(
        pipeline,
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
    assert pipeline._usable_cached_source_stats(
        complete_entry,
        skip_metrics=False,
        collect_structural_findings=True,
    ) == (5, 2, 1, 1)
    assert (
        pipeline._usable_cached_source_stats(
            base_entry,
            skip_metrics=False,
            collect_structural_findings=False,
        )
        is None
    )
    assert (
        pipeline._usable_cached_source_stats(
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
