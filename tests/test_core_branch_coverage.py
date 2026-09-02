# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from argparse import Namespace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import orjson
import pytest

import codeclone.core.discovery as core_discovery
import codeclone.core.entrypoints as entrypoints_mod
import codeclone.core.pipeline as core_pipeline
import codeclone.surfaces.cli.console as cli_console
import codeclone.surfaces.cli.workflow as cli
from codeclone.analysis.normalizer import NormalizationConfig
from codeclone.cache._validators import _is_dead_candidate_dict
from codeclone.cache._wire_decode import (
    _decode_content_binding,
    _decode_wire_file_entry,
    _decode_wire_structural_findings_optional,
    _decode_wire_structural_group,
    _decode_wire_structural_occurrence,
    _decode_wire_structural_signature,
    _decode_wire_unit,
)
from codeclone.cache._wire_encode import _encode_wire_file_entry
from codeclone.cache.entries import _as_risk_literal
from codeclone.cache.projection import (
    SegmentReportProjection,
    build_segment_report_projection,
    decode_segment_report_projection,
)
from codeclone.cache.reuse import binding_context_digest
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
    decode_cached_structural_finding_group,
)
from codeclone.core.entrypoints import collect_project_entrypoint_qualnames
from codeclone.core.pipeline import analyze
from codeclone.findings.clones.grouping import build_segment_groups
from codeclone.models import (
    BlockGroupItem,
    CacheDependentPayload,
    CacheEntryV3,
    CacheLaneVerdict,
    CacheNeutralPayload,
    CacheReuseDecision,
    ContentIdentityVerdict,
    DeadCandidate,
    DigestObject,
    FileStat,
    FoundationConfigInput,
    GitBlobIdentity,
    GitContentSnapshot,
    GitDirtyEntry,
    GitIndexEntryInput,
    GitStatusEntryInput,
    GitTrackedContent,
    GitWorkspaceSnapshot,
    ModuleDep,
    SemanticFileFacts,
    SourceStatsDict,
)
from codeclone.report.gates.reasons import policy_context
from tests._assertions import assert_contains_all
from tests._ast_metrics_helpers import (
    build_test_module_registry,
    extract_file_metrics,
    module_registry_context,
)
from tests.test_observation_contract import TEST_OBSERVATION_BUNDLE


def _source_digest_fixture(raw_source: bytes) -> DigestObject:
    return DigestObject(
        domain="codeclone.source-content.v1",
        algorithm="sha256",
        value=sha256(raw_source).hexdigest(),
    )


def _dead_candidate(
    qualname: str,
    *,
    kind: str = "function",
) -> DeadCandidate:
    module_path, _, local_name = qualname.partition(":")
    return DeadCandidate(
        qualname=qualname,
        local_name=local_name.rsplit(".", 1)[-1],
        filepath=f"{module_path.replace('.', '/')}.py",
        start_line=1,
        end_line=2,
        kind=cast(Literal["class", "function", "method"], kind),
    )


def test_cache_risk_and_shape_helpers() -> None:
    assert _as_risk_literal("low") == "low"
    assert _as_risk_literal("medium") == "medium"
    assert _as_risk_literal("high") == "high"
    assert _as_risk_literal("oops") is None

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


@pytest.mark.parametrize(
    "wire",
    [
        {},
        {"cb": "0", "gb": None},
        {"cb": "1", "gb": None, "sd": []},
        {"cb": "1", "gb": None, "sd": ["wrong", "sha256", "0" * 64]},
        {
            "cb": "1",
            "gb": None,
            "sd": ["codeclone.source-content.v1", "wrong", "0" * 64],
        },
        {
            "cb": "1",
            "gb": None,
            "sd": ["codeclone.source-content.v1", "sha256", "bad"],
        },
        {
            "cb": "1",
            "gb": "bad",
            "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
        },
        {
            "cb": "1",
            "gb": ["sha1"],
            "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
        },
        {
            "cb": "1",
            "gb": ["wrong", "1" * 40],
            "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
        },
        {
            "cb": "1",
            "gb": ["sha1", "bad"],
            "sd": ["codeclone.source-content.v1", "sha256", "0" * 64],
        },
    ],
)
def test_content_binding_wire_rejects_invalid_contracts(
    wire: dict[str, object],
) -> None:
    assert _decode_content_binding(wire) is None


def test_content_binding_wire_accepts_both_git_object_formats() -> None:
    digest_row = ["codeclone.source-content.v1", "sha256", "0" * 64]
    without_blob = _decode_content_binding({"cb": "1", "sd": digest_row, "gb": None})
    sha1 = _decode_content_binding(
        {"cb": "1", "sd": digest_row, "gb": ["sha1", "1" * 40]}
    )
    sha256_blob = _decode_content_binding(
        {"cb": "1", "sd": digest_row, "gb": ["sha256", "2" * 64]}
    )

    assert without_blob is not None and without_blob[1] is None
    assert sha1 is not None and sha1[1] == GitBlobIdentity(
        object_format="sha1", object_id="1" * 40
    )
    assert sha256_blob is not None and sha256_blob[1] == GitBlobIdentity(
        object_format="sha256", object_id="2" * 64
    )


