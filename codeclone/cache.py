# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Collection
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict, TypeGuard, TypeVar, cast

from .baseline import current_python_tag
from .contracts import BASELINE_FINGERPRINT_VERSION, CACHE_VERSION
from .errors import CacheError
from .models import (
    BlockGroupItem,
    BlockUnit,
    ClassMetrics,
    DeadCandidate,
    FileMetrics,
    FunctionGroupItem,
    ModuleDep,
    SegmentGroupItem,
    SegmentUnit,
    StructuralFindingGroup,
    StructuralFindingOccurrence,
    Unit,
)
from .structural_findings import normalize_structural_finding_group

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

MAX_CACHE_SIZE_BYTES = 50 * 1024 * 1024
LEGACY_CACHE_SECRET_FILENAME = ".cache_secret"
_DEFAULT_WIRE_UNIT_FLOW_PROFILES = (
    0,
    "none",
    False,
    "fallthrough",
    "none",
    "none",
)


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


class SourceStatsDict(TypedDict):
    lines: int
    functions: int
    methods: int
    classes: int


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


class DeadCandidateDictBase(TypedDict):
    qualname: str
    local_name: str
    filepath: str
    start_line: int
    end_line: int
    kind: str


class DeadCandidateDict(DeadCandidateDictBase, total=False):
    suppressed_rules: list[str]


class StructuralFindingOccurrenceDict(TypedDict):
    qualname: str
    start: int
    end: int


class StructuralFindingGroupDict(TypedDict):
    finding_kind: str
    finding_key: str
    signature: dict[str, str]
    items: list[StructuralFindingOccurrenceDict]


class CacheEntryBase(TypedDict):
    stat: FileStat
    units: list[UnitDict]
    blocks: list[BlockDict]
    segments: list[SegmentDict]


class CacheEntry(CacheEntryBase, total=False):
    source_stats: SourceStatsDict
    class_metrics: list[ClassMetricsDict]
    module_deps: list[ModuleDepDict]
    dead_candidates: list[DeadCandidateDict]
    referenced_names: list[str]
    referenced_qualnames: list[str]
    import_names: list[str]
    class_names: list[str]
    structural_findings: list[StructuralFindingGroupDict]


class AnalysisProfile(TypedDict):
    min_loc: int
    min_stmt: int
    block_min_loc: int
    block_min_stmt: int
    segment_min_loc: int
    segment_min_stmt: int


class CacheData(TypedDict):
    version: str
    python_tag: str
    fingerprint_version: str
    analysis_profile: AnalysisProfile
    files: dict[str, CacheEntry]


class SegmentReportProjection(TypedDict):
    digest: str
    suppressed: int
    groups: dict[str, list[SegmentDict]]


def build_segment_report_projection(
    *,
    digest: str,
    suppressed: int,
    groups: Mapping[str, Sequence[Mapping[str, object]]],
) -> SegmentReportProjection:
    normalized_groups: dict[str, list[SegmentDict]] = {}
    for group_key in sorted(groups):
        normalized_items: list[SegmentDict] = []
        for raw_item in sorted(
            groups[group_key],
            key=lambda item: (
                str(item.get("filepath", "")),
                str(item.get("qualname", "")),
                _as_int(item.get("start_line")) or 0,
                _as_int(item.get("end_line")) or 0,
            ),
        ):
            segment_hash = _as_str(raw_item.get("segment_hash"))
            segment_sig = _as_str(raw_item.get("segment_sig"))
            filepath = _as_str(raw_item.get("filepath"))
            qualname = _as_str(raw_item.get("qualname"))
            start_line = _as_int(raw_item.get("start_line"))
            end_line = _as_int(raw_item.get("end_line"))
            size = _as_int(raw_item.get("size"))
            if (
                segment_hash is None
                or segment_sig is None
                or filepath is None
                or qualname is None
                or start_line is None
                or end_line is None
                or size is None
            ):
                continue
            normalized_items.append(
                SegmentGroupItem(
                    segment_hash=segment_hash,
                    segment_sig=segment_sig,
                    filepath=filepath,
                    qualname=qualname,
                    start_line=start_line,
                    end_line=end_line,
                    size=size,
                )
            )
        if normalized_items:
            normalized_groups[group_key] = normalized_items
    return {
        "digest": digest,
        "suppressed": max(0, int(suppressed)),
        "groups": normalized_groups,
    }


def _normalize_cached_structural_group(
    group: StructuralFindingGroupDict,
    *,
    filepath: str,
) -> StructuralFindingGroupDict | None:
    signature = dict(group["signature"])
    finding_kind = group["finding_kind"]
    finding_key = group["finding_key"]
    normalized = normalize_structural_finding_group(
        StructuralFindingGroup(
            finding_kind=finding_kind,
            finding_key=finding_key,
            signature=signature,
            items=tuple(
                StructuralFindingOccurrence(
                    finding_kind=finding_kind,
                    finding_key=finding_key,
                    file_path=filepath,
                    qualname=item["qualname"],
                    start=item["start"],
                    end=item["end"],
                    signature=signature,
                )
                for item in group["items"]
            ),
        )
    )
    if normalized is None:
        return None
    return StructuralFindingGroupDict(
        finding_kind=normalized.finding_kind,
        finding_key=normalized.finding_key,
        signature=dict(normalized.signature),
        items=[
            StructuralFindingOccurrenceDict(
                qualname=item.qualname,
                start=item.start,
                end=item.end,
            )
            for item in normalized.items
        ],
    )


def _normalize_cached_structural_groups(
    groups: Sequence[StructuralFindingGroupDict],
    *,
    filepath: str,
) -> list[StructuralFindingGroupDict]:
    normalized = [
        candidate
        for candidate in (
            _normalize_cached_structural_group(group, filepath=filepath)
            for group in groups
        )
        if candidate is not None
    ]
    normalized.sort(key=lambda group: (-len(group["items"]), group["finding_key"]))
    return normalized


_DecodedItemT = TypeVar("_DecodedItemT")
_ValidatedItemT = TypeVar("_ValidatedItemT")


