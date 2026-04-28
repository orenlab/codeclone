# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from hashlib import sha256
from pathlib import Path
from typing import cast

import orjson
import pytest

import codeclone.core.discovery as core_discovery
import codeclone.core.pipeline as core_pipeline
import codeclone.surfaces.cli.console as cli_console
import codeclone.surfaces.cli.workflow as cli
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.cache._canonicalize import (
    _as_file_stat_dict,
    _has_cache_entry_container_shape,
)
from codeclone.cache._validators import _is_dead_candidate_dict
from codeclone.cache._wire_decode import (
    _decode_wire_file_entry,
    _decode_wire_structural_findings_optional,
    _decode_wire_structural_group,
    _decode_wire_structural_occurrence,
    _decode_wire_structural_signature,
    _decode_wire_unit,
)
from codeclone.cache._wire_encode import _encode_wire_file_entry
from codeclone.cache.entries import CacheEntry, SourceStatsDict, _as_risk_literal
from codeclone.cache.projection import (
    SegmentReportProjection,
    build_segment_report_projection,
    decode_segment_report_projection,
)
from codeclone.cache.store import Cache, file_stat_signature
from codeclone.contracts.errors import CacheError
from codeclone.core._types import (
    AnalysisResult,
    BootstrapResult,
    DiscoveryResult,
    OutputPaths,
    ProcessingResult,
    _coerce_segment_report_projection,
    _segment_groups_digest,
)
from codeclone.core.discovery import discover
from codeclone.core.discovery_cache import (
    _cache_entry_source_stats,
    decode_cached_structural_finding_group,
)
from codeclone.core.pipeline import analyze
from codeclone.findings.clones.grouping import build_segment_groups
from codeclone.models import (
    BlockUnit,
    ClassMetrics,
    DeadCandidate,
    FileMetrics,
    ModuleDep,
    SegmentUnit,
)
from codeclone.report.gates.reasons import policy_context
from tests._assertions import assert_contains_all


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


def test_cache_decode_wire_file_entry_with_invalid_referenced_qualnames() -> None:
    wire_entry = {
        "st": [1, 2],
        "u": [],
        "b": [],
        "s": [],
        "cm": [],
        "md": [],
        "dc": [],
        "rn": [],
        "rq": "invalid",
        "in": [],
        "cn": [],
        "cc": [],
    }
    assert _decode_wire_file_entry(wire_entry, "a.py") is None


def test_cache_decode_wire_unit_extended_invalid_shape() -> None:
    row = [
        "pkg:a",
        1,
        2,
        10,
        3,
        "fp",
        "1-19",
        1,
        0,
        "low",
        "raw",
        1,
        "return_only",
        0,
        123,  # invalid terminal_kind -> must be str
        "none",
        "none",
    ]
    assert _decode_wire_unit(row, "a.py") is None


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
        "referenced_qualnames": [],
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


def test_cache_encode_wire_file_entry_includes_rq() -> None:
    entry = cast(
        CacheEntry,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": [],
            "class_metrics": [],
            "module_deps": [],
            "dead_candidates": [],
            "referenced_names": [],
            "referenced_qualnames": ["pkg:b", "pkg:a", "pkg:a"],
            "import_names": [],
            "class_names": [],
        },
    )
    wire = _encode_wire_file_entry(entry)
    assert wire.get("rq") == ["pkg:a", "pkg:b"]


def test_cache_segment_report_projection_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    root = tmp_path.resolve()
    cache = Cache(cache_path, root=root)

    segment_file = str((tmp_path / "pkg" / "a.py").resolve())
    cache.segment_report_projection = build_segment_report_projection(
        digest="digest-1",
        suppressed=3,
        groups={
            "seg-group": [
                {
                    "segment_hash": "h1",
                    "segment_sig": "s1",
                    "filepath": segment_file,
                    "qualname": "pkg.a:f",
                    "start_line": 10,
                    "end_line": 20,
                    "size": 11,
                }
            ]
        },
    )
    cache.save()

    loaded = Cache(cache_path, root=root)
    loaded.load()
    projection = loaded.segment_report_projection
    assert projection is not None
    assert projection["digest"] == "digest-1"
    assert projection["suppressed"] == 3
    item = projection["groups"]["seg-group"][0]
    assert item["filepath"] == segment_file
    assert item["qualname"] == "pkg.a:f"
    assert item["segment_hash"] == "h1"