def test_content_identity_models_reject_impossible_states(tmp_path: Path) -> None:
    assert (
        FoundationConfigInput.model_validate(
            {"baseline_scope_id": None}
        ).baseline_scope_id
        is None
    )
    with pytest.raises(ValueError, match="exactly two characters"):
        GitStatusEntryInput.model_validate({"status_xy": "?", "path": "module.py"})
    with pytest.raises(ValueError, match="path must be non-empty"):
        GitStatusEntryInput.model_validate({"status_xy": "??", "path": ""})
    with pytest.raises(ValueError, match="exactly one character"):
        GitIndexEntryInput.model_validate(
            {
                "tag": "HH",
                "mode": "100644",
                "object_id": "1" * 40,
                "stage": 0,
                "path": "module.py",
                "mtime_ns": 1,
                "size": 1,
                "flags": 0,
            }
        )
    with pytest.raises(ValueError, match="text fields must be non-empty"):
        GitIndexEntryInput.model_validate(
            {
                "tag": "H",
                "mode": "",
                "object_id": "1" * 40,
                "stage": 0,
                "path": "module.py",
                "mtime_ns": 1,
                "size": 1,
                "flags": 0,
            }
        )
    with pytest.raises(ValueError, match="sha256 digest"):
        DigestObject(
            domain="codeclone.source-content.v1",
            algorithm="sha256",
            value="not-a-digest",
        )
    with pytest.raises(ValueError, match="git object id"):
        GitBlobIdentity(object_format="sha1", object_id="0" * 64)
    with pytest.raises(ValueError, match="sorted and unique"):
        GitWorkspaceSnapshot(
            git_available=True,
            entries=(
                GitDirtyEntry(
                    path="z.py", status_xy="??", digest=None, digest_status="ok"
                ),
                GitDirtyEntry(
                    path="a.py", status_xy="??", digest=None, digest_status="ok"
                ),
            ),
        )
    with pytest.raises(ValueError, match="unavailable git snapshot"):
        GitContentSnapshot(
            root=str(tmp_path),
            git_available=False,
            object_format="sha1",
            tracked=(),
            dirty_paths=frozenset(),
            untracked_paths=frozenset(),
            index_ambiguous_paths=frozenset(),
            racy_paths=frozenset(),
        )
    digest = _source_digest_fixture(b"source")
    with pytest.raises(ValueError, match="sorted and unique"):
        GitContentSnapshot(
            root=str(tmp_path),
            git_available=True,
            object_format="sha1",
            tracked=(
                GitTrackedContent(
                    path="z.py",
                    blob=GitBlobIdentity(
                        object_format="sha1",
                        object_id="1" * 40,
                    ),
                    source_content_digest=digest,
                ),
                GitTrackedContent(
                    path="a.py",
                    blob=GitBlobIdentity(
                        object_format="sha1",
                        object_id="2" * 40,
                    ),
                    source_content_digest=digest,
                ),
            ),
            dirty_paths=frozenset(),
            untracked_paths=frozenset(),
            index_ambiguous_paths=frozenset(),
            racy_paths=frozenset(),
        )


def test_content_snapshot_binary_lookup_and_external_path(tmp_path: Path) -> None:
    digest = _source_digest_fixture(b"source")
    first = GitTrackedContent(
        path="a.py",
        blob=GitBlobIdentity(object_format="sha1", object_id="1" * 40),
        source_content_digest=digest,
    )
    last = GitTrackedContent(
        path="z.py",
        blob=GitBlobIdentity(object_format="sha1", object_id="2" * 40),
        source_content_digest=digest,
    )
    snapshot = GitContentSnapshot(
        root=str(tmp_path),
        git_available=True,
        object_format="sha1",
        tracked=(first, last),
        dirty_paths=frozenset(),
        untracked_paths=frozenset(),
        index_ambiguous_paths=frozenset(),
        racy_paths=frozenset(),
    )

    assert snapshot.tracked_content("a.py") == first
    assert snapshot.tracked_content("z.py") == last
    assert snapshot.tracked_content("m.py") is None
    assert snapshot.repository_path(tmp_path.parent / "outside.py") is None
    assert snapshot.tracked_content(tmp_path.parent / "outside.py") is None
    assert snapshot.fallback_reason(tmp_path.parent / "outside.py") == (
        "index_ambiguous"
    )


def test_cached_relationship_decoders_ignore_non_records() -> None:
    assert core_discovery._decode_cached_relationship_record({}) is None
    assert (
        core_discovery._decode_cached_function_relationship_facts(
            [{"source_qualname": 1, "relationships": []}]
        )
        == []
    )


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
    assert _decode_wire_file_entry(wire_entry, "a.py", analysed_filepath="a.py") is None


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
    assert _decode_wire_file_entry(wire_entry, "a.py", analysed_filepath="a.py") is None


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