class Cache:
    __slots__ = (
        "_canonical_runtime_paths",
        "_dirty",
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
        "segment_report_projection",
    )

    _CACHE_VERSION = CACHE_VERSION

    def __init__(
        self,
        path: str | Path,
        *,
        root: str | Path | None = None,
        max_size_bytes: int | None = None,
        min_loc: int = 10,
        min_stmt: int = 6,
        block_min_loc: int = 20,
        block_min_stmt: int = 8,
        segment_min_loc: int = 20,
        segment_min_stmt: int = 10,
    ):
        self.path = Path(path)
        self.root = _resolve_root(root)
        self.fingerprint_version = BASELINE_FINGERPRINT_VERSION
        self.analysis_profile: AnalysisProfile = {
            "min_loc": min_loc,
            "min_stmt": min_stmt,
            "block_min_loc": block_min_loc,
            "block_min_stmt": block_min_stmt,
            "segment_min_loc": segment_min_loc,
            "segment_min_stmt": segment_min_stmt,
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
        self.segment_report_projection: SegmentReportProjection | None = None
        self._dirty: bool = True  # new cache is dirty until loaded from disk

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
        self.segment_report_projection = None

    def _reject_cache_load(
        self,
        message: str,
        *,
        status: CacheStatus,
        schema_version: str | None = None,
    ) -> CacheData | None:
        self._ignore_cache(
            message,
            status=status,
            schema_version=schema_version,
        )
        return None

    def _reject_invalid_cache_format(
        self,
        *,
        schema_version: str | None = None,
    ) -> CacheData | None:
        return self._reject_cache_load(
            "Cache format invalid; ignoring cache.",
            status=CacheStatus.INVALID_TYPE,
            schema_version=schema_version,
        )

    def _reject_version_mismatch(self, version: str) -> CacheData | None:
        return self._reject_cache_load(
            f"Cache version mismatch (found {version}); ignoring cache.",
            status=CacheStatus.VERSION_MISMATCH,
            schema_version=version,
        )

    @staticmethod
    def _sign_data(data: Mapping[str, object]) -> str:
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
            self.segment_report_projection = None
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
            self._dirty = False  # freshly loaded — nothing to persist

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
            return self._reject_invalid_cache_format()

        # Legacy cache format: top-level {version, files, _signature}.
        legacy_version = _as_str(raw.get("version"))
        if legacy_version is not None:
            return self._reject_version_mismatch(legacy_version)

        version = _as_str(raw.get("v"))
        if version is None:
            return self._reject_invalid_cache_format()

        if version != self._CACHE_VERSION:
            return self._reject_version_mismatch(version)

        sig = _as_str(raw.get("sig"))
        payload_obj = raw.get("payload")
        payload = _as_str_dict(payload_obj)
        if sig is None or payload is None:
            return self._reject_invalid_cache_format(schema_version=version)

        expected_sig = self._sign_data(payload)
        if not hmac.compare_digest(sig, expected_sig):
            return self._reject_cache_load(
                "Cache signature mismatch; ignoring cache.",
                status=CacheStatus.INTEGRITY_FAILED,
                schema_version=version,
            )

        runtime_tag = current_python_tag()
        py_tag = _as_str(payload.get("py"))
        if py_tag is None:
            return self._reject_invalid_cache_format(schema_version=version)

        if py_tag != runtime_tag:
            return self._reject_cache_load(
                "Cache python tag mismatch "
                f"(found {py_tag}, expected {runtime_tag}); ignoring cache.",
                status=CacheStatus.PYTHON_TAG_MISMATCH,
                schema_version=version,
            )

        fp_version = _as_str(payload.get("fp"))
        if fp_version is None:
            return self._reject_invalid_cache_format(schema_version=version)

        if fp_version != self.fingerprint_version:
            return self._reject_cache_load(
                "Cache fingerprint version mismatch "
                f"(found {fp_version}, expected {self.fingerprint_version}); "
                "ignoring cache.",
                status=CacheStatus.FINGERPRINT_MISMATCH,
                schema_version=version,
            )

        analysis_profile = _as_analysis_profile(payload.get("ap"))
        if analysis_profile is None:
            return self._reject_invalid_cache_format(schema_version=version)

        if analysis_profile != self.analysis_profile:
            return self._reject_cache_load(
                "Cache analysis profile mismatch "
                f"(found min_loc={analysis_profile['min_loc']}, "
                f"min_stmt={analysis_profile['min_stmt']}; "
                f"expected min_loc={self.analysis_profile['min_loc']}, "
                f"min_stmt={self.analysis_profile['min_stmt']}); "
                "ignoring cache.",
                status=CacheStatus.ANALYSIS_PROFILE_MISMATCH,
                schema_version=version,
            )

        files_obj = payload.get("files")
        files_dict = _as_str_dict(files_obj)
        if files_dict is None:
            return self._reject_invalid_cache_format(schema_version=version)

        parsed_files: dict[str, CacheEntry] = {}
        for wire_path, file_entry_obj in files_dict.items():
            runtime_path = self._runtime_filepath_from_wire(wire_path)
            parsed_entry = self._decode_entry(file_entry_obj, runtime_path)
            if parsed_entry is None:
                return self._reject_invalid_cache_format(schema_version=version)
            parsed_files[runtime_path] = _canonicalize_cache_entry(parsed_entry)
        self.segment_report_projection = self._decode_segment_report_projection(
            payload.get("sr")
        )

        self.cache_schema_version = version
        return CacheData(
            version=self._CACHE_VERSION,
            python_tag=runtime_tag,
            fingerprint_version=self.fingerprint_version,
            analysis_profile=self.analysis_profile,
            files=parsed_files,
        )

    def save(self) -> None:
        if not self._dirty:
            return
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
            segment_projection = self._encode_segment_report_projection()
            if segment_projection is not None:
                payload["sr"] = segment_projection
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
            self._dirty = False

            self.data["version"] = self._CACHE_VERSION
            self.data["python_tag"] = current_python_tag()
            self.data["fingerprint_version"] = self.fingerprint_version
            self.data["analysis_profile"] = self.analysis_profile

        except OSError as e:
            raise CacheError(f"Failed to save cache: {e}") from e

    @staticmethod
    def _decode_entry(value: object, filepath: str) -> CacheEntry | None:
        return _decode_wire_file_entry(value, filepath)

    @staticmethod
    def _encode_entry(entry: CacheEntry) -> dict[str, object]:
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

    def _decode_segment_report_projection(
        self,
        value: object,
    ) -> SegmentReportProjection | None:
        obj = _as_str_dict(value)
        if obj is None:
            return None
        digest = _as_str(obj.get("d"))
        suppressed = _as_int(obj.get("s"))
        groups_raw = _as_list(obj.get("g"))
        if digest is None or suppressed is None or groups_raw is None:
            return None
        groups: dict[str, list[SegmentDict]] = {}
        for group_row in groups_raw:
            group_list = _as_list(group_row)
            if group_list is None or len(group_list) != 2:
                return None
            group_key = _as_str(group_list[0])
            items_raw = _as_list(group_list[1])
            if group_key is None or items_raw is None:
                return None
            items: list[SegmentDict] = []
            for item_raw in items_raw:
                item_list = _as_list(item_raw)
                if item_list is None or len(item_list) != 7:
                    return None
                wire_filepath = _as_str(item_list[0])
                qualname = _as_str(item_list[1])
                start_line = _as_int(item_list[2])
                end_line = _as_int(item_list[3])
                size = _as_int(item_list[4])
                segment_hash = _as_str(item_list[5])
                segment_sig = _as_str(item_list[6])
                if (
                    wire_filepath is None
                    or qualname is None
                    or start_line is None
                    or end_line is None
                    or size is None
                    or segment_hash is None
                    or segment_sig is None
                ):
                    return None
                items.append(
                    SegmentGroupItem(
                        segment_hash=segment_hash,
                        segment_sig=segment_sig,
                        filepath=self._runtime_filepath_from_wire(wire_filepath),
                        qualname=qualname,
                        start_line=start_line,
                        end_line=end_line,
                        size=size,
                    )
                )
            groups[group_key] = items
        return {
            "digest": digest,
            "suppressed": max(0, suppressed),
            "groups": groups,
        }

    def _encode_segment_report_projection(self) -> dict[str, object] | None:
        projection = self.segment_report_projection
        if projection is None:
            return None
        groups_rows: list[list[object]] = []
        for group_key in sorted(projection["groups"]):
            items = sorted(
                projection["groups"][group_key],
                key=lambda item: (
                    item["filepath"],
                    item["qualname"],
                    item["start_line"],
                    item["end_line"],
                ),
            )
            encoded_items = [
                [
                    self._wire_filepath_from_runtime(item["filepath"]),
                    item["qualname"],
                    item["start_line"],
                    item["end_line"],
                    item["size"],
                    item["segment_hash"],
                    item["segment_sig"],
                ]
                for item in items
            ]
            groups_rows.append([group_key, encoded_items])
        return {
            "d": projection["digest"],
            "s": max(0, int(projection["suppressed"])),
            "g": groups_rows,
        }

    def _store_canonical_file_entry(
        self,
        *,
        runtime_path: str,
        canonical_entry: CacheEntry,
    ) -> CacheEntry:
        previous_entry = self.data["files"].get(runtime_path)
        was_canonical = runtime_path in self._canonical_runtime_paths
        self.data["files"][runtime_path] = canonical_entry
        self._canonical_runtime_paths.add(runtime_path)
        if not was_canonical or previous_entry != canonical_entry:
            self._dirty = True
        return canonical_entry

    def get_file_entry(self, filepath: str) -> CacheEntry | None:
        runtime_lookup_key = filepath
        entry_obj = self.data["files"].get(runtime_lookup_key)
        if entry_obj is None:
            wire_key = self._wire_filepath_from_runtime(filepath)
            runtime_lookup_key = self._runtime_filepath_from_wire(wire_key)
            entry_obj = self.data["files"].get(runtime_lookup_key)

        if entry_obj is None:
            return None

        if runtime_lookup_key in self._canonical_runtime_paths:
            if _is_canonical_cache_entry(entry_obj):
                return entry_obj
            self._canonical_runtime_paths.discard(runtime_lookup_key)

        if not isinstance(entry_obj, dict):
            return None
        entry = entry_obj

        required = {"stat", "units", "blocks", "segments"}
        if not required.issubset(entry.keys()):
            return None

        stat = _as_file_stat_dict(entry.get("stat"))
        units = _as_typed_unit_list(entry.get("units"))
        blocks = _as_typed_block_list(entry.get("blocks"))
        segments = _as_typed_segment_list(entry.get("segments"))
        if stat is None or units is None or blocks is None or segments is None:
            return None

        class_metrics_raw = _as_typed_class_metrics_list(entry.get("class_metrics", []))
        module_deps_raw = _as_typed_module_deps_list(entry.get("module_deps", []))
        dead_candidates_raw = _as_typed_dead_candidates_list(
            entry.get("dead_candidates", [])
        )
        referenced_names_raw = _as_typed_string_list(entry.get("referenced_names", []))
        referenced_qualnames_raw = _as_typed_string_list(
            entry.get("referenced_qualnames", [])
        )
        import_names_raw = _as_typed_string_list(entry.get("import_names", []))
        class_names_raw = _as_typed_string_list(entry.get("class_names", []))
        if (
            class_metrics_raw is None
            or module_deps_raw is None
            or dead_candidates_raw is None
            or referenced_names_raw is None
            or referenced_qualnames_raw is None
            or import_names_raw is None
            or class_names_raw is None
        ):
            return None

        entry_to_canonicalize: CacheEntry = CacheEntry(
            stat=stat,
            units=units,
            blocks=blocks,
            segments=segments,
            class_metrics=class_metrics_raw,
            module_deps=module_deps_raw,
            dead_candidates=dead_candidates_raw,
            referenced_names=referenced_names_raw,
            referenced_qualnames=referenced_qualnames_raw,
            import_names=import_names_raw,
            class_names=class_names_raw,
        )
        source_stats = _as_source_stats_dict(entry.get("source_stats"))
        if source_stats is not None:
            entry_to_canonicalize["source_stats"] = source_stats
        sf_raw = entry.get("structural_findings")
        if isinstance(sf_raw, list):
            entry_to_canonicalize["structural_findings"] = sf_raw
        canonical_entry = _canonicalize_cache_entry(entry_to_canonicalize)
        return self._store_canonical_file_entry(
            runtime_path=runtime_lookup_key,
            canonical_entry=canonical_entry,
        )

    def put_file_entry(
        self,
        filepath: str,
        stat_sig: FileStat,
        units: list[Unit],
        blocks: list[BlockUnit],
        segments: list[SegmentUnit],
        *,
        source_stats: SourceStatsDict | None = None,
        file_metrics: FileMetrics | None = None,
        structural_findings: list[StructuralFindingGroup] | None = None,
    ) -> None:
        runtime_path = self._runtime_filepath_from_wire(
            self._wire_filepath_from_runtime(filepath)
        )

        unit_rows = [_unit_dict_from_model(unit, runtime_path) for unit in units]
        block_rows = [_block_dict_from_model(block, runtime_path) for block in blocks]
        segment_rows = [
            _segment_dict_from_model(segment, runtime_path) for segment in segments
        ]

        (
            class_metrics_rows,
            module_dep_rows,
            dead_candidate_rows,
            referenced_names,
            referenced_qualnames,
            import_names,
            class_names,
        ) = _new_optional_metrics_payload()
        if file_metrics is not None:
            class_metrics_rows = [
                _class_metrics_dict_from_model(metric, runtime_path)
                for metric in file_metrics.class_metrics
            ]
            module_dep_rows = [
                _module_dep_dict_from_model(dep) for dep in file_metrics.module_deps
            ]
            dead_candidate_rows = [
                _dead_candidate_dict_from_model(candidate, runtime_path)
                for candidate in file_metrics.dead_candidates
            ]
            referenced_names = sorted(set(file_metrics.referenced_names))
            referenced_qualnames = sorted(set(file_metrics.referenced_qualnames))
            import_names = sorted(set(file_metrics.import_names))
            class_names = sorted(set(file_metrics.class_names))

        source_stats_payload = source_stats or SourceStatsDict(
            lines=0,
            functions=0,
            methods=0,
            classes=0,
        )
        entry_dict = CacheEntry(
            stat=stat_sig,
            source_stats=source_stats_payload,
            units=unit_rows,
            blocks=block_rows,
            segments=segment_rows,
            class_metrics=class_metrics_rows,
            module_deps=module_dep_rows,
            dead_candidates=dead_candidate_rows,
            referenced_names=referenced_names,
            referenced_qualnames=referenced_qualnames,
            import_names=import_names,
            class_names=class_names,
        )
        if structural_findings is not None:
            entry_dict["structural_findings"] = _normalize_cached_structural_groups(
                [
                    _structural_group_dict_from_model(group)
                    for group in structural_findings
                ],
                filepath=runtime_path,
            )
        canonical_entry = _canonicalize_cache_entry(entry_dict)
        self._store_canonical_file_entry(
            runtime_path=runtime_path,
            canonical_entry=canonical_entry,
        )


def file_stat_signature(path: str) -> FileStat:
    st = os.stat(path)
    return FileStat(
        mtime_ns=st.st_mtime_ns,
        size=st.st_size,
    )


def _empty_cache_data(
    *,
    version: str,
    python_tag: str,
    fingerprint_version: str,
    analysis_profile: AnalysisProfile,
) -> CacheData:
    return CacheData(
        version=version,
        python_tag=python_tag,
        fingerprint_version=fingerprint_version,
        analysis_profile=analysis_profile,
        files={},
    )


def _canonical_json(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _as_list(value: object) -> list[object] | None:
    return value if isinstance(value, list) else None


def _as_risk_literal(value: object) -> Literal["low", "medium", "high"] | None:
    match value:
        case "low":
            return "low"
        case "medium":
            return "medium"
        case "high":
            return "high"
        case _:
            return None


def _new_optional_metrics_payload() -> tuple[
    list[ClassMetricsDict],
    list[ModuleDepDict],
    list[DeadCandidateDict],
    list[str],
    list[str],
    list[str],
    list[str],
]:
    return [], [], [], [], [], [], []


def _unit_dict_from_model(unit: Unit, filepath: str) -> UnitDict:
    return FunctionGroupItem(
        qualname=unit.qualname,
        filepath=filepath,
        start_line=unit.start_line,
        end_line=unit.end_line,
        loc=unit.loc,
        stmt_count=unit.stmt_count,
        fingerprint=unit.fingerprint,
        loc_bucket=unit.loc_bucket,
        cyclomatic_complexity=unit.cyclomatic_complexity,
        nesting_depth=unit.nesting_depth,
        risk=unit.risk,
        raw_hash=unit.raw_hash,
        entry_guard_count=unit.entry_guard_count,
        entry_guard_terminal_profile=unit.entry_guard_terminal_profile,
        entry_guard_has_side_effect_before=unit.entry_guard_has_side_effect_before,
        terminal_kind=unit.terminal_kind,
        try_finally_profile=unit.try_finally_profile,
        side_effect_order_profile=unit.side_effect_order_profile,
    )


def _block_dict_from_model(block: BlockUnit, filepath: str) -> BlockDict:
    return BlockGroupItem(
        block_hash=block.block_hash,
        filepath=filepath,
        qualname=block.qualname,
        start_line=block.start_line,
        end_line=block.end_line,
        size=block.size,
    )


def _segment_dict_from_model(segment: SegmentUnit, filepath: str) -> SegmentDict:
    return SegmentGroupItem(
        segment_hash=segment.segment_hash,
        segment_sig=segment.segment_sig,
        filepath=filepath,
        qualname=segment.qualname,
        start_line=segment.start_line,
        end_line=segment.end_line,
        size=segment.size,
    )


def _class_metrics_dict_from_model(
    metric: ClassMetrics,
    filepath: str,
) -> ClassMetricsDict:
    return ClassMetricsDict(
        qualname=metric.qualname,
        filepath=filepath,
        start_line=metric.start_line,
        end_line=metric.end_line,
        cbo=metric.cbo,
        lcom4=metric.lcom4,
        method_count=metric.method_count,
        instance_var_count=metric.instance_var_count,
        risk_coupling=metric.risk_coupling,
        risk_cohesion=metric.risk_cohesion,
        coupled_classes=sorted(set(metric.coupled_classes)),
    )


def _module_dep_dict_from_model(dep: ModuleDep) -> ModuleDepDict:
    return ModuleDepDict(
        source=dep.source,
        target=dep.target,
        import_type=dep.import_type,
        line=dep.line,
    )


def _dead_candidate_dict_from_model(
    candidate: DeadCandidate,
    filepath: str,
) -> DeadCandidateDict:
    result = DeadCandidateDict(
        qualname=candidate.qualname,
        local_name=candidate.local_name,
        filepath=filepath,
        start_line=candidate.start_line,
        end_line=candidate.end_line,
        kind=candidate.kind,
    )
    if candidate.suppressed_rules:
        result["suppressed_rules"] = sorted(set(candidate.suppressed_rules))
    return result


def _structural_occurrence_dict_from_model(
    occurrence: StructuralFindingOccurrence,
) -> StructuralFindingOccurrenceDict:
    return StructuralFindingOccurrenceDict(
        qualname=occurrence.qualname,
        start=occurrence.start,
        end=occurrence.end,
    )


def _structural_group_dict_from_model(
    group: StructuralFindingGroup,
) -> StructuralFindingGroupDict:
    return StructuralFindingGroupDict(
        finding_kind=group.finding_kind,
        finding_key=group.finding_key,
        signature=dict(group.signature),
        items=[
            _structural_occurrence_dict_from_model(occurrence)
            for occurrence in group.items
        ],
    )


def _as_file_stat_dict(value: object) -> FileStat | None:
    if not _is_file_stat_dict(value):
        return None
    obj = cast("Mapping[str, object]", value)
    mtime_ns = obj.get("mtime_ns")
    size = obj.get("size")
    if not isinstance(mtime_ns, int) or not isinstance(size, int):
        return None
    return FileStat(mtime_ns=mtime_ns, size=size)


def _as_source_stats_dict(value: object) -> SourceStatsDict | None:
    if not _is_source_stats_dict(value):
        return None
    obj = cast("Mapping[str, object]", value)
    lines = obj.get("lines")
    functions = obj.get("functions")
    methods = obj.get("methods")
    classes = obj.get("classes")
    assert isinstance(lines, int)
    assert isinstance(functions, int)
    assert isinstance(methods, int)
    assert isinstance(classes, int)
    return SourceStatsDict(
        lines=lines,
        functions=functions,
        methods=methods,
        classes=classes,
    )


def _as_typed_list(
    value: object,
    *,
    predicate: Callable[[object], bool],
) -> list[_ValidatedItemT] | None:
    if not isinstance(value, list):
        return None
    if not all(predicate(item) for item in value):
        return None
    return cast("list[_ValidatedItemT]", value)


def _as_typed_unit_list(value: object) -> list[UnitDict] | None:
    return _as_typed_list(value, predicate=_is_unit_dict)


def _as_typed_block_list(value: object) -> list[BlockDict] | None:
    return _as_typed_list(value, predicate=_is_block_dict)


def _as_typed_segment_list(value: object) -> list[SegmentDict] | None:
    return _as_typed_list(value, predicate=_is_segment_dict)


def _as_typed_class_metrics_list(value: object) -> list[ClassMetricsDict] | None:
    return _as_typed_list(value, predicate=_is_class_metrics_dict)


def _as_typed_dead_candidates_list(
    value: object,
) -> list[DeadCandidateDict] | None:
    return _as_typed_list(value, predicate=_is_dead_candidate_dict)


def _as_typed_module_deps_list(value: object) -> list[ModuleDepDict] | None:
    return _as_typed_list(value, predicate=_is_module_dep_dict)


def _as_typed_string_list(value: object) -> list[str] | None:
    return _as_typed_list(value, predicate=lambda item: isinstance(item, str))


def _is_canonical_cache_entry(value: object) -> TypeGuard[CacheEntry]:
    return isinstance(value, dict) and _has_cache_entry_container_shape(value)


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
    source_stats = entry.get("source_stats")
    if source_stats is not None and not _is_source_stats_dict(source_stats):
        return False
    optional_list_keys = (
        "class_metrics",
        "module_deps",
        "dead_candidates",
        "referenced_names",
        "referenced_qualnames",
        "import_names",
        "class_names",
        "structural_findings",
    )
    return all(isinstance(entry.get(key, []), list) for key in optional_list_keys)


def _canonicalize_cache_entry(entry: CacheEntry) -> CacheEntry:
    class_metrics_sorted = sorted(
        entry["class_metrics"],
        key=lambda item: (
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
    dead_candidates_normalized: list[DeadCandidateDict] = []
    for candidate in entry["dead_candidates"]:
        suppressed_rules = candidate.get("suppressed_rules", [])
        normalized_candidate = DeadCandidateDict(
            qualname=candidate["qualname"],
            local_name=candidate["local_name"],
            filepath=candidate["filepath"],
            start_line=candidate["start_line"],
            end_line=candidate["end_line"],
            kind=candidate["kind"],
        )
        if _is_string_list(suppressed_rules):
            normalized_rules = sorted(set(suppressed_rules))
            if normalized_rules:
                normalized_candidate["suppressed_rules"] = normalized_rules
        dead_candidates_normalized.append(normalized_candidate)

    dead_candidates_sorted = sorted(
        dead_candidates_normalized,
        key=lambda item: (
            item["start_line"],
            item["end_line"],
            item["qualname"],
            item["local_name"],
            item["kind"],
            tuple(item.get("suppressed_rules", [])),
        ),
    )

    result: CacheEntry = {
        "stat": entry["stat"],
        "units": entry["units"],
        "blocks": entry["blocks"],
        "segments": entry["segments"],
        "class_metrics": class_metrics_sorted,
        "module_deps": module_deps_sorted,
        "dead_candidates": dead_candidates_sorted,
        "referenced_names": sorted(set(entry["referenced_names"])),
        "referenced_qualnames": sorted(set(entry.get("referenced_qualnames", []))),
        "import_names": sorted(set(entry["import_names"])),
        "class_names": sorted(set(entry["class_names"])),
    }
    sf = entry.get("structural_findings")
    if sf is not None:
        result["structural_findings"] = sf
    source_stats = entry.get("source_stats")
    if source_stats is not None:
        result["source_stats"] = source_stats
    return result


def _decode_wire_qualname_span(
    row: list[object],
) -> tuple[str, int, int] | None:
    qualname = _as_str(row[0])
    start_line = _as_int(row[1])
    end_line = _as_int(row[2])
    if qualname is None or start_line is None or end_line is None:
        return None
    return qualname, start_line, end_line


def _decode_wire_qualname_span_size(
    row: list[object],
) -> tuple[str, int, int, int] | None:
    qualname_span = _decode_wire_qualname_span(row)
    if qualname_span is None:
        return None
    size = _as_int(row[3])
    if size is None:
        return None
    qualname, start_line, end_line = qualname_span
    return qualname, start_line, end_line, size


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

    _REQUIRED = {
        "min_loc",
        "min_stmt",
        "block_min_loc",
        "block_min_stmt",
        "segment_min_loc",
        "segment_min_stmt",
    }
    if set(obj.keys()) < _REQUIRED:
        return None

    min_loc = _as_int(obj.get("min_loc"))
    min_stmt = _as_int(obj.get("min_stmt"))
    block_min_loc = _as_int(obj.get("block_min_loc"))
    block_min_stmt = _as_int(obj.get("block_min_stmt"))
    segment_min_loc = _as_int(obj.get("segment_min_loc"))
    segment_min_stmt = _as_int(obj.get("segment_min_stmt"))
    if (
        min_loc is None
        or min_stmt is None
        or block_min_loc is None
        or block_min_stmt is None
        or segment_min_loc is None
        or segment_min_stmt is None
    ):
        return None

    return AnalysisProfile(
        min_loc=min_loc,
        min_stmt=min_stmt,
        block_min_loc=block_min_loc,
        block_min_stmt=block_min_stmt,
        segment_min_loc=segment_min_loc,
        segment_min_stmt=segment_min_stmt,
    )


def _decode_wire_stat(obj: dict[str, object]) -> FileStat | None:
    stat_list = _as_list(obj.get("st"))
    if stat_list is None or len(stat_list) != 2:
        return None
    mtime_ns = _as_int(stat_list[0])
    size = _as_int(stat_list[1])
    if mtime_ns is None or size is None:
        return None
    return FileStat(mtime_ns=mtime_ns, size=size)


def _decode_optional_wire_source_stats(
    *,
    obj: dict[str, object],
) -> SourceStatsDict | None:
    raw = obj.get("ss")
    if raw is None:
        return None
    row = _as_list(raw)
    if row is None or len(row) != 4:
        return None
    counts = _decode_wire_int_fields(row, 0, 1, 2, 3)
    if counts is None:
        return None
    lines, functions, methods, classes = counts
    if any(value < 0 for value in counts):
        return None
    return SourceStatsDict(
        lines=lines,
        functions=functions,
        methods=methods,
        classes=classes,
    )


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


def _decode_optional_wire_items_for_filepath(
    *,
    obj: dict[str, object],
    key: str,
    filepath: str,
    decode_item: Callable[[object, str], _DecodedItemT | None],
) -> list[_DecodedItemT] | None:
    raw_items = obj.get(key)
    if raw_items is None:
        return []
    wire_items = _as_list(raw_items)
    if wire_items is None:
        return None
    decoded_items: list[_DecodedItemT] = []
    for wire_item in wire_items:
        decoded = decode_item(wire_item, filepath)
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
    source_stats = _decode_optional_wire_source_stats(obj=obj)
    file_sections = _decode_wire_file_sections(obj=obj, filepath=filepath)
    if file_sections is None:
        return None
    (
        units,
        blocks,
        segments,
        class_metrics,
        module_deps,
        dead_candidates,
    ) = file_sections
    name_sections = _decode_wire_name_sections(obj=obj)
    if name_sections is None:
        return None
    (
        referenced_names,
        referenced_qualnames,
        import_names,
        class_names,
    ) = name_sections
    coupled_classes_map = _decode_optional_wire_coupled_classes(obj=obj, key="cc")
    if coupled_classes_map is None:
        return None

    for metric in class_metrics:
        names = coupled_classes_map.get(metric["qualname"], [])
        if names:
            metric["coupled_classes"] = names

    has_structural_findings = "sf" in obj
    structural_findings = _decode_wire_structural_findings_optional(obj)
    if structural_findings is None:
        return None

    result = CacheEntry(
        stat=stat,
        units=units,
        blocks=blocks,
        segments=segments,
        class_metrics=class_metrics,
        module_deps=module_deps,
        dead_candidates=dead_candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        import_names=import_names,
        class_names=class_names,
    )
    if source_stats is not None:
        result["source_stats"] = source_stats
    if has_structural_findings:
        result["structural_findings"] = _normalize_cached_structural_groups(
            structural_findings,
            filepath=filepath,
        )
    return result


def _decode_wire_file_sections(
    *,
    obj: dict[str, object],
    filepath: str,
) -> (
    tuple[
        list[UnitDict],
        list[BlockDict],
        list[SegmentDict],
        list[ClassMetricsDict],
        list[ModuleDepDict],
        list[DeadCandidateDict],
    ]
    | None
):
    units = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="u",
        filepath=filepath,
        decode_item=_decode_wire_unit,
    )
    blocks = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="b",
        filepath=filepath,
        decode_item=_decode_wire_block,
    )
    segments = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="s",
        filepath=filepath,
        decode_item=_decode_wire_segment,
    )
    class_metrics = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="cm",
        filepath=filepath,
        decode_item=_decode_wire_class_metric,
    )
    module_deps = _decode_optional_wire_items(
        obj=obj,
        key="md",
        decode_item=_decode_wire_module_dep,
    )
    dead_candidates = _decode_optional_wire_items_for_filepath(
        obj=obj,
        key="dc",
        filepath=filepath,
        decode_item=_decode_wire_dead_candidate,
    )
    if (
        units is None
        or blocks is None
        or segments is None
        or class_metrics is None
        or module_deps is None
        or dead_candidates is None
    ):
        return None
    return (
        units,
        blocks,
        segments,
        class_metrics,
        module_deps,
        dead_candidates,
    )


