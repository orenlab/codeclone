# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Literal, TypedDict, TypeVar, cast

from .baseline import current_python_tag
from .contracts import BASELINE_FINGERPRINT_VERSION, CACHE_VERSION
from .errors import CacheError
from .models import (
    BlockGroupItem,
    BlockUnit,
    FileMetrics,
    FunctionGroupItem,
    SegmentGroupItem,
    SegmentUnit,
    Unit,
)

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
    ANALYSIS_PROFILE_MISMATCH = "analysis_profile_mismatch"
    INTEGRITY_FAILED = "integrity_failed"


class FileStat(TypedDict):
    mtime_ns: int
    size: int


UnitDict = FunctionGroupItem
BlockDict = BlockGroupItem
SegmentDict = SegmentGroupItem


class ClassMetricsDictBase(TypedDict):
    qualname: str
    filepath: str
    start_line: int
    end_line: int
    cbo: int
    lcom4: int
    method_count: int
    instance_var_count: int
    risk_coupling: str
    risk_cohesion: str


class ClassMetricsDict(ClassMetricsDictBase, total=False):
    coupled_classes: list[str]


class ModuleDepDict(TypedDict):
    source: str
    target: str
    import_type: str
    line: int


class DeadCandidateDict(TypedDict):
    qualname: str
    local_name: str
    filepath: str
    start_line: int
    end_line: int
    kind: str


class CacheEntryBase(TypedDict):
    stat: FileStat
    units: list[UnitDict]
    blocks: list[BlockDict]
    segments: list[SegmentDict]


class CacheEntry(CacheEntryBase, total=False):
    class_metrics: list[ClassMetricsDict]
    module_deps: list[ModuleDepDict]
    dead_candidates: list[DeadCandidateDict]
    referenced_names: list[str]
    import_names: list[str]
    class_names: list[str]


class AnalysisProfile(TypedDict):
    min_loc: int
    min_stmt: int


class CacheData(TypedDict):
    version: str
    python_tag: str
    fingerprint_version: str
    analysis_profile: AnalysisProfile
    files: dict[str, CacheEntry]


_DecodedItemT = TypeVar("_DecodedItemT")


