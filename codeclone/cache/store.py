# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
from collections.abc import Collection, Sequence
from json import JSONDecodeError
from pathlib import Path
from typing import Protocol

from ..baseline.trust import current_python_tag
from ..contracts import (
    BASELINE_FINGERPRINT_VERSION,
    CACHE_VERSION,
    DEFAULT_BLOCK_MIN_LOC,
    DEFAULT_BLOCK_MIN_STMT,
    DEFAULT_MIN_LOC,
    DEFAULT_MIN_STMT,
    DEFAULT_SEGMENT_MIN_LOC,
    DEFAULT_SEGMENT_MIN_STMT,
)
from ..contracts.errors import CacheError
from ..models import (
    BlockUnit,
    CacheDependentPayload,
    CacheEntryV3,
    CacheNeutralBlock,
    CacheNeutralPayload,
    CacheNeutralSegment,
    CacheNeutralUnit,
    CacheReuseDecision,
    ContentIdentityVerdict,
    DigestObject,
    FileMetrics,
    FileStat,
    FunctionRelationshipFacts,
    GitContentSnapshot,
    ModuleRegistryHandle,
    SegmentUnit,
    SemanticFileFacts,
    SourceStatsDict,
    StructuralFindingGroup,
    Unit,
)
from ..observability import span
from ._wire_decode import _decode_wire_file_entry
from ._wire_encode import _encode_wire_file_entry
from .entries import (
    _api_surface_dict_from_model,
    _class_metrics_dict_from_model,
    _dead_candidate_dict_from_model,
    _docstring_coverage_dict_from_model,
    _function_relationship_facts_dict_from_model,
    _module_dep_dict_from_model,
    _new_optional_metrics_payload,
    _normalize_cached_structural_groups,
    _runtime_reachability_dict_from_model,
    _security_surface_dict_from_model,
    _structural_group_dict_from_model,
    _typing_coverage_dict_from_model,
)
from .integrity import (
    as_str_dict as _as_str_dict,
)
from .integrity import (
    as_str_or_none as _as_str,
)
from .integrity import (
    cache_envelope_checksum,
    read_json_document,
    verify_cache_envelope_checksum,
    write_json_document_atomically,
)
from .projection import (
    SegmentReportProjection,
    decode_segment_report_projection,
    encode_segment_report_projection,
    localize_semantic_facts,
    runtime_filepath_from_wire,
    wire_filepath_from_runtime,
)
from .reuse import (
    binding_context_digest,
    build_module_dependent_profile,
    build_module_neutral_profile,
    cache_reuse_decision,
    git_blob_identity_for_parsed_source,
)
from .versioning import (
    LEGACY_CACHE_SECRET_FILENAME,
    MAX_CACHE_SIZE_BYTES,
    CacheData,
    CacheStatus,
    _empty_cache_data,
    _resolve_root,
)


class _CacheStatusLike(Protocol):
    @property
    def load_status(self) -> CacheStatus | str | None: ...

    @property
    def load_warning(self) -> str | None: ...

    @property
    def cache_schema_version(self) -> str | None: ...


def resolve_cache_status(cache: _CacheStatusLike) -> tuple[CacheStatus, str | None]:
    raw_cache_status = getattr(cache, "load_status", None)
    load_warning = getattr(cache, "load_warning", None)
    if isinstance(raw_cache_status, CacheStatus):
        cache_status = raw_cache_status
    elif isinstance(raw_cache_status, str):
        try:
            cache_status = CacheStatus(raw_cache_status)
        except ValueError:
            cache_status = (
                CacheStatus.OK if load_warning is None else CacheStatus.INVALID_TYPE
            )
    else:
        cache_status = (
            CacheStatus.OK if load_warning is None else CacheStatus.INVALID_TYPE
        )

    raw_cache_schema_version = getattr(cache, "cache_schema_version", None)
    cache_schema_version = (
        raw_cache_schema_version if isinstance(raw_cache_schema_version, str) else None
    )
    return cache_status, cache_schema_version


