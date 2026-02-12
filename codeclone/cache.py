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
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from .blocks import BlockUnit, SegmentUnit
    from .extractor import Unit

from .baseline import current_python_tag
from .contracts import BASELINE_FINGERPRINT_VERSION, CACHE_VERSION
from .errors import CacheError

MAX_CACHE_SIZE_BYTES = 50 * 1024 * 1024
LEGACY_CACHE_SECRET_FILENAME = ".cache_secret"


class CacheStatus(str, Enum):
    OK = "ok"
    MISSING = "missing"
    TOO_LARGE = "too_large"
    UNREADABLE = "unreadable"
    INVALID_JSON = "invalid_json"
    INVALID_TYPE = "invalid_type"
    VERSION_MISMATCH = "version_mismatch"
    PYTHON_TAG_MISMATCH = "python_tag_mismatch"
    FINGERPRINT_MISMATCH = "mismatch_fingerprint_version"
    INTEGRITY_FAILED = "integrity_failed"


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
    python_tag: str
    fingerprint_version: str
    files: dict[str, CacheEntry]


class Cache:
    __slots__ = (
        "cache_schema_version",
        "data",
        "fingerprint_version",
        "legacy_secret_warning",
        "load_status",
        "load_warning",
        "max_size_bytes",
        "path",
        "root",
    )

    _CACHE_VERSION = CACHE_VERSION

    def __init__(
        self,
        path: str | Path,
        *,
        root: str | Path | None = None,
        max_size_bytes: int | None = None,
    ):
        self.path = Path(path)
        self.root = _resolve_root(root)
        self.fingerprint_version = BASELINE_FINGERPRINT_VERSION
        self.data: CacheData = _empty_cache_data(
            version=self._CACHE_VERSION,
            python_tag=current_python_tag(),
            fingerprint_version=self.fingerprint_version,
        )
        self.legacy_secret_warning = self._detect_legacy_secret_warning()
        self.cache_schema_version: str | None = None
        self.load_status = CacheStatus.MISSING
        self.load_warning: str | None = self.legacy_secret_warning
        self.max_size_bytes = (
            MAX_CACHE_SIZE_BYTES if max_size_bytes is None else max_size_bytes
        )

    def _detect_legacy_secret_warning(self) -> str | None:
        secret_path = self.path.parent / LEGACY_CACHE_SECRET_FILENAME
        try:
            if secret_path.exists():
                return (
                    f"Legacy cache secret file detected at {secret_path}; "
                    "delete this obsolete file."
                )
        except OSError as e:
            return f"Legacy cache secret check failed: {e}"
        return None

    def _set_load_warning(self, message: str | None) -> None:
        if message is None:
            self.load_warning = self.legacy_secret_warning
            return
        if self.legacy_secret_warning:
            self.load_warning = f"{message}\n{self.legacy_secret_warning}"
            return
        self.load_warning = message

    def _ignore_cache(
        self,
        message: str,
        *,
        status: CacheStatus,
        schema_version: str | None = None,
    ) -> None:
        self._set_load_warning(message)
        self.load_status = status
        self.cache_schema_version = schema_version
        self.data = _empty_cache_data(
            version=self._CACHE_VERSION,
            python_tag=current_python_tag(),
            fingerprint_version=self.fingerprint_version,
        )

    def _sign_data(self, data: Mapping[str, object]) -> str:
        """Create deterministic SHA-256 signature for canonical payload data."""
        canonical = _canonical_json(data)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def load(self) -> None:
        try:
            exists = self.path.exists()
        except OSError as e:
            self._ignore_cache(
                f"Cache unreadable; ignoring cache: {e}",
                status=CacheStatus.UNREADABLE,
            )
            return

        if not exists:
            self._set_load_warning(None)
            self.load_status = CacheStatus.MISSING
            self.cache_schema_version = None
            return

        try:
            size = self.path.stat().st_size
            if size > self.max_size_bytes:
                self._ignore_cache(
                    "Cache file too large "
                    f"({size} bytes, max {self.max_size_bytes}); ignoring cache.",
                    status=CacheStatus.TOO_LARGE,
                )
                return

            raw_obj: object = json.loads(self.path.read_text("utf-8"))
            parsed = self._parse_cache_document(raw_obj)
            if parsed is None:
                return
            self.data = parsed
            self.load_status = CacheStatus.OK
            self._set_load_warning(None)

        except OSError as e:
            self._ignore_cache(
                f"Cache unreadable; ignoring cache: {e}",
                status=CacheStatus.UNREADABLE,
            )
        except json.JSONDecodeError:
            self._ignore_cache(
                "Cache corrupted; ignoring cache.",
                status=CacheStatus.INVALID_JSON,
            )

    def _parse_cache_document(self, raw_obj: object) -> CacheData | None:
        raw = _as_str_dict(raw_obj)
        if raw is None:
            self._ignore_cache(
                "Cache format invalid; ignoring cache.",
                status=CacheStatus.INVALID_TYPE,
            )
            return None

        # Legacy cache format: top-level {version, files, _signature}.
        legacy_version = _as_str(raw.get("version"))
        if legacy_version is not None:
            self._ignore_cache(
                f"Cache version mismatch (found {legacy_version}); ignoring cache.",
                status=CacheStatus.VERSION_MISMATCH,
                schema_version=legacy_version,
            )
            return None

        version = _as_str(raw.get("v"))
        if version is None:
            self._ignore_cache(
                "Cache format invalid; ignoring cache.",
                status=CacheStatus.INVALID_TYPE,
            )
            return None

        if version != self._CACHE_VERSION:
            self._ignore_cache(
                f"Cache version mismatch (found {version}); ignoring cache.",
                status=CacheStatus.VERSION_MISMATCH,
                schema_version=version,
            )
            return None

        sig = _as_str(raw.get("sig"))
        payload_obj = raw.get("payload")
        payload = _as_str_dict(payload_obj)
        if sig is None or payload is None:
            self._ignore_cache(
                "Cache format invalid; ignoring cache.",
                status=CacheStatus.INVALID_TYPE,
                schema_version=version,
            )
            return None

        expected_sig = self._sign_data(payload)
        if not hmac.compare_digest(sig, expected_sig):
            self._ignore_cache(
                "Cache signature mismatch; ignoring cache.",
                status=CacheStatus.INTEGRITY_FAILED,
                schema_version=version,
            )
            return None

        runtime_tag = current_python_tag()
        py_tag = _as_str(payload.get("py"))
        if py_tag is None:
            self._ignore_cache(
                "Cache format invalid; ignoring cache.",
                status=CacheStatus.INVALID_TYPE,
                schema_version=version,
            )
            return None

        if py_tag != runtime_tag:
            self._ignore_cache(
                "Cache python tag mismatch "
                f"(found {py_tag}, expected {runtime_tag}); ignoring cache.",
                status=CacheStatus.PYTHON_TAG_MISMATCH,
                schema_version=version,
            )
            return None

        fp_version = _as_str(payload.get("fp"))
        if fp_version is None:
            self._ignore_cache(
                "Cache format invalid; ignoring cache.",
                status=CacheStatus.INVALID_TYPE,
                schema_version=version,
            )
            return None

        if fp_version != self.fingerprint_version:
            self._ignore_cache(
                "Cache fingerprint version mismatch "
                f"(found {fp_version}, expected {self.fingerprint_version}); "
                "ignoring cache.",
                status=CacheStatus.FINGERPRINT_MISMATCH,
                schema_version=version,
            )
            return None

        files_obj = payload.get("files")
        files_dict = _as_str_dict(files_obj)
        if files_dict is None:
            self._ignore_cache(
                "Cache format invalid; ignoring cache.",
                status=CacheStatus.INVALID_TYPE,
                schema_version=version,
            )
            return None

        parsed_files: dict[str, CacheEntry] = {}
        for wire_path, file_entry_obj in files_dict.items():
            runtime_path = self._runtime_filepath_from_wire(wire_path)
            parsed_entry = _decode_wire_file_entry(file_entry_obj, runtime_path)
            if parsed_entry is None:
                self._ignore_cache(
                    "Cache format invalid; ignoring cache.",
                    status=CacheStatus.INVALID_TYPE,
                    schema_version=version,
                )
                return None
            parsed_files[runtime_path] = parsed_entry

        self.cache_schema_version = version
        return {
            "version": self._CACHE_VERSION,
            "python_tag": runtime_tag,
            "fingerprint_version": self.fingerprint_version,
            "files": parsed_files,
        }

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            wire_files: dict[str, object] = {}
            for runtime_path in sorted(
                self.data["files"], key=self._wire_filepath_from_runtime
            ):
                entry = self.get_file_entry(runtime_path)
                if entry is None:
                    continue
                wire_path = self._wire_filepath_from_runtime(runtime_path)
                wire_files[wire_path] = _encode_wire_file_entry(entry)

            payload: dict[str, object] = {
                "py": current_python_tag(),
                "fp": self.fingerprint_version,
                "files": wire_files,
            }
            signed_doc = {
                "v": self._CACHE_VERSION,
                "payload": payload,
                "sig": self._sign_data(payload),
            }

            tmp_path = self.path.with_name(f"{self.path.name}.tmp")
            tmp_path.write_text(_canonical_json(signed_doc), "utf-8")
            os.replace(tmp_path, self.path)

            self.data["version"] = self._CACHE_VERSION
            self.data["python_tag"] = current_python_tag()
            self.data["fingerprint_version"] = self.fingerprint_version

        except OSError as e:
            raise CacheError(f"Failed to save cache: {e}") from e

    def _wire_filepath_from_runtime(self, runtime_filepath: str) -> str:
        runtime_path = Path(runtime_filepath)
        if self.root is None:
            return runtime_path.as_posix()

        try:
            relative = runtime_path.relative_to(self.root)
            return relative.as_posix()
        except ValueError:
            pass

        try:
            relative = runtime_path.resolve().relative_to(self.root.resolve())
            return relative.as_posix()
        except OSError:
            return runtime_path.as_posix()
        except ValueError:
            return runtime_path.as_posix()

    def _runtime_filepath_from_wire(self, wire_filepath: str) -> str:
        wire_path = Path(wire_filepath)
        if self.root is None or wire_path.is_absolute():
            return str(wire_path)

        combined = self.root / wire_path
        try:
            return str(combined.resolve(strict=False))
        except OSError:
            return str(combined)

    def get_file_entry(self, filepath: str) -> CacheEntry | None:
        entry = self.data["files"].get(filepath)
        if entry is None:
            wire_key = self._wire_filepath_from_runtime(filepath)
            runtime_key = self._runtime_filepath_from_wire(wire_key)
            entry = self.data["files"].get(runtime_key)

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
        runtime_path = self._runtime_filepath_from_wire(
            self._wire_filepath_from_runtime(filepath)
        )

        unit_rows: list[UnitDict] = [
            {
                "qualname": unit.qualname,
                "filepath": runtime_path,
                "start_line": unit.start_line,
                "end_line": unit.end_line,
                "loc": unit.loc,
                "stmt_count": unit.stmt_count,
                "fingerprint": unit.fingerprint,
                "loc_bucket": unit.loc_bucket,
            }
            for unit in units
        ]

        block_rows: list[BlockDict] = [
            {
                "block_hash": block.block_hash,
                "filepath": runtime_path,
                "qualname": block.qualname,
                "start_line": block.start_line,
                "end_line": block.end_line,
                "size": block.size,
            }
            for block in blocks
        ]

        segment_rows: list[SegmentDict] = [
            {
                "segment_hash": segment.segment_hash,
                "segment_sig": segment.segment_sig,
                "filepath": runtime_path,
                "qualname": segment.qualname,
                "start_line": segment.start_line,
                "end_line": segment.end_line,
                "size": segment.size,
            }
            for segment in segments
        ]

        self.data["files"][runtime_path] = {
            "stat": stat_sig,
            "units": unit_rows,
            "blocks": block_rows,
            "segments": segment_rows,
        }


