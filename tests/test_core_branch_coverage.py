from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import cast

import pytest

import codeclone.cli as cli
import codeclone.pipeline as pipeline
from codeclone.cache import (
    Cache,
    CacheEntry,
    _as_file_stat_dict,
    _as_risk_literal,
    _decode_wire_file_entry,
    _decode_wire_structural_findings_optional,
    _decode_wire_structural_group,
    _decode_wire_structural_occurrence,
    _decode_wire_structural_signature,
    _decode_wire_unit,
    _has_cache_entry_container_shape,
    _is_dead_candidate_dict,
)
from codeclone.errors import CacheError
from codeclone.models import (
    BlockUnit,
    ClassMetrics,
    DeadCandidate,
    FileMetrics,
    ModuleDep,
    SegmentUnit,
)
from codeclone.normalize import NormalizationConfig


def test_cache_risk_and_shape_helpers() -> None:
    assert _as_risk_literal("low") == "low"
    assert _as_risk_literal("medium") == "medium"
    assert _as_risk_literal("high") == "high"
    assert _as_risk_literal("oops") is None

    assert _has_cache_entry_container_shape({}) is False
    assert (
        _has_cache_entry_container_shape(
            {
                "stat": {"mtime_ns": 1, "size": 1},
                "units": 1,
                "blocks": [],
                "segments": [],
            }
        )
        is False
    )
    assert (
        _has_cache_entry_container_shape(
            {
                "stat": {"mtime_ns": 1, "size": 1},
                "units": [],
                "blocks": 1,
                "segments": [],
            }
        )
        is False
    )
    assert (
        _has_cache_entry_container_shape(
            {
                "stat": 1,
                "units": [],
                "blocks": [],
                "segments": [],
            }
        )
        is False
    )
    assert (
        _has_cache_entry_container_shape(
            {
                "stat": {"mtime_ns": 1, "size": 1},
                "units": [],
                "blocks": [],
                "segments": 1,
            }
        )
        is False
    )
    assert _is_dead_candidate_dict("bad") is False
    assert (
        _is_dead_candidate_dict(
            {
                "qualname": "pkg:dead",
                "local_name": "dead",
                "filepath": "a.py",
                "kind": "function",
                "start_line": 1,
                "end_line": 2,
            }
        )
        is True
    )


def test_cache_as_file_stat_dict_flaky_mapping() -> None:
    class _FlakyDict(dict[str, object]):
        def __init__(self) -> None:
            super().__init__()
            self._calls = 0

        def get(self, key: str, default: object = None) -> object:
            self._calls += 1
            if self._calls <= 2:
                return 1
            return "not-int"

    assert _as_file_stat_dict(_FlakyDict()) is None


def test_cache_decode_structural_invalid_rows() -> None:
    assert _decode_wire_structural_findings_optional({"sf": "bad"}) is None
    assert _decode_wire_structural_findings_optional({"sf": [["broken"]]}) is None

    assert _decode_wire_structural_group("bad") is None
    assert _decode_wire_structural_group(["kind", "key", [], "bad-items"]) is None
    assert _decode_wire_structural_group(["kind", "key", [], [["q", "x", 1]]]) is None

    assert _decode_wire_structural_signature("bad") is None
    assert _decode_wire_structural_signature([["k"]]) is None
    assert _decode_wire_structural_signature([[1, "v"]]) is None

    assert _decode_wire_structural_occurrence("bad") is None
    assert _decode_wire_structural_occurrence(["q", "x", 1]) is None

    assert _decode_wire_unit(["q", 1, 2], "a.py") is None
    assert (
        _decode_wire_unit([1, 1, 2, 1, 1, "fp", "1-19", 1, 0, "low", "rh"], "a.py")
        is None
    )