def _decode_wire_name_sections(
    *,
    obj: dict[str, object],
) -> tuple[list[str], list[str], list[str], list[str]] | None:
    referenced_names = _decode_optional_wire_names(obj=obj, key="rn")
    referenced_qualnames = _decode_optional_wire_names(obj=obj, key="rq")
    import_names = _decode_optional_wire_names(obj=obj, key="in")
    class_names = _decode_optional_wire_names(obj=obj, key="cn")
    if (
        referenced_names is None
        or referenced_qualnames is None
        or import_names is None
        or class_names is None
    ):
        return None
    return (
        referenced_names,
        referenced_qualnames,
        import_names,
        class_names,
    )


def _decode_wire_structural_findings_optional(
    obj: dict[str, object],
) -> list[StructuralFindingGroupDict] | None:
    """Decode optional 'sf' wire key. Returns [] if absent, None on invalid format."""
    raw = obj.get("sf")
    if raw is None:
        return []
    groups_raw = _as_list(raw)
    if groups_raw is None:
        return None
    groups: list[StructuralFindingGroupDict] = []
    for group_raw in groups_raw:
        group = _decode_wire_structural_group(group_raw)
        if group is None:
            return None
        groups.append(group)
    return groups


def _decode_wire_row(
    value: object,
    *,
    valid_lengths: Collection[int],
) -> list[object] | None:
    row = _as_list(value)
    if row is None or len(row) not in valid_lengths:
        return None
    return row