def file_stat_signature(path: str) -> FileStat:
    st = os.stat(path)
    return {
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
    }


def _empty_cache_data(
    *,
    version: str,
    python_tag: str,
    fingerprint_version: str,
) -> CacheData:
    return {
        "version": version,
        "python_tag": python_tag,
        "fingerprint_version": fingerprint_version,
        "files": {},
    }


def _canonical_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _as_list(value: object) -> list[object] | None:
    return value if isinstance(value, list) else None


def _as_str_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    for key in value:
        if not isinstance(key, str):
            return None
    return value


def _decode_wire_file_entry(value: object, filepath: str) -> CacheEntry | None:
    obj = _as_str_dict(value)
    if obj is None:
        return None

    stat_obj = obj.get("st")
    stat_list = _as_list(stat_obj)
    if stat_list is None or len(stat_list) != 2:
        return None
    mtime_ns = _as_int(stat_list[0])
    size = _as_int(stat_list[1])
    if mtime_ns is None or size is None:
        return None

    units: list[UnitDict] = []
    blocks: list[BlockDict] = []
    segments: list[SegmentDict] = []

    units_obj = obj.get("u")
    if units_obj is not None:
        units_list = _as_list(units_obj)
        if units_list is None:
            return None
        for unit_obj in units_list:
            decoded_unit = _decode_wire_unit(unit_obj, filepath)
            if decoded_unit is None:
                return None
            units.append(decoded_unit)

    blocks_obj = obj.get("b")
    if blocks_obj is not None:
        blocks_list = _as_list(blocks_obj)
        if blocks_list is None:
            return None
        for block_obj in blocks_list:
            decoded_block = _decode_wire_block(block_obj, filepath)
            if decoded_block is None:
                return None
            blocks.append(decoded_block)

    segments_obj = obj.get("s")
    if segments_obj is not None:
        segments_list = _as_list(segments_obj)
        if segments_list is None:
            return None
        for segment_obj in segments_list:
            decoded_segment = _decode_wire_segment(segment_obj, filepath)
            if decoded_segment is None:
                return None
            segments.append(decoded_segment)

    return {
        "stat": {"mtime_ns": mtime_ns, "size": size},
        "units": units,
        "blocks": blocks,
        "segments": segments,
    }