def test_cache_encode_wire_file_entry_includes_rq() -> None:
    entry = CacheEntryV3(
        cache_content_binding_version="1",
        binding_context_digest=binding_context_digest(None),
        source_content_digest=_source_digest_fixture(b"source"),
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
            source_stats={"lines": 0, "functions": 0, "methods": 0, "classes": 0},
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
            referenced_qualnames=("pkg:b", "pkg:a", "pkg:a"),
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
    wire = _encode_wire_file_entry(entry)
    dependent = wire.get("d")
    assert isinstance(dependent, dict)
    assert dependent.get("rq") == ["pkg:a", "pkg:b"]


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

    def _must_not_run(_segment_groups: object) -> object:
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
        module_registry=module_registry_context(
            filepath="placeholder.py",
            module_name="placeholder",
        )[1],
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
    assert result.low_value_segment_groups == 7
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
        module_registry=module_registry_context(
            filepath="pkg/mod.py",
            module_name="pkg.mod",
        )[1],
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
        "unresolved_external_override": 0,
        "unreachable_statements": 0,
        "live_roots": 0,
    }


def test_pipeline_analyze_gates_block_group_facts_on_report_consumers() -> None:
    """Perf-ledger #3: block-group facts are built only for report consumers.

    The facts re-parse every clone-carrying source file, yet they are
    observable only through the report document. The gated call must skip the
    build entirely while leaving the block clone groups themselves untouched;
    the default keeps collect-everything behavior for every other caller.
    """

    boot = BootstrapResult(
        root=Path("."),
        config=NormalizationConfig(),
        args=Namespace(
            skip_metrics=True,
            skip_dependencies=True,
            skip_dead_code=True,
            min_loc=1,
            min_stmt=1,
            processes=1,
        ),
        output_paths=OutputPaths(),
        cache_path=Path("cache.json"),
    )
    block_hash = "|".join(("ab" * 32,) * 4)
    blocks = tuple(
        BlockGroupItem(
            block_hash=block_hash,
            filepath="pkg/mod.py",
            qualname=qualname,
            start_line=start_line,
            end_line=start_line + 24,
            size=25,
        )
        for qualname, start_line in (("pkg.mod:f", 1), ("pkg.mod:g", 40))
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
        module_registry=module_registry_context(
            filepath="pkg/mod.py",
            module_name="pkg.mod",
        )[1],
    )
    processing = ProcessingResult(
        units=(),
        blocks=cast("tuple[dict[str, object], ...]", blocks),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(),
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

    default = analyze(boot=boot, discovery=discovery, processing=processing)
    gated = analyze(
        boot=boot,
        discovery=discovery,
        processing=processing,
        collect_block_group_facts=False,
    )

    assert set(default.block_group_facts) == {block_hash}
    assert gated.block_group_facts == {}
    # The gate touches only the explain lane: group identity is unchanged.
    assert set(default.block_groups) == set(gated.block_groups) == {block_hash}
    assert default.block_clones_count == gated.block_clones_count == 1


def test_project_entrypoints_mark_exact_and_unique_layout_symbols_live(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project.scripts]
exact = "pkg.cli:main"
src-layout = "pkg.worker:run"
ambiguous = "pkg.dup:main"
invalid = "pkg.dynamic"

[project.gui-scripts]
gui = "pkg.gui:start [gui]"

[project.entry-points."codeclone.plugins"]
plugin = "pkg.plugins:Plugin"

[tool.poetry.scripts]
poetry-cli = "pkg.poetry:main"
""".strip(),
        "utf-8",
    )
    candidates = (
        _dead_candidate("pkg.cli:main"),
        _dead_candidate("src.pkg.worker:run"),
        _dead_candidate("pkg.gui:start"),
        _dead_candidate("pkg.plugins:Plugin", kind="class"),
        _dead_candidate("pkg.poetry:main"),
        _dead_candidate("src.pkg.dup:main"),
        _dead_candidate("vendor.pkg.dup:main"),
    )

    assert collect_project_entrypoint_qualnames(
        root=tmp_path,
        dead_candidates=candidates,
    ) == frozenset(
        {
            "pkg.cli:main",
            "src.pkg.worker:run",
            "pkg.gui:start",
            "pkg.plugins:Plugin",
            "pkg.poetry:main",
        }
    )


def test_export_roots_add_only_qualnames_nothing_else_holds_live() -> None:
    """The export-root helper must never re-emit an already-referenced qualname.

    ``__all__`` membership and the package ``__init__`` re-export chain are
    resolved upstream by the module walk, so exported functions and classes are
    already inside ``referenced_qualnames``. Returning them again would be a
    provable no-op: the result is unioned straight back into the set it came
    from. The helper's only real contribution is extending an exported class to
    its public methods.
    """
    api_module = "distillations.api"
    package_module = "distillations"
    registry = build_test_module_registry(
        root=Path(__file__).parent / "fixtures" / "liveness_policy"
    )
    module_deps = (
        ModuleDep(
            source=package_module,
            target=api_module,
            import_type="from_import",
            line=1,
            resolution="analyzed",
            # The names the package actually re-exported. The real walk always
            # supplies them for a ``from .api import X, Y`` (verified against
            # the liveness_policy fixture); the export rule reads exactly this.
            requested_names=("DocumentedService", "exported_function"),
        ),
        # A sibling module importing a NON-exported class: the class becomes
        # referenced without ever joining the package export chain.
        ModuleDep(
            source=f"{package_module}.internal_use",
            target=api_module,
            import_type="from_import",
            line=1,
            resolution="analyzed",
            requested_names=("InternalHelper",),
        ),
    )
    dead_candidates = (
        _dead_candidate(f"{api_module}:DocumentedService", kind="class"),
        _dead_candidate(f"{api_module}:DocumentedService.render", kind="method"),
        _dead_candidate(f"{api_module}:DocumentedService._hidden", kind="method"),
        _dead_candidate(f"{api_module}:exported_function"),
        _dead_candidate(f"{api_module}:internal_function"),
        _dead_candidate(f"{api_module}:InternalHelper", kind="class"),
        _dead_candidate(
            f"{api_module}:InternalHelper.never_called_public_method", kind="method"
        ),
    )
    # What the module walk already holds live: the export chain for the
    # exported pair, the sibling import for the internal helper.
    referenced_qualnames = frozenset(
        {
            f"{api_module}:DocumentedService",
            f"{api_module}:exported_function",
            f"{api_module}:InternalHelper",
        }
    )

    # No call site anywhere in this constructed population, so "already live"
    # is exactly the referenced set - which is what makes this the pin on the
    # export rule alone, with the call-site arm held at zero.
    already_live = entrypoints_mod.already_live_candidate_qualnames(
        dead_candidates=dead_candidates,
        referenced_names=frozenset(),
        referenced_qualnames=referenced_qualnames,
    )
    evidence = entrypoints_mod.collect_project_export_root_evidence(
        module_deps=module_deps,
        referenced_qualnames=referenced_qualnames,
        dead_candidates=dead_candidates,
        module_registry=registry,
        already_live_qualnames=already_live,
    )
    roots = entrypoints_mod.collect_project_export_root_qualnames(
        module_deps=module_deps,
        referenced_qualnames=referenced_qualnames,
        dead_candidates=dead_candidates,
        module_registry=registry,
        already_live_qualnames=already_live,
    )

    # Exactly the public method of the exported class, and nothing already held.
    assert roots == frozenset({f"{api_module}:DocumentedService.render"})
    assert roots.isdisjoint(referenced_qualnames)
    assert evidence == ((f"{api_module}:DocumentedService.render", "export_root"),)
    # A private method of an exported class is not a root.
    assert f"{api_module}:DocumentedService._hidden" not in roots
    # A non-exported sibling function is never rooted.
    assert f"{api_module}:internal_function" not in roots
    # Being referenced is not being exported: a class that only a sibling
    # module imports never extends liveness to its public methods.
    assert f"{api_module}:InternalHelper.never_called_public_method" not in roots


def test_project_entrypoints_ignore_invalid_metadata_shapes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project.scripts]
not-string = 42
bad-module = "pkg-dash.cli:main"
bad-local = "pkg.cli:bad-name"
valid = "pkg.valid:run"

[project.entry-points]
broken-group = "not a table"

[project.entry-points."codeclone.plugins"]
plugin = "pkg.plugins:Plugin"
invalid-plugin = "pkg.plugins"

[tool.poetry.scripts]
not-string = 1
poetry-cli = "pkg.poetry:main"
""".strip(),
        "utf-8",
    )
    candidates = (
        _dead_candidate("pkg.valid:run"),
        _dead_candidate("pkg.plugins:Plugin", kind="class"),
        _dead_candidate("pkg.poetry:main"),
    )

    assert collect_project_entrypoint_qualnames(
        root=tmp_path,
        dead_candidates=candidates,
    ) == frozenset(
        {
            "pkg.valid:run",
            "pkg.plugins:Plugin",
            "pkg.poetry:main",
        }
    )