def _decode_wire_named_span(
    value: object,
    *,
    valid_lengths: Collection[int],
) -> tuple[list[object], str, int, int] | None:
    row = _decode_wire_row(value, valid_lengths=valid_lengths)
    if row is None:
        return None
    span = _decode_wire_qualname_span(row)
    if span is None:
        return None
    qualname, start_line, end_line = span
    return row, qualname, start_line, end_line


def _decode_wire_named_sized_span(
    value: object,
    *,
    valid_lengths: Collection[int],
) -> tuple[list[object], str, int, int, int] | None:
    row = _decode_wire_row(value, valid_lengths=valid_lengths)
    if row is None:
        return None
    span = _decode_wire_qualname_span_size(row)
    if span is None:
        return None
    qualname, start_line, end_line, size = span
    return row, qualname, start_line, end_line, size


def _decode_wire_int_fields(
    row: list[object],
    *indexes: int,
) -> tuple[int, ...] | None:
    values: list[int] = []
    for index in indexes:
        value = _as_int(row[index])
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _decode_wire_str_fields(
    row: list[object],
    *indexes: int,
) -> tuple[str, ...] | None:
    values: list[str] = []
    for index in indexes:
        value = _as_str(row[index])
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def _decode_wire_unit_core_fields(
    row: list[object],
) -> tuple[int, int, str, str, int, int, Literal["low", "medium", "high"], str] | None:
    int_fields = _decode_wire_int_fields(row, 3, 4, 7, 8)
    str_fields = _decode_wire_str_fields(row, 5, 6, 10)
    risk = _as_risk_literal(row[9])
    if int_fields is None or str_fields is None or risk is None:
        return None
    loc, stmt_count, cyclomatic_complexity, nesting_depth = int_fields
    fingerprint, loc_bucket, raw_hash = str_fields
    return (
        loc,
        stmt_count,
        fingerprint,
        loc_bucket,
        cyclomatic_complexity,
        nesting_depth,
        risk,
        raw_hash,
    )


