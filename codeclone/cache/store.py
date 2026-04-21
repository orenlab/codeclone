# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from collections.abc import Collection
from json import JSONDecodeError
from pathlib import Path

from ..baseline.trust import current_python_tag
from ..contracts import BASELINE_FINGERPRINT_VERSION, CACHE_VERSION
from ..contracts.errors import CacheError
from ..models import BlockUnit, FileMetrics, SegmentUnit, StructuralFindingGroup, Unit
from ._canonicalize import (
    _as_file_stat_dict,
    _as_typed_block_list,
    _as_typed_segment_list,
    _as_typed_unit_list,
    _attach_optional_cache_sections,
    _canonicalize_cache_entry,
    _decode_optional_cache_sections,
    _is_canonical_cache_entry,
)
from ._wire_decode import _decode_wire_file_entry
from ._wire_encode import _encode_wire_file_entry
from .entries import (
    CacheEntry,
    FileStat,
    SourceStatsDict,
    _api_surface_dict_from_model,
    _block_dict_from_model,
    _class_metrics_dict_from_model,
    _dead_candidate_dict_from_model,
    _docstring_coverage_dict_from_model,
    _module_dep_dict_from_model,
    _new_optional_metrics_payload,
    _normalize_cached_structural_groups,
    _segment_dict_from_model,
    _structural_group_dict_from_model,
    _typing_coverage_dict_from_model,
    _unit_dict_from_model,
)
from .integrity import (
    as_str_dict as _as_str_dict,
)
from .integrity import (
    as_str_or_none as _as_str,
)
from .integrity import (
    read_json_document,
    sign_cache_payload,
    verify_cache_payload_signature,
    write_json_document_atomically,
)
from .projection import (
    SegmentReportProjection,
    decode_segment_report_projection,
    encode_segment_report_projection,
    runtime_filepath_from_wire,
    wire_filepath_from_runtime,
)
from .versioning import (
    LEGACY_CACHE_SECRET_FILENAME,
    MAX_CACHE_SIZE_BYTES,
    AnalysisProfile,
    CacheData,
    CacheStatus,
    _as_analysis_profile,
    _empty_cache_data,
    _resolve_root,
)


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
        collect_api_surface: bool = False,
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
            "collect_api_surface": collect_api_surface,
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
        self._dirty: bool = True

    def _detect_legacy_secret_warning(self) -> str | None:
        secret_path = self.path.parent / LEGACY_CACHE_SECRET_FILENAME
        try:
            if secret_path.exists():
                return (
                    f"Legacy cache secret file detected at {secret_path}; "
                    "delete this obsolete file."
                )
        except OSError as exc:
            return f"Legacy cache secret check failed: {exc}"
        return None

    def _set_load_warning(self, message: str | None) -> None:
        warning = message
        if warning is None:
            warning = self.legacy_secret_warning
        elif self.legacy_secret_warning:
            warning = f"{warning}\n{self.legacy_secret_warning}"
        self.load_warning = warning

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

    def load(self) -> None:
        try:
            exists = self.path.exists()
        except OSError as exc:
            self._ignore_cache(
                f"Cache unreadable; ignoring cache: {exc}",
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

            raw_obj = read_json_document(self.path)
            parsed = self._load_and_validate(raw_obj)
            if parsed is None:
                return
            self.data = parsed
            self._canonical_runtime_paths = set(parsed["files"].keys())
            self.load_status = CacheStatus.OK
            self._set_load_warning(None)
            self._dirty = False
        except OSError as exc:
            self._ignore_cache(
                f"Cache unreadable; ignoring cache: {exc}",
                status=CacheStatus.UNREADABLE,
            )
        except JSONDecodeError:
            self._ignore_cache(
                "Cache corrupted; ignoring cache.",
                status=CacheStatus.INVALID_JSON,
            )

    def _load_and_validate(self, raw_obj: object) -> CacheData | None:
        raw = _as_str_dict(raw_obj)
        if raw is None:
            return self._reject_invalid_cache_format()

        legacy_version = _as_str(raw.get("version"))
        if legacy_version is not None:
            return self._reject_version_mismatch(legacy_version)

        version = _as_str(raw.get("v"))
        if version is None:
            return self._reject_invalid_cache_format()

        if version != self._CACHE_VERSION:
            return self._reject_version_mismatch(version)

        sig = _as_str(raw.get("sig"))
        payload = _as_str_dict(raw.get("payload"))
        if sig is None or payload is None:
            return self._reject_invalid_cache_format(schema_version=version)

        if not verify_cache_payload_signature(payload, sig):
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
                f"min_stmt={analysis_profile['min_stmt']}, "
                "collect_api_surface="
                f"{str(analysis_profile['collect_api_surface']).lower()}; "
                f"expected min_loc={self.analysis_profile['min_loc']}, "
                f"min_stmt={self.analysis_profile['min_stmt']}, "
                "collect_api_surface="
                f"{str(self.analysis_profile['collect_api_surface']).lower()}); "
                "ignoring cache.",
                status=CacheStatus.ANALYSIS_PROFILE_MISMATCH,
                schema_version=version,
            )

        files_dict = _as_str_dict(payload.get("files"))
        if files_dict is None:
            return self._reject_invalid_cache_format(schema_version=version)

        parsed_files: dict[str, CacheEntry] = {}
        for wire_path, file_entry_obj in files_dict.items():
            runtime_path = runtime_filepath_from_wire(wire_path, root=self.root)
            parsed_entry = self._decode_entry(file_entry_obj, runtime_path)
            if parsed_entry is None:
                return self._reject_invalid_cache_format(schema_version=version)
            parsed_files[runtime_path] = _canonicalize_cache_entry(parsed_entry)
        self.segment_report_projection = decode_segment_report_projection(
            payload.get("sr"),
            root=self.root,
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
            wire_files: dict[str, object] = {}
            wire_map = {
                runtime_path: wire_filepath_from_runtime(runtime_path, root=self.root)
                for runtime_path in self.data["files"]
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
            segment_projection = encode_segment_report_projection(
                self.segment_report_projection,
                root=self.root,
            )
            if segment_projection is not None:
                payload["sr"] = segment_projection
            signed_doc = {
                "v": self._CACHE_VERSION,
                "payload": payload,
                "sig": sign_cache_payload(payload),
            }
            write_json_document_atomically(self.path, signed_doc)
            self._dirty = False

            self.data["version"] = self._CACHE_VERSION
            self.data["python_tag"] = current_python_tag()
            self.data["fingerprint_version"] = self.fingerprint_version
            self.data["analysis_profile"] = self.analysis_profile
        except OSError as exc:
            raise CacheError(f"Failed to save cache: {exc}") from exc

    @staticmethod
    def _decode_entry(value: object, filepath: str) -> CacheEntry | None:
        return _decode_wire_file_entry(value, filepath)

    @staticmethod
    def _encode_entry(entry: CacheEntry) -> dict[str, object]:
        return _encode_wire_file_entry(entry)

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
            wire_key = wire_filepath_from_runtime(filepath, root=self.root)
            runtime_lookup_key = runtime_filepath_from_wire(wire_key, root=self.root)
            entry_obj = self.data["files"].get(runtime_lookup_key)

        if entry_obj is None:
            return None

        if runtime_lookup_key in self._canonical_runtime_paths:
            if _is_canonical_cache_entry(entry_obj):
                return entry_obj
            self._canonical_runtime_paths.discard(runtime_lookup_key)

        if not isinstance(entry_obj, dict):
            return None

        stat = _as_file_stat_dict(entry_obj.get("stat"))
        units = _as_typed_unit_list(entry_obj.get("units"))
        blocks = _as_typed_block_list(entry_obj.get("blocks"))
        segments = _as_typed_segment_list(entry_obj.get("segments"))
        if stat is None or units is None or blocks is None or segments is None:
            return None

        optional_sections = _decode_optional_cache_sections(entry_obj)
        if optional_sections is None:
            return None
        (
            class_metrics_raw,
            module_deps_raw,
            dead_candidates_raw,
            referenced_names_raw,
            referenced_qualnames_raw,
            import_names_raw,
            class_names_raw,
            typing_coverage_raw,
            docstring_coverage_raw,
            api_surface_raw,
            source_stats,
            structural_findings,
        ) = optional_sections

        entry_to_canonicalize: CacheEntry = _attach_optional_cache_sections(
            CacheEntry(
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
            ),
            typing_coverage=typing_coverage_raw,
            docstring_coverage=docstring_coverage_raw,
            api_surface=api_surface_raw,
            source_stats=source_stats,
            structural_findings=structural_findings,
        )
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
        runtime_path = runtime_filepath_from_wire(
            wire_filepath_from_runtime(filepath, root=self.root),
            root=self.root,
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
            typing_coverage,
            docstring_coverage,
            api_surface,
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
            typing_coverage = _typing_coverage_dict_from_model(
                file_metrics.typing_coverage,
                filepath=runtime_path,
            )
            docstring_coverage = _docstring_coverage_dict_from_model(
                file_metrics.docstring_coverage,
                filepath=runtime_path,
            )
            api_surface = _api_surface_dict_from_model(
                file_metrics.api_surface,
                filepath=runtime_path,
            )

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
        if typing_coverage is not None:
            entry_dict["typing_coverage"] = typing_coverage
        if docstring_coverage is not None:
            entry_dict["docstring_coverage"] = docstring_coverage
        if api_surface is not None:
            entry_dict["api_surface"] = api_surface
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

    def prune_file_entries(self, existing_filepaths: Collection[str]) -> int:
        keep_runtime_paths = {
            runtime_filepath_from_wire(
                wire_filepath_from_runtime(filepath, root=self.root),
                root=self.root,
            )
            for filepath in existing_filepaths
        }
        stale_runtime_paths = sorted(
            runtime_path
            for runtime_path in self.data["files"]
            if runtime_path not in keep_runtime_paths
        )
        if not stale_runtime_paths:
            return 0
        for runtime_path in stale_runtime_paths:
            self.data["files"].pop(runtime_path, None)
            self._canonical_runtime_paths.discard(runtime_path)
        self._dirty = True
        return len(stale_runtime_paths)


def file_stat_signature(path: str) -> FileStat:
    stat_result = os.stat(path)
    return FileStat(
        mtime_ns=stat_result.st_mtime_ns,
        size=stat_result.st_size,
    )


__all__ = ["Cache", "file_stat_signature"]
