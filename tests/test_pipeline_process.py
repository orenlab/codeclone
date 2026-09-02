# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import builtins
from argparse import Namespace
from collections.abc import Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast, get_args

import pytest

import codeclone.core.discovery as core_discovery
import codeclone.core.parallelism as core_parallelism
import codeclone.core.pipeline as core_pipeline
import codeclone.core.worker as core_worker
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.analysis.phase_ledger import INERT_PHASE_LEDGER, PhaseLedger
from codeclone.cache.reuse import (
    binding_context_digest,
    cache_reuse_decision,
    source_content_digest,
)
from codeclone.cache.store import Cache, file_stat_signature
from codeclone.canonical.identity import DEAD_CODE_CANDIDATE_KINDS
from codeclone.core._types import (
    DEFAULT_RUNTIME_PROCESSES,
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    FileProcessResult,
    OutputPaths,
    ProcessingResult,
    _unit_to_group_item,
)
from codeclone.core.discovery_cache import (
    CachedSourceStatsRefusal,
    usable_cached_source_stats,
)
from codeclone.core.parallelism import (
    _parallel_min_files,
    _resolve_process_count,
    process,
)
from codeclone.core.pipeline import analyze
from codeclone.core.reporting import GatingResult, report
from codeclone.domain.findings import SYMBOL_KIND_IMPORT
from codeclone.metrics.coverage_join import CoverageJoinParseError
from codeclone.models import (
    CacheDependentPayload,
    CacheEntryV3,
    CacheLaneReuseReason,
    CacheNeutralPayload,
    ContentIdentityVerdict,
    DeadCodeCandidateKind,
    DepGraph,
    DigestObject,
    HealthScore,
    ModuleDep,
    ProjectMetrics,
    PythonModuleIdentity,
    RehydratedCacheNeutral,
    SemanticFileFacts,
    SourceStatsDict,
    Unit,
)
from codeclone.observations.lanes import (
    build_observation_lanes,
    canonical_observation_lane_bytes,
)
from codeclone.observations.projection import build_observation_bundle
from codeclone.paths.module_identity.inventory import build_module_registry
from tests._pipeline_fixtures import analysis_boot, discover_and_process
from tests._tmp_tree import write_files
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
        collect_near_miss: bool = False,
        collect_renamed_structure: bool = False,
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
        # True for every run now, and asserted rather than defaulted: this is
        # the structural edge from ``structural_findings_required`` to the
        # extraction it governs. Flip the owner and these stubs go red, which
        # is what proves the owner is wired to production and not merely
        # declared.
        assert collect_structural_findings is True
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
    # No row was cached, so no lane judged anything: every reason reads a
    # measured zero rather than being absent, which is what tells "none of
    # these happened" apart from "this span never ran".
    assert recorded[1].counters == {
        "cache_lane_neutral_hit": 0,
        "cache_lane_dependent_hit": 0,
        "cache_lane_dependent_miss": 0,
        "cache_profile_hit": 0,
        "cache_profile_miss": 1,
        "cache_lane_dependent_content_miss": 0,
        "cache_lane_dependent_profile_mismatch": 0,
        "cache_lane_neutral_binding_context_mismatch": 0,
        "cache_lane_neutral_clone_channels_mismatch": 0,
        "cache_lane_neutral_content_miss": 0,
        "cache_lane_neutral_profile_mismatch": 0,
        "cache_reuse_structural_findings_absent": 0,
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
    # The span said reuse happened; these two say whether it hit.
    assert recorded[1].counters == {
        "cache_lane_neutral_hit": 1,
        "cache_lane_dependent_hit": 1,
        "cache_lane_dependent_miss": 0,
        "cache_profile_hit": 1,
        "cache_profile_miss": 0,
        "cache_lane_dependent_content_miss": 0,
        "cache_lane_dependent_profile_mismatch": 0,
        "cache_lane_neutral_binding_context_mismatch": 0,
        "cache_lane_neutral_clone_channels_mismatch": 0,
        "cache_lane_neutral_content_miss": 0,
        "cache_lane_neutral_profile_mismatch": 0,
        "cache_reuse_structural_findings_absent": 0,
    }

    (tmp_path / "added.py").write_text("VALUE = 1\n", "utf-8")
    recorded.clear()
    partial = core_discovery.discover(boot=boot, cache=cache)
    assert partial.cache_hits == 0
    assert [stage.name for stage in recorded].count("cache.profile_reuse") == 1
    # Adding a module moves the module manifest, which the dependent profile
    # embeds -- so the surviving row keeps its neutral lane and loses its
    # dependent one, and now says which of the two it was.
    assert recorded[1].counters == {
        "cache_lane_neutral_hit": 1,
        "cache_lane_dependent_hit": 0,
        "cache_lane_dependent_miss": 1,
        "cache_lane_dependent_profile_mismatch": 1,
        "cache_profile_hit": 0,
        "cache_profile_miss": 2,
        "cache_lane_dependent_content_miss": 0,
        "cache_lane_neutral_binding_context_mismatch": 0,
        "cache_lane_neutral_clone_channels_mismatch": 0,
        "cache_lane_neutral_content_miss": 0,
        "cache_lane_neutral_profile_mismatch": 0,
        "cache_reuse_structural_findings_absent": 0,
    }


def _dependency_lane_bytes(
    result: ProcessingResult,
    discovery: DiscoveryResult,
) -> bytes:
    bundle = build_observation_bundle(
        scan_root=Path("."),
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


def _metrics_package(
    tmp_path: Path,
    *,
    modules: dict[str, str],
) -> tuple[BootstrapResult, Path]:
    """Write a metrics-enabled package and return its boot plus cache path."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", "utf-8")
    for name, source in sorted(modules.items()):
        (package / name).write_text(source, "utf-8")
    boot = _build_boot(tmp_path, processes=1)
    boot.args.skip_metrics = False
    return boot, tmp_path / "cache.json"


def _dead_code_lane_bytes(
    result: ProcessingResult,
    discovery: DiscoveryResult,
) -> bytes:
    bundle = build_observation_bundle(
        scan_root=Path("."),
        module_registry=discovery.module_registry,
        dead_candidates=result.dead_candidates,
        referenced_names=result.referenced_names,
        referenced_qualnames=result.referenced_qualnames,
        collect_metrics=False,
        collect_dependencies=False,
        collect_api_surface=False,
    )
    dead_code = next(
        lane
        for lane in build_observation_lanes(bundle)
        if lane.descriptor.name == "dead_code"
    )
    return canonical_observation_lane_bytes(dead_code)


def test_dead_code_lane_bytes_and_live_root_reasons_match_cold_and_warm(
    tmp_path: Path,
) -> None:
    """39Y cycle 2b: the liveness reason must survive a cache hit.

    The reason is produced by the per-file module walk, and the walk does not
    run for cached files. Before the reason rode the ``dc`` wire, a warm run
    produced no reasons at all, so the lane payload diverged cold vs warm.
    This is the guard that keeps the CACHE_VERSION 3.2 carriage honest.
    """
    boot, cache_path = _metrics_package(
        tmp_path,
        modules={
            "mod.py": (
                "import external_lib\n"
                "\n"
                "\n"
                "@external_lib.register\n"
                "def framework_handler(payload):\n"
                "    return payload\n"
                "\n"
                "\n"
                "def plain_unused(value):\n"
                "    return value\n"
            )
        },
    )

    cold_cache, cold_discovery, cold_result = discover_and_process(
        boot, cache_path, root=tmp_path, warm=False
    )
    cold_bytes = _dead_code_lane_bytes(cold_result, cold_discovery)
    cold_cache.save()

    _warm_cache, warm_discovery, warm_result = discover_and_process(
        boot, cache_path, root=tmp_path, warm=True
    )
    warm_bytes = _dead_code_lane_bytes(warm_result, warm_discovery)

    # The warm run must actually be warm, or this guard proves nothing.
    assert warm_discovery.cache_hits == 2
    reasons = tuple(
        tuple(
            sorted(
                (candidate.qualname, candidate.live_root_reason)
                for candidate in result.dead_candidates
                if candidate.live_root_reason is not None
            )
        )
        for result in (cold_result, warm_result)
    )
    assert reasons[0] == (("pkg.mod:framework_handler", "external_decorator"),)
    assert reasons[0] == reasons[1]
    assert cold_bytes == warm_bytes


def test_the_dead_code_kind_vocabulary_declares_one_kind_no_producer_emits(
    tmp_path: Path,
) -> None:
    """The closed vocabulary is checked against its population, not a mirror.

    ``DEAD_CODE_CANDIDATE_KINDS`` is pinned against ``DeadCodeCandidateKind``
    and mirrored again by the baseline lane and the cache decode. Every one of
    those guards compares a copy to a copy, so all of them stay green while
    the vocabulary declares a value nothing can construct -- and it does:
    ``import`` is declared and unreachable from any producer. This measures
    the other side, the kinds a real run actually attaches to a symbol, cold
    from the module walk and warm from the cache decode, over a fixture that
    offers functions, classes, methods and imports.

    The excess is recorded as a measured fact, not endorsed as a design. The
    honest repair is to narrow the vocabulary, and it is not free: the
    canonical wire-freeze corpus carries an ``import`` row, so narrowing
    re-freezes a ratification-gated KAT (``tests/test_canonical_roundtrip.py``
    pins that document's length and sha256). Until that is ratified this reds
    on every way the divergence could move: the value becoming constructible,
    the vocabulary dropping or growing a declared value, a real kind ceasing
    to be produced, an undeclared kind appearing, or warm disagreeing with
    cold. Repairing it therefore has to come back through here.
    """
    boot, cache_path = _metrics_package(
        tmp_path,
        modules={
            "mod.py": (
                "import json\n"
                "import unused_external\n"
                "from pathlib import Path\n"
                "\n"
                "\n"
                "def plain_function(value):\n"
                "    return json.dumps(value)\n"
                "\n"
                "\n"
                "class PlainClass:\n"
                "    def plain_method(self):\n"
                "        return Path('.')\n"
            )
        },
    )

    cold_cache, _cold_discovery, cold_result = discover_and_process(
        boot, cache_path, root=tmp_path, warm=False
    )
    cold_cache.save()
    _warm_cache, warm_discovery, warm_result = discover_and_process(
        boot, cache_path, root=tmp_path, warm=True
    )

    # Both halves must be load-bearing: a fixture carrying no import edge
    # would make "no import kind" vacuous, and a warm pass that re-analysed
    # would leave the cache decode unmeasured behind the module walk.
    assert any(dep.source == "pkg.mod" for dep in cold_result.module_deps)
    assert warm_discovery.cache_hits == 2

    produced = {candidate.kind for candidate in cold_result.dead_candidates}
    warm_kinds = {candidate.kind for candidate in warm_result.dead_candidates}

    # Both authorities that declare this vocabulary, gathered on purpose: they
    # are separate by design, and a value dropped from one of them would
    # otherwise hide behind the other. They have to be one set before the
    # excess below measures anything -- a mutation proved that reading only
    # the wire tuple left a silent narrowing of the alias alive.
    wire_vocabulary = set(DEAD_CODE_CANDIDATE_KINDS)
    declared = set(get_args(DeadCodeCandidateKind))
    assert wire_vocabulary == declared

    # The excess is spelled once, by the contract constant that names it, so
    # a rename follows instead of stranding a string literal here.
    assert declared - produced == {SYMBOL_KIND_IMPORT}
    assert produced <= declared
    assert warm_kinds == produced


def test_dependency_lane_bytes_match_cold_warm_partial_and_full_hits(
    tmp_path: Path,
) -> None:
    boot, cache_path = _metrics_package(
        tmp_path,
        modules={
            "dep.py": "VALUE = 1\n",
            "mod.py": "from .dep import VALUE\n",
        },
    )

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
    # A load leaves the lanes on disk, so the entries have to be asked for
    # before they can be made stale; the in-memory map starts empty by design.
    for filepath in cold_discovery.all_file_paths:
        entry = warm_cache.get_file_entry(filepath)
        assert entry is not None
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
    valid, broken = write_files(
        tmp_path,
        (
            "valid.py",
            "from .. import missing\ndef identity(value):\n    return value\n",
        ),
        ("broken.py", "def broken(:\n"),
    )
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
        collect_near_miss: bool = False,
        collect_renamed_structure: bool = False,
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
        low_value_segment_groups=0,
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
            collect_structural_findings=True,
            collect_api_surface=False,
            api_include_private_modules=False,
            collect_near_miss=False,
            collect_renamed_structure=False,
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
            materialized_clone_channels: tuple[str, ...] = (),
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
            materialized_clone_channels: tuple[str, ...] = (),
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


#: One function, two if-branches with the same shape: the smallest source that
#: makes ``scan_function_structure`` emit a structural finding group, so a test
#: can compare a warm run's structural population against a cold run's instead
#: of comparing two empty tuples.
_REPEATED_BRANCH_SOURCE = """def foo(x):
    a = 1
    b = 2
    c = 3
    d = 4
    e = 5
    if x == 1:
        log("a")
        value = x + 1
        return value
    elif x == 2:
        log("b")
        value = x + 2
        return value
    return a + b + c + d + e
"""


def _reason_boot(
    tmp_path: Path,
    *,
    report_output: bool,
    min_loc: int = 1,
    near_miss: bool = False,
) -> BootstrapResult:
    """A boot whose knobs decide the lane profile, channels and sections.

    ``report_output`` says whether the operator asked for a report FILE. It is
    presentation intent and nothing else: which facts the analysis materialises
    is not its to decide.
    """

    return BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(
            processes=1,
            min_loc=min_loc,
            min_stmt=1,
            block_min_loc=20,
            block_min_stmt=8,
            segment_min_loc=20,
            segment_min_stmt=10,
            skip_metrics=False,
            near_miss=near_miss,
            renamed_structure=False,
        ),
        output_paths=OutputPaths(
            json=tmp_path / "report.json" if report_output else None
        ),
        cache_path=tmp_path / "cache.json",
    )


def _profile_counters(
    monkeypatch: pytest.MonkeyPatch,
    *,
    boot: BootstrapResult,
    cache: Cache,
) -> dict[str, int]:
    recorded: list[_ObservedAnalysisSpan] = []

    @contextmanager
    def _recording_span(*, name: str) -> Iterator[_ObservedAnalysisSpan]:
        observed = _ObservedAnalysisSpan(name)
        recorded.append(observed)
        yield observed

    monkeypatch.setattr(core_discovery, "span", _recording_span)
    core_discovery.discover(boot=boot, cache=cache)
    monkeypatch.undo()
    by_name = {observed.name: observed for observed in recorded}
    assert "cache.profile_reuse" in by_name, sorted(by_name)
    return dict(by_name["cache.profile_reuse"].counters)


def test_cache_profile_reuse_names_which_reason_refused_each_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cold run caused by a profile move must say so, per lane.

    The content half of the same decision has been diagnosable per reason for
    a while -- eight ``cache_content_decision_*`` counters -- while the lane
    half published totals only. So "the cache went cold" was answerable when
    the file changed and unanswerable when the profile did, and the reason was
    computed on every entry and thrown away.
    """

    (tmp_path / "module.py").write_text("def example():\n    return 1\n", "utf-8")
    cache = Cache(tmp_path / "cache.json", root=tmp_path, min_loc=1, min_stmt=1)
    cold = _reason_boot(tmp_path, report_output=False)
    discovery = core_discovery.discover(boot=cold, cache=cache)
    process(boot=cold, discovery=discovery, cache=cache)
    cache.save()

    def _at_profile(min_loc: int) -> dict[str, int]:
        """Read the lane counters through a handle opened at ``min_loc``.

        The neutral lane keys on the analysis profile the *cache* was opened
        with, so a moved profile has to reach the same store through its own
        handle -- and reading both profiles through one helper keeps the two
        readings from being the same six lines twice.
        """

        handle = Cache(
            tmp_path / "cache.json", root=tmp_path, min_loc=min_loc, min_stmt=1
        )
        handle.load()
        return _profile_counters(
            monkeypatch,
            boot=_reason_boot(tmp_path, report_output=False, min_loc=min_loc),
            cache=handle,
        )

    lanes = (
        "cache_lane_neutral_hit",
        "cache_lane_neutral_profile_mismatch",
        "cache_lane_dependent_hit",
        "cache_lane_dependent_profile_mismatch",
    )
    unchanged = _at_profile(1)
    assert {key: unchanged[key] for key in lanes} == {
        "cache_lane_neutral_hit": 1,
        "cache_lane_neutral_profile_mismatch": 0,
        "cache_lane_dependent_hit": 1,
        "cache_lane_dependent_profile_mismatch": 0,
    }

    # The dependent lane embeds the neutral digest, so a moved neutral profile
    # refuses both lanes -- each naming its own reason rather than a shared
    # "miss".
    moved = _at_profile(2)
    assert {key: moved[key] for key in lanes} == {
        "cache_lane_neutral_hit": 0,
        "cache_lane_neutral_profile_mismatch": 1,
        "cache_lane_dependent_hit": 0,
        "cache_lane_dependent_profile_mismatch": 1,
    }


def test_cache_reuse_refusal_after_the_lanes_is_named_not_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both lanes hit and the entry is still refused -- say which section is missing.

    Measured 2026-09-02 on this repository: an MCP analysis reused none of the
    rows a CLI run had just written, with ``cache_lane_neutral_hit`` equal to
    the entry count and ``cache_lane_dependent_miss`` zero. Every lane agreed
    and every entry was still processed, because the rows were written without
    structural findings and the MCP run needs them -- a refusal that reached no
    counter at all, which is why the cause could not be named for two days.
    """

    (tmp_path / "module.py").write_text("def example():\n    return 1\n", "utf-8")
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    legacy = _reason_boot(tmp_path, report_output=False)
    discovery = core_discovery.discover(boot=legacy, cache=cache)
    with _legacy_writer():
        process(boot=legacy, discovery=discovery, cache=cache)

    current = _reason_boot(tmp_path, report_output=True)
    counters = _profile_counters(monkeypatch, boot=current, cache=cache)

    # The lanes are unanimous -- nothing about the profile, the binding context
    # or the content rejected this row -- and it was processed anyway, now with
    # the reason beside it. Read as one mapping rather than a run of asserts:
    # the whole verdict is the claim, and a run of them is a clone the block
    # lane names on sight.
    decisive = (
        "cache_lane_neutral_hit",
        "cache_lane_dependent_hit",
        "cache_lane_dependent_miss",
        "cache_profile_hit",
        "cache_profile_miss",
        "cache_reuse_structural_findings_absent",
    )
    assert {key: counters[key] for key in decisive} == {
        "cache_lane_neutral_hit": 1,
        "cache_lane_dependent_hit": 1,
        "cache_lane_dependent_miss": 0,
        "cache_profile_hit": 0,
        "cache_profile_miss": 1,
        "cache_reuse_structural_findings_absent": 1,
    }

    # The partition closes: one cached row was judged, so each lane family sums
    # to exactly one. A reason that stopped being counted, or one counted
    # twice, breaks this without needing a test per reason.
    assert (
        sum(
            counters[key]
            for key in core_discovery._NEUTRAL_LANE_REASON_COUNTERS.values()
        )
        == 1
    )
    assert (
        sum(
            counters[key]
            for key in core_discovery._DEPENDENT_LANE_REASON_COUNTERS.values()
        )
        == 1
    )


def _rewrite(path: Path, text: str) -> None:
    """Write and discard the byte count, so the callable stays ``() -> None``."""

    path.write_text(text, "utf-8")


@contextmanager
def _legacy_writer() -> Iterator[None]:
    """Write rows the way every build before the owner landed wrote them.

    The materialisation requirement now has one owner and one value, so NO run
    configuration produces a row without structural findings -- lowering the
    owner would only make the section empty, not absent, because the writer no
    longer branches on it. A store an older build populated is the one input
    that still carries the absent shape, and it is a real input: it is what an
    upgrade meets on its first run. So the row is fabricated at the store
    boundary, which is the only place the two shapes are still distinguishable.
    """

    original = cast("Callable[..., None]", Cache.put_file_entry)

    def _legacy_put(*args: object, **kwargs: object) -> None:
        original(*args, **{**kwargs, "structural_findings": None})

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Cache, "put_file_entry", _legacy_put)
        yield


def _warm_counters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    warm_boot: BootstrapResult,
    warm_cache: Cache | None = None,
    mutate: Callable[[], None] | None = None,
    legacy_cold_rows: bool = False,
) -> dict[str, int]:
    """Write a cold generation, optionally disturb it, then read the warm one."""

    cold = _reason_boot(tmp_path, report_output=False)
    cache = Cache(tmp_path / "cache.json", root=tmp_path, min_loc=1, min_stmt=1)
    discovery = core_discovery.discover(boot=cold, cache=cache)
    with ExitStack() as stack:
        if legacy_cold_rows:
            stack.enter_context(_legacy_writer())
        process(boot=cold, discovery=discovery, cache=cache)
    cache.save()
    if mutate is not None:
        mutate()
    warm = warm_cache
    if warm is None:
        warm = Cache(tmp_path / "cache.json", root=tmp_path, min_loc=1, min_stmt=1)
    warm.load()
    return _profile_counters(monkeypatch, boot=warm_boot, cache=warm)


def test_every_declared_reuse_reason_counter_has_an_input_that_raises_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each counter is shown non-zero by a real run, or by the decision itself.

    A counter no configuration can raise is the same theatre as a guard no
    input reaches, and declaring one is how a vocabulary comes to describe a
    build that cannot produce it. So the families are not merely declared here
    -- each member is driven to a non-zero value, and the set that was driven
    is compared against the set that was declared.
    """

    raised: set[str] = set()
    source = "def example(a, b):\n    return a + b\n"

    def _record(counters: dict[str, int], expected: str) -> None:
        """One scenario, one counter: the set alone is blind to mis-attribution.

        Measured 2026-09-02: a mutation that swaps two reasons in the mapping
        leaves the *set* of non-zero counters unchanged and survived an earlier
        version of this test. What each input raises is the assertion.
        """

        moved = {key for key, value in counters.items() if value}
        assert expected in moved, (expected, sorted(moved))
        raised.update(moved)

    def _seed(name: str) -> Path:
        root = tmp_path / name
        root.mkdir()
        (root / "module.py").write_text(source, "utf-8")
        return root

    # Nothing moved: both lanes hit.
    unchanged = _seed("unchanged")
    _record(
        _warm_counters(
            unchanged,
            monkeypatch,
            warm_boot=_reason_boot(unchanged, report_output=False),
        ),
        "cache_lane_neutral_hit",
    )

    # The file changed: content refuses both lanes before either is consulted.
    changed = _seed("changed")
    _record(
        _warm_counters(
            changed,
            monkeypatch,
            warm_boot=_reason_boot(changed, report_output=False),
            mutate=lambda: _rewrite(changed / "module.py", source + "VALUE = 1\n"),
        ),
        "cache_lane_neutral_content_miss",
    )

    # The run asks for clone artifacts the stored row was not materialised with.
    channels = _seed("channels")
    _record(
        _warm_counters(
            channels,
            monkeypatch,
            warm_boot=_reason_boot(channels, report_output=False, near_miss=True),
        ),
        "cache_lane_neutral_clone_channels_mismatch",
    )

    # The analysis profile moved, so the row describes a different question.
    moved = _seed("moved")
    _record(
        _warm_counters(
            moved,
            monkeypatch,
            warm_boot=_reason_boot(moved, report_output=False, min_loc=2),
            warm_cache=Cache(moved / "cache.json", root=moved, min_loc=2, min_stmt=1),
        ),
        "cache_lane_neutral_profile_mismatch",
    )

    # The run needs a section the row was written without.
    sections = _seed("sections")
    _record(
        _warm_counters(
            sections,
            monkeypatch,
            warm_boot=_reason_boot(sections, report_output=True),
            legacy_cold_rows=True,
        ),
        "cache_reuse_structural_findings_absent",
    )

    declared = set(core_discovery._REUSE_REASON_COUNTER_KEYS)
    assert declared, "no reuse reason counter was declared, so nothing was compared"
    # binding_context_mismatch is reached by the decision, not by a layout:
    # eight probed layouts (2026-09-02) all moved the module manifest first, so
    # the dependent lane refused before the binding context could. Its input is
    # the decision's own, exercised below.
    binding_counter = core_discovery._NEUTRAL_LANE_REASON_COUNTERS[
        "binding_context_mismatch"
    ]
    assert declared - raised == {binding_counter}, sorted(declared - raised)


def _entry_with_binding(binding: DigestObject) -> CacheEntryV3:
    """A minimal complete row whose only interesting field is its binding."""

    stats: SourceStatsDict = {"lines": 5, "functions": 2, "methods": 1, "classes": 1}
    return CacheEntryV3(
        cache_content_binding_version="1",
        binding_context_digest=binding,
        source_content_digest=source_content_digest(b"source"),
        git_blob_id_at_write=None,
        stat={"mtime_ns": 1, "size": 1},
        module_neutral_profile=DigestObject(
            domain="codeclone.cache.profile.neutral.v1",
            algorithm="sha256",
            value="1" * 64,
        ),
        module_dependent_profile=DigestObject(
            domain="codeclone.cache.profile.dependent.v1",
            algorithm="sha256",
            value="2" * 64,
        ),
        module_neutral=CacheNeutralPayload(
            source_stats=stats,
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


def test_the_binding_context_lane_reason_is_reachable_from_the_decision(
    tmp_path: Path,
) -> None:
    """The one reason no layout reached still has an input that decides it.

    Left uncounted it would be a hole in the partition; declared without an
    input it would be theatre. The input is the decision's own argument: a row
    written under one binding context, read under another.
    """

    entry = _entry_with_binding(binding_context_digest(None))
    moved = binding_context_digest(
        PythonModuleIdentity(
            module="pkg.module",
            package="pkg",
            is_package=False,
            mount_path="pkg/module.py",
            origin="import_mount",
            node_kind="module_file",
        )
    )
    decision = cache_reuse_decision(
        content=ContentIdentityVerdict(
            hit=True,
            reason="blob_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        ),
        entry=entry,
        neutral_profile=entry.module_neutral_profile,
        dependent_profile=entry.module_dependent_profile,
        binding_context=moved,
        required_clone_channels=(),
    )
    assert decision.neutral.reason == "binding_context_mismatch"
    assert decision.neutral.hit is False
    assert (
        core_discovery._NEUTRAL_LANE_REASON_COUNTERS[decision.neutral.reason]
        == "cache_lane_neutral_binding_context_mismatch"
    )


def test_cache_reuse_reason_counters_are_the_decisions_own_vocabulary() -> None:
    """The declared counters are re-derived from what decides them.

    A prefix rule would bless any plausible-looking key, including one no
    decision can produce. Each family here is the domain of its own decider,
    so a counter with no reason behind it, or a reason with no counter, fails.
    """

    from codeclone.observability.vocabulary import COUNTER_KEYS

    lane_reasons = set(get_args(CacheLaneReuseReason))
    assert lane_reasons, "the lane reason vocabulary is empty, so nothing was compared"
    # malformed_payload is declared by the alias and constructed by no producer
    # in this build (measured 2026-09-02: zero construction sites); a counter
    # for it could never leave zero, which is the theatre this file rejects
    # elsewhere. It is instrumented when something can decide it.
    decidable = lane_reasons - {"malformed_payload"}

    assert (
        set(core_discovery._NEUTRAL_LANE_REASON_COUNTERS)
        | {"dependent_profile_mismatch"}
        == decidable
    )
    assert set(core_discovery._DEPENDENT_LANE_REASON_COUNTERS) <= decidable
    assert {
        key for key in COUNTER_KEYS if key.startswith("cache_lane_neutral_")
    } == set(core_discovery._NEUTRAL_LANE_REASON_COUNTERS.values())
    dependent_family = {
        key for key in COUNTER_KEYS if key.startswith("cache_lane_dependent_")
    } - {"cache_lane_dependent_miss"}
    assert dependent_family == set(
        core_discovery._DEPENDENT_LANE_REASON_COUNTERS.values()
    )

    refusals = set(get_args(CachedSourceStatsRefusal))
    assert refusals, "the post-lane refusal vocabulary is empty"
    assert set(core_discovery._POST_LANE_REFUSAL_COUNTERS) == refusals
    assert set(core_discovery._POST_LANE_REFUSAL_COUNTERS.values()) == {
        key for key in COUNTER_KEYS if key.startswith("cache_reuse_")
    }


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
        binding_context_digest=binding_context_digest(None),
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
        binding_context_digest=complete_entry.binding_context_digest,
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


def _processed_package(
    tmp_path: Path,
    modules: Mapping[str, str],
) -> ProcessingResult:
    """Analyse a one-package repository with semantics enabled."""

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", "utf-8")
    for name, body in modules.items():
        (package / name).write_text(body, "utf-8")
    boot = _build_boot(tmp_path, processes=1)
    boot.args.skip_metrics = False
    boot.args.semantic_authority = True
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    discovery = core_discovery.discover(boot=boot, cache=cache)
    return process(boot=boot, discovery=discovery, cache=cache)


def _dynamic_load_deps(
    tmp_path: Path,
    source: str,
) -> tuple[ModuleDep, ...]:
    result = _processed_package(
        tmp_path,
        {"plugin.py": "VALUE = 1\n", "loader.py": source},
    )
    return tuple(dep for dep in result.module_deps if dep.source == "pkg.loader")


def test_literal_dynamic_load_resolves_through_existing_machinery(
    tmp_path: Path,
) -> None:
    deps = _dynamic_load_deps(
        tmp_path,
        "import importlib\n"
        "\n"
        "\n"
        "def internal() -> object:\n"
        "    return importlib.import_module('pkg.plugin')\n"
        "\n"
        "\n"
        "def external() -> object:\n"
        "    return importlib.import_module('orjson')\n",
    )
    dynamic = {dep.target: dep for dep in deps if dep.mechanism == "dynamic"}

    # The internal target is resolved by the same classifier the static
    # statements use — a dynamic edge is a real edge, not a second graph.
    assert dynamic["pkg.plugin"].resolution == "analyzed"
    assert dynamic["pkg.plugin"].requested_module == "pkg.plugin"
    assert dynamic["orjson"].resolution == "external"

    # The static import of importlib itself keeps the static discriminator.
    static = {dep.target: dep for dep in deps if dep.mechanism == "static"}
    assert static["importlib"].resolution == "external"


def test_opaque_dynamic_load_keeps_the_site_without_inventing_a_target(
    tmp_path: Path,
) -> None:
    deps = _dynamic_load_deps(
        tmp_path,
        "import importlib\n"
        "\n"
        "\n"
        "def probe(name: str) -> object:\n"
        "    return importlib.import_module(name)\n",
    )
    opaque = [dep for dep in deps if dep.resolution == "unresolved_dynamic"]

    assert len(opaque) == 1
    assert opaque[0].mechanism == "dynamic"
    assert opaque[0].target == ""
    assert opaque[0].candidate_targets == ()
    assert opaque[0].requested_module is None


def test_unlisted_dynamic_mechanisms_produce_no_dependency_record(
    tmp_path: Path,
) -> None:
    deps = _dynamic_load_deps(
        tmp_path,
        "import runpy\n"
        "\n"
        "\n"
        "def run() -> object:\n"
        "    return runpy.run_module('pkg.plugin')\n",
    )

    # runpy executes a module; it is not an import edge, and the capability
    # gate must not turn it into one.
    assert [dep.target for dep in deps if dep.mechanism == "dynamic"] == []
    assert [dep.target for dep in deps if dep.mechanism == "static"] == ["runpy"]


def test_builtin_import_and_spec_from_file_literals_follow_decision_one(
    tmp_path: Path,
) -> None:
    deps = _dynamic_load_deps(
        tmp_path,
        "import importlib.util\n"
        "\n"
        "\n"
        "def builtin() -> object:\n"
        "    return __import__('pkg.plugin')\n"
        "\n"
        "\n"
        "def from_file() -> object:\n"
        "    return importlib.util.spec_from_file_location('pkg.plugin', 'p.py')\n",
    )
    dynamic = sorted(
        (dep for dep in deps if dep.mechanism == "dynamic"),
        key=lambda dep: dep.line,
    )

    # Both mechanisms must produce their own edge; a set comparison alone
    # would stay green if only one of them fired.
    assert len(dynamic) == 2
    assert [dep.target for dep in dynamic] == ["pkg.plugin", "pkg.plugin"]
    assert [dep.resolution for dep in dynamic] == ["analyzed", "analyzed"]


def test_overloads_and_property_pairs_do_not_break_semantic_authority(
    tmp_path: Path,
) -> None:
    result = _processed_package(
        tmp_path,
        {
            "shapes.py": (
                "from typing import overload\n"
                "\n"
                "\n"
                "@overload\n"
                "def widen(value: int) -> int: ...\n"
                "\n"
                "\n"
                "@overload\n"
                "def widen(value: str) -> str: ...\n"
                "\n"
                "\n"
                "def widen(value: int | str) -> int | str:\n"
                "    return value\n"
                "\n"
                "\n"
                "class Holder:\n"
                "    @property\n"
                "    def label(self) -> str:\n"
                "        return self._label\n"
                "\n"
                "    @label.setter\n"
                "    def label(self, value: str) -> None:\n"
                "        self._label = value\n"
            ),
        },
    )

    # A qualname shared by overload stubs or by a property/setter pair must not
    # abort the run: stubs are declarations, and a genuinely shared qualname
    # carries no contract rather than an arbitrary one.
    assert result.semantic_authority is not None
    contracts = {
        contract.function
        for contract in result.semantic_authority.contract_ir.contracts
    }
    assert "pkg.shapes:widen" in contracts
    assert "pkg.shapes:Holder.label" not in contracts


def test_worker_identity_guards_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A worker without an installed registry, or asked about a file the
    registry never saw, refuses instead of guessing a module identity."""

    source = tmp_path / "module.py"
    source.write_bytes(b"def example():\n    return 1\n")
    registry = build_module_registry(root=tmp_path)

    with pytest.raises(ValueError, match="absent from module registry"):
        core_worker._source_identity_for_worker(
            registry=registry,
            root=str(tmp_path),
            resolved_path=(tmp_path / "never_discovered.py").resolve(),
        )

    monkeypatch.setattr(core_worker, "_WORKER_MODULE_REGISTRY", None)
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
    assert result.success is False
    assert result.error is not None
    assert "module registry is not installed" in result.error


def test_cache_saved_over_cap_must_still_warm_next_run(tmp_path: Path) -> None:
    """Pinned maintainer predicate: cache larger than cap => second run must
    still get cached > 0.

    This was a strict xfail from 2026-08-04 to 2026-09-01.  While the cache was
    one JSON document, ``save()`` never enforced ``max_size_bytes`` and
    ``load()`` hard-rejected any file above it, so the tool wrote caches it then
    refused to read (Django 5.2 shape: 73 MB written against the then-default
    50 MB load cap => permanently cold at defaults; raising the default to
    256 MB moved that cliff without removing it).  The xfail was written to
    start erroring the moment save/load symmetry was restored, and it did:
    moving the cache onto the row-addressed SQLite backend turned it
    ``XPASS(strict)``.

    The body below is unchanged from the pinned version -- same cap, same
    premise assertion, same ``cache_hits`` predicate.  Only the marker is gone,
    because the predicate now holds.  Two things keep it honest rather than
    decorative:

    * the premise assertion still demands the store be *over* its cap, so a
      regression that made the cap refuse writes would fail here, not pass;
    * ``cache_hits > 0`` still demands the next run actually warm, so a
      regression that dropped the entry to satisfy the budget would fail too.

    Neither escape route the ruling forbade is taken: the cap is not raised
    (it is still 256 bytes, still smaller than one entry) and the monolith is
    not compressed (there is no monolith).  What changed is that reading an
    entry no longer requires reading the store, so store size stopped being a
    reason to refuse.
    """
    (tmp_path / "mod.py").write_text(
        "def alpha(left, right):\n    total = left + right\n    return total\n",
        "utf-8",
    )
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=True)
    cache_path = tmp_path / "cache.sqlite3"
    # Any saved single-entry cache is larger than this cap; the unit-scale
    # mirror of a real-repo cache outgrowing its configured cap (the default
    # moved 50 -> 256 MB on 2026-08-04; the cliff moved with it).
    cap_bytes = 256

    cold_cache = Cache(cache_path, root=tmp_path, max_size_bytes=cap_bytes)
    cold_discovery = core_discovery.discover(boot=boot, cache=cold_cache)
    process(boot=boot, discovery=cold_discovery, cache=cold_cache)
    cold_cache.save()

    # Premise, still true: save() wrote a store above its own configured cap
    # rather than shrinking, splitting, or refusing it.  The budget evicts only
    # rows an older generation left behind, and this run owns every row here.
    assert cache_path.stat().st_size > cap_bytes

    warm_cache = Cache(cache_path, root=tmp_path, max_size_bytes=cap_bytes)
    warm_cache.load()
    warm_discovery = core_discovery.discover(boot=boot, cache=warm_cache)
    assert warm_discovery.cache_hits > 0


def test_worker_types_unsupported_construct_refusals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wire refusal is a typed, attributable outcome, not an unexpected error.

    Python 3.15 probe, G1b: a file whose (parsed) syntax the wire whitelist
    refuses must surface as ``unsupported_construct`` with a witness naming the
    construct, so the loss is visible instead of a silent skip.
    """

    from codeclone.analysis.wire import WireUnsupportedNode

    source = tmp_path / "module.py"
    source.write_text("def example():\n    return 1\n", "utf-8")
    core_worker._install_module_registry(build_module_registry(root=tmp_path))

    def _refuse(**_kwargs: object) -> object:
        raise WireUnsupportedNode("unsupported fields on Import: is_lazy")

    monkeypatch.setattr(core_worker, "extract_units_and_stats_from_source", _refuse)
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

    assert result.success is False
    assert result.error_kind == "unsupported_construct"
    assert result.error == (
        "Unsupported construct: unsupported fields on Import: is_lazy"
    )


def test_process_collects_unsupported_construct_witnesses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire-refused files are counted as skipped and carry a per-file witness."""

    from codeclone.analysis.wire import WireUnsupportedNode
    from codeclone.models import UnsupportedConstructSkip

    filepath, boot, discovery = _build_single_file_process_case(tmp_path)
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    cache.bind_module_registry(discovery.module_registry)

    def _refuse(**_kwargs: object) -> object:
        raise WireUnsupportedNode("unsupported fields on Import: is_lazy")

    monkeypatch.setattr(core_worker, "extract_units_and_stats_from_source", _refuse)
    result = process(boot=boot, discovery=discovery, cache=cache)

    assert result.files_analyzed == 0
    assert result.files_skipped == 1
    assert result.failed_files == (
        f"{filepath}: Unsupported construct: unsupported fields on Import: is_lazy",
    )
    assert result.source_read_failures == ()
    assert result.unsupported_construct_skips == (
        UnsupportedConstructSkip(
            filepath=filepath,
            construct="unsupported fields on Import: is_lazy",
        ),
    )


def _materialise(tmp_path: Path, cache: Cache, boot: BootstrapResult) -> None:
    """Run one full discover/process pass, leaving its rows in ``cache``."""

    discovery = core_discovery.discover(boot=boot, cache=cache)
    process(boot=boot, discovery=discovery, cache=cache)


def test_gate_only_run_writes_rows_a_report_run_can_serve(tmp_path: Path) -> None:
    """A run that asked for no report file still materialises the full row.

    Measured 2026-09-02 on this repository (1148 files): a CLI run with no
    ``--json`` populated the store, and the next MCP analysis reused 0 of 1148
    rows and rewrote every one -- 2296 row writes to converge instead of 1148.
    Both cache lanes hit and content identity said the bytes were unchanged;
    the rows were discarded downstream because they carried no structural
    findings. The population an analysis materialises is not the operator's
    output flags to decide, so the row a gate-only run writes has to serve the
    run that consumes the report document.
    """

    (tmp_path / "module.py").write_text(_REPEATED_BRANCH_SOURCE, "utf-8")
    cache = Cache(tmp_path / "cache.json", root=tmp_path, min_loc=1, min_stmt=1)
    _materialise(tmp_path, cache, _reason_boot(tmp_path, report_output=False))

    warm = core_discovery.discover(
        boot=_reason_boot(tmp_path, report_output=True), cache=cache
    )

    assert (warm.cache_hits, warm.files_to_process) == (1, ())


def test_warm_structural_findings_equal_the_cold_run_s(tmp_path: Path) -> None:
    """The findings served off a gate-only row are the findings a cold run computes.

    The reuse verdict alone would be satisfied by a row that is accepted and
    then read as empty, which is the failure this whole class hides behind: a
    warm run that is fast and quietly reports less than the cold run it claims
    to replace. So the population is compared, not just the hit count.
    """

    (tmp_path / "module.py").write_text(_REPEATED_BRANCH_SOURCE, "utf-8")
    reporting = _reason_boot(tmp_path, report_output=True)

    cold_cache = Cache(tmp_path / "cold.json", root=tmp_path, min_loc=1, min_stmt=1)
    cold_discovery = core_discovery.discover(boot=reporting, cache=cold_cache)
    cold = process(boot=reporting, discovery=cold_discovery, cache=cold_cache)

    warm_cache = Cache(tmp_path / "warm.json", root=tmp_path, min_loc=1, min_stmt=1)
    _materialise(tmp_path, warm_cache, _reason_boot(tmp_path, report_output=False))
    warm = core_discovery.discover(boot=reporting, cache=warm_cache)

    assert cold.structural_findings, "fixture must produce a structural finding"
    assert warm.cached_structural_findings == cold.structural_findings


def _cohort_unit(name: str, *, divergent: bool) -> Unit:
    """One member of a four-way clone cohort, uniform unless asked to diverge."""

    return Unit(
        qualname=f"pkg.{name}:handler",
        filepath=f"pkg/{name}.py",
        start_line=10,
        end_line=40,
        loc=30,
        stmt_count=20,
        # Same fingerprint and bucket for every member: that pair is what makes
        # them one clone group, which is the input the cohort derivation reads.
        # The fingerprint is a real 64-hex value because the clone id it forms
        # is validated downstream as a canonical fp-v2 identifier.
        fingerprint="c" * 64,
        loc_bucket="20-49",
        entry_guard_count=1 if divergent else 2,
        entry_guard_terminal_profile="raise" if divergent else "return_const,raise",
        entry_guard_has_side_effect_before=divergent,
        terminal_kind="raise" if divergent else "return_const",
        try_finally_profile="try_no_finally" if divergent else "none",
        side_effect_order_profile=(
            "effect_before_guard" if divergent else "guard_then_effect"
        ),
    )


def test_clone_cohort_structural_findings_reach_the_analysis_result(
    tmp_path: Path,
) -> None:
    """The whole-project half of the population is derived, not merely derivable.

    Measured by mutation 2026-09-02: replacing this call site with an empty
    tuple left the full suite -- 8251 tests -- green. The per-file half of the
    structural population is pinned in several places; the cohort half, which
    only the pipeline can produce because only it has the clone groups, was
    pinned solely as a unit test of the emitter. So the call could be deleted
    and nothing would say so, and the run that no longer needs a report flag to
    materialise the rest would have kept silently dropping this part.
    """

    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(
            processes=None,
            skip_metrics=True,
            skip_dead_code=True,
            skip_dependencies=True,
            min_loc=6,
            min_stmt=4,
        ),
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    units = (
        _cohort_unit("a", divergent=False),
        _cohort_unit("b", divergent=False),
        _cohort_unit("c", divergent=False),
        _cohort_unit("d", divergent=True),
    )
    processing = ProcessingResult(
        units=tuple(_unit_to_group_item(unit) for unit in units),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
        referenced_names=frozenset(),
        referenced_qualnames=frozenset(),
        structural_findings=(),
        files_analyzed=len(units),
        files_skipped=0,
        analyzed_lines=0,
        analyzed_functions=0,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
    )

    result = analyze(
        boot=boot,
        discovery=_build_discovery((), root=tmp_path),
        processing=processing,
    )

    assert {group.finding_kind for group in result.structural_findings} == {
        "clone_cohort_drift",
        "clone_guard_exit_divergence",
    }