def _decode_wire_unit_flow_profiles(
    row: list[object],
) -> tuple[int, str, bool, str, str, str] | None:
    if len(row) != 17:
        return _DEFAULT_WIRE_UNIT_FLOW_PROFILES

    parsed_entry_guard_count = _as_int(row[11])
    parsed_entry_guard_terminal_profile = _as_str(row[12])
    parsed_entry_guard_has_side_effect_before = _as_int(row[13])
    parsed_terminal_kind = _as_str(row[14])
    parsed_try_finally_profile = _as_str(row[15])
    parsed_side_effect_order_profile = _as_str(row[16])
    if (
        parsed_entry_guard_count is None
        or parsed_entry_guard_terminal_profile is None
        or parsed_entry_guard_has_side_effect_before is None
        or parsed_terminal_kind is None
        or parsed_try_finally_profile is None
        or parsed_side_effect_order_profile is None
    ):
        return None
    return (
        max(0, parsed_entry_guard_count),
        parsed_entry_guard_terminal_profile or "none",
        parsed_entry_guard_has_side_effect_before != 0,
        parsed_terminal_kind or "fallthrough",
        parsed_try_finally_profile or "none",
        parsed_side_effect_order_profile or "none",
    )


def _decode_wire_class_metric_fields(
    row: list[object],
) -> tuple[int, int, int, int, str, str] | None:
    int_fields = _decode_wire_int_fields(row, 3, 4, 5, 6)
    str_fields = _decode_wire_str_fields(row, 7, 8)
    if int_fields is None or str_fields is None:
        return None
    cbo, lcom4, method_count, instance_var_count = int_fields
    risk_coupling, risk_cohesion = str_fields
    return (
        cbo,
        lcom4,
        method_count,
        instance_var_count,
        risk_coupling,
        risk_cohesion,
    )