def test_cache_decode_wire_file_entry_with_invalid_structural() -> None:
    wire_entry = {
        "st": [1, 2],
        "u": [],
        "b": [],
        "s": [],
        "cm": [],
        "md": [],
        "dc": [],
        "rn": [],
        "in": [],
        "cn": [],
        "cc": [],
        "sf": "invalid",
    }
    assert _decode_wire_file_entry(wire_entry, "a.py") is None


def test_cache_get_file_entry_canonicalization_paths(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json", root=tmp_path)
    filepath = str((tmp_path / "a.py").resolve())

    cast(dict[str, object], cache.data["files"])[filepath] = {
        "stat": {"mtime_ns": 1, "size": 1},
        "units": 1,
        "blocks": [],
        "segments": [],
    }
    cache._canonical_runtime_paths.add(filepath)
    assert cache.get_file_entry(filepath) is None
    assert filepath not in cache._canonical_runtime_paths

    cast(dict[str, object], cache.data["files"])[filepath] = {
        "stat": {"mtime_ns": 1, "size": 1},
        "units": [
            {
                "qualname": "q",
                "filepath": filepath,
                "start_line": 1,
                "end_line": 2,
                "loc": 1,
                "stmt_count": 1,
                "fingerprint": "fp",
                "loc_bucket": "1-19",
                "cyclomatic_complexity": 1,
                "nesting_depth": 0,
                "risk": "low",
                "raw_hash": "rh",
            }
        ],
        "blocks": [
            {
                "block_hash": "bh",
                "filepath": filepath,
                "qualname": "q",
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ],
        "segments": [
            {
                "segment_hash": "sh",
                "segment_sig": "ss",
                "filepath": filepath,
                "qualname": "q",
                "start_line": 1,
                "end_line": 2,
                "size": 2,
            }
        ],
        "class_metrics": [],
        "module_deps": [],
        "dead_candidates": [],
        "referenced_names": [],
        "import_names": [],
        "class_names": [],
        "structural_findings": [
            {
                "finding_kind": "duplicated_branches",
                "finding_key": "k",
                "signature": {"stmt_seq": "Expr,Return"},
                "items": [{"qualname": "q", "start": 1, "end": 2}],
            }
        ],
    }
    entry = cache.get_file_entry(filepath)
    assert entry is not None
    assert "structural_findings" in entry

    metric = ClassMetrics(
        qualname="pkg:Cls",
        filepath=filepath,
        start_line=1,
        end_line=10,
        cbo=11,
        lcom4=4,
        method_count=4,
        instance_var_count=1,
        risk_coupling="high",
        risk_cohesion="high",
        coupled_classes=("A", "B"),
    )
    dep = ModuleDep(source="pkg.a", target="pkg.b", import_type="import", line=3)
    dead = DeadCandidate(
        qualname="pkg:dead",
        local_name="dead",
        filepath=filepath,
        start_line=20,
        end_line=22,
        kind="function",
    )
    file_metrics = FileMetrics(
        class_metrics=(metric,),
        module_deps=(dep,),
        dead_candidates=(dead,),
        referenced_names=frozenset({"used"}),
        import_names=frozenset({"pkg.b"}),
        class_names=frozenset({"Cls"}),
    )
    cache.put_file_entry(
        filepath,
        {"mtime_ns": 1, "size": 1},
        [],
        [BlockUnit("bh", filepath, "q", 1, 2, 2)],
        [SegmentUnit("sh", "ss", filepath, "q", 1, 2, 2)],
        file_metrics=file_metrics,
    )


def test_pipeline_decode_cached_structural_group() -> None:
    decoded = pipeline._decode_cached_structural_finding_group(
        {
            "finding_kind": "duplicated_branches",
            "finding_key": "k",
            "signature": {"stmt_seq": "Expr,Return"},
            "items": [{"qualname": "pkg:q", "start": 1, "end": 2}],
        },
        "/repo/codeclone/codeclone/cache.py",
    )
    assert decoded.finding_key == "k"
    assert decoded.items[0].file_path.endswith("cache.py")


def test_pipeline_discover_uses_cached_metrics_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n", "utf-8")
    filepath = str(source)
    stat = {"mtime_ns": 1, "size": 1}
    cached_entry: dict[str, object] = {
        "stat": stat,
        "units": [],
        "blocks": [],
        "segments": [],
        "class_metrics": [
            {
                "qualname": "pkg:Cls",
                "filepath": filepath,
                "start_line": 1,
                "end_line": 10,
                "cbo": 11,
                "lcom4": 4,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "high",
                "risk_cohesion": "high",
                "coupled_classes": ["A", "B"],
            }
        ],
        "module_deps": [
            {"source": "pkg.a", "target": "pkg.b", "import_type": "import", "line": 3}
        ],
        "dead_candidates": [
            {
                "qualname": "pkg:dead",
                "local_name": "dead",
                "filepath": filepath,
                "start_line": 20,
                "end_line": 22,
                "kind": "function",
            }
        ],
        "referenced_names": ["used_name"],
        "import_names": [],
        "class_names": [],
        "source_stats": {"lines": 2, "functions": 1, "methods": 0, "classes": 0},
    }

    class _FakeCache:
        def get_file_entry(self, _path: str) -> dict[str, object]:
            return cached_entry

    boot = pipeline.BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(skip_metrics=False, min_loc=1, min_stmt=1, processes=1),
        output_paths=pipeline.OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    monkeypatch.setattr(pipeline, "iter_py_files", lambda _root: [filepath])
    monkeypatch.setattr(pipeline, "file_stat_signature", lambda _path: stat)

    discovered = pipeline.discover(boot=boot, cache=cast(Cache, _FakeCache()))
    assert discovered.cache_hits == 1
    assert len(discovered.cached_class_metrics) == 1
    assert len(discovered.cached_module_deps) == 1
    assert len(discovered.cached_dead_candidates) == 1
    assert "used_name" in discovered.cached_referenced_names


def test_pipeline_discover_missing_source_stats_forces_reprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n", "utf-8")
    filepath = str(source)
    stat = {"mtime_ns": 1, "size": 1}
    cached_entry: dict[str, object] = {
        "stat": stat,
        "units": [],
        "blocks": [],
        "segments": [],
        "class_metrics": [],
        "module_deps": [],
        "dead_candidates": [],
        "referenced_names": ["used_name"],
        "import_names": [],
        "class_names": [],
    }

    class _FakeCache:
        def get_file_entry(self, _path: str) -> dict[str, object]:
            return cached_entry

    boot = pipeline.BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(skip_metrics=False, min_loc=1, min_stmt=1, processes=1),
        output_paths=pipeline.OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    monkeypatch.setattr(pipeline, "iter_py_files", lambda _root: [filepath])
    monkeypatch.setattr(pipeline, "file_stat_signature", lambda _path: stat)

    discovered = pipeline.discover(boot=boot, cache=cast(Cache, _FakeCache()))
    assert discovered.cache_hits == 0
    assert discovered.files_to_process == (filepath,)


def test_pipeline_cached_source_stats_helper_invalid_shapes() -> None:
    assert pipeline._cache_entry_source_stats(cast(CacheEntry, {})) is None
    assert (
        pipeline._cache_entry_source_stats(
            cast(
                CacheEntry,
                {
                    "source_stats": {
                        "lines": 1,
                        "functions": 1,
                        "methods": -1,
                        "classes": 0,
                    }
                },
            )
        )
        is None
    )


def test_cli_metric_reason_parser_and_policy_context() -> None:
    assert cli._parse_metric_reason_entry(
        "New high-risk functions vs metrics baseline: 1."
    ) == ("new_high_risk_functions", "1")
    assert cli._parse_metric_reason_entry(
        "New high-coupling classes vs metrics baseline: 2."
    ) == ("new_high_coupling_classes", "2")
    assert cli._parse_metric_reason_entry(
        "New dependency cycles vs metrics baseline: 3."
    ) == ("new_dependency_cycles", "3")
    assert cli._parse_metric_reason_entry(
        "New dead code items vs metrics baseline: 4."
    ) == ("new_dead_code_items", "4")
    assert cli._parse_metric_reason_entry(
        "Health score regressed vs metrics baseline: delta=-7."
    ) == ("health_delta", "-7")
    assert cli._parse_metric_reason_entry(
        "Dependency cycles detected: 3 cycle(s)."
    ) == ("dependency_cycles", "3")
    assert cli._parse_metric_reason_entry(
        "Dead code detected (high confidence): 2 item(s)."
    ) == ("dead_code_items", "2")
    assert cli._parse_metric_reason_entry(
        "Complexity threshold exceeded: max=11, threshold=10."
    ) == ("complexity_max", "11 (threshold=10)")
    assert cli._parse_metric_reason_entry(
        "Coupling threshold exceeded: max=12, threshold=9."
    ) == ("coupling_max", "12 (threshold=9)")
    assert cli._parse_metric_reason_entry(
        "Cohesion threshold exceeded: max=13, threshold=8."
    ) == ("cohesion_max", "13 (threshold=8)")
    assert cli._parse_metric_reason_entry(
        "Health score below threshold: score=70, threshold=80."
    ) == ("health_score", "70 (threshold=80)")
    assert cli._parse_metric_reason_entry("custom reason.") == (
        "detail",
        "custom reason",
    )

    args = Namespace(
        ci=False,
        fail_on_new_metrics=True,
        fail_complexity=10,
        fail_coupling=9,
        fail_cohesion=8,
        fail_cycles=True,
        fail_dead_code=True,
        fail_health=80,
        fail_on_new=True,
        fail_threshold=5,
    )
    metrics_policy = cli._policy_context(args=args, gate_kind="metrics")
    assert "fail-on-new-metrics" in metrics_policy
    assert "fail-complexity=10" in metrics_policy
    assert "fail-coupling=9" in metrics_policy
    assert "fail-cohesion=8" in metrics_policy
    assert "fail-cycles" in metrics_policy
    assert "fail-dead-code" in metrics_policy
    assert "fail-health=80" in metrics_policy
    assert cli._policy_context(args=args, gate_kind="new-clones") == "fail-on-new"
    assert cli._policy_context(args=args, gate_kind="threshold") == "fail-threshold=5"
    args.fail_on_new = False
    args.fail_threshold = -1
    assert cli._policy_context(args=args, gate_kind="new-clones") == "custom"
    assert cli._policy_context(args=args, gate_kind="threshold") == "custom"


def test_cli_run_analysis_stages_handles_cache_save_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = Namespace(quiet=False, no_progress=False, skip_metrics=True)
    boot = pipeline.BootstrapResult(
        root=Path("."),
        config=NormalizationConfig(),
        args=args,
        output_paths=pipeline.OutputPaths(),
        cache_path=Path("cache.json"),
    )

    monkeypatch.setattr(
        cli,
        "discover",
        lambda **_kwargs: pipeline.DiscoveryResult(
            files_found=0,
            cache_hits=0,
            files_skipped=0,
            all_file_paths=(),
            cached_units=(),
            cached_blocks=(),
            cached_segments=(),
            cached_class_metrics=(),
            cached_module_deps=(),
            cached_dead_candidates=(),
            cached_referenced_names=frozenset(),
            files_to_process=(),
            skipped_warnings=(),
        ),
    )
    monkeypatch.setattr(
        cli,
        "process",
        lambda **_kwargs: pipeline.ProcessingResult(
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
        ),
    )
    monkeypatch.setattr(
        cli,
        "analyze",
        lambda **_kwargs: pipeline.AnalysisResult(
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
            structural_findings=(),
        ),
    )

    class _BadCache:
        load_warning: str | None = None

        def save(self) -> None:
            raise CacheError("boom")

    cli._run_analysis_stages(args=args, boot=boot, cache=cast(Cache, _BadCache()))
    cli.print_banner(root=None)
