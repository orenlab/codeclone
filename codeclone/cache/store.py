# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import os
import time
from collections.abc import Collection, Sequence
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
    CloneArtifactChannel,
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
from ..observability import SpanHandle, span
from ..paths.workspace import workspace_dir_for_cache_path
from ._wire_decode import _decode_wire_file_entry
from ._wire_encode import _encode_wire_file_entry
from .backend import (
    CACHE_BACKEND_SCHEMA_VERSION,
    META_KEY_CHECKSUM,
    META_KEY_FINGERPRINT,
    META_KEY_GENERATION,
    META_KEY_PYTHON_TAG,
    META_KEY_SCHEMA,
    META_KEY_VERSION,
    SINGLETON_SEGMENT_REPORT,
    TABLE_DEPENDENT,
    TABLE_NEUTRAL,
    CacheBackend,
    CacheBackendForeign,
    CacheBackendUnreadable,
    CacheBackendUnusable,
    EntryIdentity,
    WireShapeRefused,
    join_wire_entry,
    split_wire_entry,
    verify_envelope,
)
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
from .gc import collect_cache_garbage
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
    LEGACY_CACHE_MONOLITH_FILENAME,
    LEGACY_CACHE_SECRET_FILENAME,
    MAX_CACHE_SIZE_BYTES,
    CacheData,
    CacheStatus,
    _empty_cache_data,
    _resolve_root,
    new_tracked_files,
    tracked_files,
)
from .versioning import (
    mark_deleted as _mark_deleted,
)


class _CacheStatusLike(Protocol):
    @property
    def load_status(self) -> CacheStatus | str | None: ...

    @property
    def load_warning(self) -> str | None: ...

    @property
    def cache_schema_version(self) -> str | None: ...


def _now_epoch() -> int:
    """Wall-clock seconds, for recency marks only.

    Never for ordering anything a result depends on: the cache's own ordering
    is the generation counter, which does not move backwards when a clock does.
    """

    return int(time.time())


def _record_db_cost(handle: SpanHandle, backend: CacheBackend) -> None:
    """Publish this handle's SQLite work into the observer's db_cost section.

    A span joins ``db_cost`` by carrying ``db_queries``; the other two give the
    section its N+1 shape (many statements, few rows). Without these the cache
    is the one store in the process whose work cannot be looked at, which is
    exactly the black box the observer exists to prevent.
    """

    handle.set_counter("db_queries", backend.queries)
    handle.set_counter("db_writes", backend.writes)
    handle.set_counter("db_rows", backend.rows)


