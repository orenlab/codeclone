# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import builtins
from argparse import Namespace
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

import codeclone.core.discovery as core_discovery
import codeclone.core.parallelism as core_parallelism
import codeclone.core.pipeline as core_pipeline
import codeclone.core.worker as core_worker
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.phase_ledger import INERT_PHASE_LEDGER, PhaseLedger
from codeclone.cache.reuse import source_content_digest
from codeclone.cache.store import Cache, file_stat_signature
from codeclone.core._types import (
    DEFAULT_RUNTIME_PROCESSES,
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    FileProcessResult,
    OutputPaths,
    ProcessingResult,
)
from codeclone.core.discovery_cache import usable_cached_source_stats
from codeclone.core.parallelism import (
    _parallel_min_files,
    _resolve_process_count,
    process,
)
from codeclone.core.pipeline import analyze
from codeclone.core.reporting import GatingResult, report
from codeclone.metrics.coverage_join import CoverageJoinParseError
from codeclone.models import (
    CacheDependentPayload,
    CacheEntryV3,
    CacheNeutralPayload,
    DepGraph,
    DigestObject,
    HealthScore,
    ProjectMetrics,
    RehydratedCacheNeutral,
    SemanticFileFacts,
    SourceStatsDict,
)
from codeclone.observations.lanes import (
    build_observation_lanes,
    canonical_observation_lane_bytes,
)
from codeclone.observations.projection import build_observation_bundle
from codeclone.paths.module_identity.inventory import build_module_registry
from tests.test_observation_contract import TEST_OBSERVATION_BUNDLE


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


def _build_boot(tmp_path: Path, *, processes: int) -> BootstrapResult:
    return BootstrapResult(
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
        output_paths=OutputPaths(html=None, json=None, text=None),
        cache_path=tmp_path / "cache.json",
    )


def test_resolve_process_count_defaults_in_runtime() -> None:
    assert _resolve_process_count(None) == DEFAULT_RUNTIME_PROCESSES
    assert _resolve_process_count(0) == 1
    assert _resolve_process_count(3) == 3


def _build_discovery(filepaths: tuple[str, ...], *, root: Path) -> DiscoveryResult:
    return DiscoveryResult(
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
        module_registry=build_module_registry(root=root),
    )


def _ok_result(filepath: str) -> FileProcessResult:
    return FileProcessResult(
        filepath=filepath,
        success=True,
        source_content_digest=source_content_digest(Path(filepath).read_bytes()),
        units=[],
        blocks=[],
        segments=[],
        lines=2,
        functions=1,
        methods=0,
        classes=0,
        stat=file_stat_signature(filepath),
    )


def test_successful_file_result_requires_source_digest() -> None:
    with pytest.raises(ValueError, match="requires a source digest"):
        FileProcessResult(
            filepath="module.py",
            success=True,
            source_content_digest=None,
        )


def test_worker_hashes_and_decodes_one_source_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "module.py"
    raw_source = b"def example():\n    return 1\n"
    source.write_bytes(raw_source)
    core_worker._install_module_registry(build_module_registry(root=tmp_path))
    real_read_bytes = Path.read_bytes
    reads = 0

    def _counted_read_bytes(path: Path) -> bytes:
        nonlocal reads
        if path.resolve() == source.resolve():
            reads += 1
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _counted_read_bytes)
    result = core_worker.process_file(
        str(source),
        str(tmp_path),
        NormalizationConfig(),
        1,
        1,
        collect_structural_findings=False,
        collect_api_surface=False,
        api_include_private_modules=False,
        block_min_loc=20,
        block_min_stmt=8,
        segment_min_loc=20,
        segment_min_stmt=10,
    )

    assert result.success is True
    assert result.source_content_digest == source_content_digest(raw_source)
    assert reads == 1


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
        collect_api_surface: bool = False,
        api_include_private_modules: bool = False,
        block_min_loc: int = 20,
        block_min_stmt: int = 8,
        segment_min_loc: int = 20,
        segment_min_stmt: int = 10,
        phase_ledger: PhaseLedger = INERT_PHASE_LEDGER,
        neutral_reuse: RehydratedCacheNeutral | None = None,
    ) -> FileProcessResult:
        if expected_root is not None:
            assert root == expected_root
        if expected_filepath is not None:
            assert filepath == expected_filepath
        assert min_loc == 1
        assert min_stmt == 1
        assert collect_structural_findings is False
        assert collect_api_surface is False
        assert api_include_private_modules is False
        assert phase_ledger is INERT_PHASE_LEDGER
        assert neutral_reuse is None
        return _ok_result(filepath)

    return _process_file