def _decode_wire_structural_group(value: object) -> StructuralFindingGroupDict | None:
    group_row = _as_list(value)
    if group_row is None or len(group_row) != 4:
        return None
    finding_kind = _as_str(group_row[0])
    finding_key = _as_str(group_row[1])
    items_raw = _as_list(group_row[3])
    signature = _decode_wire_structural_signature(group_row[2])
    if (
        finding_kind is None
        or finding_key is None
        or items_raw is None
        or signature is None
    ):
        return None
    items: list[StructuralFindingOccurrenceDict] = []
    for item_raw in items_raw:
        item = _decode_wire_structural_occurrence(item_raw)
        if item is None:
            return None
        items.append(item)
    return StructuralFindingGroupDict(
        finding_kind=finding_kind,
        finding_key=finding_key,
        signature=signature,
        items=items,
    )


def _decode_wire_structural_signature(value: object) -> dict[str, str] | None:
    sig_raw = _as_list(value)
    if sig_raw is None:
        return None
    signature: dict[str, str] = {}
    for pair in sig_raw:
        pair_list = _as_list(pair)
        if pair_list is None or len(pair_list) != 2:
            return None
        key = _as_str(pair_list[0])
        val = _as_str(pair_list[1])
        if key is None or val is None:
            return None
        signature[key] = val
    return signature