class Cache:
    __slots__ = (
        "_canonical_runtime_paths",
        "analysis_profile",
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
        min_loc: int = 15,
        min_stmt: int = 6,
    ):
        self.path = Path(path)
        self.root = _resolve_root(root)
        self.fingerprint_version = BASELINE_FINGERPRINT_VERSION
        self.analysis_profile: AnalysisProfile = {
            "min_loc": min_loc,
            "min_stmt": min_stmt,
        }
        self.data: CacheData = _empty_cache_data(
            version=self._CACHE_VERSION,
            python_tag=current_python_tag(),
            fingerprint_version=self.fingerprint_version,
            analysis_profile=self.analysis_profile,
        )
        self._canonical_runtime_paths: set[str] = set()
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
            analysis_profile=self.analysis_profile,
        )
        self._canonical_runtime_paths = set()

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
            self._canonical_runtime_paths = set()
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
            parsed = self._load_and_validate(raw_obj)
            if parsed is None:
                return
            self.data = parsed
            self._canonical_runtime_paths = set(parsed["files"].keys())
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

    def _load_and_validate(self, raw_obj: object) -> CacheData | None:
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

        analysis_profile = _as_analysis_profile(payload.get("ap"))
        if analysis_profile is None:
            self._ignore_cache(
                "Cache format invalid; ignoring cache.",
                status=CacheStatus.INVALID_TYPE,
                schema_version=version,
            )
            return None

        if analysis_profile != self.analysis_profile:
            self._ignore_cache(
                "Cache analysis profile mismatch "
                f"(found min_loc={analysis_profile['min_loc']}, "
                f"min_stmt={analysis_profile['min_stmt']}; "
                f"expected min_loc={self.analysis_profile['min_loc']}, "
                f"min_stmt={self.analysis_profile['min_stmt']}); "
                "ignoring cache.",
                status=CacheStatus.ANALYSIS_PROFILE_MISMATCH,
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
            parsed_entry = self._decode_entry(file_entry_obj, runtime_path)
            if parsed_entry is None:
                self._ignore_cache(
                    "Cache format invalid; ignoring cache.",
                    status=CacheStatus.INVALID_TYPE,
                    schema_version=version,
                )
                return None
            parsed_files[runtime_path] = _canonicalize_cache_entry(parsed_entry)

        self.cache_schema_version = version
        return {
            "version": self._CACHE_VERSION,
            "python_tag": runtime_tag,
            "fingerprint_version": self.fingerprint_version,
            "analysis_profile": self.analysis_profile,
            "files": parsed_files,
        }

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            wire_files: dict[str, object] = {}
            wire_map = {
                rp: self._wire_filepath_from_runtime(rp) for rp in self.data["files"]
            }
            for runtime_path in sorted(self.data["files"], key=wire_map.__getitem__):
                entry = self.get_file_entry(runtime_path)
                if entry is None:
                    continue
                wire_files[wire_map[runtime_path]] = self._encode_entry(entry)

            payload: dict[str, object] = {
                "py": current_python_tag(),
                "fp": self.fingerprint_version,
                "ap": self.analysis_profile,
                "files": wire_files,
            }
            signed_doc = {
                "v": self._CACHE_VERSION,
                "payload": payload,
                "sig": self._sign_data(payload),
            }

            tmp_path = self.path.with_name(f"{self.path.name}.tmp")
            data = _canonical_json(signed_doc).encode("utf-8")
            with tmp_path.open("wb") as tmp_file:
                tmp_file.write(data)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, self.path)

            self.data["version"] = self._CACHE_VERSION
            self.data["python_tag"] = current_python_tag()
            self.data["fingerprint_version"] = self.fingerprint_version
            self.data["analysis_profile"] = self.analysis_profile

        except OSError as e:
            raise CacheError(f"Failed to save cache: {e}") from e

    def _decode_entry(self, value: object, filepath: str) -> CacheEntry | None:
        return _decode_wire_file_entry(value, filepath)

    def _encode_entry(self, entry: CacheEntry) -> dict[str, object]:
        return _encode_wire_file_entry(entry)

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
        runtime_lookup_key = filepath
        entry = self.data["files"].get(runtime_lookup_key)
        if entry is None:
            wire_key = self._wire_filepath_from_runtime(filepath)
            runtime_lookup_key = self._runtime_filepath_from_wire(wire_key)
            entry = self.data["files"].get(runtime_lookup_key)

        if entry is None:
            return None

        if not isinstance(entry, dict):
            return None

        if runtime_lookup_key in self._canonical_runtime_paths:
            if _has_cache_entry_container_shape(entry):
                return entry
            self._canonical_runtime_paths.discard(runtime_lookup_key)

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

        class_metrics_raw = entry.get("class_metrics", [])
        module_deps_raw = entry.get("module_deps", [])
        dead_candidates_raw = entry.get("dead_candidates", [])
        referenced_names_raw = entry.get("referenced_names", [])
        import_names_raw = entry.get("import_names", [])
        class_names_raw = entry.get("class_names", [])
        if not (
            _is_class_metrics_list(class_metrics_raw)
            and _is_module_deps_list(module_deps_raw)
            and _is_dead_candidates_list(dead_candidates_raw)
            and _is_string_list(referenced_names_raw)
            and _is_string_list(import_names_raw)
            and _is_string_list(class_names_raw)
        ):
            return None

        canonical_entry = _canonicalize_cache_entry(
            {
                "stat": stat,
                "units": units,
                "blocks": blocks,
                "segments": segments,
                "class_metrics": class_metrics_raw,
                "module_deps": module_deps_raw,
                "dead_candidates": dead_candidates_raw,
                "referenced_names": referenced_names_raw,
                "import_names": import_names_raw,
                "class_names": class_names_raw,
            }
        )
        self.data["files"][runtime_lookup_key] = canonical_entry
        self._canonical_runtime_paths.add(runtime_lookup_key)
        return canonical_entry

    def put_file_entry(
        self,
        filepath: str,
        stat_sig: FileStat,
        units: list[Unit],
        blocks: list[BlockUnit],
        segments: list[SegmentUnit],
        *,
        file_metrics: FileMetrics | None = None,
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
                "cyclomatic_complexity": unit.cyclomatic_complexity,
                "nesting_depth": unit.nesting_depth,
                "risk": unit.risk,
                "raw_hash": unit.raw_hash,
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

        (
            class_metrics_rows,
            module_dep_rows,
            dead_candidate_rows,
            referenced_names,
            import_names,
            class_names,
        ) = _new_optional_metrics_payload()
        if file_metrics is not None:
            class_metrics_rows = [
                {
                    "qualname": metric.qualname,
                    "filepath": runtime_path,
                    "start_line": metric.start_line,
                    "end_line": metric.end_line,
                    "cbo": metric.cbo,
                    "lcom4": metric.lcom4,
                    "method_count": metric.method_count,
                    "instance_var_count": metric.instance_var_count,
                    "risk_coupling": metric.risk_coupling,
                    "risk_cohesion": metric.risk_cohesion,
                    "coupled_classes": sorted(set(metric.coupled_classes)),
                }
                for metric in file_metrics.class_metrics
            ]
            module_dep_rows = [
                {
                    "source": dep.source,
                    "target": dep.target,
                    "import_type": dep.import_type,
                    "line": dep.line,
                }
                for dep in file_metrics.module_deps
            ]
            dead_candidate_rows = [
                {
                    "qualname": candidate.qualname,
                    "local_name": candidate.local_name,
                    "filepath": runtime_path,
                    "start_line": candidate.start_line,
                    "end_line": candidate.end_line,
                    "kind": candidate.kind,
                }
                for candidate in file_metrics.dead_candidates
            ]
            referenced_names = sorted(set(file_metrics.referenced_names))
            import_names = sorted(set(file_metrics.import_names))
            class_names = sorted(set(file_metrics.class_names))

        canonical_entry = _canonicalize_cache_entry(
            {
                "stat": stat_sig,
                "units": unit_rows,
                "blocks": block_rows,
                "segments": segment_rows,
                "class_metrics": class_metrics_rows,
                "module_deps": module_dep_rows,
                "dead_candidates": dead_candidate_rows,
                "referenced_names": referenced_names,
                "import_names": import_names,
                "class_names": class_names,
            }
        )
        self.data["files"][runtime_path] = canonical_entry
        self._canonical_runtime_paths.add(runtime_path)


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
    analysis_profile: AnalysisProfile,
) -> CacheData:
    return {
        "version": version,
        "python_tag": python_tag,
        "fingerprint_version": fingerprint_version,
        "analysis_profile": analysis_profile,
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


def _new_optional_metrics_payload() -> tuple[
    list[ClassMetricsDict],
    list[ModuleDepDict],
    list[DeadCandidateDict],
    list[str],
    list[str],
    list[str],
]:
    return [], [], [], [], [], []


def _has_cache_entry_container_shape(entry: Mapping[str, object]) -> bool:
    required = {"stat", "units", "blocks", "segments"}
    if not required.issubset(entry.keys()):
        return False
    if not isinstance(entry.get("stat"), dict):
        return False
    if not isinstance(entry.get("units"), list):
        return False
    if not isinstance(entry.get("blocks"), list):
        return False
    if not isinstance(entry.get("segments"), list):
        return False
    optional_list_keys = (
        "class_metrics",
        "module_deps",
        "dead_candidates",
        "referenced_names",
        "import_names",
        "class_names",
    )
    return all(isinstance(entry.get(key, []), list) for key in optional_list_keys)


def _canonicalize_cache_entry(entry: CacheEntry) -> CacheEntry:
    class_metrics_sorted = sorted(
        entry["class_metrics"],
        key=lambda item: (
            item["filepath"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )
    for metric in class_metrics_sorted:
        coupled_classes = metric.get("coupled_classes", [])
        if coupled_classes:
            metric["coupled_classes"] = sorted(set(coupled_classes))

    module_deps_sorted = sorted(
        entry["module_deps"],
        key=lambda item: (
            item["source"],
            item["target"],
            item["import_type"],
            item["line"],
        ),
    )
    dead_candidates_sorted = sorted(
        entry["dead_candidates"],
        key=lambda item: (
            item["filepath"],
            item["start_line"],
            item["end_line"],
            item["qualname"],
        ),
    )

    return {
        "stat": entry["stat"],
        "units": entry["units"],
        "blocks": entry["blocks"],
        "segments": entry["segments"],
        "class_metrics": class_metrics_sorted,
        "module_deps": module_deps_sorted,
        "dead_candidates": dead_candidates_sorted,
        "referenced_names": sorted(set(entry["referenced_names"])),
        "import_names": sorted(set(entry["import_names"])),
        "class_names": sorted(set(entry["class_names"])),
    }


def _decode_wire_qualname_span(
    row: list[object],
) -> tuple[str, int, int] | None:
    qualname = _as_str(row[0])
    start_line = _as_int(row[1])
    end_line = _as_int(row[2])
    if qualname is None or start_line is None or end_line is None:
        return None
    return qualname, start_line, end_line


def _as_str_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    for key in value:
        if not isinstance(key, str):
            return None
    return value


def _as_analysis_profile(value: object) -> AnalysisProfile | None:
    obj = _as_str_dict(value)
    if obj is None:
        return None

    if set(obj.keys()) != {"min_loc", "min_stmt"}:
        return None

    min_loc = _as_int(obj.get("min_loc"))
    min_stmt = _as_int(obj.get("min_stmt"))
    if min_loc is None or min_stmt is None:
        return None

    return {"min_loc": min_loc, "min_stmt": min_stmt}


def _decode_wire_stat(obj: dict[str, object]) -> FileStat | None:
    stat_list = _as_list(obj.get("st"))
    if stat_list is None or len(stat_list) != 2:
        return None
    mtime_ns = _as_int(stat_list[0])
    size = _as_int(stat_list[1])
    if mtime_ns is None or size is None:
        return None
    return {"mtime_ns": mtime_ns, "size": size}


def _decode_optional_wire_items(
    *,
    obj: dict[str, object],
    key: str,
    decode_item: Callable[[object], _DecodedItemT | None],
) -> list[_DecodedItemT] | None:
    raw_items = obj.get(key)
    if raw_items is None:
        return []
    wire_items = _as_list(raw_items)
    if wire_items is None:
        return None
    decoded_items: list[_DecodedItemT] = []
    for wire_item in wire_items:
        decoded = decode_item(wire_item)
        if decoded is None:
            return None
        decoded_items.append(decoded)
    return decoded_items


def _decode_optional_wire_names(
    *,
    obj: dict[str, object],
    key: str,
) -> list[str] | None:
    raw_names = obj.get(key)
    if raw_names is None:
        return []
    names = _as_list(raw_names)
    if names is None or not all(isinstance(name, str) for name in names):
        return None
    return [str(name) for name in names]


def _decode_optional_wire_coupled_classes(
    *,
    obj: dict[str, object],
    key: str,
) -> dict[str, list[str]] | None:
    raw = obj.get(key)
    if raw is None:
        return {}

    rows = _as_list(raw)
    if rows is None:
        return None

    decoded: dict[str, list[str]] = {}
    for wire_row in rows:
        row = _as_list(wire_row)
        if row is None or len(row) != 2:
            return None
        qualname = _as_str(row[0])
        names = _as_list(row[1])
        if qualname is None or names is None:
            return None
        if not all(isinstance(name, str) for name in names):
            return None
        decoded[qualname] = sorted({str(name) for name in names if str(name)})

    return decoded


def _decode_wire_file_entry(value: object, filepath: str) -> CacheEntry | None:
    obj = _as_str_dict(value)
    if obj is None:
        return None

    stat = _decode_wire_stat(obj)
    if stat is None:
        return None

    units = _decode_optional_wire_items(
        obj=obj,
        key="u",
        decode_item=lambda item: _decode_wire_unit(item, filepath),
    )
    if units is None:
        return None
    blocks = _decode_optional_wire_items(
        obj=obj,
        key="b",
        decode_item=lambda item: _decode_wire_block(item, filepath),
    )
    if blocks is None:
        return None
    segments = _decode_optional_wire_items(
        obj=obj,
        key="s",
        decode_item=lambda item: _decode_wire_segment(item, filepath),
    )
    if segments is None:
        return None
    class_metrics = _decode_optional_wire_items(
        obj=obj,
        key="cm",
        decode_item=lambda item: _decode_wire_class_metric(item, filepath),
    )
    if class_metrics is None:
        return None
    module_deps = _decode_optional_wire_items(
        obj=obj,
        key="md",
        decode_item=_decode_wire_module_dep,
    )
    if module_deps is None:
        return None
    dead_candidates = _decode_optional_wire_items(
        obj=obj,
        key="dc",
        decode_item=lambda item: _decode_wire_dead_candidate(item, filepath),
    )
    if dead_candidates is None:
        return None
    referenced_names = _decode_optional_wire_names(obj=obj, key="rn")
    if referenced_names is None:
        return None
    import_names = _decode_optional_wire_names(obj=obj, key="in")
    if import_names is None:
        return None
    class_names = _decode_optional_wire_names(obj=obj, key="cn")
    if class_names is None:
        return None
    coupled_classes_map = _decode_optional_wire_coupled_classes(obj=obj, key="cc")
    if coupled_classes_map is None:
        return None

    for metric in class_metrics:
        names = coupled_classes_map.get(metric["qualname"], [])
        if names:
            metric["coupled_classes"] = names

    return {
        "stat": stat,
        "units": units,
        "blocks": blocks,
        "segments": segments,
        "class_metrics": class_metrics,
        "module_deps": module_deps,
        "dead_candidates": dead_candidates,
        "referenced_names": referenced_names,
        "import_names": import_names,
        "class_names": class_names,
    }


def _decode_wire_unit(value: object, filepath: str) -> UnitDict | None:
    row = _as_list(value)
    if row is None or len(row) not in {7, 11}:
        return None

    qualname_span = _decode_wire_qualname_span(row)
    if qualname_span is None:
        return None
    qualname, start_line, end_line = qualname_span
    loc = _as_int(row[3])
    stmt_count = _as_int(row[4])
    fingerprint = _as_str(row[5])
    loc_bucket = _as_str(row[6])
    cyclomatic_complexity = _as_int(row[7]) if len(row) == 11 else 1
    nesting_depth = _as_int(row[8]) if len(row) == 11 else 0
    risk = _as_str(row[9]) if len(row) == 11 else "low"
    raw_hash = _as_str(row[10]) if len(row) == 11 else ""

    if (
        loc is None
        or stmt_count is None
        or fingerprint is None
        or loc_bucket is None
        or cyclomatic_complexity is None
        or nesting_depth is None
        or risk not in {"low", "medium", "high"}
        or raw_hash is None
    ):
        return None
    risk_value = cast(Literal["low", "medium", "high"], risk)

    return {
        "qualname": qualname,
        "filepath": filepath,
        "start_line": start_line,
        "end_line": end_line,
        "loc": loc,
        "stmt_count": stmt_count,
        "fingerprint": fingerprint,
        "loc_bucket": loc_bucket,
        "cyclomatic_complexity": cyclomatic_complexity,
        "nesting_depth": nesting_depth,
        "risk": risk_value,
        "raw_hash": raw_hash,
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


def _decode_wire_class_metric(
    value: object,
    filepath: str,
) -> ClassMetricsDict | None:
    row = _as_list(value)
    if row is None or len(row) != 9:
        return None

    qualname_span = _decode_wire_qualname_span(row)
    if qualname_span is None:
        return None
    qualname, start_line, end_line = qualname_span
    cbo = _as_int(row[3])
    lcom4 = _as_int(row[4])
    method_count = _as_int(row[5])
    instance_var_count = _as_int(row[6])
    risk_coupling = _as_str(row[7])
    risk_cohesion = _as_str(row[8])
    if (
        cbo is None
        or lcom4 is None
        or method_count is None
        or instance_var_count is None
        or risk_coupling is None
        or risk_cohesion is None
    ):
        return None
    return {
        "qualname": qualname,
        "filepath": filepath,
        "start_line": start_line,
        "end_line": end_line,
        "cbo": cbo,
        "lcom4": lcom4,
        "method_count": method_count,
        "instance_var_count": instance_var_count,
        "risk_coupling": risk_coupling,
        "risk_cohesion": risk_cohesion,
    }


def _decode_wire_module_dep(value: object) -> ModuleDepDict | None:
    row = _as_list(value)
    if row is None or len(row) != 4:
        return None
    source = _as_str(row[0])
    target = _as_str(row[1])
    import_type = _as_str(row[2])
    line = _as_int(row[3])
    if source is None or target is None or import_type is None or line is None:
        return None
    return {
        "source": source,
        "target": target,
        "import_type": import_type,
        "line": line,
    }


def _decode_wire_dead_candidate(
    value: object,
    filepath: str,
) -> DeadCandidateDict | None:
    row = _as_list(value)
    if row is None or len(row) != 6:
        return None
    qualname = _as_str(row[0])
    local_name = _as_str(row[1])
    start_line = _as_int(row[2])
    end_line = _as_int(row[3])
    kind = _as_str(row[4])
    candidate_filepath = _as_str(row[5])
    if (
        qualname is None
        or local_name is None
        or start_line is None
        or end_line is None
        or kind is None
        or candidate_filepath is None
    ):
        return None
    return {
        "qualname": qualname,
        "local_name": local_name,
        "filepath": candidate_filepath or filepath,
        "start_line": start_line,
        "end_line": end_line,
        "kind": kind,
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
                unit.get("cyclomatic_complexity", 1),
                unit.get("nesting_depth", 0),
                unit.get("risk", "low"),
                unit.get("raw_hash", ""),
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

    class_metrics = sorted(
        entry["class_metrics"],
        key=lambda metric: (
            metric["filepath"],
            metric["start_line"],
            metric["end_line"],
            metric["qualname"],
        ),
    )
    if class_metrics:
        wire["cm"] = [
            [
                metric["qualname"],
                metric["start_line"],
                metric["end_line"],
                metric["cbo"],
                metric["lcom4"],
                metric["method_count"],
                metric["instance_var_count"],
                metric["risk_coupling"],
                metric["risk_cohesion"],
            ]
            for metric in class_metrics
        ]
        coupled_classes_rows = []
        for metric in class_metrics:
            coupled_classes_raw = metric.get("coupled_classes", [])
            if not _is_string_list(coupled_classes_raw):
                continue
            coupled_classes = sorted(set(coupled_classes_raw))
            if not coupled_classes:
                continue
            coupled_classes_rows.append([metric["qualname"], coupled_classes])
        if coupled_classes_rows:
            wire["cc"] = coupled_classes_rows

    module_deps = sorted(
        entry["module_deps"],
        key=lambda dep: (dep["source"], dep["target"], dep["import_type"], dep["line"]),
    )
    if module_deps:
        wire["md"] = [
            [
                dep["source"],
                dep["target"],
                dep["import_type"],
                dep["line"],
            ]
            for dep in module_deps
        ]

    dead_candidates = sorted(
        entry["dead_candidates"],
        key=lambda candidate: (
            candidate["filepath"],
            candidate["start_line"],
            candidate["end_line"],
            candidate["qualname"],
        ),
    )
    if dead_candidates:
        wire["dc"] = [
            [
                candidate["qualname"],
                candidate["local_name"],
                candidate["start_line"],
                candidate["end_line"],
                candidate["kind"],
                candidate["filepath"],
            ]
            for candidate in dead_candidates
        ]

    if entry["referenced_names"]:
        wire["rn"] = sorted(set(entry["referenced_names"]))
    if entry["import_names"]:
        wire["in"] = sorted(set(entry["import_names"]))
    if entry["class_names"]:
        wire["cn"] = sorted(set(entry["class_names"]))

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
    if not _has_typed_fields(value, string_keys=string_keys, int_keys=int_keys):
        return False
    cyclomatic_complexity = value.get("cyclomatic_complexity", 1)
    nesting_depth = value.get("nesting_depth", 0)
    risk = value.get("risk", "low")
    raw_hash = value.get("raw_hash", "")
    return (
        isinstance(cyclomatic_complexity, int)
        and isinstance(nesting_depth, int)
        and isinstance(risk, str)
        and risk in {"low", "medium", "high"}
        and isinstance(raw_hash, str)
    )


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


def _is_class_metrics_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if not _has_typed_fields(
        value,
        string_keys=(
            "qualname",
            "filepath",
            "risk_coupling",
            "risk_cohesion",
        ),
        int_keys=(
            "start_line",
            "end_line",
            "cbo",
            "lcom4",
            "method_count",
            "instance_var_count",
        ),
    ):
        return False

    coupled_classes = value.get("coupled_classes")
    if coupled_classes is None:
        return True
    return _is_string_list(coupled_classes)


def _is_module_dep_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return _has_typed_fields(
        value,
        string_keys=("source", "target", "import_type"),
        int_keys=("line",),
    )


def _is_dead_candidate_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return _has_typed_fields(
        value,
        string_keys=("qualname", "local_name", "filepath", "kind"),
        int_keys=("start_line", "end_line"),
    )


def _is_class_metrics_list(value: object) -> bool:
    return isinstance(value, list) and all(
        _is_class_metrics_dict(item) for item in value
    )


def _is_module_deps_list(value: object) -> bool:
    return isinstance(value, list) and all(_is_module_dep_dict(item) for item in value)


def _is_dead_candidates_list(value: object) -> bool:
    return isinstance(value, list) and all(
        _is_dead_candidate_dict(item) for item in value
    )


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _has_typed_fields(
    value: Mapping[str, object],
    *,
    string_keys: Sequence[str],
    int_keys: Sequence[str],
) -> bool:
    return all(isinstance(value.get(key), str) for key in string_keys) and all(
        isinstance(value.get(key), int) for key in int_keys
    )