def _build_large_batch_case(
    tmp_path: Path,
) -> tuple[BootstrapResult, DiscoveryResult, Cache, list[str]]:
    filepaths: list[str] = []
    for idx in range(_parallel_min_files(2) + 1):
        src = tmp_path / f"a{idx}.py"
        src.write_text("def f():\n    return 1\n", "utf-8")
        filepaths.append(str(src))

    boot = _build_boot(tmp_path, processes=2)
    discovery = _build_discovery(tuple(filepaths), root=tmp_path)
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    cache.bind_module_registry(discovery.module_registry)
    return boot, discovery, cache, filepaths


def _build_single_file_process_case(
    tmp_path: Path,
) -> tuple[str, BootstrapResult, DiscoveryResult]:
    src = tmp_path / "a.py"
    src.write_text("def f():\n    return 1\n", "utf-8")
    filepath = str(src)
    return (
        filepath,
        _build_boot(tmp_path, processes=1),
        _build_discovery((filepath,), root=tmp_path),
    )


class _ObservedAnalysisSpan:
    def __init__(self, name: str) -> None:
        self.name = name
        self.counters: dict[str, int] = {}

    def set_counter(self, key: str, value: int) -> None:
        self.counters[key] = value


def test_cache_content_identity_stage_is_wrapped_once_and_passive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "module.py"
    source.write_text("def example():\n    return 1\n", "utf-8")
    boot = _build_boot(tmp_path, processes=1)
    unobserved = core_discovery.discover(
        boot=boot,
        cache=Cache(tmp_path / "unobserved-discovery.json", root=tmp_path),
    )
    recorded: list[_ObservedAnalysisSpan] = []

    @contextmanager
    def _recording_span(*, name: str) -> Iterator[_ObservedAnalysisSpan]:
        observed = _ObservedAnalysisSpan(name)
        recorded.append(observed)
        yield observed

    monkeypatch.setattr(core_discovery, "span", _recording_span)
    observed = core_discovery.discover(
        boot=boot,
        cache=Cache(tmp_path / "observed-discovery.json", root=tmp_path),
    )

    assert observed == unobserved
    assert [observed_span.name for observed_span in recorded] == [
        "cache.content_identity",
        "cache.profile_reuse",
    ]
    assert set(recorded[0].counters) == {
        "cache_content_decision_blob_hit",
        "cache_content_decision_digest_hit",
        "cache_content_decision_digest_miss",
        "cache_content_decision_dirty",
        "cache_content_decision_git_unavailable",
        "cache_content_decision_index_ambiguous",
        "cache_content_decision_racy",
        "cache_content_decision_untracked",
        "cache_content_digest_verify_cost_us",
        "cache_stat_fast_reject",
    }
    assert recorded[1].counters == {
        "cache_lane_neutral_hit": 0,
        "cache_lane_dependent_miss": 0,
    }


def test_cache_profile_reuse_span_is_single_for_full_and_partial_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "module.py"
    source.write_text("def example():\n    return 1\n", "utf-8")
    boot = _build_boot(tmp_path, processes=1)
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    cold = core_discovery.discover(boot=boot, cache=cache)
    process(boot=boot, discovery=cold, cache=cache)

    recorded: list[_ObservedAnalysisSpan] = []

    @contextmanager
    def _recording_span(*, name: str) -> Iterator[_ObservedAnalysisSpan]:
        observed = _ObservedAnalysisSpan(name)
        recorded.append(observed)
        yield observed

    monkeypatch.setattr(core_discovery, "span", _recording_span)
    full = core_discovery.discover(boot=boot, cache=cache)
    assert full.cache_hits == 1
    assert [stage.name for stage in recorded].count("cache.profile_reuse") == 1
    assert recorded[1].counters == {
        "cache_lane_neutral_hit": 1,
        "cache_lane_dependent_miss": 0,
    }

    (tmp_path / "added.py").write_text("VALUE = 1\n", "utf-8")
    recorded.clear()
    partial = core_discovery.discover(boot=boot, cache=cache)
    assert partial.cache_hits == 0
    assert [stage.name for stage in recorded].count("cache.profile_reuse") == 1
    assert recorded[1].counters == {
        "cache_lane_neutral_hit": 1,
        "cache_lane_dependent_miss": 1,
    }