def _decode_wire_structural_occurrence(
    value: object,
) -> StructuralFindingOccurrenceDict | None:
    item_list = _as_list(value)
    if item_list is None or len(item_list) != 3:
        return None
    qualname = _as_str(item_list[0])
    start = _as_int(item_list[1])
    end = _as_int(item_list[2])
    if qualname is None or start is None or end is None:
        return None
    return StructuralFindingOccurrenceDict(
        qualname=qualname,
        start=start,
        end=end,
    )


def _decode_wire_unit(value: object, filepath: str) -> UnitDict | None:
    decoded = _decode_wire_named_span(value, valid_lengths={11, 17})
    if decoded is None:
        return None
    row, qualname, start_line, end_line = decoded
    core_fields = _decode_wire_unit_core_fields(row)
    flow_profiles = _decode_wire_unit_flow_profiles(row)
    if core_fields is None or flow_profiles is None:
        return None
    (
        loc,
        stmt_count,
        fingerprint,
        loc_bucket,
        cyclomatic_complexity,
        nesting_depth,
        risk,
        raw_hash,
    ) = core_fields
    (
        entry_guard_count,
        entry_guard_terminal_profile,
        entry_guard_has_side_effect_before,
        terminal_kind,
        try_finally_profile,
        side_effect_order_profile,
    ) = flow_profiles
    return FunctionGroupItem(
        qualname=qualname,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        loc=loc,
        stmt_count=stmt_count,
        fingerprint=fingerprint,
        loc_bucket=loc_bucket,
        cyclomatic_complexity=cyclomatic_complexity,
        nesting_depth=nesting_depth,
        risk=risk,
        raw_hash=raw_hash,
        entry_guard_count=entry_guard_count,
        entry_guard_terminal_profile=entry_guard_terminal_profile,
        entry_guard_has_side_effect_before=entry_guard_has_side_effect_before,
        terminal_kind=terminal_kind,
        try_finally_profile=try_finally_profile,
        side_effect_order_profile=side_effect_order_profile,
    )