def test_cache_segment_report_projection_filters_invalid_items(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json", root=tmp_path.resolve())
    cache.segment_report_projection = build_segment_report_projection(
        digest="d",
        suppressed=1,
        groups={
            "invalid_only": [
                {
                    "segment_hash": "h",
                    "segment_sig": "s",
                    "filepath": "a.py",
                    "qualname": "q",
                    "start_line": "x",  # invalid int
                    "end_line": 2,
                    "size": 2,
                }
            ],
            "valid": [
                {
                    "segment_hash": "h2",
                    "segment_sig": "s2",
                    "filepath": "a.py",
                    "qualname": "q",
                    "start_line": 1,
                    "end_line": 2,
                    "size": 2,
                }
            ],
        },
    )
    projection = cache.segment_report_projection
    assert projection is not None
    assert "invalid_only" not in projection["groups"]
    assert "valid" in projection["groups"]


def test_cache_decode_segment_projection_invalid_shapes(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json", root=tmp_path.resolve())
    assert (
        decode_segment_report_projection(
            {"d": "x", "s": 0, "g": "bad"},
            root=cache.root,
        )
        is None
    )
    assert (
        decode_segment_report_projection(
            {"d": "x", "s": 0, "g": [["k"]]},
            root=cache.root,
        )
        is None
    )
    assert (
        decode_segment_report_projection(
            {"d": "x", "s": 0, "g": [[1, []]]},
            root=cache.root,
        )
        is None
    )
    assert (
        decode_segment_report_projection(
            {"d": "x", "s": 0, "g": [["k", ["bad-item"]]]},
            root=cache.root,
        )
        is None
    )
    assert (
        decode_segment_report_projection(
            {
                "d": "x",
                "s": 0,
                "g": [["k", [["a.py", "q", 1, 2, 3, "h", None]]]],
            },
            root=cache.root,
        )
        is None
    )


def test_pipeline_analyze_uses_cached_segment_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seg_item_a = {
        "segment_hash": "seg-hash",
        "segment_sig": "seg-sig",
        "filepath": "/tmp/a.py",
        "qualname": "pkg.a:f",
        "start_line": 10,
        "end_line": 15,
        "size": 6,
    }
    seg_item_b = {
        "segment_hash": "seg-hash",
        "segment_sig": "seg-sig",
        "filepath": "/tmp/a.py",
        "qualname": "pkg.a:f",
        "start_line": 20,
        "end_line": 25,
        "size": 6,
    }
    raw_groups = build_segment_groups((seg_item_a, seg_item_b))
    digest = _segment_groups_digest(raw_groups)
    cached_projection = {
        "digest": digest,
        "suppressed": 7,
        "groups": {
            "seg-hash|pkg.a:f": [
                {
                    "segment_hash": "seg-hash",
                    "segment_sig": "seg-sig",
                    "filepath": "/tmp/a.py",
                    "qualname": "pkg.a:f",
                    "start_line": 10,
                    "end_line": 25,
                    "size": 16,
                }
            ]
        },
    }

    expected_payload = orjson.dumps(
        (
            (
                "seg-hash|pkg.a:f",
                (
                    ("/tmp/a.py", "pkg.a:f", 10, 15, 6, "seg-hash", "seg-sig"),
                    ("/tmp/a.py", "pkg.a:f", 20, 25, 6, "seg-hash", "seg-sig"),
                ),
            ),
        ),
        option=orjson.OPT_SORT_KEYS,
    )
    assert digest == sha256(expected_payload).hexdigest()

    def _must_not_run(
        _segment_groups: object,
    ) -> tuple[dict[str, list[dict[str, object]]], int]:
        raise AssertionError("prepare_segment_report_groups must not be called")

    monkeypatch.setattr(core_pipeline, "prepare_segment_report_groups", _must_not_run)

    boot = BootstrapResult(
        root=Path("."),
        config=NormalizationConfig(),
        args=Namespace(
            skip_metrics=True,
            skip_dependencies=False,
            skip_dead_code=False,
            min_loc=1,
            min_stmt=1,
            processes=1,
        ),
        output_paths=OutputPaths(),
        cache_path=Path("cache.json"),
    )
    discovery = DiscoveryResult(
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
        cached_segment_report_projection=cast(
            SegmentReportProjection, cached_projection
        ),
    )
    processing = ProcessingResult(
        units=(),
        blocks=(),
        segments=(seg_item_a, seg_item_b),
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

    result = analyze(boot=boot, discovery=discovery, processing=processing)
    assert result.suppressed_segment_groups == 7
    assert result.segment_groups == cached_projection["groups"]
    assert result.segment_groups_raw_digest == digest


def test_pipeline_coerce_segment_projection_invalid_shapes() -> None:
    assert _coerce_segment_report_projection("bad") is None
    assert (
        _coerce_segment_report_projection({"digest": 1, "suppressed": 0, "groups": {}})
        is None
    )
    assert (
        _coerce_segment_report_projection(
            {"digest": "d", "suppressed": 0, "groups": {"k": "bad"}}
        )
        is None
    )

    assert (
        _coerce_segment_report_projection(
            {
                "digest": "d",
                "suppressed": 0,
                "groups": {"k": [{"segment_hash": "h", "segment_sig": "s"}]},
            }
        )
        is None
    )

    assert (
        _coerce_segment_report_projection(
            {
                "digest": "d",
                "suppressed": 0,
                "groups": {"k": ["bad-item"]},
            }
        )
        is None
    )


def test_pipeline_coerce_segment_projection_valid_group_items() -> None:
    projection = _coerce_segment_report_projection(
        {
            "digest": "digest",
            "suppressed": 2,
            "groups": {
                "sig-1": [
                    {
                        "segment_hash": "hash-1",
                        "segment_sig": "sig-1",
                        "filepath": "pkg/mod.py",
                        "qualname": "pkg.mod:run",
                        "start_line": 10,
                        "end_line": 16,
                        "size": 6,
                    }
                ]
            },
        }
    )

    assert projection == {
        "digest": "digest",
        "suppressed": 2,
        "groups": {
            "sig-1": [
                {
                    "segment_hash": "hash-1",
                    "segment_sig": "sig-1",
                    "filepath": "pkg/mod.py",
                    "qualname": "pkg.mod:run",
                    "start_line": 10,
                    "end_line": 16,
                    "size": 6,
                }
            ]
        },
    }


def test_pipeline_analyze_tracks_suppressed_dead_code_candidates() -> None:
    boot = BootstrapResult(
        root=Path("."),
        config=NormalizationConfig(),
        args=Namespace(
            skip_metrics=False,
            skip_dependencies=True,
            skip_dead_code=False,
            min_loc=1,
            min_stmt=1,
            processes=1,
        ),
        output_paths=OutputPaths(),
        cache_path=Path("cache.json"),
    )
    discovery = DiscoveryResult(
        files_found=1,
        cache_hits=0,
        files_skipped=0,
        all_file_paths=("pkg/mod.py",),
        cached_units=(),
        cached_blocks=(),
        cached_segments=(),
        cached_class_metrics=(),
        cached_module_deps=(),
        cached_dead_candidates=(),
        cached_referenced_names=frozenset(),
        files_to_process=(),
        skipped_warnings=(),
    )
    processing = ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(
            DeadCandidate(
                qualname="pkg.mod:runtime_hook",
                local_name="runtime_hook",
                filepath="pkg/mod.py",
                start_line=10,
                end_line=11,
                kind="function",
                suppressed_rules=("dead-code",),
            ),
        ),
        referenced_names=frozenset(),
        files_analyzed=1,
        files_skipped=0,
        analyzed_lines=1,
        analyzed_functions=1,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
    )

    result = analyze(boot=boot, discovery=discovery, processing=processing)
    assert result.project_metrics is not None
    assert result.project_metrics.dead_code == ()
    assert result.suppressed_dead_code_items == 1
    assert result.metrics_payload is not None
    dead_summary = cast(dict[str, object], result.metrics_payload["dead_code"])[
        "summary"
    ]
    assert dead_summary == {
        "total": 0,
        "critical": 0,
        "high_confidence": 0,
        "suppressed": 1,
    }


def test_pipeline_decode_cached_structural_group() -> None:
    decoded = decode_cached_structural_finding_group(
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


def _discover_with_single_cached_entry(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_entry: dict[str, object],
) -> DiscoveryResult:
    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n", "utf-8")
    filepath = str(source)
    stat = {"mtime_ns": 1, "size": 1}
    cache_entry = {"stat": stat, **cached_entry}

    class _FakeCache:
        def get_file_entry(self, _path: str) -> dict[str, object]:
            return cache_entry

        def prune_file_entries(self, existing_filepaths: object) -> int:
            return 0

    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(skip_metrics=False, min_loc=1, min_stmt=1, processes=1),
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )
    monkeypatch.setattr(core_discovery, "iter_py_files", lambda _root: [filepath])
    monkeypatch.setattr(core_discovery, "file_stat_signature", lambda _path: stat)
    return discover(boot=boot, cache=cast(Cache, _FakeCache()))


def test_discover_prunes_deleted_cache_entries(tmp_path: Path) -> None:
    live = tmp_path / "a.py"
    stale = tmp_path / "stale.py"
    live.write_text("def f():\n    return 1\n", "utf-8")

    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path)
    cache.put_file_entry(
        str(live),
        file_stat_signature(str(live)),
        [],
        [],
        [],
        source_stats=SourceStatsDict(lines=2, functions=1, methods=0, classes=0),
    )
    cache.put_file_entry(
        str(stale),
        {"mtime_ns": 1, "size": 1},
        [],
        [],
        [],
        source_stats=SourceStatsDict(lines=0, functions=0, methods=0, classes=0),
    )
    cache.save()

    loaded = Cache(cache_path, root=tmp_path)
    loaded.load()
    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(skip_metrics=False, min_loc=1, min_stmt=1, processes=1),
        output_paths=OutputPaths(),
        cache_path=cache_path,
    )

    result = discover(boot=boot, cache=loaded)

    assert result.files_found == 1
    assert result.cache_hits == 1
    assert result.files_to_process == ()
    assert str(stale) not in loaded.data["files"]

    loaded.save()

    reloaded = Cache(cache_path, root=tmp_path)
    reloaded.load()
    assert str(stale) not in reloaded.data["files"]