def _dependency_lane_bytes(
    result: ProcessingResult,
    discovery: DiscoveryResult,
) -> bytes:
    bundle = build_observation_bundle(
        module_registry=discovery.module_registry,
        module_deps=result.module_deps,
        collect_metrics=False,
        collect_dead_code=False,
        collect_api_surface=False,
    )
    dependencies = next(
        lane
        for lane in build_observation_lanes(bundle)
        if lane.descriptor.name == "dependencies"
    )
    return canonical_observation_lane_bytes(dependencies)


def test_dependency_lane_bytes_match_cold_warm_partial_and_full_hits(
    tmp_path: Path,
) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", "utf-8")
    (package / "dep.py").write_text("VALUE = 1\n", "utf-8")
    (package / "mod.py").write_text("from .dep import VALUE\n", "utf-8")
    boot = _build_boot(tmp_path, processes=1)
    boot.args.skip_metrics = False
    cache_path = tmp_path / "cache.json"

    cold_cache = Cache(cache_path, root=tmp_path)
    cold_discovery = core_discovery.discover(boot=boot, cache=cold_cache)
    cold_result = process(
        boot=boot,
        discovery=cold_discovery,
        cache=cold_cache,
    )
    cold_bytes = _dependency_lane_bytes(cold_result, cold_discovery)
    assert len(cold_result.module_deps) == 1
    cold_cache.save()

    warm_cache = Cache(cache_path, root=tmp_path)
    warm_cache.load()
    stale_dependent_profile = DigestObject(
        domain="codeclone.cache.profile.dependent.v1",
        algorithm="sha256",
        value="f" * 64,
    )
    for filepath, entry in tuple(warm_cache.data["files"].items()):
        warm_cache.data["files"][filepath] = replace(
            entry,
            module_dependent_profile=stale_dependent_profile,
        )
    warm_discovery = core_discovery.discover(boot=boot, cache=warm_cache)
    assert warm_discovery.cache_hits == 0
    assert len(warm_discovery.neutral_reuse_by_file) == 3
    warm_result = process(
        boot=boot,
        discovery=warm_discovery,
        cache=warm_cache,
    )
    warm_bytes = _dependency_lane_bytes(warm_result, warm_discovery)
    warm_cache.save()

    full_cache = Cache(cache_path, root=tmp_path)
    full_cache.load()
    full_discovery = core_discovery.discover(boot=boot, cache=full_cache)
    assert full_discovery.cache_hits == 3
    full_result = process(
        boot=boot,
        discovery=full_discovery,
        cache=full_cache,
    )
    full_bytes = _dependency_lane_bytes(full_result, full_discovery)

    assert cold_result.module_deps == warm_result.module_deps == full_result.module_deps
    assert cold_bytes == warm_bytes == full_bytes