def _decode_wire_unit(value: object, filepath: str) -> UnitDict | None:
    row = _as_list(value)
    if row is None or len(row) != 7:
        return None

    qualname = _as_str(row[0])
    start_line = _as_int(row[1])
    end_line = _as_int(row[2])
    loc = _as_int(row[3])
    stmt_count = _as_int(row[4])
    fingerprint = _as_str(row[5])
    loc_bucket = _as_str(row[6])

    if (
        qualname is None
        or start_line is None
        or end_line is None
        or loc is None
        or stmt_count is None
        or fingerprint is None
        or loc_bucket is None
    ):
        return None

    return {
        "qualname": qualname,
        "filepath": filepath,
        "start_line": start_line,
        "end_line": end_line,
        "loc": loc,
        "stmt_count": stmt_count,
        "fingerprint": fingerprint,
        "loc_bucket": loc_bucket,
    }


def _decode_wire_block(value: object, filepath: str) -> BlockDict | None:
    row = _as_list(value)
    if row is None or len(row) != 5:
        return None

    qualname = _as_str(row[0])
    start_line = _as_int(row[1])
    end_line = _as_int(row[2])
    size = _as_int(row[3])
    block_hash = _as_str(row[4])

    if (
        qualname is None
        or start_line is None
        or end_line is None
        or size is None
        or block_hash is None
    ):
        return None

    return {
        "block_hash": block_hash,
        "filepath": filepath,
        "qualname": qualname,
        "start_line": start_line,
        "end_line": end_line,
        "size": size,
    }