class Cache:
    __slots__ = (
        "_binding_context_by_runtime_path",
        "_canonical_runtime_paths",
        "_collect_api_surface",
        "_dirty",
        "_git_content_snapshot",
        "_module_dependent_profile",
        "_module_names_by_runtime_path",
        "_module_neutral_profile",
        "_write_enabled",
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
        min_loc: int = DEFAULT_MIN_LOC,
        min_stmt: int = DEFAULT_MIN_STMT,
        block_min_loc: int = DEFAULT_BLOCK_MIN_LOC,
        block_min_stmt: int = DEFAULT_BLOCK_MIN_STMT,
        segment_min_loc: int = DEFAULT_SEGMENT_MIN_LOC,
        segment_min_stmt: int = DEFAULT_SEGMENT_MIN_STMT,
        collect_api_surface: bool = False,
        write_enabled: bool = True,
    ):
        self.path = Path(path)
        self.root = _resolve_root(root)
        self._write_enabled = write_enabled
        self.fingerprint_version = BASELINE_FINGERPRINT_VERSION
        self._collect_api_surface = collect_api_surface
        self._module_neutral_profile = build_module_neutral_profile(
            fingerprint_version=self.fingerprint_version,
            min_loc=min_loc,
            min_stmt=min_stmt,
            block_min_loc=block_min_loc,
            block_min_stmt=block_min_stmt,
            segment_min_loc=segment_min_loc,
            segment_min_stmt=segment_min_stmt,
        )
        self._module_dependent_profile = build_module_dependent_profile(
            neutral_profile=self._module_neutral_profile,
            module_manifest_digest=DigestObject(
                domain="codeclone.module-registry.v1",
                algorithm="sha256",
                value="0" * 64,
            ),
            collect_api_surface=collect_api_surface,
        )
        self._module_names_by_runtime_path: dict[str, str] = {}
        self._binding_context_by_runtime_path: dict[str, DigestObject] = {}
        self.data: CacheData = _empty_cache_data(
            version=self._CACHE_VERSION,
            python_tag=current_python_tag(),
            fingerprint_version=self.fingerprint_version,
        )
        self._canonical_runtime_paths: set[str] = set()
        snapshot_root = self.root if self.root is not None else self.path.parent
        self._git_content_snapshot = GitContentSnapshot(
            root=str(snapshot_root.resolve()),
            git_available=False,
            object_format=None,
            tracked=(),
            dirty_paths=frozenset(),
            untracked_paths=frozenset(),
            index_ambiguous_paths=frozenset(),
            racy_paths=frozenset(),
        )
        self.legacy_secret_warning = self._detect_legacy_secret_warning()
        self.cache_schema_version: str | None = None
        self.load_status = CacheStatus.MISSING
        self.load_warning: str | None = self.legacy_secret_warning
        self.max_size_bytes = (
            MAX_CACHE_SIZE_BYTES if max_size_bytes is None else max_size_bytes
        )
        self.segment_report_projection: SegmentReportProjection | None = None
        self._dirty: bool = write_enabled

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

    def bind_git_content_snapshot(self, snapshot: GitContentSnapshot) -> None:
        self._git_content_snapshot = snapshot

    def bind_module_registry(self, registry: ModuleRegistryHandle) -> None:
        if self.root is None:
            raise ValueError("cache module registry binding requires a project root")
        # Each entry carries its own binding context, not the whole manifest:
        # one module moving mount must invalidate that module, not the repo.
        self._binding_context_by_runtime_path = {
            str((self.root / entry.identity.file.path).resolve()): (
                binding_context_digest(entry.identity.python_module)
            )
            for entry in registry.entries_by_path.values()
            if entry.analyzed
        }
        self._module_names_by_runtime_path = {
            str((self.root / entry.identity.file.path).resolve()): (
                entry.identity.python_module.module
                if entry.identity.python_module is not None
                else entry.identity.file.path
            )
            for entry in registry.entries_by_path.values()
            if entry.analyzed
        }
        self._module_dependent_profile = build_module_dependent_profile(
            neutral_profile=self._module_neutral_profile,
            module_manifest_digest=registry.digest,
            collect_api_surface=self._collect_api_surface,
        )

    def _binding_context_for(self, runtime_path: str) -> DigestObject:
        """Binding context of one analysed file, or the module-less digest.

        A path absent from the registry has no module identity to bind, and the
        module-less digest is what such a file is written with, so the two
        agree instead of silently never matching.
        """

        known = self._binding_context_by_runtime_path.get(runtime_path)
        return known if known is not None else binding_context_digest(None)

    def reuse_decision(
        self,
        *,
        content: ContentIdentityVerdict,
        entry: CacheEntryV3,
        runtime_path: str,
    ) -> CacheReuseDecision:
        return cache_reuse_decision(
            content=content,
            entry=entry,
            neutral_profile=self._module_neutral_profile,
            dependent_profile=self._module_dependent_profile,
            binding_context=self._binding_context_for(runtime_path),
        )

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
        size: int | None = None
        with span(name="cache.stat") as stat_span:
            try:
                exists = self.path.exists()
            except OSError as exc:
                self._ignore_cache(
                    f"Cache unreadable; ignoring cache: {exc}",
                    status=CacheStatus.UNREADABLE,
                )
                return
            if exists:
                try:
                    size = self.path.stat().st_size
                    stat_span.set_counter("cache_file_bytes", size)
                except OSError:
                    pass

        if not exists:
            self._set_load_warning(None)
            self.load_status = CacheStatus.MISSING
            self.cache_schema_version = None
            self._canonical_runtime_paths = set()
            self.segment_report_projection = None
            return

        try:
            if size is None:
                with span(name="cache.stat") as stat_span:
                    size = self.path.stat().st_size
                    stat_span.set_counter("cache_file_bytes", size)
            if size > self.max_size_bytes:
                self._ignore_cache(
                    "Cache file too large "
                    f"({size} bytes, max {self.max_size_bytes}); ignoring cache.",
                    status=CacheStatus.TOO_LARGE,
                )
                return

            with span(name="cache.read_json") as read_span:
                read_span.set_counter("cache_file_bytes", size)
                raw_obj = read_json_document(self.path, max_bytes=self.max_size_bytes)
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
        with span(name="cache.validate_envelope"):
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

            checksum = _as_str(raw.get("checksum"))
            payload = _as_str_dict(raw.get("payload"))
            if checksum is None or payload is None:
                return self._reject_invalid_cache_format(schema_version=version)

            # Verify over {version, payload}: the on-disk ``v`` is inside the
            # checksummed scope, so a generation retagged by migration is refused
            # here even though it passed the ``v == _CACHE_VERSION`` gate above.
            # This is NOT redundant with that gate - see cache_envelope_checksum
            # for the {11,17} decode-tolerance cross-defect witness. The checksum
            # is an integrity check, NOT authentication (see its threat model).
            if not verify_cache_envelope_checksum(version, payload, checksum):
                return self._reject_cache_load(
                    "Cache checksum mismatch; ignoring cache.",
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

            files_dict = _as_str_dict(payload.get("files"))
            if files_dict is None:
                return self._reject_invalid_cache_format(schema_version=version)
            segment_projection_obj = payload.get("sr")
            payload.pop("files", None)
            payload.clear()
            raw.clear()

        parsed_files: dict[str, CacheEntryV3] = {}
        with span(name="cache.decode_entries") as decode_span:
            decode_span.set_counter("cache_entries", len(files_dict))
            while files_dict:
                wire_path = next(iter(files_dict))
                file_entry_obj = files_dict.pop(wire_path)
                runtime_path = runtime_filepath_from_wire(wire_path, root=self.root)
                parsed_entry = self._decode_entry(file_entry_obj, runtime_path)
                if parsed_entry is None:
                    return self._reject_invalid_cache_format(schema_version=version)
                parsed_files[runtime_path] = parsed_entry
            decode_span.set_counter("decoded_entries", len(parsed_files))
        with span(name="cache.segment_projection"):
            self.segment_report_projection = decode_segment_report_projection(
                segment_projection_obj,
                root=self.root,
            )

        self.cache_schema_version = version
        return CacheData(
            version=self._CACHE_VERSION,
            python_tag=runtime_tag,
            fingerprint_version=self.fingerprint_version,
            files=parsed_files,
        )

    def save(self) -> None:
        if not self._write_enabled:
            return
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
                "files": wire_files,
            }
            segment_projection = encode_segment_report_projection(
                self.segment_report_projection,
                root=self.root,
            )
            if segment_projection is not None:
                payload["sr"] = segment_projection
            envelope = {
                "v": self._CACHE_VERSION,
                "payload": payload,
                "checksum": cache_envelope_checksum(self._CACHE_VERSION, payload),
            }
            write_json_document_atomically(self.path, envelope)
            self._dirty = False

            self.data["version"] = self._CACHE_VERSION
            self.data["python_tag"] = current_python_tag()
            self.data["fingerprint_version"] = self.fingerprint_version
        except OSError as exc:
            raise CacheError(f"Failed to save cache: {exc}") from exc

    def release_loaded_entries(self, *, allow_dirty: bool = False) -> int:
        if self._dirty and not allow_dirty:
            return 0
        with span(name="cache.release_entries") as release_span:
            released = len(self.data["files"])
            self.data["files"] = {}
            self._canonical_runtime_paths.clear()
            release_span.set_counter("released_entries", released)
            return released

    @staticmethod
    def _decode_entry(value: object, filepath: str) -> CacheEntryV3 | None:
        return _decode_wire_file_entry(value, filepath)

    @staticmethod
    def _encode_entry(entry: CacheEntryV3) -> dict[str, object]:
        return _encode_wire_file_entry(entry)

    def _store_canonical_file_entry(
        self,
        *,
        runtime_path: str,
        canonical_entry: CacheEntryV3,
    ) -> CacheEntryV3:
        previous_entry = self.data["files"].get(runtime_path)
        was_canonical = runtime_path in self._canonical_runtime_paths
        self.data["files"][runtime_path] = canonical_entry
        self._canonical_runtime_paths.add(runtime_path)
        if not was_canonical or previous_entry != canonical_entry:
            self._dirty = True
        return canonical_entry

    def get_file_entry(self, filepath: str) -> CacheEntryV3 | None:
        runtime_lookup_key = filepath
        entry_obj = self.data["files"].get(runtime_lookup_key)
        if entry_obj is None:
            wire_key = wire_filepath_from_runtime(filepath, root=self.root)
            runtime_lookup_key = runtime_filepath_from_wire(wire_key, root=self.root)
            entry_obj = self.data["files"].get(runtime_lookup_key)

        if entry_obj is None:
            return None

        return entry_obj

    def put_file_entry(
        self,
        filepath: str,
        stat_sig: FileStat,
        units: list[Unit],
        blocks: list[BlockUnit],
        segments: list[SegmentUnit],
        *,
        source_content_digest: DigestObject,
        source_stats: SourceStatsDict | None = None,
        file_metrics: FileMetrics | None = None,
        structural_findings: list[StructuralFindingGroup] | None = None,
        function_relationship_facts: Sequence[FunctionRelationshipFacts] | None = None,
    ) -> None:
        if not self._write_enabled:
            return
        runtime_path = runtime_filepath_from_wire(
            wire_filepath_from_runtime(filepath, root=self.root),
            root=self.root,
        )

        effective_relationship_facts = function_relationship_facts
        if effective_relationship_facts is None:
            effective_relationship_facts = (
                file_metrics.function_relationship_facts
                if file_metrics is not None
                else ()
            )
        function_relationship_fact_rows = [
            _function_relationship_facts_dict_from_model(
                facts,
                filepath=runtime_path,
            )
            for facts in effective_relationship_facts
        ]

        (
            class_metrics_rows,
            module_dep_rows,
            dead_candidate_rows,
            referenced_names,
            referenced_qualnames,
            import_names,
            class_names,
            runtime_reachability,
            security_surfaces,
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
            runtime_reachability = [
                _runtime_reachability_dict_from_model(fact, runtime_path)
                for fact in file_metrics.runtime_reachability
            ]
            security_surfaces = [
                _security_surface_dict_from_model(surface, runtime_path)
                for surface in file_metrics.security_surfaces
            ]
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
        git_blob_id_at_write = git_blob_identity_for_parsed_source(
            path=Path(runtime_path),
            source_digest=source_content_digest,
            git_snapshot=self._git_content_snapshot,
        )
        module_name = self._module_names_by_runtime_path.get(runtime_path)
        if module_name is None:
            raise ValueError(
                f"cache entry path is absent from module registry: {runtime_path}"
            )

        def local_name(qualname: str) -> str:
            prefix = f"{module_name}:"
            if not qualname.startswith(prefix):
                raise ValueError(
                    "cache neutral qualname is outside module "
                    f"{module_name}: {qualname}"
                )
            return qualname[len(prefix) :]

        structural_rows = (
            tuple(
                _normalize_cached_structural_groups(
                    [
                        _structural_group_dict_from_model(group)
                        for group in structural_findings
                    ],
                    filepath=runtime_path,
                )
            )
            if structural_findings is not None
            else None
        )
        entry = CacheEntryV3(
            cache_content_binding_version="1",
            source_content_digest=source_content_digest,
            binding_context_digest=self._binding_context_for(runtime_path),
            git_blob_id_at_write=git_blob_id_at_write,
            stat=stat_sig,
            module_neutral_profile=self._module_neutral_profile,
            module_dependent_profile=self._module_dependent_profile,
            module_neutral=CacheNeutralPayload(
                source_stats=source_stats_payload,
                units=tuple(
                    CacheNeutralUnit(
                        local_name=local_name(unit.qualname),
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
                        statement_sequence=unit.statement_sequence,
                        renamed_fingerprint=unit.renamed_fingerprint,
                        renamed_statement_sequence=unit.renamed_statement_sequence,
                        unreachable_statements=unit.unreachable_statements,
                    )
                    for unit in units
                ),
                blocks=tuple(
                    CacheNeutralBlock(
                        local_name=local_name(block.qualname),
                        start_line=block.start_line,
                        end_line=block.end_line,
                        size=block.size,
                        block_hash=block.block_hash,
                    )
                    for block in blocks
                ),
                segments=tuple(
                    CacheNeutralSegment(
                        local_name=local_name(segment.qualname),
                        start_line=segment.start_line,
                        end_line=segment.end_line,
                        size=segment.size,
                        segment_hash=segment.segment_hash,
                        segment_sig=segment.segment_sig,
                    )
                    for segment in segments
                ),
                semantic_facts=localize_semantic_facts(
                    (
                        file_metrics.semantic_facts
                        if file_metrics is not None
                        else SemanticFileFacts()
                    ),
                    module_name=module_name,
                ),
            ),
            module_dependent=CacheDependentPayload(
                class_metrics=tuple(class_metrics_rows),
                module_deps=tuple(module_dep_rows),
                dead_candidates=tuple(dead_candidate_rows),
                referenced_names=tuple(referenced_names),
                referenced_qualnames=tuple(referenced_qualnames),
                import_names=tuple(import_names),
                class_names=tuple(class_names),
                runtime_reachability=tuple(runtime_reachability),
                security_surfaces=tuple(security_surfaces),
                function_relationship_facts=tuple(function_relationship_fact_rows),
                typing_coverage=typing_coverage,
                docstring_coverage=docstring_coverage,
                api_surface=api_surface,
                structural_findings=structural_rows,
            ),
        )
        self._store_canonical_file_entry(
            runtime_path=runtime_path,
            canonical_entry=entry,
        )

    def prune_file_entries(self, existing_filepaths: Collection[str]) -> int:
        if not self._write_enabled:
            return 0
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