@pytest.mark.parametrize("authority_enabled", [False, True])
def test_registry_and_relative_import_stages_are_single_and_fact_neutral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_enabled: bool,
) -> None:
    valid = tmp_path / "valid.py"
    broken = tmp_path / "broken.py"
    valid.write_text(
        "from .. import missing\ndef identity(value):\n    return value\n",
        "utf-8",
    )
    broken.write_text("def broken(:\n", "utf-8")
    filepaths = (str(broken), str(valid))
    boot = _build_boot(tmp_path, processes=1)
    boot.args.skip_metrics = False
    boot.args.semantic_authority = authority_enabled
    discovery = _build_discovery(filepaths, root=tmp_path)

    unobserved_cache = Cache(tmp_path / "unobserved-cache.json", root=tmp_path)
    unobserved_cache.bind_module_registry(discovery.module_registry)
    unobserved = process(
        boot=boot,
        discovery=discovery,
        cache=unobserved_cache,
    )

    recorded: list[_ObservedAnalysisSpan] = []

    @contextmanager
    def _recording_span(*, name: str) -> Iterator[_ObservedAnalysisSpan]:
        observed = _ObservedAnalysisSpan(name)
        recorded.append(observed)
        yield observed

    real_process_file = core_worker.process_file
    process_calls = 0

    def _counted_process_file(
        filepath: str,
        root: str,
        cfg: NormalizationConfig,
        min_loc: int,
        min_stmt: int,
        collect_structural_findings: bool = True,
        collect_api_surface: bool = False,
        api_include_private_modules: bool = False,
        block_min_loc: int = 20,
        block_min_stmt: int = 8,
        segment_min_loc: int = 20,
        segment_min_stmt: int = 10,
        phase_ledger: PhaseLedger = INERT_PHASE_LEDGER,
        neutral_reuse: RehydratedCacheNeutral | None = None,
    ) -> FileProcessResult:
        nonlocal process_calls
        process_calls += 1
        return real_process_file(
            filepath,
            root,
            cfg,
            min_loc,
            min_stmt,
            collect_structural_findings=collect_structural_findings,
            collect_api_surface=collect_api_surface,
            api_include_private_modules=api_include_private_modules,
            block_min_loc=block_min_loc,
            block_min_stmt=block_min_stmt,
            segment_min_loc=segment_min_loc,
            segment_min_stmt=segment_min_stmt,
            phase_ledger=phase_ledger,
            neutral_reuse=neutral_reuse,
        )

    monkeypatch.setattr(core_parallelism, "span", _recording_span)
    monkeypatch.setattr(core_worker, "process_file", _counted_process_file)
    observed_cache = Cache(tmp_path / "observed-cache.json", root=tmp_path)
    observed_cache.bind_module_registry(discovery.module_registry)
    observed = process(
        boot=boot,
        discovery=discovery,
        cache=observed_cache,
    )

    assert observed == unobserved
    assert tuple(unit["fingerprint"] for unit in observed.units) == tuple(
        unit["fingerprint"] for unit in unobserved.units
    )
    assert process_calls == len(filepaths)
    assert [stage.name for stage in recorded] == [
        "analysis.registry_bind",
        "analysis.relative_imports",
        "semantics.events",
        "semantics.flow",
        "semantics.authority.build",
    ]
    assert recorded[0].counters == {"facts_bound": 1}
    assert recorded[1].counters == {
        "analysis_dependency_targets": 0,
        "analysis_inventory_submodule_expansions": 0,
        "analysis_known_internal_not_analyzed": 0,
        "typed_failures": 1,
        "unresolved_relatives": 1,
    }
    assert recorded[2].counters == {
        "events_by_kind.return_value": 1,
        "events_unresolved": 0,
    }
    assert recorded[3].counters == {
        "functions_summarized": 1,
        "unresolved_flow_functions": 0,
    }
    authority_counters = recorded[4].counters
    assert set(authority_counters) == {
        "candidates_emitted",
        "fixpoint_iterations",
        "ir_nodes",
        "scc_count",
        "sinks_by_status.adapter",
        "sinks_by_status.authoritative",
        "sinks_by_status.mixed",
        "sinks_by_status.shadow",
        "sinks_by_status.unavailable",
    }
    if authority_enabled:
        assert authority_counters["ir_nodes"] > 0
    else:
        assert all(value == 0 for value in authority_counters.values())


