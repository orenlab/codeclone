"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict, cast

if TYPE_CHECKING:
    from .blocks import BlockUnit, SegmentUnit
    from .extractor import Unit

from .contracts import CACHE_VERSION
from .errors import CacheError

# Any: cache JSON payload boundary before per-entry structural validation.

OS_NAME = os.name
MAX_CACHE_SIZE_BYTES = 50 * 1024 * 1024


class FileStat(TypedDict):
    mtime_ns: int
    size: int


class UnitDict(TypedDict):
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    loc: int
    stmt_count: int
    fingerprint: str
    loc_bucket: str


class BlockDict(TypedDict):
    block_hash: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


class SegmentDict(TypedDict):
    segment_hash: str
    segment_sig: str
    filepath: str
    qualname: str
    start_line: int
    end_line: int
    size: int


class CacheEntry(TypedDict):
    stat: FileStat
    units: list[UnitDict]
    blocks: list[BlockDict]
    segments: list[SegmentDict]


class CacheData(TypedDict):
    version: str
    files: dict[str, CacheEntry]


class Cache:
    __slots__ = ("data", "load_warning", "max_size_bytes", "path", "secret")
    _CACHE_VERSION = CACHE_VERSION

    def __init__(self, path: str | Path, *, max_size_bytes: int | None = None):
        self.path = Path(path)
        self.data: CacheData = {"version": self._CACHE_VERSION, "files": {}}
        self.secret = self._load_secret()
        self.load_warning: str | None = None
        self.max_size_bytes = (
            MAX_CACHE_SIZE_BYTES if max_size_bytes is None else max_size_bytes
        )

    def _load_secret(self) -> bytes:
        """Load or create cache signing secret."""
        # Store secret in the same directory as the cache file, named .cache_secret
        # If cache is at ~/.cache/codeclone/cache.json, secret is
        # ~/.cache/codeclone/.cache_secret
        secret_path = self.path.parent / ".cache_secret"
        if secret_path.exists():
            return secret_path.read_bytes()
        else:
            secret = secrets.token_bytes(32)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                secret_path.write_bytes(secret)
                # Set restrictive permissions on secret file (Unix only)
                if OS_NAME == "posix":
                    secret_path.chmod(0o600)
            except OSError:
                pass
            return secret

    def _sign_data(self, data: Mapping[str, Any]) -> str:
        """Create HMAC signature of cache data."""
        # Sort keys for deterministic JSON serialization
        data_str = json.dumps(data, sort_keys=True)
        return hmac.new(self.secret, data_str.encode(), hashlib.sha256).hexdigest()

    def load(self) -> None:
        if not self.path.exists():
            return

        try:
            size = self.path.stat().st_size
            if size > self.max_size_bytes:
                self.load_warning = (
                    "Cache file too large "
                    f"({size} bytes, max {self.max_size_bytes}); ignoring cache."
                )
                self.data = {"version": self._CACHE_VERSION, "files": {}}
                return

            raw = json.loads(self.path.read_text("utf-8"))
            stored_sig = raw.get("_signature")

            # Extract data without signature for verification
            data = {k: v for k, v in raw.items() if k != "_signature"}

            # Verify signature
            expected_sig = self._sign_data(data)
            if not (
                isinstance(stored_sig, str)
                and hmac.compare_digest(stored_sig, expected_sig)
            ):
                self.load_warning = "Cache signature mismatch; ignoring cache."
                self.data = {"version": self._CACHE_VERSION, "files": {}}
                return

            if data.get("version") != self._CACHE_VERSION:
                self.load_warning = (
                    "Cache version mismatch "
                    f"(found {data.get('version')}); ignoring cache."
                )
                self.data = {"version": self._CACHE_VERSION, "files": {}}
                return

            # Basic structure check
            if not isinstance(data.get("files"), dict):
                self.load_warning = "Cache format invalid; ignoring cache."
                self.data = {"version": self._CACHE_VERSION, "files": {}}
                return

            self.data = cast(CacheData, cast(object, data))
            self.load_warning = None

        except (json.JSONDecodeError, ValueError):
            self.load_warning = "Cache corrupted; ignoring cache."
            self.data = {"version": self._CACHE_VERSION, "files": {}}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)

            # Add signature
            data_with_sig = {**self.data, "_signature": self._sign_data(self.data)}

            self.path.write_text(
                json.dumps(data_with_sig, ensure_ascii=False, indent=2),
                "utf-8",
            )
        except OSError as e:
            raise CacheError(f"Failed to save cache: {e}") from e

    def get_file_entry(self, filepath: str) -> CacheEntry | None:
        entry = self.data["files"].get(filepath)

        if entry is None:
            return None

        if not isinstance(entry, dict):
            return None

        required = {"stat", "units", "blocks", "segments"}
        if not required.issubset(entry.keys()):
            return None

        stat = entry.get("stat")
        units = entry.get("units")
        blocks = entry.get("blocks")
        segments = entry.get("segments")
        if not (
            _is_file_stat_dict(stat)
            and _is_unit_list(units)
            and _is_block_list(blocks)
            and _is_segment_list(segments)
        ):
            return None

        return entry

    def put_file_entry(
        self,
        filepath: str,
        stat_sig: FileStat,
        units: list[Unit],
        blocks: list[BlockUnit],
        segments: list[SegmentUnit],
    ) -> None:
        self.data["files"][filepath] = {
            "stat": stat_sig,
            "units": cast(list[UnitDict], cast(object, [asdict(u) for u in units])),
            "blocks": cast(list[BlockDict], cast(object, [asdict(b) for b in blocks])),
            "segments": cast(
                list[SegmentDict], cast(object, [asdict(s) for s in segments])
            ),
        }


def file_stat_signature(path: str) -> FileStat:
    st = os.stat(path)
    return {
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
    }


def _is_file_stat_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return isinstance(value.get("mtime_ns"), int) and isinstance(value.get("size"), int)


def _is_unit_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    string_keys = ("qualname", "filepath", "fingerprint", "loc_bucket")
    int_keys = ("start_line", "end_line", "loc", "stmt_count")
    return _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys)


def _is_block_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    string_keys = ("block_hash", "filepath", "qualname")
    int_keys = ("start_line", "end_line", "size")
    return _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys)


def _is_segment_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    string_keys = ("segment_hash", "segment_sig", "filepath", "qualname")
    int_keys = ("start_line", "end_line", "size")
    return _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys)


def _is_unit_list(value: object) -> bool:
    return isinstance(value, list) and all(_is_unit_dict(item) for item in value)


def _is_block_list(value: object) -> bool:
    return isinstance(value, list) and all(_is_block_dict(item) for item in value)


def _is_segment_list(value: object) -> bool:
    return isinstance(value, list) and all(_is_segment_dict(item) for item in value)


def _has_typed_fields(
    value: dict[str, object],
    *,
    string_keys: tuple[str, ...],
    int_keys: tuple[str, ...],
) -> bool:
    return all(isinstance(value.get(key), str) for key in string_keys) and all(
        isinstance(value.get(key), int) for key in int_keys
    )
