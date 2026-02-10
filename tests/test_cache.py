from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

import codeclone.cache as cache_mod
from codeclone.blocks import BlockUnit, SegmentUnit
from codeclone.cache import Cache
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


def test_cache_signature_mismatch_warns(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    data = json.loads(cache_path.read_text("utf-8"))
    data["_signature"] = "bad"
    cache_path.write_text(json.dumps(data), "utf-8")

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "signature" in loaded.load_warning
    assert loaded.data["version"] == Cache._CACHE_VERSION
    assert loaded.data["files"] == {}


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


def test_cache_entry_not_dict(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.data["files"]["x.py"] = cast(Any, ["bad"])
    assert cache.get_file_entry("x.py") is None


def test_cache_load_corrupted_json(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache_path.write_text("{invalid json", "utf-8")
    cache = Cache(cache_path)
    cache.load()
    assert cache.load_warning is not None
    assert "corrupted" in cache.load_warning


def test_cache_load_invalid_files_type(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    data = {"version": cache._CACHE_VERSION, "files": []}
    signature = cache._sign_data(data)
    cache_path.write_text(json.dumps({**data, "_signature": signature}), "utf-8")
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
        if self == cache_path:
            raise OSError("nope")
        return original_write_text(
            self, data, encoding=encoding, errors=errors, newline=newline
        )

    monkeypatch.setattr(Path, "write_text", _raise_write_text)

    with pytest.raises(CacheError):
        cache.save()


def test_cache_secret_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    secret_path = cache_path.parent / ".cache_secret"
    original_write_bytes = Path.write_bytes

    def _raise_write_bytes(self: Path, data: bytes) -> int:
        if self == secret_path:
            raise OSError("nope")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", _raise_write_bytes)
    cache = Cache(cache_path)
    assert isinstance(cache.secret, bytes)
    assert len(cache.secret) == 32


def test_cache_secret_chmod_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    secret_path = cache_path.parent / ".cache_secret"

    original_write_bytes = Path.write_bytes
    original_chmod = Path.chmod

    def _write_bytes(self: Path, data: bytes) -> int:
        return original_write_bytes(self, data)

    def _raise_chmod(self: Path, _mode: int) -> None:
        if self == secret_path:
            raise OSError("nope")
        return original_chmod(self, _mode)

    monkeypatch.setattr(Path, "write_bytes", _write_bytes)
    monkeypatch.setattr(Path, "chmod", _raise_chmod)
    monkeypatch.setattr(os, "name", "posix")

    cache = Cache(cache_path)
    assert isinstance(cache.secret, bytes)


def test_cache_secret_non_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr("codeclone.cache.OS_NAME", "nt")
    cache = Cache(cache_path)
    secret_path = cache_path.parent / ".cache_secret"
    assert secret_path.exists()
    assert isinstance(cache.secret, bytes)


def test_cache_secret_read_failure_graceful_ignore(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.json"
    cache = Cache(cache_path)
    cache.put_file_entry("x.py", {"mtime_ns": 1, "size": 10}, [], [], [])
    cache.save()

    secret_path = cache_path.parent / ".cache_secret"
    secret_path.unlink()
    secret_path.mkdir()

    loaded = Cache(cache_path)
    loaded.load()
    assert loaded.load_warning is not None
    assert "signature mismatch" in loaded.load_warning
    assert loaded.data["files"] == {}