def _build_report_case(
    tmp_path: Path,
    *,
    json_out: bool = True,
    md_out: bool = False,
    sarif_out: bool = False,
) -> tuple[
    BootstrapResult,
    DiscoveryResult,
    ProcessingResult,
    AnalysisResult,
]:
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(
            fail_complexity=-1,
            fail_coupling=-1,
            fail_cohesion=-1,
            fail_cycles=False,
            fail_dead_code=False,
            fail_health=-1,
            fail_on_new_metrics=False,
        ),
        output_paths=OutputPaths(
            json=tmp_path / "report.json" if json_out else None,
            md=tmp_path / "report.md" if md_out else None,
            sarif=tmp_path / "report.sarif" if sarif_out else None,
        ),
        cache_path=tmp_path / "cache.json",
    )
    discovery = _build_discovery((), root=tmp_path)
    processing = ProcessingResult(
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
    analysis = AnalysisResult(
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
        observation_bundle=TEST_OBSERVATION_BUNDLE,
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

    result = process(
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
    discovery = _build_discovery((str(src),), root=tmp_path)
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    cache.bind_module_registry(discovery.module_registry)
    callbacks: list[str] = []

    monkeypatch.setattr(core_parallelism, "ProcessPoolExecutor", _UnexpectedExec)
    monkeypatch.setattr(
        core_worker,
        "process_file",
        _stub_process_file(expected_root=str(tmp_path)),
    )
    result = process(
        boot=boot,
        discovery=discovery,
        cache=cache,
        on_parallel_fallback=lambda exc: callbacks.append(str(exc)),
    )

    assert callbacks == []
    assert result.files_analyzed == 1
    assert result.files_skipped == 0


def test_process_empty_authority_builds_the_empty_repo_fact(tmp_path: Path) -> None:
    boot = _build_boot(tmp_path, processes=1)
    boot.args.semantic_authority = True
    result = process(
        boot=boot,
        discovery=_build_discovery((), root=tmp_path),
        cache=Cache(tmp_path / "cache.json", root=tmp_path),
    )

    assert result.semantic_authority is not None
    assert result.semantic_authority.contract_ir.contracts == ()


def test_invoke_process_file_passes_full_contract_without_introspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_file = _stub_process_file(expected_root=str(tmp_path))
    monkeypatch.setattr(core_worker, "process_file", process_file)

    for idx in range(2):
        filepath = tmp_path / f"cached_{idx}.py"
        filepath.write_text("def cached():\n    return 1\n", encoding="utf-8")
        result = core_worker._invoke_process_file(
            str(filepath),
            str(tmp_path),
            NormalizationConfig(),
            1,
            1,
            collect_structural_findings=False,
            collect_api_surface=False,
            api_include_private_modules=False,
            block_min_loc=20,
            block_min_stmt=8,
            segment_min_loc=20,
            segment_min_stmt=10,
        )
        assert result.success is True


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
    result = process(
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

    result = process(
        boot=boot,
        discovery=discovery,
        cache=cache,
    )

    assert result.files_analyzed == len(filepaths)
    assert result.files_skipped == 0
    assert result.failed_files == ()
    assert cache.get_file_entry(filepaths[0]) is not None


def test_process_cache_put_file_entry_receives_required_binding_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filepath, boot, discovery = _build_single_file_process_case(tmp_path)

    class _RecordingCache:
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
            source_content_digest: object,
            source_stats: object | None = None,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            self.calls += 1

        def save(self) -> None:
            return None

    cache = _RecordingCache()
    monkeypatch.setattr(
        core_worker,
        "process_file",
        _stub_process_file(
            expected_root=str(tmp_path),
            expected_filepath=filepath,
        ),
    )

    result = process(
        boot=boot,
        discovery=discovery,
        cache=cache,  # type: ignore[arg-type]
    )

    assert result.files_analyzed == 1
    assert result.files_skipped == 0
    assert cache.calls == 1


def test_process_respects_read_only_cache_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    filepath, boot, discovery = _build_single_file_process_case(tmp_path)
    cache = Cache(tmp_path / "cache.json", root=tmp_path, write_enabled=False)
    monkeypatch.setattr(
        core_worker,
        "process_file",
        _stub_process_file(
            expected_root=str(tmp_path),
            expected_filepath=filepath,
        ),
    )

    result = process(boot=boot, discovery=discovery, cache=cache)

    assert result.files_analyzed == 1
    assert result.source_stats_by_file
    assert cache.get_file_entry(filepath) is None


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
            source_content_digest: object,
            source_stats: object | None = None,
            file_metrics: object | None = None,
            structural_findings: object | None = None,
        ) -> None:
            raise TypeError("broken cache write")

    monkeypatch.setattr(
        core_worker,
        "process_file",
        _stub_process_file(
            expected_root=str(tmp_path),
            expected_filepath=filepath,
        ),
    )

    with pytest.raises(TypeError, match="broken cache write"):
        process(
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
    profile = DigestObject(
        domain="codeclone.cache.profile.neutral.v1",
        algorithm="sha256",
        value="1" * 64,
    )
    dependent_profile = DigestObject(
        domain="codeclone.cache.profile.dependent.v1",
        algorithm="sha256",
        value="2" * 64,
    )
    complete_entry = CacheEntryV3(
        cache_content_binding_version="1",
        source_content_digest=source_content_digest(b"source"),
        git_blob_id_at_write=None,
        stat={"mtime_ns": 1, "size": 1},
        module_neutral_profile=profile,
        module_dependent_profile=dependent_profile,
        module_neutral=CacheNeutralPayload(
            source_stats=source_stats,
            units=(),
            blocks=(),
            segments=(),
            semantic_facts=SemanticFileFacts(),
        ),
        module_dependent=CacheDependentPayload(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=(),
            referenced_qualnames=(),
            import_names=(),
            class_names=(),
            runtime_reachability=(),
            security_surfaces=(),
            function_relationship_facts=(),
            typing_coverage=None,
            docstring_coverage=None,
            api_surface=None,
            structural_findings=(),
        ),
    )
    assert usable_cached_source_stats(
        complete_entry,
        skip_metrics=False,
        collect_structural_findings=True,
    ) == (5, 2, 1, 1)
    no_structural_entry = CacheEntryV3(
        cache_content_binding_version=complete_entry.cache_content_binding_version,
        source_content_digest=complete_entry.source_content_digest,
        git_blob_id_at_write=None,
        stat=complete_entry.stat,
        module_neutral_profile=profile,
        module_dependent_profile=dependent_profile,
        module_neutral=complete_entry.module_neutral,
        module_dependent=CacheDependentPayload(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=(),
            referenced_qualnames=(),
            import_names=(),
            class_names=(),
            runtime_reachability=(),
            security_surfaces=(),
            function_relationship_facts=(),
            typing_coverage=None,
            docstring_coverage=None,
            api_surface=None,
            structural_findings=None,
        ),
    )
    assert usable_cached_source_stats(
        no_structural_entry,
        skip_metrics=False,
        collect_structural_findings=False,
    ) == (5, 2, 1, 1)
    assert (
        usable_cached_source_stats(
            no_structural_entry,
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
        if name in {
            "codeclone.report.renderers.markdown",
            "codeclone.report.renderers.sarif",
        }:
            raise AssertionError(f"unexpected import: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guard_import)

    artifacts = report(
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


def test_report_requires_gate_config_and_result_as_one_evaluation(
    tmp_path: Path,
) -> None:
    boot, discovery, processing, analysis = _build_report_case(tmp_path, json_out=True)

    with pytest.raises(
        ValueError,
        match="gate config and result must be supplied together",
    ):
        report(
            boot=boot,
            discovery=discovery,
            processing=processing,
            analysis=analysis,
            report_meta={},
            new_func=(),
            new_block=(),
            report_body={},
            gate_result=GatingResult(exit_code=0, reasons=()),
        )


def test_analyze_skips_suppressed_dead_code_scan_when_dead_code_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(
            processes=None,
            skip_metrics=False,
            skip_dead_code=True,
            skip_dependencies=True,
        ),
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    discovery = _build_discovery((), root=tmp_path)
    processing = ProcessingResult(
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

    analysis = analyze(boot=boot, discovery=discovery, processing=processing)
    assert analysis.project_metrics == project_metrics
    assert analysis.suppressed_dead_code_items == 0


def test_analyze_coverage_join_parse_error_sets_invalid_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot, discovery, processing, _analysis = _build_report_case(tmp_path)
    boot.args.skip_metrics = False
    boot.args.skip_dead_code = True
    boot.args.skip_dependencies = True
    boot.args.coverage_xml = "coverage.xml"
    boot.args.coverage_min = 88

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
        lambda **kwargs: (
            project_metrics,
            DepGraph(frozenset(), (), (), 0, 0.0, 0, ()),
            (),
        ),
    )
    monkeypatch.setattr(core_pipeline, "compute_suggestions", lambda **kwargs: ())
    monkeypatch.setattr(
        core_pipeline,
        "build_metrics_report_payload",
        lambda **kwargs: {"health": {"score": 100, "grade": "A", "dimensions": {}}},
    )
    monkeypatch.setattr(
        core_pipeline,
        "build_coverage_join",
        lambda **kwargs: (_ for _ in ()).throw(CoverageJoinParseError("bad xml")),
    )

    result = analyze(boot=boot, discovery=discovery, processing=processing)
    assert result.coverage_join is not None
    assert result.coverage_join.status == "invalid"