def _decode_wire_block(value: object, filepath: str) -> BlockDict | None:
    decoded = _decode_wire_named_sized_span(value, valid_lengths={5})
    if decoded is None:
        return None
    row, qualname, start_line, end_line, size = decoded
    block_hash = _as_str(row[4])
    if block_hash is None:
        return None

    return BlockGroupItem(
        block_hash=block_hash,
        filepath=filepath,
        qualname=qualname,
        start_line=start_line,
        end_line=end_line,
        size=size,
    )


def _decode_wire_segment(value: object, filepath: str) -> SegmentDict | None:
    decoded = _decode_wire_named_sized_span(value, valid_lengths={6})
    if decoded is None:
        return None
    row, qualname, start_line, end_line, size = decoded
    segment_hash = _as_str(row[4])
    segment_sig = _as_str(row[5])
    if segment_hash is None or segment_sig is None:
        return None

    return SegmentGroupItem(
        segment_hash=segment_hash,
        segment_sig=segment_sig,
        filepath=filepath,
        qualname=qualname,
        start_line=start_line,
        end_line=end_line,
        size=size,
    )


def _decode_wire_class_metric(
    value: object,
    filepath: str,
) -> ClassMetricsDict | None:
    decoded = _decode_wire_named_span(value, valid_lengths={9})
    if decoded is None:
        return None
    row, qualname, start_line, end_line = decoded
    metric_fields = _decode_wire_class_metric_fields(row)
    if metric_fields is None:
        return None
    cbo, lcom4, method_count, instance_var_count, risk_coupling, risk_cohesion = (
        metric_fields
    )
    return ClassMetricsDict(
        qualname=qualname,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        cbo=cbo,
        lcom4=lcom4,
        method_count=method_count,
        instance_var_count=instance_var_count,
        risk_coupling=risk_coupling,
        risk_cohesion=risk_cohesion,
    )


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
    return ModuleDepDict(
        source=source,
        target=target,
        import_type=import_type,
        line=line,
    )


def _decode_wire_dead_candidate(
    value: object,
    filepath: str,
) -> DeadCandidateDict | None:
    row = _decode_wire_row(value, valid_lengths={5, 6})
    if row is None:
        return None
    qualname = _as_str(row[0])
    local_name = _as_str(row[1])
    start_line = _as_int(row[2])
    end_line = _as_int(row[3])
    kind = _as_str(row[4])
    suppressed_rules: list[str] | None = []
    if len(row) == 6:
        raw_rules = _as_list(row[5])
        if raw_rules is None or not all(isinstance(rule, str) for rule in raw_rules):
            return None
        suppressed_rules = sorted({str(rule) for rule in raw_rules if str(rule)})
    if (
        qualname is None
        or local_name is None
        or start_line is None
        or end_line is None
        or kind is None
    ):
        return None
    decoded = DeadCandidateDict(
        qualname=qualname,
        local_name=local_name,
        filepath=filepath,
        start_line=start_line,
        end_line=end_line,
        kind=kind,
    )
    if suppressed_rules:
        decoded["suppressed_rules"] = suppressed_rules
    return decoded


def _encode_wire_file_entry(entry: CacheEntry) -> dict[str, object]:
    wire: dict[str, object] = {
        "st": [entry["stat"]["mtime_ns"], entry["stat"]["size"]],
    }
    source_stats = entry.get("source_stats")
    if source_stats is not None:
        wire["ss"] = [
            source_stats["lines"],
            source_stats["functions"],
            source_stats["methods"],
            source_stats["classes"],
        ]

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
                unit.get("entry_guard_count", 0),
                unit.get("entry_guard_terminal_profile", "none"),
                1 if unit.get("entry_guard_has_side_effect_before", False) else 0,
                unit.get("terminal_kind", "fallthrough"),
                unit.get("try_finally_profile", "none"),
                unit.get("side_effect_order_profile", "none"),
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
            candidate["start_line"],
            candidate["end_line"],
            candidate["qualname"],
            candidate["local_name"],
            candidate["kind"],
        ),
    )
    if dead_candidates:
        # Dead candidates are stored inside a per-file cache entry, so the
        # filepath is implicit and does not need to be repeated in every row.
        encoded_dead_candidates: list[list[object]] = []
        for candidate in dead_candidates:
            encoded = [
                candidate["qualname"],
                candidate["local_name"],
                candidate["start_line"],
                candidate["end_line"],
                candidate["kind"],
            ]
            suppressed_rules = candidate.get("suppressed_rules", [])
            if _is_string_list(suppressed_rules):
                normalized_rules = sorted(set(suppressed_rules))
                if normalized_rules:
                    encoded.append(normalized_rules)
            encoded_dead_candidates.append(encoded)
        wire["dc"] = encoded_dead_candidates

    if entry["referenced_names"]:
        wire["rn"] = sorted(set(entry["referenced_names"]))
    if entry.get("referenced_qualnames"):
        wire["rq"] = sorted(set(entry["referenced_qualnames"]))
    if entry["import_names"]:
        wire["in"] = sorted(set(entry["import_names"]))
    if entry["class_names"]:
        wire["cn"] = sorted(set(entry["class_names"]))

    if "structural_findings" in entry:
        sf = entry.get("structural_findings", [])
        wire["sf"] = [
            [
                group["finding_kind"],
                group["finding_key"],
                sorted(group["signature"].items()),
                [
                    [item["qualname"], item["start"], item["end"]]
                    for item in group["items"]
                ],
            ]
            for group in sf
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


def _is_source_stats_dict(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    lines = value.get("lines")
    functions = value.get("functions")
    methods = value.get("methods")
    classes = value.get("classes")
    return (
        isinstance(lines, int)
        and lines >= 0
        and isinstance(functions, int)
        and functions >= 0
        and isinstance(methods, int)
        and methods >= 0
        and isinstance(classes, int)
        and classes >= 0
    )


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
        and isinstance(value.get("entry_guard_count", 0), int)
        and isinstance(value.get("entry_guard_terminal_profile", "none"), str)
        and isinstance(value.get("entry_guard_has_side_effect_before", False), bool)
        and isinstance(value.get("terminal_kind", "fallthrough"), str)
        and isinstance(value.get("try_finally_profile", "none"), str)
        and isinstance(value.get("side_effect_order_profile", "none"), str)
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
    if not _has_typed_fields(
        value,
        string_keys=("qualname", "local_name", "filepath", "kind"),
        int_keys=("start_line", "end_line"),
    ):
        return False
    suppressed_rules = value.get("suppressed_rules")
    if suppressed_rules is None:
        return True
    return _is_string_list(suppressed_rules)


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
