from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.cache as cache_mod
from codeclone.blocks import BlockUnit, SegmentUnit
from codeclone.cache import Cache, CacheStatus
from codeclone.errors import CacheError
from codeclone.extractor import Unit


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


def test_get_file_entry_missing_after_fallback_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    cache = Cache(tmp_path / "cache.json", root=root)
    assert cache.get_file_entry(str(root / "pkg" / "missing.py")) is None


def test_cache_v12_uses_relpaths_when_root_set(tmp_path: Path) -> None:
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


def test_cache_v12_missing_optional_sections_default_empty(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": {"x.py": {"st": [1, 2]}},
    }
    signature = cache._sign_data(payload)
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
    cache = Cache(cache_path)
    data = {"version": "0.0", "files": {}}
    signature = cache._sign_data(data)
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


def test_cache_v_field_version_mismatch_warns(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": {},
    }
    signature = cache._sign_data(payload)
    cache_path.write_text(
        json.dumps({"v": "0.0", "payload": payload, "sig": signature}), "utf-8"
    )

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "version mismatch" in loaded.load_warning
    assert loaded.data["files"] == {}
    assert loaded.load_status == CacheStatus.VERSION_MISMATCH
    assert loaded.cache_schema_version == "0.0"


def test_cache_too_large_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps({"version": Cache._CACHE_VERSION, "files": {}}))
    monkeypatch.setattr(cache_mod, "MAX_CACHE_SIZE_BYTES", 1)
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
    stat = cache_mod.file_stat_signature(str(file_path))
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
    assert cache.load_warning is not None
    assert "unreadable" in cache.load_warning
    assert cache.data["files"] == {}
    assert cache.load_status == CacheStatus.UNREADABLE
    assert cache.cache_schema_version is None


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
    assert cache.load_warning is not None
    assert "unreadable" in cache.load_warning
    assert cache.data["files"] == {}
    assert cache.load_status == CacheStatus.UNREADABLE
    assert cache.cache_schema_version is None


def test_cache_load_invalid_files_type(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": [],
    }
    signature = cache._sign_data(payload)
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

    original_write_text = Path.write_text

    def _raise_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if self.name.endswith(".tmp"):
            raise OSError("nope")
        return original_write_text(
            self, data, encoding=encoding, errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "write_text", _raise_write_text)

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
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": {},
    }
    sig = cache._sign_data(payload)
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


def test_cache_load_missing_python_tag_in_payload(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {"fp": cache.data["fingerprint_version"], "files": {}}
    sig = cache._sign_data(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


def test_cache_load_python_tag_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {"py": "cp999", "fp": cache.data["fingerprint_version"], "files": {}}
    sig = cache._sign_data(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "python tag mismatch" in cache.load_warning


def test_cache_load_missing_fingerprint_version(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {"py": cache.data["python_tag"], "files": {}}
    sig = cache._sign_data(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "format invalid" in cache.load_warning


def test_cache_load_fingerprint_version_mismatch(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {"py": cache.data["python_tag"], "fp": "old", "files": {}}
    sig = cache._sign_data(payload)
    cache_path.write_text(
        json.dumps({"v": cache._CACHE_VERSION, "payload": payload, "sig": sig}), "utf-8"
    )
    cache.load()
    assert cache.load_warning is not None
    assert "fingerprint version mismatch" in cache.load_warning


def test_cache_load_invalid_wire_file_entry(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    payload = {
        "py": cache.data["python_tag"],
        "fp": cache.data["fingerprint_version"],
        "files": {"x.py": {"st": "bad"}},
    }
    sig = cache._sign_data(payload)
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
    assert cache._wire_filepath_from_runtime(str(outside)) == outside.as_posix()


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
    assert cache._wire_filepath_from_runtime(str(runtime)) == runtime.as_posix()


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
    assert cache._wire_filepath_from_runtime(str(runtime)) == "pkg/module.py"


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
    assert cache._runtime_filepath_from_wire("pkg/module.py") == str(combined)


def test_as_str_dict_rejects_non_string_keys() -> None:
    assert cache_mod._as_str_dict({1: "x"}) is None


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
    assert cache_mod._decode_wire_file_entry(entry, filepath) is None


def test_decode_wire_item_type_failures() -> None:
    assert cache_mod._decode_wire_unit(["q", 1, 2, 3, 4, "fp"], "x.py") is None
    assert (
        cache_mod._decode_wire_unit(["q", "1", 2, 3, 4, "fp", "0-19"], "x.py") is None
    )
    assert cache_mod._decode_wire_block(["q", 1, 2, 3], "x.py") is None
    assert cache_mod._decode_wire_block(["q", 1, 2, "4", "hash"], "x.py") is None
    assert cache_mod._decode_wire_segment(["q", 1, 2, 3, "h"], "x.py") is None
    assert cache_mod._decode_wire_segment(["q", 1, 2, "3", "h", "sig"], "x.py") is None


def test_resolve_root_oserror_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_resolve = Path.resolve

    def _resolve_with_error(self: Path, *, strict: bool = False) -> Path:
        if self == tmp_path:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_with_error)
    assert cache_mod._resolve_root(tmp_path) is None
