# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.cache.store as cache_store
from codeclone.cache._canonicalize import (
    _as_module_api_surface_dict,
    _as_module_docstring_coverage_dict,
    _as_module_typing_coverage_dict,
    _canonicalize_cache_entry,
    _has_cache_entry_container_shape,
)
from codeclone.cache._validators import (
    _is_api_param_spec_dict,
    _is_class_metrics_dict,
    _is_dead_candidate_dict,
    _is_module_api_surface_dict,
    _is_module_dep_dict,
    _is_public_symbol_dict,
    _is_security_surface_dict,
)
from codeclone.cache._wire_decode import (
    _decode_optional_wire_api_surface,
    _decode_optional_wire_module_ints,
    _decode_optional_wire_source_stats,
    _decode_wire_api_param_spec,
    _decode_wire_api_surface_symbol,
    _decode_wire_block,
    _decode_wire_class_metric,
    _decode_wire_dead_candidate,
    _decode_wire_file_entry,
    _decode_wire_file_sections,
    _decode_wire_module_dep,
    _decode_wire_name_sections,
    _decode_wire_security_surface,
    _decode_wire_segment,
    _decode_wire_unit,
)
from codeclone.cache._wire_encode import _encode_wire_file_entry
from codeclone.cache._wire_helpers import (
    _decode_optional_wire_coupled_classes,
    _decode_wire_int_fields,
    _decode_wire_qualname_span_size,
)
from codeclone.cache.entries import (
    CacheEntry,
    _as_security_surface_category,
    _as_security_surface_classification_mode,
    _as_security_surface_evidence_kind,
    _as_security_surface_location_scope,
    _block_dict_from_model,
    _segment_dict_from_model,
    _unit_dict_from_model,
)
from codeclone.cache.integrity import as_str_dict as _as_str_dict
from codeclone.cache.integrity import sign_cache_payload
from codeclone.cache.projection import (
    runtime_filepath_from_wire,
    wire_filepath_from_runtime,
)
from codeclone.cache.store import Cache, file_stat_signature
from codeclone.cache.versioning import CacheStatus, _as_analysis_profile, _resolve_root
from codeclone.contracts.errors import CacheError
from codeclone.models import (
    ApiParamSpec,
    BlockUnit,
    FileMetrics,
    ModuleApiSurface,
    PublicSymbol,
    SecuritySurface,
    SegmentUnit,
    Unit,
)


def _make_unit(filepath: str) -> Unit:
    return Unit(
        qualname="mod:func",
        filepath=filepath,
        start_line=1,
        end_line=2,
        loc=2,
        stmt_count=1,
        fingerprint="abc",
        loc_bucket="0-19",
    )


def _make_block(filepath: str) -> BlockUnit:
    return BlockUnit(
        block_hash="h1",
        filepath=filepath,
        qualname="mod:func",
        start_line=1,
        end_line=2,
        size=4,
    )


def _make_segment(filepath: str) -> SegmentUnit:
    return SegmentUnit(
        segment_hash="s1",
        segment_sig="sig1",
        filepath=filepath,
        qualname="mod:func",
        start_line=1,
        end_line=6,
        size=6,
    )


def _analysis_payload(cache: Cache, *, files: object) -> dict[str, object]:
    return {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "ap": cache.data["analysis_profile"],
        "files": files,
    }


def _roundtrip_cache_entry_with_metrics(
    tmp_path: Path,
    *,
    file_metrics: FileMetrics,
) -> CacheEntry:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        file_metrics=file_metrics,
    )
    cache.save()

    loaded = Cache(cache_path)
    loaded.load()
    entry = loaded.get_file_entry("x.py")
    assert entry is not None
    return entry