def test_project_entrypoint_loader_handles_invalid_toml_and_legacy_tomli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_path = tmp_path / "missing.toml"
    assert entrypoints_mod._load_toml_payload(missing_path) == {}

    invalid_path = tmp_path / "pyproject.toml"
    invalid_path.write_text("[project", "utf-8")
    assert entrypoints_mod._load_toml_payload(invalid_path) == {}

    original_resolve = Path.resolve
    escaped_path = tmp_path.parent / "escaped.toml"

    def _resolve_outside_repo(self: Path) -> Path:
        if self == invalid_path:
            return escaped_path
        return original_resolve(self)

    invalid_path.write_text(
        """
[project.scripts]
tool = "pkg.cli:main"
""".strip(),
        "utf-8",
    )
    with monkeypatch.context() as path_patch:
        path_patch.setattr(Path, "resolve", _resolve_outside_repo)
        assert entrypoints_mod._load_toml_payload(invalid_path) == {}

    invalid_path.write_text("", "utf-8")
    monkeypatch.setattr(
        entrypoints_mod,
        "sys",
        SimpleNamespace(version_info=(3, 10)),
    )

    def _missing_tomli(_name: str) -> object:
        raise ModuleNotFoundError("tomli")

    monkeypatch.setattr(
        entrypoints_mod,
        "importlib",
        SimpleNamespace(import_module=_missing_tomli),
    )
    assert entrypoints_mod._load_toml_payload(invalid_path) == {}

    class _NoLoad:
        load = None

    monkeypatch.setattr(
        entrypoints_mod,
        "importlib",
        SimpleNamespace(import_module=lambda _name: _NoLoad),
    )
    assert entrypoints_mod._load_toml_payload(invalid_path) == {}

    class _BadLoad:
        @staticmethod
        def load(_file: object) -> object:
            raise ValueError("bad toml")

    monkeypatch.setattr(
        entrypoints_mod,
        "importlib",
        SimpleNamespace(import_module=lambda _name: _BadLoad),
    )
    assert entrypoints_mod._load_toml_payload(invalid_path) == {}

    class _GoodLoad:
        @staticmethod
        def load(_file: object) -> object:
            return {"project": {"scripts": {"tool": "pkg.cli:main"}}}

    monkeypatch.setattr(
        entrypoints_mod,
        "importlib",
        SimpleNamespace(import_module=lambda _name: _GoodLoad),
    )
    assert entrypoints_mod._load_toml_payload(invalid_path) == {
        "project": {"scripts": {"tool": "pkg.cli:main"}}
    }