def _decode_wire_segment(value: object, filepath: str) -> SegmentDict | None:
    row = _as_list(value)
    if row is None or len(row) != 6:
        return None

    qualname = _as_str(row[0])
    start_line = _as_int(row[1])
    end_line = _as_int(row[2])
    size = _as_int(row[3])
    segment_hash = _as_str(row[4])
    segment_sig = _as_str(row[5])

    if (
        qualname is None
        or start_line is None
        or end_line is None
        or size is None
        or segment_hash is None
        or segment_sig is None
    ):
        return None

    return {
        "segment_hash": segment_hash,
        "segment_sig": segment_sig,
        "filepath": filepath,
        "qualname": qualname,
        "start_line": start_line,
        "end_line": end_line,
        "size": size,
    }


def _encode_wire_file_entry(entry: CacheEntry) -> dict[str, object]:
    wire: dict[str, object] = {
        "st": [entry["stat"]["mtime_ns"], entry["stat"]["size"]],
    }

    units = sorted(
        entry["units"],
        key=lambda unit: (
            unit["qualname"],
            unit["start_line"],
            unit["end_line"],
            unit["fingerprint"],
        ),
    )
    if units:
        wire["u"] = [
            [
                unit["qualname"],
                unit["start_line"],
                unit["end_line"],
                unit["loc"],
                unit["stmt_count"],
                unit["fingerprint"],
                unit["loc_bucket"],
            ]
            for unit in units
        ]

    blocks = sorted(
        entry["blocks"],
        key=lambda block: (
            block["qualname"],
            block["start_line"],
            block["end_line"],
            block["block_hash"],
        ),
    )
    if blocks:
        wire["b"] = [
            [
                block["qualname"],
                block["start_line"],
                block["end_line"],
                block["size"],
                block["block_hash"],
            ]
            for block in blocks
        ]

    segments = sorted(
        entry["segments"],
        key=lambda segment: (
            segment["qualname"],
            segment["start_line"],
            segment["end_line"],
            segment["segment_hash"],
        ),
    )
    if segments:
        wire["s"] = [
            [
                segment["qualname"],
                segment["start_line"],
                segment["end_line"],
                segment["size"],
                segment["segment_hash"],
                segment["segment_sig"],
            ]
            for segment in segments
        ]

    return wire


def _resolve_root(root: str | Path | None) -> Path | None:
    if root is None:
        return None
    try:
        return Path(root).resolve(strict=False)
    except OSError:
        return None


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
    value: Mapping[str, object],
    *,
    string_keys: Sequence[str],
    int_keys: Sequence[str],
) -> bool:
    return all(isinstance(value.get(key), str) for key in string_keys) and all(
        isinstance(value.get(key), int) for key in int_keys
    )