@pytest.mark.parametrize(
    ("cached_entry", "expected_cache_hits", "expected_files_to_process"),
    [
        (
            {
                "units": [],
                "blocks": [],
                "segments": [],
                "class_metrics": [
                    {
                        "qualname": "pkg:Cls",
                        "filepath": "placeholder",
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
                    {
                        "source": "pkg.a",
                        "target": "pkg.b",
                        "import_type": "import",
                        "line": 3,
                    }
                ],
                "dead_candidates": [
                    {
                        "qualname": "pkg:dead",
                        "local_name": "dead",
                        "filepath": "placeholder",
                        "start_line": 20,
                        "end_line": 22,
                        "kind": "function",
                    }
                ],
                "referenced_names": ["used_name"],
                "referenced_qualnames": [],
                "import_names": [],
                "class_names": [],
                "source_stats": {
                    "lines": 2,
                    "functions": 1,
                    "methods": 0,
                    "classes": 0,
                },
            },
            1,
            (),
        ),
        (
            {
                "units": [],
                "blocks": [],
                "segments": [],
                "class_metrics": [],
                "module_deps": [],
                "dead_candidates": [],
                "referenced_names": ["used_name"],
                "referenced_qualnames": [],
                "import_names": [],
                "class_names": [],
            },
            0,
            ("a.py",),
        ),
        (
            {
                "units": [],
                "blocks": [],
                "segments": [],
                "source_stats": {
                    "lines": 2,
                    "functions": 1,
                    "methods": 0,
                    "classes": 0,
                },
            },
            0,
            ("a.py",),
        ),
    ],
    ids=[
        "cached-metrics-hit",
        "missing-source-stats",
        "missing-metrics-sections",
    ],
)
def test_pipeline_discover_cache_admission_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cached_entry: dict[str, object],
    expected_cache_hits: int,
    expected_files_to_process: tuple[str, ...],
) -> None:
    discovered = _discover_with_single_cached_entry(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        cached_entry=cached_entry,
    )
    assert discovered.cache_hits == expected_cache_hits
    assert tuple(Path(path).name for path in discovered.files_to_process) == (
        expected_files_to_process
    )
    if expected_cache_hits == 1:
        assert len(discovered.cached_class_metrics) == 1
        assert len(discovered.cached_module_deps) == 1
        assert len(discovered.cached_dead_candidates) == 1
        assert "used_name" in discovered.cached_referenced_names