def test_cache_roundtrip(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    unit = _make_unit("x.py")
    block = _make_block("x.py")
    segment = _make_segment("x.py")
    cache.put_file_entry(
        "x.py", {"mtime_ns": 1, "size": 10}, [unit], [block], [segment]
    )
    cache.save()

    loaded = Cache(cache_path)
    loaded.load()
    entry = loaded.get_file_entry("x.py")
    assert entry is not None
    assert entry["stat"]["size"] == 10
    assert entry["units"][0]["qualname"] == "mod:func"
    assert loaded.load_status == CacheStatus.OK
    assert loaded.cache_schema_version == Cache._CACHE_VERSION


def test_cache_prune_file_entries_removes_stale_paths(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    cache_path = root / "cache.json"
    live = root / "live.py"
    stale = root / "stale.py"
    live.write_text("def live():\n    return 1\n", "utf-8")

    cache = Cache(cache_path, root=root)
    cache.put_file_entry(
        str(live),
        file_stat_signature(str(live)),
        [],
        [],
        [],
    )
    cache.put_file_entry(
        str(stale),
        {"mtime_ns": 1, "size": 1},
        [],
        [],
        [],
    )
    cache.save()

    loaded = Cache(cache_path, root=root)
    loaded.load()

    removed = loaded.prune_file_entries((str(live),))

    assert removed == 1
    assert str(live) in loaded.data["files"]
    assert str(stale) not in loaded.data["files"]

    loaded.save()

    reloaded = Cache(cache_path, root=root)
    reloaded.load()
    assert reloaded.get_file_entry(str(live)) is not None
    assert reloaded.get_file_entry(str(stale)) is None


def test_cache_roundtrip_preserves_empty_structural_findings(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry(
        "x.py",
        {"mtime_ns": 1, "size": 10},
        [],
        [],
        [],
        structural_findings=[],
    )
    cache.save()

    loaded = Cache(cache_path)
    loaded.load()
    entry = loaded.get_file_entry("x.py")
    assert entry is not None
    assert "structural_findings" in entry
    assert entry["structural_findings"] == []


def test_cache_roundtrip_preserves_api_surface_parameter_order(
    tmp_path: Path,
) -> None:
    entry = _roundtrip_cache_entry_with_metrics(
        tmp_path,
        file_metrics=FileMetrics(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset(),
            api_surface=ModuleApiSurface(
                module="pkg.mod",
                filepath="x.py",
                all_declared=("run",),
                symbols=(
                    PublicSymbol(
                        qualname="pkg.mod:run",
                        kind="function",
                        start_line=1,
                        end_line=2,
                        params=(
                            ApiParamSpec(
                                name="beta",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                            ApiParamSpec(
                                name="alpha",
                                kind="pos_or_kw",
                                has_default=False,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    params = entry["api_surface"]["symbols"][0]["params"]
    assert [param["name"] for param in params] == ["beta", "alpha"]


def test_cache_roundtrip_preserves_security_surfaces(tmp_path: Path) -> None:
    entry = _roundtrip_cache_entry_with_metrics(
        tmp_path,
        file_metrics=FileMetrics(
            class_metrics=(),
            module_deps=(),
            dead_candidates=(),
            referenced_names=frozenset(),
            import_names=frozenset(),
            class_names=frozenset(),
            security_surfaces=(
                SecuritySurface(
                    category="process_boundary",
                    capability="subprocess_run",
                    module="pkg.runner",
                    filepath="x.py",
                    qualname="pkg.runner:run_command",
                    start_line=10,
                    end_line=10,
                    location_scope="callable",
                    classification_mode="exact_call",
                    evidence_kind="call",
                    evidence_symbol="subprocess.run",
                ),
            ),
        ),
    )
    assert entry["security_surfaces"] == [
        {
            "category": "process_boundary",
            "capability": "subprocess_run",
            "module": "pkg.runner",
            "filepath": "x.py",
            "qualname": "pkg.runner:run_command",
            "start_line": 10,
            "end_line": 10,
            "location_scope": "callable",
            "classification_mode": "exact_call",
            "evidence_kind": "call",
            "evidence_symbol": "subprocess.run",
        }
    ]


def test_security_surface_cache_helpers_reject_invalid_values() -> None:
    assert _as_security_surface_category("process_boundary") == "process_boundary"
    assert _as_security_surface_category("broken") is None
    assert _as_security_surface_location_scope("callable") == "callable"
    assert _as_security_surface_location_scope("broken") is None
    assert _as_security_surface_classification_mode("exact_call") == "exact_call"
    assert _as_security_surface_classification_mode("broken") is None
    assert _as_security_surface_evidence_kind("call") == "call"
    assert _as_security_surface_evidence_kind("broken") is None
    assert (
        _is_module_api_surface_dict(
            {
                "module": "pkg.mod",
                "filepath": "pkg/mod.py",
                "all_declared": ["run"],
                "symbols": "bad",
            }
        )
        is False
    )
    assert _is_security_surface_dict(object()) is False


def test_decode_wire_security_surface_covers_valid_and_invalid_rows() -> None:
    assert _decode_wire_security_surface(object(), "pkg/mod.py") is None
    assert (
        _decode_wire_security_surface(
            [
                "broken",
                "subprocess_run",
                "pkg.mod",
                "pkg.mod:run",
                10,
                12,
                "callable",
                "exact_call",
                "call",
                "subprocess.run",
            ],
            "pkg/mod.py",
        )
        is None
    )
    assert (
        _decode_wire_security_surface(
            [
                "process_boundary",
                "subprocess_run",
                "pkg.mod",
                "pkg.mod:run",
                "10",
                12,
                "callable",
                "exact_call",
                "call",
                "subprocess.run",
            ],
            "pkg/mod.py",
        )
        is None
    )
    assert (
        _decode_wire_security_surface(
            [
                "process_boundary",
                "subprocess_run",
                "pkg.mod",
                "pkg.mod:run",
                10,
                12,
                "broken",
                "exact_call",
                "call",
                "subprocess.run",
            ],
            "pkg/mod.py",
        )
        is None
    )
    decoded = _decode_wire_security_surface(
        [
            "process_boundary",
            "subprocess_run",
            "pkg.mod",
            "pkg.mod:run",
            10,
            12,
            "callable",
            "exact_call",
            "call",
            "subprocess.run",
        ],
        "pkg/mod.py",
    )
    assert decoded == {
        "category": "process_boundary",
        "capability": "subprocess_run",
        "module": "pkg.mod",
        "filepath": "pkg/mod.py",
        "qualname": "pkg.mod:run",
        "start_line": 10,
        "end_line": 12,
        "location_scope": "callable",
        "classification_mode": "exact_call",
        "evidence_kind": "call",
        "evidence_symbol": "subprocess.run",
    }


def test_cache_load_normalizes_stale_structural_findings(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    entry = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 10},
            "units": [],
            "blocks": [],
            "segments": [],
            "class_metrics": [],
            "module_deps": [],
            "dead_candidates": [],
            "referenced_names": [],
            "import_names": [],
            "class_names": [],
            "structural_findings": [
                {
                    "finding_kind": "duplicated_branches",
                    "finding_key": "abc" * 13 + "a",
                    "signature": {
                        "calls": "2+",
                        "has_loop": "0",
                        "has_try": "0",
                        "nested_if": "0",
                        "raises": "0",
                        "stmt_seq": "Expr",
                        "terminal": "expr",
                    },
                    "items": [
                        {"qualname": "mod:fn", "start": 5, "end": 5},
                        {"qualname": "mod:fn", "start": 8, "end": 8},
                    ],
                },
                {
                    "finding_kind": "duplicated_branches",
                    "finding_key": "def" * 13 + "d",
                    "signature": {
                        "calls": "0",
                        "has_loop": "0",
                        "has_try": "1",
                        "nested_if": "1",
                        "raises": "0",
                        "stmt_seq": "Try",
                        "terminal": "fallthrough",
                    },
                    "items": [
                        {"qualname": "mod:fn", "start": 10, "end": 20},
                        {"qualname": "mod:fn", "start": 14, "end": 20},
                        {"qualname": "mod:fn", "start": 30, "end": 35},
                    ],
                },
            ],
        },
    )
    payload = _analysis_payload(
        cache,
        files={"x.py": _encode_wire_file_entry(entry)},
    )
    signature = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": signature}),
        "utf-8",
    )

    loaded = Cache(cache_path)
    loaded.load()
    loaded_entry = loaded.get_file_entry("x.py")
    assert loaded_entry is not None
    findings = loaded_entry["structural_findings"]
    assert len(findings) == 1
    assert findings[0]["finding_key"] == "def" * 13 + "d"
    assert findings[0]["items"] == [
        {"qualname": "mod:fn", "start": 10, "end": 20},
        {"qualname": "mod:fn", "start": 30, "end": 35},
    ]


def test_get_file_entry_uses_wire_key_fallback(tmp_path: Path) -> None:
    root = tmp_path / "project"
    file_path = root / "pkg" / "module.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    cache = Cache(tmp_path / "cache.json", root=root)
    runtime_key = str(file_path.resolve())
    cache.data["files"][runtime_key] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": [],
        },
    )
    non_canonical = str(root / "pkg" / ".." / "pkg" / "module.py")
    assert cache.get_file_entry(non_canonical) is not None


def test_get_file_entry_keeps_loaded_cache_clean_on_canonical_hit(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded._dirty is False
    assert loaded.get_file_entry("x.py") is not None
    assert loaded._dirty is False


def test_store_canonical_file_entry_marks_dirty_only_when_entry_changes(
    tmp_path: Path,
) -> None:
    cache = Cache(tmp_path / "cache.json")
    canonical_entry = cast(
        Any,
        _canonicalize_cache_entry(
            {
                "stat": {"mtime_ns": 1, "size": 1},
                "units": [],
                "blocks": [],
                "segments": [],
                "class_metrics": [],
                "module_deps": [],
                "dead_candidates": [],
                "referenced_names": [],
                "referenced_qualnames": [],
                "import_names": [],
                "class_names": [],
            }
        ),
    )
    cache.data["files"]["x.py"] = canonical_entry
    cache._canonical_runtime_paths.add("x.py")
    cache._dirty = False

    cache._store_canonical_file_entry(
        runtime_path="x.py",
        canonical_entry=canonical_entry,
    )
    assert cache._dirty is False

    cache._canonical_runtime_paths.clear()
    cache._store_canonical_file_entry(
        runtime_path="x.py",
        canonical_entry=canonical_entry,
    )
    assert cache._dirty is True


def test_cache_helper_type_guards_and_wire_api_decoders_cover_invalid_inputs() -> None:
    assert _as_module_typing_coverage_dict({"module": "pkg"}) is None
    assert _as_module_docstring_coverage_dict({"module": "pkg"}) is None
    assert _as_module_api_surface_dict({"module": "pkg"}) is None
    assert (
        _has_cache_entry_container_shape(
            {
                "stat": {"mtime_ns": 1, "size": 1},
                "units": [],
                "blocks": [],
                "segments": [],
                "typing_coverage": {"module": "pkg"},
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
                "segments": [],
                "docstring_coverage": {"module": "pkg"},
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
                "segments": [],
                "api_surface": {"module": "pkg"},
            }
        )
        is False
    )
    assert (
        _decode_optional_wire_api_surface(
            obj={"as": ["pkg.mod", ["run"], [None]]},
            filepath="pkg/mod.py",
        )
        is None
    )
    assert (
        _decode_optional_wire_module_ints(
            obj={"tc": ["pkg.mod", "bad"]},
            key="tc",
            expected_len=2,
            int_indexes=(1,),
        )
        is None
    )
    assert _decode_wire_api_surface_symbol(["pkg.mod:run"]) is None
    assert (
        _decode_wire_api_surface_symbol(
            ["pkg.mod:run", "function", 1, 2, "name", "", [None]]
        )
        is None
    )
    assert _decode_wire_api_param_spec(["value"]) is None
    assert _is_api_param_spec_dict([]) is False
    assert _is_public_symbol_dict([]) is False
    assert (
        _is_public_symbol_dict(
            {
                "qualname": "pkg.mod:run",
                "kind": "function",
                "exported_via": "name",
                "start_line": 1,
                "end_line": 2,
                "params": "bad",
            }
        )
        is False
    )


def test_get_file_entry_missing_after_fallback_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cache = Cache(tmp_path / "cache.json", root=root)
    assert cache.get_file_entry(str(root / "pkg" / "missing.py")) is None


def test_cache_v13_uses_relpaths_when_root_set(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    target = project_root / "pkg" / "module.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def f():\n    return 1\n", "utf-8")

    cache_path = project_root / ".cache" / "codeclone" / "cache.json"
    cache = Cache(cache_path, root=project_root)
    cache.put_file_entry(
        str(target),
        {"mtime_ns": 1, "size": 10},
        [_make_unit(str(target))],
        [_make_block(str(target))],
        [_make_segment(str(target))],
    )
    cache.save()

    raw = json.loads(cache_path.read_text("utf-8"))
    payload = cast(dict[str, object], raw["payload"])
    files = cast(dict[str, object], payload["files"])
    assert "pkg/module.py" in files
    assert str(target) not in files


def test_cache_v13_missing_optional_sections_default_empty(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = _analysis_payload(cache, files={"x.py": {"st": [1, 2]}})
    signature = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": signature}),
        "utf-8",
    )

    cache.load()
    entry = cache.get_file_entry("x.py")
    assert entry is not None
    assert entry["units"] == []
    assert entry["blocks"] == []
    assert entry["segments"] == []


def test_cache_signature_validation_ignores_json_whitespace(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    raw = json.loads(cache_path.read_text("utf-8"))
    cache_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), "utf-8")

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is None
    assert loaded.get_file_entry("x.py") is not None


def test_decode_wire_file_and_name_section_helpers_cover_valid_and_invalid() -> None:
    encoded = _encode_wire_file_entry(
        {
            "stat": {"mtime_ns": 1, "size": 10},
            "units": [_unit_dict_from_model(_make_unit("x.py"), "x.py")],
            "blocks": [_block_dict_from_model(_make_block("x.py"), "x.py")],
            "segments": [_segment_dict_from_model(_make_segment("x.py"), "x.py")],
            "class_metrics": [],
            "module_deps": [],
            "dead_candidates": [],
            "referenced_names": ["used"],
            "referenced_qualnames": ["pkg.mod:used"],
            "import_names": ["pkg"],
            "class_names": ["Service"],
        }
    )
    assert isinstance(encoded, dict)

    file_sections = _decode_wire_file_sections(obj=encoded, filepath="x.py")
    assert file_sections is not None
    units, blocks, segments, class_metrics, module_deps, dead_candidates = file_sections
    assert units[0]["qualname"] == "mod:func"
    assert blocks[0]["qualname"] == "mod:func"
    assert segments[0]["qualname"] == "mod:func"
    assert class_metrics == []
    assert module_deps == []
    assert dead_candidates == []

    name_sections = _decode_wire_name_sections(obj=encoded)
    assert name_sections == (
        ["used"],
        ["pkg.mod:used"],
        ["pkg"],
        ["Service"],
    )

    invalid_sections = dict(encoded)
    invalid_sections["u"] = "bad"
    assert (
        _decode_wire_file_sections(
            obj=invalid_sections,
            filepath="x.py",
        )
        is None
    )

    invalid_names = dict(encoded)
    invalid_names["rn"] = 1
    assert _decode_wire_name_sections(obj=invalid_names) is None


def test_cache_signature_mismatch_warns(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    data = json.loads(cache_path.read_text("utf-8"))
    data["sig"] = "bad"
    cache_path.write_text(json.dumps(data), "utf-8")

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "signature" in loaded.load_warning
    assert loaded.data["version"] == Cache._CACHE_VERSION
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.INTEGRITY_FAILED
    assert loaded.cache_schema_version == Cache._CACHE_VERSION


def test_cache_version_mismatch_warns(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    data = {"version": "0.0", "files": {}}
    signature = sign_cache_payload(data)
    cache_path.write_text(
        json.dumps({**data, "_signature": signature}, ensure_ascii=False, indent=2),
        "utf-8",
    )

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "version" in loaded.load_warning
    assert loaded.data["version"] == Cache._CACHE_VERSION
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.VERSION_MISMATCH
    assert loaded.cache_schema_version == "0.0"


@pytest.mark.parametrize("version", ["0.0", "2.2"])
def test_cache_v_field_version_mismatch_warns(tmp_path: Path, version: str) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = _analysis_payload(cache, files={})
    signature = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": version, "payload": payload, "sig": signature}), "utf-8"
    )

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "version mismatch" in loaded.load_warning
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.VERSION_MISMATCH
    assert loaded.cache_schema_version == version


def test_cache_too_large_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"version": Cache._CACHE_VERSION, "files": {}}))
    monkeypatch.setattr(cache_store, "MAX_CACHE_SIZE_BYTES", 1)
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "too large" in cache.load_warning
    assert cache.data["version"] == Cache._CACHE_VERSION
    assert cache.data["files"] == {}
    assert cache.load_status == CacheStatus.TOO_LARGE
    assert cache.cache_schema_version is None


def test_cache_entry_validation(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.data["files"]["x.py"] = cast(Any, {"stat": {"mtime_ns": 1, "size": 1}})
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_invalid_stat_types(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": "1", "size": 1},
            "units": [],
            "blocks": [],
            "segments": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_stat_not_dict(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": [],
            "units": [],
            "blocks": [],
            "segments": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_invalid_units_container_type(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": {},
            "blocks": [],
            "segments": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_unit_item_not_dict(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": ["bad"],
            "blocks": [],
            "segments": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_invalid_unit_field_type(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [
                {
                    "qualname": "q",
                    "filepath": "x.py",
                    "start_line": "1",
                    "end_line": 2,
                    "loc": 2,
                    "stmt_count": 1,
                    "fingerprint": "fp",
                    "loc_bucket": "0-19",
                }
            ],
            "blocks": [],
            "segments": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_block_item_not_dict(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": ["bad"],
            "segments": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_invalid_block_field_type(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [
                {
                    "block_hash": "h",
                    "filepath": "x.py",
                    "qualname": "q",
                    "start_line": 1,
                    "end_line": 2,
                    "size": "4",
                }
            ],
            "segments": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_segment_item_not_dict(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": ["bad"],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_invalid_segment_field_type(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": [
                {
                    "segment_hash": "h",
                    "segment_sig": "sig",
                    "filepath": "x.py",
                    "qualname": "q",
                    "start_line": 1,
                    "end_line": 2,
                    "size": "6",
                }
            ],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_cache_entry_valid_deep_schema(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [
                {
                    "qualname": "q",
                    "filepath": "x.py",
                    "start_line": 1,
                    "end_line": 2,
                    "loc": 2,
                    "stmt_count": 1,
                    "fingerprint": "fp",
                    "loc_bucket": "0-19",
                }
            ],
            "blocks": [
                {
                    "block_hash": "h",
                    "filepath": "x.py",
                    "qualname": "q",
                    "start_line": 1,
                    "end_line": 2,
                    "size": 4,
                }
            ],
            "segments": [
                {
                    "segment_hash": "h",
                    "segment_sig": "sig",
                    "filepath": "x.py",
                    "qualname": "q",
                    "start_line": 1,
                    "end_line": 2,
                    "size": 6,
                }
            ],
        },
    )
    assert cache.get_file_entry("x.py") is not None


def test_cache_load_missing_file(tmp_path: Path) -> None:
    cache_path = tmp_path / "missing.json"
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is None
    assert cache.load_status == CacheStatus.MISSING
    assert cache.cache_schema_version is None


def test_cache_entry_not_dict(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.data["files"]["x.py"] = cast(Any, ["bad"])
    assert cache.get_file_entry("x.py") is None


def test_file_stat_signature(tmp_path: Path) -> None:
    file_path = tmp_path / "x.py"
    file_path.write_text("print('x')\n", "utf-8")
    stat = file_stat_signature(str(file_path))
    assert stat["size"] == file_path.stat().st_size
    assert isinstance(stat["mtime_ns"], int)


def test_cache_load_corrupted_json(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{invalid json", "utf-8")
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "corrupted" in cache.load_warning
    assert cache.load_status == CacheStatus.INVALID_JSON
    assert cache.cache_schema_version is None


def test_cache_load_unreadable_stat_graceful_ignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text('{"version":"1.0","files":{}}', "utf-8")
    original_stat = Path.stat

    def _raise_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        if self == cache_path:
            raise OSError("no stat")
        return original_stat(self)

    monkeypatch.setattr(Path, "stat", _raise_stat)
    cache = Cache(cache_path)
    cache.load()
    _assert_unreadable_cache_contract(cache)


def test_cache_load_unreadable_read_graceful_ignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text('{"version":"1.0","files":{}}', "utf-8")
    original_read_text = Path.read_text

    def _raise_read_text(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if self == cache_path:
            raise OSError("no read")
        return original_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", _raise_read_text)
    cache = Cache(cache_path)
    cache.load()
    _assert_unreadable_cache_contract(cache)


def _assert_unreadable_cache_contract(cache: Cache) -> None:
    assert cache.load_warning is not None
    assert "unreadable" in cache.load_warning
    assert cache.data["files"] == {}
    assert cache.load_status == CacheStatus.UNREADABLE
    assert cache.cache_schema_version is None


def test_cache_load_invalid_files_type(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = _analysis_payload(cache, files=[])
    signature = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": signature}),
        "utf-8",
    )
    cache.load()
    assert cache.load_warning is not None
    assert "format" in cache.load_warning


def test_cache_save_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)

    def _raise_fsync(_fd: int) -> None:
        raise OSError("nope")

    monkeypatch.setattr(os, "fsync", _raise_fsync)

    with pytest.raises(CacheError):
        cache.save()


def test_cache_legacy_secret_warning_on_init(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_secret = cache_path.parent / ".cache_secret"
    legacy_secret.write_text("legacy", "utf-8")

    cache = Cache(cache_path)
    assert cache.load_warning is not None
    assert "Legacy cache secret file detected" in cache.load_warning
    assert "delete this obsolete file" in cache.load_warning


def test_cache_legacy_secret_warning_preserved_after_successful_load(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_secret = cache_path.parent / ".cache_secret"
    legacy_secret.write_text("legacy", "utf-8")
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.get_file_entry("x.py") is not None
    assert loaded.load_warning is not None
    assert "Legacy cache secret file detected" in loaded.load_warning


def test_cache_legacy_secret_warning_combined_with_other_warning(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_secret = cache_path.parent / ".cache_secret"
    legacy_secret.write_text("legacy", "utf-8")
    cache_path.write_text("{bad json", "utf-8")

    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "Cache corrupted; ignoring cache." in cache.load_warning
    assert "Legacy cache secret file detected" in cache.load_warning


def test_cache_legacy_secret_check_oserror_sets_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    secret_path = cache_path.parent / ".cache_secret"
    original_exists = Path.exists

    def _exists_with_error(self: Path) -> bool:
        if self == secret_path:
            raise OSError("no access")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _exists_with_error)
    cache = Cache(cache_path)
    assert cache.load_warning is not None
    assert "Legacy cache secret check failed" in cache.load_warning


def test_cache_load_invalid_top_level_type(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("[]", "utf-8")
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning
    assert cache.data["files"] == {}


def test_cache_load_missing_v_field(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = _analysis_payload(cache, files={})
    sig = sign_cache_payload(payload)
    cache_path.write_text(json.dumps({"payload": payload, "sig": sig}), "utf-8")
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


def test_cache_load_missing_payload_or_sig(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": {}}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


@pytest.mark.parametrize(
    "payload_factory",
    [
        lambda cache: {"fp": cache.data["fingerprint_version"], "files": {}},
        lambda cache: {"py": cache.data["python_tag"], "files": {}},
    ],
    ids=["missing_python_tag", "missing_fingerprint_version"],
)
def test_cache_load_rejects_missing_required_payload_fields(
    tmp_path: Path,
    payload_factory: Callable[[Cache], dict[str, object]],
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = payload_factory(cache)
    sig = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


def test_cache_load_python_tag_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": "cp999",
        "fp": cache.data["fingerprint_version"],
        "ap": cache.data["analysis_profile"],
        "files": {},
    }
    sig = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "python tag mismatch" in cache.load_warning


def test_cache_load_fingerprint_version_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": "old",
        "ap": cache.data["analysis_profile"],
        "files": {},
    }
    sig = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "fingerprint version mismatch" in cache.load_warning


def test_cache_load_analysis_profile_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, min_loc=1, min_stmt=1)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    loaded = Cache(cache_path, min_loc=15, min_stmt=6)
    loaded.load()

    assert loaded.load_warning is not None
    assert "analysis profile mismatch" in loaded.load_warning
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.ANALYSIS_PROFILE_MISMATCH
    assert loaded.cache_schema_version == Cache._CACHE_VERSION


def test_cache_load_analysis_profile_mismatch_collect_api_surface(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path, collect_api_surface=False)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    loaded = Cache(cache_path, collect_api_surface=True)
    loaded.load()

    assert loaded.load_warning is not None
    assert "analysis profile mismatch" in loaded.load_warning
    assert "collect_api_surface=false" in loaded.load_warning
    assert "collect_api_surface=true" in loaded.load_warning
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.ANALYSIS_PROFILE_MISMATCH
    assert loaded.cache_schema_version == Cache._CACHE_VERSION


def test_cache_load_missing_analysis_profile_in_payload(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": {},
    }
    sig = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )

    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning
    assert cache.load_status == CacheStatus.INVALID_TYPE
    assert cache.cache_schema_version == Cache._CACHE_VERSION
    assert cache.data["files"] == {}


@pytest.mark.parametrize(
    "bad_analysis_profile",
    [
        {"min_loc": 15},
        {"min_loc": "15", "min_stmt": 6},
    ],
)
def test_cache_load_invalid_analysis_profile_payload(
    tmp_path: Path, bad_analysis_profile: object
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "ap": bad_analysis_profile,
        "files": {},
    }
    sig = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )

    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning
    assert cache.load_status == CacheStatus.INVALID_TYPE
    assert cache.cache_schema_version == Cache._CACHE_VERSION
    assert cache.data["files"] == {}


def test_cache_load_invalid_wire_file_entry(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = _analysis_payload(cache, files={"x.py": {"st": "bad"}})
    sig = sign_cache_payload(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


def test_cache_save_skips_none_entry_from_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": [],
        },
    )

    def _always_none(_self: Cache, _path: str) -> None:
        return None

    monkeypatch.setattr(Cache, "get_file_entry", _always_none)
    cache.save()
    raw = json.loads(cache_path.read_text("utf-8"))
    payload = cast(dict[str, object], raw["payload"])
    files = cast(dict[str, object], payload["files"])
    assert files == {}


def test_wire_filepath_outside_root_falls_back_to_runtime_path(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cache = Cache(tmp_path / "cache.json", root=root)
    outside = tmp_path / "outside.py"
    assert (
        wire_filepath_from_runtime(str(outside), root=cache.root) == outside.as_posix()
    )


def test_wire_filepath_resolve_oserror_falls_back_to_runtime_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime = tmp_path / "outside.py"
    cache = Cache(tmp_path / "cache.json", root=root)
    original_resolve = Path.resolve

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == runtime:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    assert (
        wire_filepath_from_runtime(str(runtime), root=cache.root) == runtime.as_posix()
    )


def test_wire_filepath_resolve_relative_success_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    runtime = tmp_path / "outside.py"
    cache = Cache(tmp_path / "cache.json", root=root)
    original_resolve = Path.resolve
    resolved_runtime = root / "pkg" / "module.py"

    def _resolve_with_mapping(self: Path, *, strict: bool = False) -> Path:
        if self == runtime:
            return resolved_runtime
        if self == root:
            return root
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_mapping)
    assert wire_filepath_from_runtime(str(runtime), root=cache.root) == "pkg/module.py"


def test_runtime_filepath_from_wire_resolve_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cache = Cache(tmp_path / "cache.json", root=root)
    original_resolve = Path.resolve
    combined = root / "pkg" / "module.py"

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == combined:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    assert runtime_filepath_from_wire("pkg/module.py", root=cache.root) == str(combined)


def test_as_str_dict_rejects_non_string_keys() -> None:
    assert _as_str_dict({1: "x"}) is None


@pytest.mark.parametrize(
    ("entry", "filepath"),
    [
        ("bad", "x.py"),
        ({"st": "bad"}, "x.py"),
        ({"st": [1]}, "x.py"),
        ({"st": [1, "2"]}, "x.py"),
        ({"st": [1, 2], "u": "bad"}, "x.py"),
        ({"st": [1, 2], "u": [["q", 1, 2, 3, 4, "fp"]]}, "x.py"),
        ({"st": [1, 2], "b": "bad"}, "x.py"),
        ({"st": [1, 2], "b": [["q", 1, 2, 3]]}, "x.py"),
        ({"st": [1, 2], "s": "bad"}, "x.py"),
        ({"st": [1, 2], "s": [["q", 1, 2, 3, "h"]]}, "x.py"),
    ],
)
def test_decode_wire_file_entry_invalid_variants(entry: object, filepath: str) -> None:
    assert _decode_wire_file_entry(entry, filepath) is None


def test_decode_wire_item_type_failures() -> None:
    assert _decode_wire_unit(["q", 1, 2, 3, 4, "fp"], "x.py") is None
    assert _decode_wire_unit(["q", 1, 2, 3, 4, "fp", "0-19"], "x.py") is None
    assert _decode_wire_unit(["q", "1", 2, 3, 4, "fp", "0-19"], "x.py") is None
    assert _decode_wire_block(["q", 1, 2, 3], "x.py") is None
    assert _decode_wire_block(["q", 1, 2, "4", "hash"], "x.py") is None
    assert _decode_wire_segment(["q", 1, 2, 3, "h"], "x.py") is None
    assert _decode_wire_segment(["q", 1, 2, "3", "h", "sig"], "x.py") is None


def test_decode_wire_item_rejects_invalid_risk_fields() -> None:
    assert (
        _decode_wire_unit(
            ["q", 1, 2, 3, 4, "fp", "0-19", 2, 1, "critical", "raw"],
            "x.py",
        )
        is None
    )
    assert (
        _decode_wire_class_metric(
            ["pkg.mod:Service", 1, 10, 3, 2, 4, 1, 7, 8],
            "x.py",
        )
        is None
    )


def test_resolve_root_oserror_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_resolve = Path.resolve

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == tmp_path:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    assert _resolve_root(tmp_path) is None


def test_cache_entry_rejects_invalid_metrics_sections(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "units": [],
            "blocks": [],
            "segments": [],
            "class_metrics": "bad",
            "module_deps": [],
            "dead_candidates": [],
            "referenced_names": [],
            "import_names": [],
            "class_names": [],
        },
    )
    assert cache.get_file_entry("x.py") is None


def test_decode_wire_file_entry_rejects_metrics_related_invalid_sections() -> None:
    assert _decode_wire_file_entry({"st": [1, 2], "cm": "bad"}, "x.py") is None
    assert (
        _decode_wire_file_entry(
            {"st": [1, 2], "cm": [["Q", 1, 2, 3, 4, 5, 6, "low"]]},
            "x.py",
        )
        is None
    )
    assert _decode_wire_file_entry({"st": [1, 2], "md": "bad"}, "x.py") is None
    assert (
        _decode_wire_file_entry(
            {"st": [1, 2], "md": [["source", "target", "import"]]},
            "x.py",
        )
        is None
    )
    assert _decode_wire_file_entry({"st": [1, 2], "dc": "bad"}, "x.py") is None
    decoded = _decode_wire_file_entry(
        {"st": [1, 2], "dc": [["q", "n", 1, 2, "function"]]},
        "x.py",
    )
    assert decoded is not None
    assert decoded["dead_candidates"][0]["filepath"] == "x.py"
    assert _decode_wire_file_entry({"st": [1, 2], "rn": [1]}, "x.py") is None
    assert _decode_wire_file_entry({"st": [1, 2], "in": [1]}, "x.py") is None
    assert _decode_wire_file_entry({"st": [1, 2], "cn": [1]}, "x.py") is None
    assert _decode_wire_file_entry({"st": [1, 2], "cc": "bad"}, "x.py") is None
    assert _decode_wire_file_entry({"st": [1, 2], "cc": [["Q"]]}, "x.py") is None
    assert (
        _decode_wire_file_entry(
            {"st": [1, 2], "cc": [["Q", ["A", 1]]]},
            "x.py",
        )
        is None
    )


def test_decode_wire_file_entry_accepts_metrics_sections() -> None:
    decoded = _decode_wire_file_entry(
        {
            "st": [1, 2],
            "cm": [["pkg.mod:Service", 1, 10, 3, 2, 4, 1, "low", "medium"]],
            "cc": [["pkg.mod:Service", ["Zeta", "Alpha"]]],
            "md": [["a", "b", "import", 1]],
            "dc": [["pkg.mod:unused", "unused", 1, 2, "function"]],
            "rn": ["name"],
            "in": ["typing", "os"],
            "cn": ["Service", "Model"],
        },
        "x.py",
    )
    assert decoded is not None
    assert decoded["class_metrics"][0]["qualname"] == "pkg.mod:Service"
    assert decoded["class_metrics"][0]["coupled_classes"] == ["Alpha", "Zeta"]
    assert decoded["module_deps"][0]["target"] == "b"
    assert decoded["dead_candidates"][0]["qualname"] == "pkg.mod:unused"
    assert decoded["import_names"] == ["typing", "os"]
    assert decoded["class_names"] == ["Service", "Model"]


def test_decode_wire_file_entry_optional_source_stats() -> None:
    decoded = _decode_wire_file_entry(
        {"st": [1, 2], "ss": [10, 3, 1, 1]},
        "x.py",
    )
    assert decoded is not None
    assert decoded["source_stats"] == {
        "lines": 10,
        "functions": 3,
        "methods": 1,
        "classes": 1,
    }

    assert _decode_optional_wire_source_stats(obj={"ss": "bad"}) is None
    assert _decode_optional_wire_source_stats(obj={"ss": [1, 2, 3]}) is None
    assert _decode_optional_wire_source_stats(obj={"ss": [1, 2, -1, 0]}) is None


def test_cache_helpers_cover_invalid_analysis_profile_and_source_stats_shapes() -> None:
    assert _decode_wire_qualname_span_size(["pkg.mod:fn", 1, 2, "bad"]) is None
    assert _decode_wire_qualname_span_size([None, 1, 2, 4]) is None
    assert (
        _as_analysis_profile(
            {
                "min_loc": 1,
                "min_stmt": 1,
                "block_min_loc": 2,
                "block_min_stmt": "bad",
                "segment_min_loc": 3,
                "segment_min_stmt": 4,
            }
        )
        is None
    )
    assert _decode_optional_wire_source_stats(obj={"ss": [1, 2, "bad", 0]}) is None


def test_canonicalize_cache_entry_skips_invalid_dead_candidate_suppression_shape() -> (
    None
):
    normalized = _canonicalize_cache_entry(
        cast(
            Any,
            {
                "stat": {"mtime_ns": 1, "size": 2},
                "units": [],
                "blocks": [],
                "segments": [],
                "class_metrics": [],
                "module_deps": [],
                "dead_candidates": [
                    {
                        "qualname": "pkg.mod:unused",
                        "local_name": "unused",
                        "filepath": "pkg/mod.py",
                        "start_line": 1,
                        "end_line": 2,
                        "kind": "function",
                        "suppressed_rules": "dead-code",
                    }
                ],
                "referenced_names": [],
                "referenced_qualnames": [],
                "import_names": [],
                "class_names": [],
            },
        )
    )
    assert normalized["dead_candidates"] == [
        {
            "qualname": "pkg.mod:unused",
            "local_name": "unused",
            "filepath": "pkg/mod.py",
            "start_line": 1,
            "end_line": 2,
            "kind": "function",
        }
    ]


def test_decode_optional_wire_coupled_classes_rejects_non_string_qualname() -> None:
    assert (
        _decode_optional_wire_coupled_classes(
            obj={"cc": [[1, ["A"]]]},
            key="cc",
        )
        is None
    )


def test_decode_wire_file_entry_skips_empty_coupled_classes_mapping() -> None:
    decoded = _decode_wire_file_entry(
        {
            "st": [1, 2],
            "cm": [["pkg.mod:Service", 1, 10, 3, 2, 4, 1, "low", "medium"]],
            "cc": [["pkg.mod:Service", ["", ""]]],
        },
        "x.py",
    )
    assert decoded is not None
    assert "coupled_classes" not in decoded["class_metrics"][0]


def test_decode_wire_metrics_items_and_deps_roundtrip_shape() -> None:
    class_metric = _decode_wire_class_metric(
        ["pkg.mod:Service", 1, 10, 3, 2, 4, 1, "low", "medium"],
        "x.py",
    )
    assert class_metric is not None
    assert class_metric["filepath"] == "x.py"
    assert (
        _decode_wire_class_metric(
            ["pkg.mod:Service", "1", 10, 3, 2, 4, 1, "low", "medium"],
            "x.py",
        )
        is None
    )

    module_dep = _decode_wire_module_dep(["a", "b", "import", 1])
    assert module_dep is not None
    assert module_dep["source"] == "a"
    assert _decode_wire_module_dep(["a", "b", "import", "1"]) is None

    dead_candidate = _decode_wire_dead_candidate(
        ["pkg.mod:unused", "unused", 1, 2, "function"],
        "fallback.py",
    )
    assert dead_candidate is not None
    assert dead_candidate["filepath"] == "fallback.py"
    assert (
        _decode_wire_dead_candidate(
            ["pkg.mod:unused", "unused", "1", 2, "function"],
            "fallback.py",
        )
        is None
    )
    assert (
        _decode_wire_dead_candidate(
            ["pkg.mod:unused", "unused", 1, 2, "function", "legacy.py"],
            "fallback.py",
        )
        is None
    )
    dead_candidate_with_suppression = _decode_wire_dead_candidate(
        ["pkg.mod:unused", "unused", 1, 2, "function", ["dead-code", "dead-code"]],
        "fallback.py",
    )
    assert dead_candidate_with_suppression is not None
    assert dead_candidate_with_suppression["suppressed_rules"] == ["dead-code"]


def test_encode_wire_file_entry_includes_optional_metrics_sections() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 2},
        "units": [],
        "blocks": [],
        "segments": [],
        "class_metrics": [
            {
                "qualname": "pkg.mod:Service",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 3,
                "lcom4": 2,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "medium",
                "coupled_classes": ["ServiceB", "ServiceA"],
            }
        ],
        "module_deps": [
            {"source": "a", "target": "b", "import_type": "import", "line": 1}
        ],
        "dead_candidates": [],
        "referenced_names": [],
        "import_names": ["z", "a"],
        "class_names": ["B", "A"],
    }
    wire = _encode_wire_file_entry(entry)
    assert "cm" in wire
    assert "cc" in wire
    assert "md" in wire
    assert wire["cc"] == [["pkg.mod:Service", ["ServiceA", "ServiceB"]]]
    assert wire["in"] == ["a", "z"]
    assert wire["cn"] == ["A", "B"]


def test_encode_wire_file_entry_compacts_dead_candidate_filepaths() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 2},
        "units": [],
        "blocks": [],
        "segments": [],
        "class_metrics": [],
        "module_deps": [],
        "dead_candidates": [
            {
                "qualname": "pkg.mod:unused",
                "local_name": "unused",
                "filepath": "/repo/pkg/mod.py",
                "start_line": 3,
                "end_line": 4,
                "kind": "function",
            }
        ],
        "referenced_names": [],
        "import_names": [],
        "class_names": [],
    }
    wire = _encode_wire_file_entry(entry)
    assert wire["dc"] == [["pkg.mod:unused", "unused", 3, 4, "function"]]


def test_encode_wire_file_entry_encodes_dead_candidate_suppressions() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 2},
        "units": [],
        "blocks": [],
        "segments": [],
        "class_metrics": [],
        "module_deps": [],
        "dead_candidates": [
            {
                "qualname": "pkg.mod:unused",
                "local_name": "unused",
                "filepath": "/repo/pkg/mod.py",
                "start_line": 3,
                "end_line": 4,
                "kind": "function",
                "suppressed_rules": ["dead-code", "dead-code"],
            }
        ],
        "referenced_names": [],
        "import_names": [],
        "class_names": [],
    }
    wire = _encode_wire_file_entry(entry)
    assert wire["dc"] == [["pkg.mod:unused", "unused", 3, 4, "function", ["dead-code"]]]


def test_encode_wire_file_entry_skips_empty_or_invalid_coupled_classes() -> None:
    entry: CacheEntry = {
        "stat": {"mtime_ns": 1, "size": 2},
        "units": [],
        "blocks": [],
        "segments": [],
        "class_metrics": [
            {
                "qualname": "pkg.mod:Empty",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 2,
                "cbo": 1,
                "lcom4": 1,
                "method_count": 1,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "low",
                "coupled_classes": [],
            },
            {
                "qualname": "pkg.mod:Invalid",
                "filepath": "x.py",
                "start_line": 3,
                "end_line": 4,
                "cbo": 1,
                "lcom4": 1,
                "method_count": 1,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "low",
                "coupled_classes": cast(Any, [1]),
            },
        ],
        "module_deps": [],
        "dead_candidates": [],
        "referenced_names": [],
        "import_names": [],
        "class_names": [],
    }
    wire = _encode_wire_file_entry(entry)
    assert "cc" not in wire


def test_get_file_entry_sorts_coupled_classes_in_runtime_payload(
    tmp_path: Path,
) -> None:
    cache = Cache(tmp_path / "cache.json")
    cache.data["files"]["x.py"] = cast(
        Any,
        {
            "stat": {"mtime_ns": 1, "size": 1},
            "source_stats": {"lines": 1, "functions": 1, "methods": 0, "classes": 0},
            "units": [],
            "blocks": [],
            "segments": [],
            "class_metrics": [
                {
                    "qualname": "pkg.mod:NoDeps",
                    "filepath": "x.py",
                    "start_line": 0,
                    "end_line": 0,
                    "cbo": 0,
                    "lcom4": 1,
                    "method_count": 0,
                    "instance_var_count": 0,
                    "risk_coupling": "low",
                    "risk_cohesion": "low",
                    "coupled_classes": [],
                },
                {
                    "qualname": "pkg.mod:Service",
                    "filepath": "x.py",
                    "start_line": 1,
                    "end_line": 10,
                    "cbo": 2,
                    "lcom4": 1,
                    "method_count": 3,
                    "instance_var_count": 1,
                    "risk_coupling": "low",
                    "risk_cohesion": "low",
                    "coupled_classes": ["Zeta", "Alpha", "Alpha"],
                },
            ],
            "module_deps": [],
            "dead_candidates": [],
            "referenced_names": [],
            "import_names": [],
            "class_names": [],
        },
    )
    entry = cache.get_file_entry("x.py")
    assert entry is not None
    assert len(entry["class_metrics"]) == 2
    assert entry["class_metrics"][0]["qualname"] == "pkg.mod:NoDeps"
    assert entry["class_metrics"][1]["coupled_classes"] == ["Alpha", "Zeta"]
    assert entry["source_stats"]["functions"] == 1


def test_cache_entry_container_shape_rejects_invalid_source_stats() -> None:
    assert (
        _has_cache_entry_container_shape(
            {
                "stat": {"mtime_ns": 1, "size": 1},
                "source_stats": {
                    "lines": 1,
                    "functions": 1,
                    "methods": "0",
                    "classes": 0,
                },
                "units": [],
                "blocks": [],
                "segments": [],
            }
        )
        is False
    )


def test_cache_type_predicates_reject_non_dict_variants() -> None:
    assert _is_class_metrics_dict([]) is False
    assert _is_module_dep_dict([]) is False
    assert _is_dead_candidate_dict([]) is False
    assert (
        _is_dead_candidate_dict(
            {
                "qualname": "pkg.mod:broken",
                "local_name": "broken",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 2,
            }
        )
        is False
    )
    assert (
        _is_dead_candidate_dict(
            {
                "qualname": "pkg.mod:unused",
                "local_name": "unused",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 2,
                "kind": "function",
                "suppressed_rules": ["dead-code"],
            }
        )
        is True
    )
    assert (
        _is_dead_candidate_dict(
            {
                "qualname": "pkg.mod:unused",
                "local_name": "unused",
                "filepath": "pkg/mod.py",
                "start_line": 1,
                "end_line": 2,
                "kind": "function",
                "suppressed_rules": [1],
            }
        )
        is False
    )
    assert (
        _is_class_metrics_dict(
            {
                "qualname": "pkg.mod:Service",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 3,
                "lcom4": 2,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "high",
            }
        )
        is True
    )
    assert (
        _is_class_metrics_dict(
            {
                "qualname": "pkg.mod:Service",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 3,
                "lcom4": 2,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "high",
                "coupled_classes": ["Alpha", "Beta"],
            }
        )
        is True
    )
    assert (
        _is_class_metrics_dict(
            {
                "qualname": "pkg.mod:Service",
                "filepath": "x.py",
                "start_line": 1,
                "end_line": 10,
                "cbo": 3,
                "lcom4": 2,
                "method_count": 4,
                "instance_var_count": 1,
                "risk_coupling": "low",
                "risk_cohesion": "high",
                "coupled_classes": [1],
            }
        )
        is False
    )
    assert _is_class_metrics_dict({"qualname": "pkg.mod:Service"}) is False
    assert (
        _is_module_dep_dict(
            {
                "source": "a",
                "target": "b",
                "import_type": "import",
                "line": 1,
            }
        )
        is True
    )


def test_decode_wire_int_fields_rejects_non_int_values() -> None:
    assert _decode_wire_int_fields(["x", "nope"], 1) is None


def test_decode_wire_block_rejects_missing_block_hash() -> None:
    assert (
        _decode_wire_block(
            ["pkg.mod:func", 10, 12, 4, None],
            "pkg/mod.py",
        )
        is None
    )


def test_decode_wire_segment_rejects_missing_segment_signature() -> None:
    assert (
        _decode_wire_segment(
            ["pkg.mod:func", 10, 12, 4, "seg-hash", None],
            "pkg/mod.py",
        )
        is None
    )


def test_decode_wire_dead_candidate_rejects_invalid_rows() -> None:
    assert _decode_wire_dead_candidate(object(), "pkg/mod.py") is None