def _as_generation(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


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
        "_discard_store",
        "_generation",
        "_git_content_snapshot",
        "_identity",
        "_module_dependent_profile",
        "_module_names_by_runtime_path",
        "_module_neutral_profile",
        "_reader",
        "_used_wire_paths",
        "_write_enabled",
        "_written_bytes",
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
        # Generation orders saves so the budget can tell rows this run touched
        # from rows left over by an older one; only the latter are evictable.
        self._generation: int = 0
        # Identity for every stored row: 0.48% of the store, measured. The
        # lanes behind these rows stay on disk until somebody asks for one.
        self._identity: dict[str, tuple[int, EntryIdentity]] = {}
        # Paths this run actually read, so the TTL sweep can tell a live entry
        # from one nothing has wanted for weeks.
        self._used_wire_paths: set[str] = set()
        self._written_bytes: int = 0
        # One read connection for the whole materialisation phase. Opening one
        # per entry made a warm run open 1133 of them -- the N+1 shape the
        # observer's db_cost section exists to catch, measured at 33 MB of
        # extra filesystem output per run before it was closed.
        self._reader: CacheBackend | None = None
        # A store whose load was refused must not survive piecewise. See
        # _write_backend_rows.
        self._discard_store: bool = False

    def _detect_legacy_secret_warning(self) -> str | None:
        warnings = [
            warning
            for warning in (
                self._legacy_secret_warning_line(),
                self._legacy_monolith_warning(),
            )
            if warning is not None
        ]
        return "\n".join(warnings) if warnings else None

    def _legacy_secret_warning_line(self) -> str | None:
        secret_path = self._workspace_dir() / LEGACY_CACHE_SECRET_FILENAME
        try:
            if secret_path.exists():
                return (
                    f"Legacy cache secret file detected at {secret_path}; "
                    "delete this obsolete file."
                )
        except OSError as exc:
            return f"Legacy cache secret check failed: {exc}"
        return None

    def _workspace_dir(self) -> Path:
        """Where this cache's non-cache siblings live.

        Both the obsolete secret file and the superseded JSON monolith sit in
        the workspace directory, which stopped being ``self.path.parent`` when
        the store moved into ``db/``.
        """

        return workspace_dir_for_cache_path(self.path)

    def _legacy_monolith_warning(self) -> str | None:
        """Name the JSON monolith the SQLite store replaced, once, if present.

        The old cache was a single 50 MB document; the new one lives in
        ``db/``.  Nothing reads the old file any more, so upgrading silently
        strands it.  Reporting it follows the ``.cache_secret`` precedent
        rather than deleting it: the file is the user's, and a cache this tool
        no longer owns is not this tool's to remove.
        """

        workspace = self._workspace_dir()
        if workspace == self.path.parent:
            # A caller-chosen cache path, not the managed layout: there is no
            # monolith of ours to have superseded.
            return None
        return self._legacy_file_warning(
            workspace / LEGACY_CACHE_MONOLITH_FILENAME,
            label="Superseded JSON cache",
        )

    @staticmethod
    def _legacy_file_warning(path: Path, *, label: str) -> str | None:
        try:
            if path.exists():
                return f"{label} detected at {path}; delete this obsolete file."
        except OSError as exc:
            return f"{label} check failed: {exc}"
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
        required_clone_channels: tuple[CloneArtifactChannel, ...] = (),
    ) -> CacheReuseDecision:
        return cache_reuse_decision(
            content=content,
            entry=entry,
            neutral_profile=self._module_neutral_profile,
            dependent_profile=self._module_dependent_profile,
            binding_context=self._binding_context_for(runtime_path),
            required_clone_channels=required_clone_channels,
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
        self._identity = {}
        self._used_wire_paths = set()
        self._discard_store = True
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

        # No whole-store size gate lives here any more, and reinstating one
        # would restore the pinned defect.  The old cap existed solely because
        # the loader had to hold the entire document in memory before it could
        # read one entry; rows are read by key, so what a load holds is bounded
        # by the row, not by the store.  ``max_size_bytes`` is now enforced
        # where it can be honoured without costing the next run its warm path:
        # on the write side, in ``save()``.  See
        # ``test_cache_saved_over_cap_must_still_warm_next_run``.
        try:
            with span(name="cache.backend.load_generation") as load_span:
                if size is not None:
                    load_span.set_counter("cache_file_bytes", size)
                backend = CacheBackend(self.path, read_only=True)
                try:
                    parsed = self._load_from_backend(backend)
                    load_span.set_counter(
                        "cache_backend_entries", backend.entry_count()
                    )
                    # Bytes this load actually read, not bytes the store holds:
                    # the lanes were left on disk, and a counter that claimed
                    # them would report work nobody did.
                    load_span.set_counter(
                        "cache_backend_read_bytes",
                        sum(
                            len(identity.wire_path)
                            for _fid, identity in self._identity.values()
                        ),
                    )
                    _record_db_cost(load_span, backend)
                finally:
                    backend.close()
            if parsed is None:
                return
            self.data = parsed
            self._canonical_runtime_paths = set(self._identity)
            self._discard_store = False
            self.load_status = CacheStatus.OK
            self._set_load_warning(None)
            self._dirty = False
        except CacheBackendForeign:
            self._reject_invalid_cache_format()
        except CacheBackendUnreadable as exc:
            self._ignore_cache(
                f"Cache unreadable; ignoring cache: {exc}",
                status=CacheStatus.UNREADABLE,
            )
        except CacheBackendUnusable as exc:
            self._ignore_cache(
                f"Cache corrupted; ignoring cache: {exc}",
                status=CacheStatus.CORRUPT,
            )
        except OSError as exc:
            self._ignore_cache(
                f"Cache unreadable; ignoring cache: {exc}",
                status=CacheStatus.UNREADABLE,
            )

    def _load_from_backend(self, backend: CacheBackend) -> CacheData | None:
        with span(name="cache.validate_envelope"):
            meta = backend.read_meta()
            version = meta.get(META_KEY_VERSION)
            if version is None:
                return self._reject_invalid_cache_format()
            if version != self._CACHE_VERSION:
                return self._reject_version_mismatch(version)

            # A store written by an older physical schema is a generation
            # mismatch, not damage. Letting it fall through would meet a
            # missing table and be reported as corruption, which invites a
            # user to go looking for a fault that is not there.
            schema = meta.get(META_KEY_SCHEMA)
            if schema != CACHE_BACKEND_SCHEMA_VERSION:
                return self._reject_cache_load(
                    "Cache schema mismatch "
                    f"(found {schema or 'none'}, expected "
                    f"{CACHE_BACKEND_SCHEMA_VERSION}); ignoring cache.",
                    status=CacheStatus.VERSION_MISMATCH,
                    schema_version=version,
                )

            checksum = meta.get(META_KEY_CHECKSUM)
            py_tag = meta.get(META_KEY_PYTHON_TAG)
            fp_version = meta.get(META_KEY_FINGERPRINT)
            if checksum is None or py_tag is None or fp_version is None:
                return self._reject_invalid_cache_format(schema_version=version)

            # The version mark sits inside the checksummed scope for the same
            # reason it did in the JSON envelope: a generation retagged in
            # place by a migration or an edit passes the equality gate above
            # and must still be refused here.
            if not verify_envelope(
                version=version,
                python_tag=py_tag,
                fingerprint_version=fp_version,
                checksum=checksum,
            ):
                return self._reject_cache_load(
                    "Cache checksum mismatch; ignoring cache.",
                    status=CacheStatus.INTEGRITY_FAILED,
                    schema_version=version,
                )

            runtime_tag = current_python_tag()
            if py_tag != runtime_tag:
                return self._reject_cache_load(
                    "Cache python tag mismatch "
                    f"(found {py_tag}, expected {runtime_tag}); ignoring cache.",
                    status=CacheStatus.PYTHON_TAG_MISMATCH,
                    schema_version=version,
                )

            if fp_version != self.fingerprint_version:
                return self._reject_cache_load(
                    "Cache fingerprint version mismatch "
                    f"(found {fp_version}, expected {self.fingerprint_version}); "
                    "ignoring cache.",
                    status=CacheStatus.FINGERPRINT_MISMATCH,
                    schema_version=version,
                )
            self._generation = _as_generation(meta.get(META_KEY_GENERATION))

        parsed_files = new_tracked_files()
        # A load reads identity and stops. Decoding every lane here is what
        # the previous shape did, and it is why a run paid 52 MB to answer
        # questions worth 247 KB. ``decoded_entries`` stays at zero on purpose:
        # nothing has been decoded yet, and a counter that said otherwise would
        # be reporting work that has not happened.
        identities: dict[str, tuple[int, EntryIdentity]] = {}
        with span(name="cache.decode_entries") as decode_span:
            for file_id, identity in backend.iter_identities(version):
                runtime_path = runtime_filepath_from_wire(
                    identity.wire_path, root=self.root
                )
                identities[runtime_path] = (file_id, identity)
            decode_span.set_counter("cache_entries", len(identities))
            decode_span.set_counter("decoded_entries", 0)
        self._identity = identities
        self._used_wire_paths = set()
        with span(name="cache.segment_projection"):
            self.segment_report_projection = decode_segment_report_projection(
                backend.read_singleton(SINGLETON_SEGMENT_REPORT, version),
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
        self._close_reader()
        tracked = tracked_files(self.data)
        generation = self._generation + 1
        try:
            with (
                span(name="cache.backend.write_generation") as write_span,
                CacheBackend(self.path) as backend,
            ):
                written, removed = self._write_backend_rows(
                    backend,
                    moved=None if tracked is None else set(tracked.dirty),
                    dropped=None if tracked is None else set(tracked.deleted),
                    generation=generation,
                )
                write_span.set_counter("cache_backend_changed_entries", written)
                write_span.set_counter("cache_backend_removed_entries", removed)
                write_span.set_counter("cache_backend_write_bytes", self._written_bytes)
                _record_db_cost(write_span, backend)
                with span(name="cache.backend.activate_generation") as activate_span:
                    backend.write_meta(
                        version=self._CACHE_VERSION,
                        python_tag=current_python_tag(),
                        fingerprint_version=self.fingerprint_version,
                        generation=generation,
                    )
                    activate_span.set_counter(
                        "cache_backend_entries", backend.entry_count()
                    )
            self._enforce_budget(generation=generation)
            self._generation = generation
            self._dirty = False
            if tracked is not None:
                tracked.mark_persisted()

            self.data["version"] = self._CACHE_VERSION
            self.data["python_tag"] = current_python_tag()
            self.data["fingerprint_version"] = self.fingerprint_version
        except CacheBackendUnusable as exc:
            raise CacheError(f"Failed to save cache: {exc}") from exc
        except OSError as exc:
            raise CacheError(f"Failed to save cache: {exc}") from exc

    def _write_backend_rows(
        self,
        backend: CacheBackend,
        *,
        moved: set[str] | None,
        dropped: set[str] | None,
        generation: int,
    ) -> tuple[int, int]:
        """Persist only what this run moved.

        The monolith re-serialised every entry on every save, so a one-file
        edit rewrote the whole repository's cache.  ``moved`` and ``dropped``
        name the keys that actually changed.  They arrive as plain sets on
        purpose: which keys moved is all this needs to know, and taking the
        tracking map itself would tie the row writer to how the caller happens
        to notice changes.  ``None`` means the caller could not tell, so
        everything is written -- the old cost, never a wrong answer.
        """

        if self._discard_store:
            # The rows on disk belong to a generation this run refused --
            # a foreign version mark, a failed checksum, a different
            # interpreter. Writing only what changed would leave them in
            # place, and the next load would serve entries this one rejected.
            # The monolith replaced the whole document for the same reason;
            # a row store has to say so explicitly.
            removed_stale = backend.clear_entries()
            dirty_runtime_paths: list[str] = list(self.data["files"])
            deleted_runtime_paths: list[str] = []
        elif moved is None or dropped is None:
            removed_stale = 0
            dirty_runtime_paths = list(self.data["files"])
            deleted_runtime_paths = []
        else:
            removed_stale = 0
            dirty_runtime_paths = sorted(moved & set(self.data["files"]))
            deleted_runtime_paths = sorted(dropped)

        rows: list[tuple[EntryIdentity, bytes, bytes]] = []
        for runtime_path in dirty_runtime_paths:
            entry = self.get_file_entry(runtime_path)
            if entry is None:
                continue
            wire_path = wire_filepath_from_runtime(runtime_path, root=self.root)
            identity, neutral, dependent = split_wire_entry(
                wire_path, self._encode_entry(entry)
            )
            rows.append((identity, neutral, dependent))
        written = backend.upsert_entries(
            rows,
            version=self._CACHE_VERSION,
            generation=generation,
            now_epoch=_now_epoch(),
        )
        self._written_bytes = sum(len(n) + len(d) for _i, n, d in rows)

        doomed = [
            wire_filepath_from_runtime(runtime_path, root=self.root)
            for runtime_path in deleted_runtime_paths
        ]
        removed = backend.delete_entries(doomed) + removed_stale
        # Entries this run read but did not change keep their payload and get
        # a fresh recency mark, so a hot file that never changes cannot age
        # out of the TTL sweep behind a cold one that was rewritten once.
        backend.touch(
            sorted(self._used_wire_paths - {i.wire_path for i, _n, _d in rows}),
            now_epoch=_now_epoch(),
        )

        segment_projection = encode_segment_report_projection(
            self.segment_report_projection,
            root=self.root,
        )
        if segment_projection is None:
            backend.delete_singleton(SINGLETON_SEGMENT_REPORT)
        else:
            backend.write_singleton(
                SINGLETON_SEGMENT_REPORT,
                segment_projection,
                version=self._CACHE_VERSION,
            )
        return written, removed

    def _enforce_budget(self, *, generation: int) -> None:
        """Hold the cache to ``max_size_bytes`` through the one collector.

        This used to be its own eviction loop here, which made the cache the
        only store in the process with a private cleanup nobody else could
        see. The bound is now a policy handed to the cache's GC job, so one
        collector answers for eviction, TTL and orphans alike, under the same
        report shape and the same telemetry as every other job.

        A budget too small to hold even the current run is reported, not
        obeyed into uselessness: the job never takes rows this generation
        wrote, so there is nothing it could evict to satisfy it.
        """

        if self.max_size_bytes <= 0:
            return
        report = collect_cache_garbage(
            path=self.path,
            version=self._CACHE_VERSION,
            generation=generation,
            now_epoch=_now_epoch(),
            max_bytes=self.max_size_bytes,
        )
        if report.refusal is not None:
            raise CacheError(f"Failed to save cache: {report.refusal}")
        collected = sum(count for _reason, count in report.collected)
        if collected:
            self._canonical_runtime_paths.clear()
            self._canonical_runtime_paths.update(self.data["files"])
            for runtime_path in tuple(self._identity):
                if runtime_path not in self.data["files"]:
                    self._identity.pop(runtime_path, None)
        with CacheBackend(self.path) as backend:
            remaining = backend.payload_bytes()
        if remaining > self.max_size_bytes:
            self._set_load_warning(
                f"Cache content is {remaining} bytes, over the configured "
                f"{self.max_size_bytes}-byte budget, and nothing evictable "
                "remains; the cache stays usable and the next run stays warm."
            )

    def release_loaded_entries(self, *, allow_dirty: bool = False) -> int:
        if self._dirty and not allow_dirty:
            return 0
        with span(name="cache.release_entries") as release_span:
            released = len(self.data["files"])
            # Releasing drops entries from memory, never from the store: the
            # rows stay on disk and a later save must not read this as a
            # deletion of every one of them.
            self._close_reader()
            self.data["files"] = new_tracked_files()
            # Identity stays. Releasing frees the lanes, which is where the
            # memory is; forgetting which rows exist would turn the next
            # lookup into a miss and the next save into a deletion.
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
        """Return one entry, fetching its lanes only if they are still on disk.

        A load leaves the heavy lanes where they are, so this is where they
        arrive -- once per file, on demand. An entry already in memory is
        handed back untouched, which keeps a lookup from looking like a change.
        """

        runtime_lookup_key = filepath
        entry_obj = self.data["files"].get(runtime_lookup_key)
        if entry_obj is None:
            wire_key = wire_filepath_from_runtime(filepath, root=self.root)
            runtime_lookup_key = runtime_filepath_from_wire(wire_key, root=self.root)
            entry_obj = self.data["files"].get(runtime_lookup_key)
        if entry_obj is not None:
            self._mark_used(runtime_lookup_key)
            return entry_obj
        return self._materialize(runtime_lookup_key)

    def _lane_reader(self) -> CacheBackend | None:
        """The one read connection the materialisation phase shares.

        Opened on first need and held until the run stops reading. A
        connection per entry is not a small waste: it is the N+1 shape, and it
        cost 33 MB of filesystem output per warm run on this repository.
        """

        if self._reader is None:
            try:
                self._reader = CacheBackend(self.path, read_only=True)
            except (CacheBackendUnusable, OSError):
                return None
        return self._reader

    def _close_reader(self) -> None:
        if self._reader is not None:
            self._reader.close()
            self._reader = None

    def _mark_used(self, runtime_path: str) -> None:
        known = self._identity.get(runtime_path)
        if known is not None:
            self._used_wire_paths.add(known[1].wire_path)

    def _materialize(self, runtime_path: str) -> CacheEntryV3 | None:
        """Pull one entry's lanes off disk and decode it.

        A lane that fails to decode makes this one entry a miss, never the
        store: the identity row that named it is dropped so the run re-analyses
        that file and the next save replaces it.
        """

        known = self._identity.get(runtime_path)
        if known is None:
            return None
        file_id, identity = known
        try:
            backend = self._lane_reader()
            if backend is None:
                return None
            with span(name="cache.backend.load_generation") as lane_span:
                neutral = backend.read_lane(TABLE_NEUTRAL, file_id)
                dependent = backend.read_lane(TABLE_DEPENDENT, file_id)
                lane_span.set_counter(
                    "cache_backend_read_bytes",
                    identity.neutral_bytes + identity.dependent_bytes,
                )
                _record_db_cost(lane_span, backend)
        except CacheBackendUnusable:
            self._identity.pop(runtime_path, None)
            return None
        except OSError:
            self._identity.pop(runtime_path, None)
            return None
        if neutral is None or dependent is None:
            self._identity.pop(runtime_path, None)
            return None
        try:
            wire = join_wire_entry(identity, neutral, dependent)
        except WireShapeRefused:
            self._identity.pop(runtime_path, None)
            return None
        entry = self._decode_entry(wire, runtime_path)
        if entry is None:
            self._identity.pop(runtime_path, None)
            return None
        # A materialised entry is what the store already holds, so it enters
        # the map without being marked changed.
        dict.__setitem__(self.data["files"], runtime_path, entry)
        self._used_wire_paths.add(identity.wire_path)
        return entry

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
        materialized_clone_channels: tuple[CloneArtifactChannel, ...] = (),
    ) -> None:
        if not self._write_enabled:
            return
        # T2 witness honesty, producer side: an artifact the witness does not
        # claim would be silently dropped by the encoder — computed work
        # thrown away behind a row that says it never existed. The default
        # (no channels) can only lie in the safe direction for units without
        # artifacts; with artifacts present it must refuse loudly.
        _validate_materialized_clone_channels(
            units=units,
            materialized_clone_channels=materialized_clone_channels,
        )
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
                        cfg_cyclomatic_complexity=unit.cfg_cyclomatic_complexity,
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
                materialized_clone_channels=materialized_clone_channels,
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
        # Every row the store holds, not merely the ones already in memory:
        # after a load the lanes are still on disk, so asking the in-memory map
        # alone would leave an entry for a deleted file behind and call it
        # pruned. Identity is the register of what exists.
        stale_runtime_paths = sorted(
            {*self.data["files"], *self._identity} - keep_runtime_paths
        )
        if not stale_runtime_paths:
            return 0
        for runtime_path in stale_runtime_paths:
            if runtime_path in self.data["files"]:
                # del, not pop: TrackedFiles tracks removal through __delitem__.
                del self.data["files"][runtime_path]
            else:
                _mark_deleted(self.data, runtime_path)
            self._identity.pop(runtime_path, None)
            self._canonical_runtime_paths.discard(runtime_path)
        self._dirty = True
        return len(stale_runtime_paths)


def _validate_materialized_clone_channels(
    *,
    units: Sequence[Unit],
    materialized_clone_channels: tuple[CloneArtifactChannel, ...],
) -> None:
    """Refuse a witness that under-claims what the units actually carry.

    The field-to-channel map is the measured consumer graph (see
    _CLONE_KEY_CLAIMS in _wire_decode): the statement sequence feeds the
    near-miss y8 domain, the digest feeds the renamed-structure tier, and the
    renamed-canonical sequence feeds both — so it is legal under either claim.
    """

    claimed = set(materialized_clone_channels)
    if "near_miss" not in claimed and any(unit.statement_sequence for unit in units):
        raise ValueError(
            "cache entry carries near-miss statement sequences the "
            "materialization witness does not claim"
        )
    if "renamed_structure" not in claimed and any(
        unit.renamed_fingerprint for unit in units
    ):
        raise ValueError(
            "cache entry carries renamed-structure digests the "
            "materialization witness does not claim"
        )
    if not claimed and any(unit.renamed_statement_sequence for unit in units):
        raise ValueError(
            "cache entry carries renamed-canonical sequences the "
            "materialization witness does not claim"
        )


def file_stat_signature(path: str) -> FileStat:
    stat_result = os.stat(path)
    return FileStat(
        mtime_ns=stat_result.st_mtime_ns,
        size=stat_result.st_size,
    )


__all__ = ["Cache", "file_stat_signature"]