def test_pipeline_cached_source_stats_helper_invalid_shapes() -> None:
    assert _cache_entry_source_stats(cast(CacheEntry, {})) is None
    assert (
        _cache_entry_source_stats(
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
    assert cli_console._parse_metric_reason_entry(
        "New high-risk functions vs metrics baseline: 1."
    ) == ("new_high_risk_functions", "1")
    assert cli_console._parse_metric_reason_entry(
        "New high-coupling classes vs metrics baseline: 2."
    ) == ("new_high_coupling_classes", "2")
    assert cli_console._parse_metric_reason_entry(
        "New dependency cycles vs metrics baseline: 3."
    ) == ("new_dependency_cycles", "3")
    assert cli_console._parse_metric_reason_entry(
        "New dead code items vs metrics baseline: 4."
    ) == ("new_dead_code_items", "4")
    assert cli_console._parse_metric_reason_entry(
        "Health score regressed vs metrics baseline: delta=-7."
    ) == ("health_delta", "-7")
    assert cli_console._parse_metric_reason_entry(
        "Typing coverage regressed vs metrics baseline: "
        "params_delta=-2, returns_delta=-1."
    ) == ("typing_coverage_delta", "-2 (returns_delta=-1)")
    assert cli_console._parse_metric_reason_entry(
        "Docstring coverage regressed vs metrics baseline: delta=-3."
    ) == ("docstring_coverage_delta", "-3")
    assert cli_console._parse_metric_reason_entry(
        "Public API breaking changes vs metrics baseline: 5."
    ) == ("api_breaking_changes", "5")
    assert cli_console._parse_metric_reason_entry(
        "Coverage hotspots detected: hotspots=2, threshold=50."
    ) == ("coverage_hotspots", "2 (threshold=50)")
    assert cli_console._parse_metric_reason_entry(
        "Dependency cycles detected: 3 cycle(s)."
    ) == ("dependency_cycles", "3")
    assert cli_console._parse_metric_reason_entry(
        "Dead code detected (high confidence): 2 item(s)."
    ) == ("dead_code_items", "2")
    assert cli_console._parse_metric_reason_entry(
        "Complexity threshold exceeded: max=11, threshold=10."
    ) == ("complexity_max", "11 (threshold=10)")
    assert cli_console._parse_metric_reason_entry(
        "Coupling threshold exceeded: max=12, threshold=9."
    ) == ("coupling_max", "12 (threshold=9)")
    assert cli_console._parse_metric_reason_entry(
        "Cohesion threshold exceeded: max=13, threshold=8."
    ) == ("cohesion_max", "13 (threshold=8)")
    assert cli_console._parse_metric_reason_entry(
        "Health score below threshold: score=70, threshold=80."
    ) == ("health_score", "70 (threshold=80)")
    assert cli_console._parse_metric_reason_entry("custom reason.") == (
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
    metrics_policy = policy_context(args=args, gate_kind="metrics")
    assert_contains_all(
        metrics_policy,
        "fail-on-new-metrics",
        "fail-complexity=10",
        "fail-coupling=9",
        "fail-cohesion=8",
        "fail-cycles",
        "fail-dead-code",
        "fail-health=80",
    )
    assert policy_context(args=args, gate_kind="new-clones") == "fail-on-new"
    assert policy_context(args=args, gate_kind="threshold") == "fail-threshold=5"
    assert policy_context(args=args, gate_kind="unknown") == "custom"
    args.fail_on_new = False
    args.fail_threshold = -1
    assert policy_context(args=args, gate_kind="new-clones") == "custom"
    assert policy_context(args=args, gate_kind="threshold") == "custom"


def test_cli_run_analysis_stages_handles_cache_save_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = Namespace(quiet=False, no_progress=False, skip_metrics=True)
    boot = BootstrapResult(
        root=Path("."),
        config=NormalizationConfig(),
        args=args,
        output_paths=OutputPaths(),
        cache_path=Path("cache.json"),
    )

    monkeypatch.setattr(
        cli,
        "discover",
        lambda **_kwargs: DiscoveryResult(
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
        lambda **_kwargs: ProcessingResult(
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
        lambda **_kwargs: AnalysisResult(
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
        ),
    )

    class _BadCache:
        load_warning: str | None = None

        def save(self) -> None:
            raise CacheError("boom")

    cli._run_analysis_stages(args=args, boot=boot, cache=cast(Cache, _BadCache()))
    cli.print_banner(root=None)