def test_pipeline_analyze_uses_project_entrypoints_for_dead_code(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project.scripts]
tool = "pkg.cli:main"
""".strip(),
        "utf-8",
    )
    boot = BootstrapResult(
        root=tmp_path,
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
        cache_path=tmp_path / "cache.json",
    )
    discovery = DiscoveryResult(
        files_found=1,
        cache_hits=0,
        files_skipped=0,
        all_file_paths=("pkg/cli.py",),
        cached_units=(),
        cached_blocks=(),
        cached_segments=(),
        cached_class_metrics=(),
        cached_module_deps=(),
        cached_dead_candidates=(),
        cached_referenced_names=frozenset(),
        files_to_process=(),
        skipped_warnings=(),
        module_registry=module_registry_context(
            filepath="pkg/cli.py",
            module_name="pkg.cli",
        )[1],
    )
    processing = ProcessingResult(
        units=(),
        blocks=(),
        segments=(),
        class_metrics=(),
        module_deps=(),
        dead_candidates=(
            DeadCandidate(
                qualname="pkg.cli:main",
                local_name="main",
                filepath="pkg/cli.py",
                start_line=1,
                end_line=2,
                kind="function",
            ),
            DeadCandidate(
                qualname="pkg.cli:unused",
                local_name="unused",
                filepath="pkg/cli.py",
                start_line=4,
                end_line=5,
                kind="function",
            ),
        ),
        referenced_names=frozenset(),
        files_analyzed=1,
        files_skipped=0,
        analyzed_lines=5,
        analyzed_functions=2,
        analyzed_methods=0,
        analyzed_classes=0,
        failed_files=(),
        source_read_failures=(),
    )

    result = analyze(boot=boot, discovery=discovery, processing=processing)

    assert result.project_metrics is not None
    assert [item.qualname for item in result.project_metrics.dead_code] == [
        "pkg.cli:unused"
    ]


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
    decision: CacheReuseDecision,
) -> DiscoveryResult:
    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n", "utf-8")
    filepath = str(source)
    stat = FileStat(mtime_ns=1, size=1)
    cache_entry = CacheEntryV3(
        cache_content_binding_version="1",
        binding_context_digest=binding_context_digest(None),
        source_content_digest=_source_digest_fixture(source.read_bytes()),
        git_blob_id_at_write=None,
        stat=stat,
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
            source_stats={"lines": 2, "functions": 1, "methods": 0, "classes": 0},
            units=(),
            blocks=(),
            segments=(),
            semantic_facts=SemanticFileFacts(),
        ),
        module_dependent=CacheDependentPayload(
            class_metrics=(
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
                },
            ),
            module_deps=(
                {
                    "source": "pkg.a",
                    "target": "pkg.b",
                    "import_type": "import",
                    "line": 3,
                    "resolution": "analyzed",
                    "mechanism": "static",
                    "inventory_expansion": False,
                    "level": 0,
                    "requested_module": "pkg.b",
                    "requested_names": [],
                    "candidate_targets": ["pkg.b"],
                },
            ),
            dead_candidates=(
                {
                    "qualname": "pkg:dead",
                    "local_name": "dead",
                    "filepath": "placeholder",
                    "start_line": 20,
                    "end_line": 22,
                    "kind": "function",
                },
            ),
            referenced_names=("used_name",),
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

    class _FakeCache:
        def bind_git_content_snapshot(self, _snapshot: object) -> None:
            return None

        def bind_module_registry(self, _registry: object) -> None:
            return None

        def get_file_entry(self, _path: str) -> CacheEntryV3:
            return cache_entry

        def reuse_decision(
            self,
            *,
            content: ContentIdentityVerdict,
            entry: CacheEntryV3,
            runtime_path: str,
            required_clone_channels: tuple[str, ...] = (),
        ) -> CacheReuseDecision:
            del entry, runtime_path, required_clone_channels
            if not content.hit:
                miss = CacheLaneVerdict(hit=False, reason="content_miss")
                return CacheReuseDecision(neutral=miss, dependent=miss)
            return decision

        def prune_file_entries(self, existing_filepaths: object) -> int:
            return 0

    boot = BootstrapResult(
        root=tmp_path,
        config=NormalizationConfig(),
        args=Namespace(skip_metrics=False, min_loc=1, min_stmt=1, processes=1),
        output_paths=OutputPaths(),
        cache_path=tmp_path / "cache.json",
    )

    def _discover_python_files(
        _root: str,
        *,
        hard_excludes: tuple[str, ...],
        max_files: int,
    ) -> tuple[tuple[str, ...], int, tuple[str, ...]]:
        del hard_excludes, max_files
        return (filepath,), 0, ()

    monkeypatch.setattr(
        "codeclone.paths.module_identity.inventory.discover_python_files",
        _discover_python_files,
    )
    monkeypatch.setattr(core_discovery, "file_stat_signature", lambda _path: stat)
    return discover(boot=boot, cache=cast(Cache, _FakeCache()))


def test_discover_prunes_deleted_cache_entries(tmp_path: Path) -> None:
    live = tmp_path / "a.py"
    stale = tmp_path / "stale.py"
    live.write_text("def f():\n    return 1\n", "utf-8")

    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, root=tmp_path)
    cache.bind_module_registry(
        module_registry_context(
            filepath="a.py",
            module_name="a",
            inventory_modules=("stale",),
        )[1]
    )
    cache.put_file_entry(
        str(live),
        file_stat_signature(str(live)),
        [],
        [],
        [],
        source_content_digest=_source_digest_fixture(live.read_bytes()),
        source_stats=SourceStatsDict(lines=2, functions=1, methods=0, classes=0),
    )
    cache.put_file_entry(
        str(stale),
        {"mtime_ns": 1, "size": 1},
        [],
        [],
        [],
        source_content_digest=_source_digest_fixture(b"stale"),
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
    assert result.cache_hits == 0
    assert result.files_to_process == (str(live),)
    assert len(result.neutral_reuse_by_file) == 1
    assert str(stale) not in loaded.data["files"]

    loaded.save()

    reloaded = Cache(cache_path, root=tmp_path)
    reloaded.load()
    assert str(stale) not in reloaded.data["files"]


@pytest.mark.parametrize(
    ("decision", "expected_cache_hits", "expected_files_to_process"),
    [
        (
            CacheReuseDecision(
                neutral=CacheLaneVerdict(hit=True, reason="hit"),
                dependent=CacheLaneVerdict(hit=True, reason="hit"),
            ),
            1,
            (),
        ),
        (
            CacheReuseDecision(
                neutral=CacheLaneVerdict(hit=True, reason="hit"),
                dependent=CacheLaneVerdict(
                    hit=False,
                    reason="dependent_profile_mismatch",
                ),
            ),
            0,
            ("a.py",),
        ),
    ],
    ids=[
        "full-hit",
        "neutral-hit-dependent-miss",
    ],
)
def test_pipeline_discover_cache_admission_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: CacheReuseDecision,
    expected_cache_hits: int,
    expected_files_to_process: tuple[str, ...],
) -> None:
    discovered = _discover_with_single_cached_entry(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        decision=decision,
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


@pytest.mark.parametrize(
    "verdict",
    [
        ContentIdentityVerdict(
            hit=False,
            reason="blob_hit",
            git_fallback_reason=None,
            digest_verify_cost_us=0,
            stat_fast_reject=False,
        ),
        ContentIdentityVerdict(
            hit=False,
            reason="digest_hit",
            git_fallback_reason="dirty",
            digest_verify_cost_us=1,
            stat_fast_reject=False,
        ),
        ContentIdentityVerdict(
            hit=False,
            reason="digest_miss",
            git_fallback_reason="git_unavailable",
            digest_verify_cost_us=2,
            stat_fast_reject=False,
        ),
        ContentIdentityVerdict(
            hit=False,
            reason="digest_miss",
            git_fallback_reason="index_ambiguous",
            digest_verify_cost_us=3,
            stat_fast_reject=False,
        ),
        ContentIdentityVerdict(
            hit=False,
            reason="digest_miss",
            git_fallback_reason="racy",
            digest_verify_cost_us=4,
            stat_fast_reject=False,
        ),
        ContentIdentityVerdict(
            hit=False,
            reason="digest_miss",
            git_fallback_reason="untracked",
            digest_verify_cost_us=5,
            stat_fast_reject=True,
        ),
    ],
)
def test_discover_records_each_content_identity_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verdict: ContentIdentityVerdict,
) -> None:
    monkeypatch.setattr(
        core_discovery,
        "prove_cached_source_identity",
        lambda **_kwargs: verdict,
    )
    discovered = _discover_with_single_cached_entry(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        decision=CacheReuseDecision(
            neutral=CacheLaneVerdict(hit=True, reason="hit"),
            dependent=CacheLaneVerdict(hit=True, reason="hit"),
        ),
    )

    assert discovered.cache_hits == 0
    assert tuple(Path(path).name for path in discovered.files_to_process) == ("a.py",)


def test_cli_metric_reason_parser_and_policy_context() -> None:
    assert cli_console._parse_metric_reason_entry(
        "New high-risk functions vs metrics baseline: 1."
    ) == ("new_high_risk_functions", "1")
    assert cli_console._parse_metric_reason_entry(
        "New high-coupling classes vs metrics baseline: 2."
    ) == ("new_high_coupling_classes", "2")
    assert cli_console._parse_metric_reason_entry(
        "New import-time dependency cycles vs metrics baseline: 3."
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
        "Import-time dependency cycles detected: 3 cycle(s)."
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
            module_registry=module_registry_context(
                filepath="placeholder.py",
                module_name="placeholder",
            )[1],
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
            structural_findings=(),
        ),
    )

    class _BadCache:
        load_warning: str | None = None

        def save(self) -> None:
            raise CacheError("boom")

    cli._run_analysis_stages(args=args, boot=boot, cache=cast(Cache, _BadCache()))
    cli.print_banner(root=None)


def test_export_root_extension_stops_at_the_package_export_chain() -> None:
    """A class extends liveness to its methods only if the package exported IT.

    The unit contract above proves the rule on constructed inputs; this proves
    it on the real fixture facts, so the two cannot drift apart. The
    discriminating ground-truth pair is ROOT-DOCUMENTED | NEG-EXPORT-METHOD
    (and its rename twin): both classes live in the same module the package
    ``__init__`` imports, and both sit in ``referenced_qualnames`` - the
    exported one through the package re-export, the other through a sibling
    module's import. A rule keyed on "referenced class in an imported module"
    roots both; only a rule keyed on the re-exported NAMES roots one and leaves
    the other dead. Both directions are asserted, because under-rooting a
    genuinely exported class is the symmetric defect.
    """
    fixture_root = Path(__file__).parent / "fixtures" / "liveness_policy"
    ground_truth = orjson.loads((fixture_root / "ground_truth.json").read_bytes())
    registry = build_test_module_registry(root=fixture_root)

    for package_module in ("distillations", "distillations_renamed"):
        api_path = f"{package_module}/api.py"
        api_module = f"{package_module}.api"
        method_cases = {
            case["symbol"]: case["expected"]
            for case in ground_truth["cases"]
            if case["path"] == api_path and "." in case["symbol"]
        }
        # One exported class method, one non-exported class method.
        assert len(method_cases) == 2

        module_deps: list[ModuleDep] = []
        referenced_qualnames: set[str] = set()
        referenced_names: set[str] = set()
        dead_candidates: list[DeadCandidate] = []
        for relative_path in (
            f"{package_module}/__init__.py",
            api_path,
            f"{package_module}/internal_use.py",
        ):
            metrics = extract_file_metrics(
                source=(fixture_root / relative_path).read_text(),
                filepath=relative_path,
                module_registry=registry,
            )
            module_deps.extend(metrics.module_deps)
            referenced_qualnames |= set(metrics.referenced_qualnames)
            referenced_names |= set(metrics.referenced_names)
            dead_candidates.extend(metrics.dead_candidates)

        # The premise of the discrimination: BOTH owning classes are referenced.
        assert {
            f"{api_module}:{symbol.partition('.')[0]}" for symbol in method_cases
        } <= referenced_qualnames

        rooted = dict(
            entrypoints_mod.collect_project_export_root_evidence(
                module_deps=tuple(module_deps),
                referenced_qualnames=frozenset(referenced_qualnames),
                dead_candidates=tuple(dead_candidates),
                module_registry=registry,
                already_live_qualnames=(
                    entrypoints_mod.already_live_candidate_qualnames(
                        dead_candidates=tuple(dead_candidates),
                        referenced_names=frozenset(referenced_names),
                        referenced_qualnames=frozenset(referenced_qualnames),
                    )
                ),
            )
        )

        assert {
            symbol: f"{api_module}:{symbol}" in rooted for symbol in method_cases
        } == {symbol: expected["live"] for symbol, expected in method_cases.items()}
        assert set(rooted.values()) == {"export_root"}


def test_load_cached_metrics_extended_skips_unparseable_rows() -> None:
    import codeclone.core.discovery_cache as dc
    from codeclone.models import CacheEntryV3

    dependent = SimpleNamespace(
        class_metrics=[],
        module_deps=[{}],
        dead_candidates=[],
        referenced_names=["ref"],
        referenced_qualnames=["pkg.mod:ref"],
        security_surfaces=[],
        runtime_reachability=[{"target_kind": "not-a-kind"}],
        typing_coverage=None,
        docstring_coverage=None,
        api_surface={
            "module": "pkg.mod",
            "filepath": "pkg/mod.py",
            "all_declared": "not-a-list",
            "symbols": [],
        },
        structural_findings=None,
    )
    entry = SimpleNamespace(module_dependent=dependent)
    (
        class_metrics,
        module_deps,
        dead_candidates,
        referenced_names,
        _referenced_qualnames,
        _typing_cov,
        _doc_cov,
        api_surface,
        reachability,
        security,
    ) = dc.load_cached_metrics_extended(
        cast(CacheEntryV3, entry), filepath="pkg/mod.py"
    )
    assert class_metrics == ()
    assert module_deps == ()
    assert dead_candidates == ()
    assert referenced_names == frozenset({"ref"})
    assert api_surface is None
    assert reachability == ()
    assert security == ()


def test_usable_cached_source_stats_requires_present_sections() -> None:
    import codeclone.core.discovery_cache as dc
    from codeclone.models import CacheEntryV3

    entry_no_metrics = SimpleNamespace(module_dependent=None)
    assert (
        dc.usable_cached_source_stats(
            cast(CacheEntryV3, entry_no_metrics),
            skip_metrics=False,
            collect_structural_findings=False,
        )
        is None
    )

    entry_no_structural = SimpleNamespace(
        module_dependent=SimpleNamespace(structural_findings=None)
    )
    assert (
        dc.usable_cached_source_stats(
            cast(CacheEntryV3, entry_no_structural),
            skip_metrics=True,
            collect_structural_findings=True,
        )
        is None
    )


def test_live_root_reason_narrows_only_known_values() -> None:
    import codeclone.core.discovery_cache as dc

    assert dc._live_root_reason("export_root") == "export_root"
    assert dc._live_root_reason("external_decorator") == "external_decorator"
    assert dc._live_root_reason("invented_reason") is None


def test_artifact_dead_items_rejects_mixed_tuples() -> None:
    from codeclone.models import DeadItem

    real = DeadItem(
        qualname="pkg.mod:gone",
        filepath="pkg/mod.py",
        start_line=1,
        end_line=2,
        kind="function",
        confidence="high",
    )
    default = (real,)
    assert core_pipeline._artifact_dead_items((real,), ()) == (real,)
    assert core_pipeline._artifact_dead_items((real, "poison"), default) == default
    assert core_pipeline._artifact_dead_items("not-a-tuple", default) == default


def _observation_failure_pipeline(
    tmp_path: Path,
) -> tuple[object, object, object]:
    from tests._pipeline_fixtures import analysis_boot, discover_and_process

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", "utf-8")
    (package / "mod.py").write_text("def f():\n    return 1\n", "utf-8")
    boot = analysis_boot(tmp_path, min_loc=1, min_stmt=1, skip_metrics=False)
    _cache, discovery, processing = discover_and_process(
        boot, tmp_path / "cache.json", root=tmp_path, warm=False
    )
    return boot, discovery, processing


def test_pipeline_observation_bundle_contract_failure_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot, discovery, processing = _observation_failure_pipeline(tmp_path)

    def _raise_bundle(*args: object, **kwargs: object) -> object:
        raise core_pipeline.ObservationContractError(  # type: ignore[attr-defined]
            "bundle contract broke"
        )

    monkeypatch.setattr(core_pipeline, "build_observation_bundle", _raise_bundle)
    with pytest.raises(
        core_pipeline.ObservationContractError,  # type: ignore[attr-defined]
        match="bundle contract broke",
    ):
        core_pipeline.analyze(
            boot=boot,  # type: ignore[arg-type]
            discovery=discovery,  # type: ignore[arg-type]
            processing=processing,  # type: ignore[arg-type]
        )


def test_pipeline_observation_lanes_contract_failure_propagates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot, discovery, processing = _observation_failure_pipeline(tmp_path)

    def _raise_lanes(*args: object, **kwargs: object) -> object:
        raise core_pipeline.ObservationContractError(  # type: ignore[attr-defined]
            "lanes contract broke"
        )

    monkeypatch.setattr(core_pipeline, "build_observation_lanes", _raise_lanes)
    with pytest.raises(
        core_pipeline.ObservationContractError,  # type: ignore[attr-defined]
        match="lanes contract broke",
    ):
        core_pipeline.analyze(
            boot=boot,  # type: ignore[arg-type]
            discovery=discovery,  # type: ignore[arg-type]
            processing=processing,  # type: ignore[arg-type]
        )


def test_cached_relationship_record_rejects_unknown_kind() -> None:
    row = {
        "relation_kind": "telepathy",
        "resolution_status": "resolved",
        "origin_lane": "production",
        "source_qualname": "pkg.mod:caller",
        "target_qualname": "pkg.mod:callee",
        "path": "pkg/mod.py",
        "line": 3,
        "expression": None,
        "resolution_rule": "direct",
    }
    assert core_discovery._decode_cached_relationship_record(row) is None


def test_cli_metric_reason_parser_covers_authority_and_unresolved_rows() -> None:
    assert cli_console._parse_metric_reason_entry(
        "Semantic authority violations detected: 2."
    ) == ("authority_violations", "2")
    assert cli_console._parse_metric_reason_entry(
        "Unresolved dead-code overrides (--fail-on-unresolved-dead-code): 3 item(s)."
    ) == ("unresolved_external_override", "3")
