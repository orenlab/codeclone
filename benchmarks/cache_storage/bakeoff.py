"""Reproducible Phase 39K K0 cache-storage bake-off.

This module is benchmark-only. Production code must never import it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import resource
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Final, Literal, Protocol, TypedDict

import orjson

from codeclone.baseline.trust import current_python_tag
from codeclone.cache.integrity import (
    as_str_dict,
    read_json_document,
    sign_cache_payload,
    verify_cache_payload_signature,
)
from codeclone.contracts import BASELINE_FINGERPRINT_VERSION, CACHE_VERSION

BackendName = Literal["bucketed_chunks", "path_shards", "sqlite_wal"]
MeasuredName = Literal[
    "monolith_reference",
    "bucketed_chunks",
    "path_shards",
    "sqlite_wal",
]
CorpusName = Literal["small", "current_repository", "synthetic_10000"]
ScenarioName = Literal[
    "cold_write",
    "unchanged_warm",
    "one_file_edit",
    "one_percent_edit",
    "prune_ten_percent",
    "corrupt_entry",
    "crash_before_activation",
    "crash_after_activation",
    "concurrent_reader_writer",
    "dead_owner_pid_reuse",
    "shared_target_worktrees",
]
RecoveryStatus = Literal["pass", "fail", "not_applicable"]

BACKEND_NAMES: Final[tuple[BackendName, ...]] = (
    "bucketed_chunks",
    "path_shards",
    "sqlite_wal",
)
CORPUS_NAMES: Final[tuple[CorpusName, ...]] = (
    "small",
    "current_repository",
    "synthetic_10000",
)
SCENARIO_NAMES: Final[tuple[ScenarioName, ...]] = (
    "cold_write",
    "unchanged_warm",
    "one_file_edit",
    "one_percent_edit",
    "prune_ten_percent",
    "corrupt_entry",
    "crash_before_activation",
    "crash_after_activation",
    "concurrent_reader_writer",
    "dead_owner_pid_reuse",
    "shared_target_worktrees",
)
_SCENARIO_BY_NAME: Final[dict[str, ScenarioName]] = {
    name: name for name in SCENARIO_NAMES
}
REFERENCE_SCENARIOS: Final[tuple[ScenarioName, ...]] = (
    "cold_write",
    "unchanged_warm",
    "one_file_edit",
    "one_percent_edit",
    "prune_ten_percent",
)
CACHE_BACKEND_BUCKETS: Final = 256
_MANIFEST_LIMIT_BYTES: Final = 4 * 1024 * 1024
_CHUNK_SLACK_BYTES: Final = 64
_LOCK_GRACE_SECONDS: Final = 0.0
_RESULT_SCHEMA: Final = "phase39k-k0-results/1"
_BACKEND_VERSION: Final = "benchmark-v1"

WireEntry = dict[str, object]
WireCorpus = dict[str, WireEntry]


class OperationMetrics(TypedDict):
    logical_syscalls: int
    read_bytes: int
    write_bytes: int
    files: int
    entries_touched: int
    buckets_touched: int


class LoadResult(TypedDict):
    entries: WireCorpus
    generation_id: str
    recovery_result: str


class ScenarioResult(TypedDict):
    recovery_status: RecoveryStatus
    recovery_result: str
    final_digest: str


class RawSample(TypedDict):
    measured: MeasuredName
    corpus: CorpusName
    scenario: ScenarioName
    sample_index: int
    elapsed_ns: int
    peak_rss_bytes: int
    logical_syscalls: int
    read_bytes: int
    write_bytes: int
    files: int
    entries_touched: int
    buckets_touched: int
    recovery_status: RecoveryStatus
    recovery_result: str
    final_digest: str


class Aggregate(TypedDict):
    measured: MeasuredName
    corpus: CorpusName
    scenario: ScenarioName
    samples: int
    median_ns: int
    p95_ns: int
    peak_rss_bytes: int
    median_read_bytes: int
    median_write_bytes: int
    median_logical_syscalls: int
    median_files: int
    median_entries_touched: int
    median_buckets_touched: int
    recovery_statuses: list[str]
    recovery_results: list[str]


class StorageBackend(Protocol):
    @property
    def metrics(self) -> OperationMetrics: ...

    def reset_metrics(self) -> None: ...

    def initialize(self, entries: Mapping[str, WireEntry]) -> str: ...

    def load_all(self) -> LoadResult: ...

    def apply(
        self,
        changes: Mapping[str, WireEntry],
        removed: set[str],
        *,
        expected_generation: str | None = None,
        crash_stage: Literal["before_activation", "after_activation"] | None = None,
    ) -> str: ...

    def corrupt_one(self) -> str: ...

    def recover_dead_owner(self, *, pid_reuse: bool) -> str: ...


class GenerationConflict(RuntimeError):
    """Raised when a benchmark adapter observes a stale generation."""


class CorruptStorage(RuntimeError):
    """Raised when benchmark storage violates its candidate contract."""


class IoCounter:
    __slots__ = (
        "buckets_touched",
        "entries_touched",
        "logical_syscalls",
        "read_bytes",
        "write_bytes",
    )

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.logical_syscalls = 0
        self.read_bytes = 0
        self.write_bytes = 0
        self.entries_touched = 0
        self.buckets_touched = 0

    def snapshot(self, root: Path) -> OperationMetrics:
        return OperationMetrics(
            logical_syscalls=self.logical_syscalls,
            read_bytes=self.read_bytes,
            write_bytes=self.write_bytes,
            files=_regular_file_count(root),
            entries_touched=self.entries_touched,
            buckets_touched=self.buckets_touched,
        )


def _canonical_bytes(value: object) -> bytes:
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object_dict(value: object, *, label: str) -> dict[str, object]:
    result = as_str_dict(value)
    if result is None:
        raise CorruptStorage(f"{label} must be a string-keyed object")
    return result


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise CorruptStorage(f"{label} must be a string")
    return value


def _integer(value: object, *, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CorruptStorage(f"{label} must be an integer")
    return value


def _regular_file_count(root: Path) -> int:
    count = 0
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_names[:] = sorted(directory_names)
        for file_name in sorted(file_names):
            path = Path(directory) / file_name
            if path.is_file() and not path.is_symlink():
                count += 1
    return count


def _fsync_directory(path: Path, counter: IoCounter) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    counter.logical_syscalls += 1
    try:
        os.fsync(descriptor)
        counter.logical_syscalls += 1
    finally:
        os.close(descriptor)
        counter.logical_syscalls += 1


def _atomic_replace(path: Path, raw: bytes, counter: IoCounter) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    counter.logical_syscalls += 1
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            counter.logical_syscalls += 1
            counter.write_bytes += written
            view = view[written:]
        os.fsync(descriptor)
        counter.logical_syscalls += 1
    finally:
        os.close(descriptor)
        counter.logical_syscalls += 1
    os.replace(temporary, path)
    counter.logical_syscalls += 1
    _fsync_directory(path.parent, counter)


def _write_immutable(path: Path, raw: bytes, counter: IoCounter) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = _read_bounded(path, max_bytes=len(raw), counter=counter)
        if existing != raw:
            raise CorruptStorage(f"immutable collision: {path.name}")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    counter.logical_syscalls += 1
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            counter.logical_syscalls += 1
            counter.write_bytes += written
            view = view[written:]
        os.fsync(descriptor)
        counter.logical_syscalls += 1
    finally:
        os.close(descriptor)
        counter.logical_syscalls += 1
    os.replace(temporary, path)
    counter.logical_syscalls += 1
    _fsync_directory(path.parent, counter)


def _read_bounded(path: Path, *, max_bytes: int, counter: IoCounter) -> bytes:
    stat = path.stat()
    counter.logical_syscalls += 1
    if not path.is_file() or path.is_symlink() or stat.st_size > max_bytes:
        raise CorruptStorage(f"unsafe or oversized file: {path.name}")
    raw = path.read_bytes()
    counter.logical_syscalls += 2
    counter.read_bytes += len(raw)
    if len(raw) != stat.st_size:
        raise CorruptStorage(f"short read: {path.name}")
    return raw


def _wire_corpus_digest(entries: Mapping[str, WireEntry]) -> str:
    rows = [[path, entries[path]] for path in sorted(entries)]
    return _sha256(_canonical_bytes(rows))


def _clone_entry(entry: WireEntry, *, delta: int) -> WireEntry:
    changed = dict(entry)
    stat_value = changed.get("st")
    if (
        not isinstance(stat_value, list)
        or len(stat_value) != 2
        or not isinstance(stat_value[0], int)
        or not isinstance(stat_value[1], int)
    ):
        raise CorruptStorage("cache-v3 wire entry has invalid stat row")
    changed["st"] = [stat_value[0] + delta, stat_value[1]]
    return changed


def _selected_paths(entries: Mapping[str, WireEntry], count: int) -> tuple[str, ...]:
    return tuple(sorted(entries)[: max(1, min(count, len(entries)))])


def _changed_entries(
    entries: Mapping[str, WireEntry],
    *,
    count: int,
) -> WireCorpus:
    return {
        path: _clone_entry(entries[path], delta=index + 1)
        for index, path in enumerate(_selected_paths(entries, count))
    }


def _load_source_cache(path: Path) -> WireCorpus:
    raw = path.read_bytes()
    document = _object_dict(
        read_json_document(path, max_bytes=len(raw) + 1),
        label="cache document",
    )
    version = _string(document.get("v"), label="cache version")
    if version != CACHE_VERSION:
        raise CorruptStorage(
            f"source cache version {version!r} is not current {CACHE_VERSION!r}"
        )
    payload = _object_dict(document.get("payload"), label="cache payload")
    signature = _string(document.get("sig"), label="cache signature")
    if not verify_cache_payload_signature(payload, signature):
        raise CorruptStorage("source cache signature mismatch")
    files = _object_dict(payload.get("files"), label="cache files")
    result: WireCorpus = {}
    for path_key in sorted(files):
        result[path_key] = _object_dict(
            files[path_key],
            label=f"cache entry {path_key}",
        )
    if not result:
        raise CorruptStorage("source cache contains no entries")
    return result


def _corpus(
    source: Mapping[str, WireEntry],
    name: CorpusName,
) -> WireCorpus:
    if name == "small":
        return {path: dict(source[path]) for path in sorted(source)[:64]}
    if name == "current_repository":
        return {path: dict(source[path]) for path in sorted(source)}
    smallest_path = min(
        source,
        key=lambda path: (len(_canonical_bytes(source[path])), path),
    )
    template = source[smallest_path]
    return {
        f"synthetic/pkg_{index // 100:04d}/module_{index:05d}.py": dict(template)
        for index in range(10_000)
    }


def _manifest_generation(
    backend: str,
    rows: Mapping[str, object],
    previous: str | None,
) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "backend_version": _BACKEND_VERSION,
                "backend": backend,
                "previous": previous,
                "rows": rows,
            }
        )
    )


def _process_start_identity(pid: int) -> str | None:
    if pid <= 0:
        return None
    completed = subprocess.run(
        ("ps", "-o", "lstart=", "-p", str(pid)),
        check=False,
        capture_output=True,
        text=True,
    )
    value = completed.stdout.strip()
    return value or None


class PublishLock:
    __slots__ = ("counter", "guard_path", "lock_path", "token")

    def __init__(self, root: Path, counter: IoCounter) -> None:
        self.lock_path = root / "publish.lock"
        self.guard_path = root / "publish.lock.recovery"
        self.counter = counter
        self.token = _sha256(f"{os.getpid()}:{time.time_ns()}:{root}".encode())

    def acquire(self) -> None:
        payload = {
            "token": self.token,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "process_start_identity": _process_start_identity(os.getpid()),
            "created_at_ns": time.time_ns(),
        }
        raw = _canonical_bytes(payload)
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            self.counter.logical_syscalls += 1
        except FileExistsError as exc:
            raise GenerationConflict("publish lock is active") from exc
        try:
            os.write(descriptor, raw)
            self.counter.logical_syscalls += 1
            self.counter.write_bytes += len(raw)
            os.fsync(descriptor)
            self.counter.logical_syscalls += 1
        finally:
            os.close(descriptor)
            self.counter.logical_syscalls += 1
        _fsync_directory(self.lock_path.parent, self.counter)

    def release(self) -> None:
        if not self.lock_path.exists():
            return
        payload = _object_dict(
            orjson.loads(
                _read_bounded(
                    self.lock_path,
                    max_bytes=4096,
                    counter=self.counter,
                )
            ),
            label="lock payload",
        )
        if payload.get("token") != self.token:
            raise GenerationConflict("lock ownership changed")
        self.lock_path.unlink()
        self.counter.logical_syscalls += 1
        _fsync_directory(self.lock_path.parent, self.counter)

    def __enter__(self) -> PublishLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> None:
        self.release()

    def seed_stale(self, *, pid_reuse: bool) -> None:
        stale_pid = os.getpid() if pid_reuse else 999_999
        payload = {
            "token": "stale-token",
            "pid": stale_pid,
            "host": socket.gethostname(),
            "process_start_identity": (
                "definitely-not-this-process" if pid_reuse else "dead"
            ),
            "created_at_ns": 0,
        }
        _atomic_replace(self.lock_path, _canonical_bytes(payload), self.counter)

    def recover(self) -> str:
        descriptor = os.open(
            self.guard_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        self.counter.logical_syscalls += 1
        try:
            os.write(descriptor, self.token.encode("ascii"))
            self.counter.logical_syscalls += 1
            os.fsync(descriptor)
            self.counter.logical_syscalls += 1
        finally:
            os.close(descriptor)
            self.counter.logical_syscalls += 1
        try:
            raw = _read_bounded(
                self.lock_path,
                max_bytes=4096,
                counter=self.counter,
            )
            payload = _object_dict(orjson.loads(raw), label="stale lock")
            token = _string(payload.get("token"), label="stale lock token")
            pid = _integer(payload.get("pid"), label="stale lock pid")
            host = _string(payload.get("host"), label="stale lock host")
            created_at = _integer(
                payload.get("created_at_ns"),
                label="stale lock created_at",
            )
            stored_identity = payload.get("process_start_identity")
            if stored_identity is not None and not isinstance(stored_identity, str):
                raise CorruptStorage("stale lock process identity must be a string")
            if host != socket.gethostname():
                raise GenerationConflict("foreign lock is not recoverable")
            age_seconds = (time.time_ns() - created_at) / 1_000_000_000
            if age_seconds < _LOCK_GRACE_SECONDS:
                raise GenerationConflict("lock grace period is active")
            live_identity = _process_start_identity(pid)
            if live_identity is not None and live_identity == stored_identity:
                raise GenerationConflict("same owner is still active")
            confirm = _object_dict(
                orjson.loads(
                    _read_bounded(
                        self.lock_path,
                        max_bytes=4096,
                        counter=self.counter,
                    )
                ),
                label="stale lock recheck",
            )
            if confirm.get("token") != token:
                raise GenerationConflict("lock token changed during recovery")
            self.lock_path.unlink()
            self.counter.logical_syscalls += 1
            _fsync_directory(self.lock_path.parent, self.counter)
            return (
                "pid_reuse_recovered" if pid == os.getpid() else "dead_owner_recovered"
            )
        finally:
            self.guard_path.unlink(missing_ok=True)
            self.counter.logical_syscalls += 1


class FileBackendBase:
    __slots__ = ("_counter", "root")

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._counter = IoCounter()

    @property
    def metrics(self) -> OperationMetrics:
        return self._counter.snapshot(self.root)

    def reset_metrics(self) -> None:
        self._counter.reset()

    def recover_dead_owner(self, *, pid_reuse: bool) -> str:
        lock = PublishLock(self.root, self._counter)
        lock.seed_stale(pid_reuse=pid_reuse)
        return lock.recover()


class BucketedChunksBackend(FileBackendBase):
    __slots__ = ("chunks", "manifest")

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.chunks = root / "chunks"
        self.chunks.mkdir(parents=True, exist_ok=True)
        self.manifest = root / "manifest.json"

    @staticmethod
    def _bucket(path: str) -> str:
        return hashlib.sha256(path.encode("utf-8")).digest()[0:1].hex()

    def _read_manifest(self) -> dict[str, object]:
        if not self.manifest.exists():
            return {
                "backend_version": _BACKEND_VERSION,
                "generation_id": "",
                "buckets": {},
            }
        raw = _read_bounded(
            self.manifest,
            max_bytes=_MANIFEST_LIMIT_BYTES,
            counter=self._counter,
        )
        return _object_dict(orjson.loads(raw), label="bucket manifest")

    def _bucket_rows(self, manifest: Mapping[str, object]) -> dict[str, object]:
        return _object_dict(manifest.get("buckets"), label="bucket map")

    def _read_bucket(self, descriptor: object) -> WireCorpus:
        row = _object_dict(descriptor, label="bucket descriptor")
        digest = _string(row.get("digest"), label="chunk digest")
        byte_count = _integer(row.get("bytes"), label="chunk bytes")
        path = self.chunks / f"{digest}.chunk"
        raw = _read_bounded(
            path,
            max_bytes=byte_count + _CHUNK_SLACK_BYTES,
            counter=self._counter,
        )
        if len(raw) != byte_count or _sha256(raw) != digest:
            raise CorruptStorage("chunk content-address mismatch")
        document = _object_dict(orjson.loads(raw), label="chunk document")
        rows = document.get("entries")
        if not isinstance(rows, list):
            raise CorruptStorage("chunk entries must be a list")
        result: WireCorpus = {}
        for raw_row in rows:
            if (
                not isinstance(raw_row, list)
                or len(raw_row) != 2
                or not isinstance(raw_row[0], str)
            ):
                raise CorruptStorage("chunk entry row is malformed")
            result[raw_row[0]] = _object_dict(
                raw_row[1],
                label="chunk cache entry",
            )
        return result

    def _write_bucket(self, entries: Mapping[str, WireEntry]) -> dict[str, object]:
        raw = _canonical_bytes(
            {"entries": [[path, entries[path]] for path in sorted(entries)]}
        )
        digest = _sha256(raw)
        _write_immutable(self.chunks / f"{digest}.chunk", raw, self._counter)
        self._counter.entries_touched += len(entries)
        self._counter.buckets_touched += 1
        return {"digest": digest, "bytes": len(raw)}

    def initialize(self, entries: Mapping[str, WireEntry]) -> str:
        buckets: dict[str, WireCorpus] = {}
        for path in sorted(entries):
            buckets.setdefault(self._bucket(path), {})[path] = dict(entries[path])
        descriptors: dict[str, object] = {}
        for bucket in sorted(buckets):
            descriptors[bucket] = self._write_bucket(buckets[bucket])
        generation = _manifest_generation("bucketed_chunks", descriptors, None)
        _atomic_replace(
            self.manifest,
            _canonical_bytes(
                {
                    "backend_version": _BACKEND_VERSION,
                    "generation_id": generation,
                    "buckets": descriptors,
                }
            ),
            self._counter,
        )
        return generation

    def load_all(self) -> LoadResult:
        manifest = self._read_manifest()
        generation = _string(
            manifest.get("generation_id"),
            label="bucket generation",
        )
        result: WireCorpus = {}
        misses = 0
        for bucket, descriptor in sorted(self._bucket_rows(manifest).items()):
            try:
                rows = self._read_bucket(descriptor)
            except (CorruptStorage, OSError, orjson.JSONDecodeError):
                misses += 1
                continue
            if any(self._bucket(path) != bucket for path in rows):
                misses += 1
                continue
            result.update(rows)
        return LoadResult(
            entries=result,
            generation_id=generation,
            recovery_result=f"bucket_miss:{misses}" if misses else "clean",
        )

    def apply(
        self,
        changes: Mapping[str, WireEntry],
        removed: set[str],
        *,
        expected_generation: str | None = None,
        crash_stage: Literal["before_activation", "after_activation"] | None = None,
    ) -> str:
        with PublishLock(self.root, self._counter):
            manifest = self._read_manifest()
            current_generation = _string(
                manifest.get("generation_id"),
                label="bucket generation",
            )
            if (
                expected_generation is not None
                and expected_generation != current_generation
            ):
                raise GenerationConflict("bucket generation changed")
            descriptors = self._bucket_rows(manifest)
            dirty_buckets = {
                self._bucket(path) for path in tuple(changes) + tuple(removed)
            }
            for bucket in sorted(dirty_buckets):
                descriptor = descriptors.get(bucket)
                rows = self._read_bucket(descriptor) if descriptor is not None else {}
                for path in sorted(removed):
                    if self._bucket(path) == bucket:
                        rows.pop(path, None)
                for path in sorted(changes):
                    if self._bucket(path) == bucket:
                        rows[path] = dict(changes[path])
                if rows:
                    descriptors[bucket] = self._write_bucket(rows)
                else:
                    descriptors.pop(bucket, None)
            generation = _manifest_generation(
                "bucketed_chunks",
                descriptors,
                current_generation,
            )
            new_manifest = {
                "backend_version": _BACKEND_VERSION,
                "generation_id": generation,
                "buckets": descriptors,
            }
            if crash_stage == "before_activation":
                return generation
            _atomic_replace(
                self.manifest,
                _canonical_bytes(new_manifest),
                self._counter,
            )
            if crash_stage == "after_activation":
                return generation
            return generation

    def corrupt_one(self) -> str:
        manifest = self._read_manifest()
        descriptors = self._bucket_rows(manifest)
        bucket = sorted(descriptors)[0]
        row = _object_dict(descriptors[bucket], label="bucket descriptor")
        digest = _string(row.get("digest"), label="chunk digest")
        path = self.chunks / f"{digest}.chunk"
        path.write_bytes(b"corrupt")
        self._counter.logical_syscalls += 2
        self._counter.write_bytes += 7
        return bucket


class PathShardsBackend(FileBackendBase):
    __slots__ = ("entries_dir", "manifest")

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.entries_dir = root / "entries"
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = root / "manifest.json"

    def _entry_path(self, path: str, digest: str) -> Path:
        path_digest = _sha256(path.encode("utf-8"))
        return self.entries_dir / path_digest[:2] / f"{path_digest}-{digest}.entry"

    def _read_manifest(self) -> dict[str, object]:
        if not self.manifest.exists():
            return {
                "backend_version": _BACKEND_VERSION,
                "generation_id": "",
                "entries": {},
            }
        return _object_dict(
            orjson.loads(
                _read_bounded(
                    self.manifest,
                    max_bytes=_MANIFEST_LIMIT_BYTES,
                    counter=self._counter,
                )
            ),
            label="shard manifest",
        )

    def _entry_rows(self, manifest: Mapping[str, object]) -> dict[str, object]:
        return _object_dict(manifest.get("entries"), label="shard entry map")

    def _write_entry(self, path: str, entry: WireEntry) -> dict[str, object]:
        raw = _canonical_bytes(entry)
        digest = _sha256(raw)
        _write_immutable(self._entry_path(path, digest), raw, self._counter)
        self._counter.entries_touched += 1
        return {"digest": digest, "bytes": len(raw)}

    def _read_entry(self, path: str, descriptor: object) -> WireEntry:
        row = _object_dict(descriptor, label="shard descriptor")
        digest = _string(row.get("digest"), label="shard digest")
        byte_count = _integer(row.get("bytes"), label="shard bytes")
        raw = _read_bounded(
            self._entry_path(path, digest),
            max_bytes=byte_count + _CHUNK_SLACK_BYTES,
            counter=self._counter,
        )
        if len(raw) != byte_count or _sha256(raw) != digest:
            raise CorruptStorage("shard content-address mismatch")
        return _object_dict(orjson.loads(raw), label="shard cache entry")

    def initialize(self, entries: Mapping[str, WireEntry]) -> str:
        descriptors = {
            path: self._write_entry(path, entries[path]) for path in sorted(entries)
        }
        generation = _manifest_generation("path_shards", descriptors, None)
        _atomic_replace(
            self.manifest,
            _canonical_bytes(
                {
                    "backend_version": _BACKEND_VERSION,
                    "generation_id": generation,
                    "entries": descriptors,
                }
            ),
            self._counter,
        )
        return generation

    def load_all(self) -> LoadResult:
        manifest = self._read_manifest()
        generation = _string(
            manifest.get("generation_id"),
            label="shard generation",
        )
        result: WireCorpus = {}
        misses = 0
        for path, descriptor in sorted(self._entry_rows(manifest).items()):
            entry = self._read_entry_or_none(path, descriptor)
            if entry is None:
                misses += 1
            else:
                result[path] = entry
        return LoadResult(
            entries=result,
            generation_id=generation,
            recovery_result=f"entry_miss:{misses}" if misses else "clean",
        )

    def _read_entry_or_none(
        self,
        path: str,
        descriptor: object,
    ) -> WireEntry | None:
        try:
            return self._read_entry(path, descriptor)
        except (CorruptStorage, OSError, orjson.JSONDecodeError):
            return None

    def apply(
        self,
        changes: Mapping[str, WireEntry],
        removed: set[str],
        *,
        expected_generation: str | None = None,
        crash_stage: Literal["before_activation", "after_activation"] | None = None,
    ) -> str:
        with PublishLock(self.root, self._counter):
            manifest = self._read_manifest()
            current_generation = _string(
                manifest.get("generation_id"),
                label="shard generation",
            )
            if (
                expected_generation is not None
                and expected_generation != current_generation
            ):
                raise GenerationConflict("shard generation changed")
            descriptors = self._entry_rows(manifest)
            for path in sorted(removed):
                descriptors.pop(path, None)
            for path in sorted(changes):
                descriptors[path] = self._write_entry(path, changes[path])
            generation = _manifest_generation(
                "path_shards",
                descriptors,
                current_generation,
            )
            new_manifest = {
                "backend_version": _BACKEND_VERSION,
                "generation_id": generation,
                "entries": descriptors,
            }
            if crash_stage == "before_activation":
                return generation
            _atomic_replace(
                self.manifest,
                _canonical_bytes(new_manifest),
                self._counter,
            )
            if crash_stage == "after_activation":
                return generation
            return generation

    def corrupt_one(self) -> str:
        manifest = self._read_manifest()
        descriptors = self._entry_rows(manifest)
        path_key = sorted(descriptors)[0]
        row = _object_dict(descriptors[path_key], label="shard descriptor")
        digest = _string(row.get("digest"), label="shard digest")
        path = self._entry_path(path_key, digest)
        path.write_bytes(b"corrupt")
        self._counter.logical_syscalls += 2
        self._counter.write_bytes += 7
        return path_key


class SQLiteWalBackend:
    __slots__ = ("_counter", "database", "root")

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = root / "cache.sqlite3"
        self._counter = IoCounter()
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS entries "
                "(path TEXT PRIMARY KEY, wire BLOB NOT NULL, digest TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        self._counter.logical_syscalls += 1
        connection = sqlite3.connect(self.database, timeout=30.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    @property
    def metrics(self) -> OperationMetrics:
        return self._counter.snapshot(self.root)

    def reset_metrics(self) -> None:
        self._counter.reset()

    def _generation(self, connection: sqlite3.Connection) -> str:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'generation_id'"
        ).fetchone()
        self._counter.logical_syscalls += 1
        if row is None:
            return ""
        value = row[0]
        if not isinstance(value, str):
            raise CorruptStorage("sqlite generation is not text")
        return value

    def initialize(self, entries: Mapping[str, WireEntry]) -> str:
        rows: dict[str, object] = {}
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for path in sorted(entries):
                raw = _canonical_bytes(entries[path])
                digest = _sha256(raw)
                connection.execute(
                    "INSERT OR REPLACE INTO entries"
                    "(path, wire, digest) VALUES (?, ?, ?)",
                    (path, raw, digest),
                )
                self._counter.logical_syscalls += 1
                self._counter.write_bytes += len(raw)
                self._counter.entries_touched += 1
                rows[path] = digest
            generation = _manifest_generation("sqlite_wal", rows, None)
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('generation_id', ?)",
                (generation,),
            )
            self._counter.logical_syscalls += 1
        return generation

    def load_all(self) -> LoadResult:
        result: WireCorpus = {}
        misses = 0
        with self._connect() as connection:
            generation = self._generation(connection)
            rows = connection.execute(
                "SELECT path, wire, digest FROM entries ORDER BY path"
            )
            self._counter.logical_syscalls += 1
            for path, raw, digest in rows:
                self._counter.logical_syscalls += 1
                if (
                    not isinstance(path, str)
                    or not isinstance(raw, bytes)
                    or not isinstance(digest, str)
                ):
                    misses += 1
                    continue
                self._counter.read_bytes += len(raw)
                try:
                    if _sha256(raw) != digest:
                        raise CorruptStorage("sqlite row digest mismatch")
                    result[path] = _object_dict(
                        orjson.loads(raw),
                        label="sqlite cache entry",
                    )
                except (CorruptStorage, orjson.JSONDecodeError):
                    misses += 1
        return LoadResult(
            entries=result,
            generation_id=generation,
            recovery_result=f"entry_miss:{misses}" if misses else "clean",
        )

    def apply(
        self,
        changes: Mapping[str, WireEntry],
        removed: set[str],
        *,
        expected_generation: str | None = None,
        crash_stage: Literal["before_activation", "after_activation"] | None = None,
    ) -> str:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            current_generation = self._generation(connection)
            if (
                expected_generation is not None
                and expected_generation != current_generation
            ):
                raise GenerationConflict("sqlite generation changed")
            for path in sorted(removed):
                connection.execute("DELETE FROM entries WHERE path = ?", (path,))
                self._counter.logical_syscalls += 1
                self._counter.entries_touched += 1
            change_digests: dict[str, object] = {}
            for path in sorted(changes):
                raw = _canonical_bytes(changes[path])
                digest = _sha256(raw)
                connection.execute(
                    "INSERT OR REPLACE INTO entries"
                    "(path, wire, digest) VALUES (?, ?, ?)",
                    (path, raw, digest),
                )
                self._counter.logical_syscalls += 1
                self._counter.write_bytes += len(raw)
                self._counter.entries_touched += 1
                change_digests[path] = digest
            generation = _manifest_generation(
                "sqlite_wal",
                {
                    "changes": change_digests,
                    "removed": sorted(removed),
                },
                current_generation,
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('generation_id', ?)",
                (generation,),
            )
            self._counter.logical_syscalls += 1
            if crash_stage == "before_activation":
                connection.rollback()
                return generation
            connection.commit()
            if crash_stage == "after_activation":
                return generation
            return generation
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def corrupt_one(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path FROM entries ORDER BY path LIMIT 1"
            ).fetchone()
            self._counter.logical_syscalls += 1
            if row is None or not isinstance(row[0], str):
                raise CorruptStorage("sqlite has no corruptible entry")
            path = row[0]
            connection.execute(
                "UPDATE entries SET wire = ? WHERE path = ?",
                (b"corrupt", path),
            )
            self._counter.logical_syscalls += 1
            self._counter.write_bytes += 7
            return path

    def recover_dead_owner(self, *, pid_reuse: bool) -> str:
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        connection.close()
        with self._connect() as recovered:
            recovered.execute("BEGIN IMMEDIATE")
            recovered.rollback()
        return (
            "sqlite_os_lock_release_pid_reuse_independent"
            if pid_reuse
            else "sqlite_os_lock_release_dead_owner"
        )


class MonolithReference:
    __slots__ = ("_counter", "document", "root")

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.document = root / "cache.json"
        self._counter = IoCounter()

    @property
    def metrics(self) -> OperationMetrics:
        return self._counter.snapshot(self.root)

    def reset_metrics(self) -> None:
        self._counter.reset()

    def _bytes(self, entries: Mapping[str, WireEntry], generation: str) -> bytes:
        payload: dict[str, object] = {
            "py": current_python_tag(),
            "fp": BASELINE_FINGERPRINT_VERSION,
            "generation_id": generation,
            "files": {path: entries[path] for path in sorted(entries)},
        }
        return _canonical_bytes(
            {
                "v": CACHE_VERSION,
                "payload": payload,
                "sig": sign_cache_payload(payload),
            }
        )

    def initialize(self, entries: Mapping[str, WireEntry]) -> str:
        generation = _wire_corpus_digest(entries)
        raw = self._bytes(entries, generation)
        self._counter.entries_touched += len(entries)
        _atomic_replace(self.document, raw, self._counter)
        return generation

    def load_all(self) -> LoadResult:
        raw = _read_bounded(
            self.document,
            max_bytes=self.document.stat().st_size + 1,
            counter=self._counter,
        )
        document = _object_dict(orjson.loads(raw), label="monolith")
        if _string(document.get("v"), label="monolith version") != CACHE_VERSION:
            raise CorruptStorage("monolith version mismatch")
        payload = _object_dict(document.get("payload"), label="monolith payload")
        signature = _string(document.get("sig"), label="monolith signature")
        if not verify_cache_payload_signature(payload, signature):
            raise CorruptStorage("monolith signature mismatch")
        if (
            _string(payload.get("py"), label="monolith python tag")
            != current_python_tag()
        ):
            raise CorruptStorage("monolith python tag mismatch")
        if (
            _string(payload.get("fp"), label="monolith fingerprint version")
            != BASELINE_FINGERPRINT_VERSION
        ):
            raise CorruptStorage("monolith fingerprint version mismatch")
        files = _object_dict(payload.get("files"), label="monolith files")
        result = {
            path: _object_dict(files[path], label="monolith entry")
            for path in sorted(files)
        }
        return LoadResult(
            entries=result,
            generation_id=_string(
                payload.get("generation_id"),
                label="monolith generation",
            ),
            recovery_result="clean",
        )

    def apply(
        self,
        changes: Mapping[str, WireEntry],
        removed: set[str],
        *,
        expected_generation: str | None = None,
        crash_stage: Literal["before_activation", "after_activation"] | None = None,
    ) -> str:
        loaded = self.load_all()
        if (
            expected_generation is not None
            and loaded["generation_id"] != expected_generation
        ):
            raise GenerationConflict("monolith generation changed")
        entries = loaded["entries"]
        for path in removed:
            entries.pop(path, None)
        for path, entry in changes.items():
            entries[path] = dict(entry)
        generation = _wire_corpus_digest(entries)
        self._counter.entries_touched += len(entries)
        _atomic_replace(self.document, self._bytes(entries, generation), self._counter)
        return generation

    def corrupt_one(self) -> str:
        raise CorruptStorage("not applicable to monolith reference")

    def recover_dead_owner(self, *, pid_reuse: bool) -> str:
        raise CorruptStorage("not applicable to monolith reference")


BackendFactory = Callable[[Path], StorageBackend]


def _factory(name: MeasuredName) -> BackendFactory:
    if name == "bucketed_chunks":
        return BucketedChunksBackend
    if name == "path_shards":
        return PathShardsBackend
    if name == "sqlite_wal":
        return SQLiteWalBackend
    return MonolithReference


def _assert_snapshot(
    loaded: LoadResult,
    expected_digests: set[str],
) -> str:
    digest = _wire_corpus_digest(loaded["entries"])
    if digest not in expected_digests:
        raise CorruptStorage(
            f"reader observed mixed generation {digest}; "
            f"expected {sorted(expected_digests)}"
        )
    return digest


def _concurrent_reader_writer(
    backend: StorageBackend,
    entries: WireCorpus,
) -> ScenarioResult:
    old_digest = _wire_corpus_digest(entries)
    changes = _changed_entries(entries, count=1)
    expected_new = dict(entries)
    expected_new.update(changes)
    new_digest = _wire_corpus_digest(expected_new)
    generation = backend.load_all()["generation_id"]
    observed: list[str] = []
    failures: list[str] = []
    start = threading.Event()

    def read_once() -> None:
        try:
            loaded = backend.load_all()
            observed.append(_assert_snapshot(loaded, {old_digest, new_digest}))
        except (CorruptStorage, OSError, sqlite3.Error) as exc:
            failures.append(str(exc))

    def reader() -> None:
        start.wait()
        for _ in range(20):
            read_once()

    thread = threading.Thread(target=reader)
    thread.start()
    start.set()
    backend.apply(changes, set(), expected_generation=generation)
    thread.join()
    final = backend.load_all()
    final_digest = _assert_snapshot(final, {new_digest})
    if failures or not observed:
        return ScenarioResult(
            recovery_status="fail",
            recovery_result=f"reader_failures:{failures!r}",
            final_digest=final_digest,
        )
    return ScenarioResult(
        recovery_status="pass",
        recovery_result="readers_observed_old_or_new_only",
        final_digest=final_digest,
    )


def _shared_target_worktrees(
    factory: BackendFactory,
    target: Path,
    entries: WireCorpus,
) -> tuple[ScenarioResult, OperationMetrics, int]:
    checkout_alpha = target.parent / "checkout-alpha"
    checkout_omega = target.parent / "checkout-omega"
    checkout_alpha.mkdir()
    checkout_omega.mkdir()
    first = factory(target)
    generation = first.initialize(entries)
    second = factory(target)
    first.reset_metrics()
    second.reset_metrics()
    changes_a = _changed_entries(entries, count=1)
    changes_b = {
        path: _clone_entry(entries[path], delta=1000)
        for path in _selected_paths(entries, 1)
    }
    started = time.perf_counter_ns()
    first.apply(changes_a, set(), expected_generation=generation)
    conflict = False
    try:
        second.apply(changes_b, set(), expected_generation=generation)
    except (GenerationConflict, sqlite3.OperationalError):
        conflict = True
    refreshed = second.load_all()["generation_id"]
    second.apply(changes_b, set(), expected_generation=refreshed)
    final = second.load_all()
    expected = dict(entries)
    expected.update(changes_b)
    final_digest = _assert_snapshot(final, {_wire_corpus_digest(expected)})
    elapsed_ns = time.perf_counter_ns() - started
    first_metrics = first.metrics
    second_metrics = second.metrics
    metrics = OperationMetrics(
        logical_syscalls=(
            first_metrics["logical_syscalls"] + second_metrics["logical_syscalls"]
        ),
        read_bytes=first_metrics["read_bytes"] + second_metrics["read_bytes"],
        write_bytes=first_metrics["write_bytes"] + second_metrics["write_bytes"],
        files=max(first_metrics["files"], second_metrics["files"]),
        entries_touched=(
            first_metrics["entries_touched"] + second_metrics["entries_touched"]
        ),
        buckets_touched=(
            first_metrics["buckets_touched"] + second_metrics["buckets_touched"]
        ),
    )
    return (
        ScenarioResult(
            recovery_status="pass" if conflict else "fail",
            recovery_result=(
                "stale_writer_conflicted_then_retried"
                if conflict
                else "stale_writer_was_not_rejected"
            ),
            final_digest=final_digest,
        ),
        metrics,
        elapsed_ns,
    )


def _read_expected_generation(
    backend: StorageBackend,
    entries: Mapping[str, WireEntry],
    *,
    recovery_result: str,
    started: int,
) -> tuple[ScenarioResult, OperationMetrics, int]:
    loaded = backend.load_all()
    digest = _assert_snapshot(loaded, {_wire_corpus_digest(entries)})
    elapsed_ns = time.perf_counter_ns() - started
    return (
        ScenarioResult(
            recovery_status="pass",
            recovery_result=recovery_result,
            final_digest=digest,
        ),
        backend.metrics,
        elapsed_ns,
    )


def _apply_changed_generation(
    backend: StorageBackend,
    entries: Mapping[str, WireEntry],
    *,
    generation: str,
    count: int,
    recovery_result: str,
    started: int,
    crash_stage: Literal["before_activation", "after_activation"] | None = None,
) -> tuple[ScenarioResult, OperationMetrics, int]:
    changes = _changed_entries(entries, count=count)
    backend.apply(
        changes,
        set(),
        expected_generation=generation,
        crash_stage=crash_stage,
    )
    expected = dict(entries)
    expected.update(changes)
    return _read_expected_generation(
        backend,
        expected,
        recovery_result=recovery_result,
        started=started,
    )


def _execute_scenario(
    measured: MeasuredName,
    scenario: ScenarioName,
    entries: WireCorpus,
    root: Path,
) -> tuple[ScenarioResult, OperationMetrics, int]:
    factory = _factory(measured)
    if scenario == "shared_target_worktrees":
        return _shared_target_worktrees(factory, root / "shared-cache", entries)

    if scenario == "cold_write":
        started = time.perf_counter_ns()
        backend = factory(root / "cache")
        backend.initialize(entries)
        return _read_expected_generation(
            backend,
            entries,
            recovery_result="cold_generation_readable",
            started=started,
        )

    backend = factory(root / "cache")
    generation = backend.initialize(entries)
    backend.reset_metrics()
    started = time.perf_counter_ns()
    if scenario == "unchanged_warm":
        return _read_expected_generation(
            backend,
            entries,
            recovery_result="warm_generation_readable",
            started=started,
        )

    if scenario == "one_file_edit":
        return _apply_changed_generation(
            backend,
            entries,
            generation=generation,
            count=1,
            recovery_result="one_entry_changed",
            started=started,
        )

    if scenario == "one_percent_edit":
        count = max(1, len(entries) // 100)
        return _apply_changed_generation(
            backend,
            entries,
            generation=generation,
            count=count,
            recovery_result=f"changed:{count}",
            started=started,
        )

    if scenario == "prune_ten_percent":
        removed = set(_selected_paths(entries, max(1, len(entries) // 10)))
        backend.apply({}, removed, expected_generation=generation)
        expected = {
            path: entry for path, entry in entries.items() if path not in removed
        }
        return _read_expected_generation(
            backend,
            expected,
            recovery_result=f"pruned:{len(removed)}",
            started=started,
        )

    if measured == "monolith_reference":
        raise CorruptStorage(f"scenario {scenario} is not a monolith reference case")

    if scenario == "corrupt_entry":
        backend.corrupt_one()
        loaded = backend.load_all()
        status = (
            "pass"
            if loaded["recovery_result"] in {"bucket_miss:1", "entry_miss:1"}
            and len(loaded["entries"]) < len(entries)
            else "fail"
        )
        elapsed_ns = time.perf_counter_ns() - started
        return (
            ScenarioResult(
                recovery_status=status,
                recovery_result=loaded["recovery_result"],
                final_digest=_wire_corpus_digest(loaded["entries"]),
            ),
            backend.metrics,
            elapsed_ns,
        )

    if scenario == "crash_before_activation":
        changes = _changed_entries(entries, count=1)
        backend.apply(
            changes,
            set(),
            expected_generation=generation,
            crash_stage="before_activation",
        )
        return _read_expected_generation(
            backend,
            entries,
            recovery_result="old_generation_survived",
            started=started,
        )

    if scenario == "crash_after_activation":
        return _apply_changed_generation(
            backend,
            entries,
            generation=generation,
            count=1,
            recovery_result="new_generation_survived",
            started=started,
            crash_stage="after_activation",
        )

    if scenario == "concurrent_reader_writer":
        result = _concurrent_reader_writer(backend, entries)
        elapsed_ns = time.perf_counter_ns() - started
        return result, backend.metrics, elapsed_ns

    dead = backend.recover_dead_owner(pid_reuse=False)
    reused = backend.recover_dead_owner(pid_reuse=True)
    elapsed_ns = time.perf_counter_ns() - started
    return (
        ScenarioResult(
            recovery_status="pass",
            recovery_result=f"{dead},{reused}",
            final_digest=_wire_corpus_digest(backend.load_all()["entries"]),
        ),
        backend.metrics,
        elapsed_ns,
    )


def _rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    value = usage.ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _worker(
    *,
    source_cache: Path,
    measured: MeasuredName,
    corpus_name: CorpusName,
    scenario: ScenarioName,
    sample_index: int,
    workspace: Path,
) -> RawSample:
    source = _load_source_cache(source_cache)
    entries = _corpus(source, corpus_name)
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    result, metrics, elapsed = _execute_scenario(
        measured,
        scenario,
        entries,
        workspace,
    )
    return RawSample(
        measured=measured,
        corpus=corpus_name,
        scenario=scenario,
        sample_index=sample_index,
        elapsed_ns=elapsed,
        peak_rss_bytes=_rss_bytes(),
        logical_syscalls=metrics["logical_syscalls"],
        read_bytes=metrics["read_bytes"],
        write_bytes=metrics["write_bytes"],
        files=metrics["files"],
        entries_touched=metrics["entries_touched"],
        buckets_touched=metrics["buckets_touched"],
        recovery_status=result["recovery_status"],
        recovery_result=result["recovery_result"],
        final_digest=result["final_digest"],
    )


def _raw_sample(value: object) -> RawSample:
    row = _object_dict(value, label="worker sample")
    measured = _measured(_optional_string(row.get("measured")))
    corpus = _corpus_name(_optional_string(row.get("corpus")))
    scenario = _scenario_name(_optional_string(row.get("scenario")))
    recovery_status = _recovery_status(row.get("recovery_status"))
    integer_fields = (
        "sample_index",
        "elapsed_ns",
        "peak_rss_bytes",
        "logical_syscalls",
        "read_bytes",
        "write_bytes",
        "files",
        "entries_touched",
        "buckets_touched",
    )
    integers = {
        key: _integer(row.get(key), label=f"sample {key}") for key in integer_fields
    }
    return RawSample(
        measured=measured,
        corpus=corpus,
        scenario=scenario,
        sample_index=integers["sample_index"],
        elapsed_ns=integers["elapsed_ns"],
        peak_rss_bytes=integers["peak_rss_bytes"],
        logical_syscalls=integers["logical_syscalls"],
        read_bytes=integers["read_bytes"],
        write_bytes=integers["write_bytes"],
        files=integers["files"],
        entries_touched=integers["entries_touched"],
        buckets_touched=integers["buckets_touched"],
        recovery_status=recovery_status,
        recovery_result=_string(
            row.get("recovery_result"),
            label="sample recovery_result",
        ),
        final_digest=_string(row.get("final_digest"), label="sample digest"),
    )


def _nearest_rank_p95(values: Sequence[int]) -> int:
    ordered = sorted(values)
    index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return ordered[index]


def _aggregate(samples: Sequence[RawSample]) -> list[Aggregate]:
    groups: dict[tuple[MeasuredName, CorpusName, ScenarioName], list[RawSample]] = {}
    for sample in samples:
        key = (sample["measured"], sample["corpus"], sample["scenario"])
        groups.setdefault(key, []).append(sample)
    result: list[Aggregate] = []
    for (measured, corpus, scenario), rows in sorted(groups.items()):
        elapsed = [row["elapsed_ns"] for row in rows]
        result.append(
            Aggregate(
                measured=measured,
                corpus=corpus,
                scenario=scenario,
                samples=len(rows),
                median_ns=int(statistics.median(elapsed)),
                p95_ns=_nearest_rank_p95(elapsed),
                peak_rss_bytes=max(row["peak_rss_bytes"] for row in rows),
                median_read_bytes=int(
                    statistics.median(row["read_bytes"] for row in rows)
                ),
                median_write_bytes=int(
                    statistics.median(row["write_bytes"] for row in rows)
                ),
                median_logical_syscalls=int(
                    statistics.median(row["logical_syscalls"] for row in rows)
                ),
                median_files=int(statistics.median(row["files"] for row in rows)),
                median_entries_touched=int(
                    statistics.median(row["entries_touched"] for row in rows)
                ),
                median_buckets_touched=int(
                    statistics.median(row["buckets_touched"] for row in rows)
                ),
                recovery_statuses=sorted({row["recovery_status"] for row in rows}),
                recovery_results=sorted({row["recovery_result"] for row in rows}),
            )
        )
    return result


def _git_head(root: Path) -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _run_worker(
    *,
    source_cache: Path,
    measured: MeasuredName,
    corpus: CorpusName,
    scenario: ScenarioName,
    sample_index: int,
    workspace: Path,
) -> RawSample:
    command = (
        sys.executable,
        "-m",
        "benchmarks.cache_storage.bakeoff",
        "--worker",
        "--source-cache",
        str(source_cache),
        "--measured",
        measured,
        "--corpus",
        corpus,
        "--scenario",
        scenario,
        "--sample-index",
        str(sample_index),
        "--workspace",
        str(workspace),
    )
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = "0"
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return _raw_sample(orjson.loads(completed.stdout))


def _guardrails(aggregates: Sequence[Aggregate]) -> dict[str, object]:
    index = {
        (row["measured"], row["corpus"], row["scenario"]): row for row in aggregates
    }
    verdicts: dict[str, object] = {}
    for backend in BACKEND_NAMES:
        backend_rows: dict[str, object] = {}
        for corpus in CORPUS_NAMES:
            reference = index[("monolith_reference", corpus, "unchanged_warm")]
            candidate = index[(backend, corpus, "unchanged_warm")]
            median_limit = reference["median_ns"] * 1.05
            p95_limit = reference["p95_ns"] * 1.10
            rss_limit = reference["peak_rss_bytes"] + max(
                int(reference["peak_rss_bytes"] * 0.10),
                32 * 1024 * 1024,
            )
            one_edit = index[(backend, corpus, "one_file_edit")]
            cold = index[(backend, corpus, "cold_write")]
            recovery_rows = [
                index[(backend, corpus, scenario)]
                for scenario in SCENARIO_NAMES
                if scenario
                in {
                    "corrupt_entry",
                    "crash_before_activation",
                    "crash_after_activation",
                    "concurrent_reader_writer",
                    "dead_owner_pid_reuse",
                    "shared_target_worktrees",
                }
            ]
            checks = {
                "warm_median_within_5_percent": (
                    candidate["median_ns"] <= median_limit
                ),
                "warm_p95_within_10_percent": candidate["p95_ns"] <= p95_limit,
                "peak_rss_within_limit": (candidate["peak_rss_bytes"] <= rss_limit),
                "one_edit_writes_less_than_cold": (
                    one_edit["median_write_bytes"] < cold["median_write_bytes"]
                ),
                "recovery_matrix_passed": all(
                    row["recovery_statuses"] == ["pass"] for row in recovery_rows
                ),
            }
            if backend == "bucketed_chunks":
                checks["one_edit_touches_one_bucket"] = (
                    one_edit["median_buckets_touched"] == 1
                )
            else:
                checks["one_edit_reports_one_changed_entry"] = (
                    one_edit["median_entries_touched"] == 1
                )
            backend_rows[corpus] = {
                "checks": checks,
                "passed": all(checks.values()),
                "reference": {
                    "median_ns": reference["median_ns"],
                    "p95_ns": reference["p95_ns"],
                    "peak_rss_bytes": reference["peak_rss_bytes"],
                },
            }
        verdicts[backend] = backend_rows
    return verdicts


def run_bakeoff(
    *,
    repository_root: Path,
    source_cache: Path,
    output: Path,
    repeats: int,
) -> None:
    if repeats < 3:
        raise ValueError("K0 requires at least three raw samples")
    source_raw = source_cache.read_bytes()
    source = _load_source_cache(source_cache)
    samples: list[RawSample] = []
    with tempfile.TemporaryDirectory(prefix="codeclone-p39k-k0-") as temporary:
        temp_root = Path(temporary)
        for corpus in CORPUS_NAMES:
            for scenario in REFERENCE_SCENARIOS:
                samples.extend(
                    _run_worker(
                        source_cache=source_cache,
                        measured="monolith_reference",
                        corpus=corpus,
                        scenario=scenario,
                        sample_index=sample_index,
                        workspace=temp_root
                        / f"monolith-{corpus}-{scenario}-{sample_index}",
                    )
                    for sample_index in range(repeats)
                )
            for backend in BACKEND_NAMES:
                for scenario in SCENARIO_NAMES:
                    samples.extend(
                        _run_worker(
                            source_cache=source_cache,
                            measured=backend,
                            corpus=corpus,
                            scenario=scenario,
                            sample_index=sample_index,
                            workspace=temp_root
                            / f"{backend}-{corpus}-{scenario}-{sample_index}",
                        )
                        for sample_index in range(repeats)
                    )
    aggregates = _aggregate(samples)
    document = {
        "schema_version": _RESULT_SCHEMA,
        "checkpoint": "39K-K0",
        "selection_status": "awaiting_maintainer",
        "prespecified_favorite": "bucketed_chunks",
        "candidates": list(BACKEND_NAMES),
        "sqlite_role": "benchmark_control_only",
        "reference": "monolith_reference",
        "repository": {
            "head": _git_head(repository_root),
            "source_cache_sha256": _sha256(source_raw),
            "source_cache_bytes": len(source_raw),
            "source_cache_entries": len(source),
        },
        "machine": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "orjson": orjson.__version__,
            "sqlite": sqlite3.sqlite_version,
            "machine_id_sha256": _sha256(socket.gethostname().encode("utf-8")),
        },
        "methodology": {
            "repeats": repeats,
            "p95": "nearest_rank",
            "timer": "time.perf_counter_ns",
            "peak_rss": "resource.getrusage(RUSAGE_SELF).ru_maxrss per worker",
            "syscalls": "logical adapter filesystem/sqlite operation count",
            "read_write_bytes": "application bytes passed through adapter reads/writes",
            "corpora": {
                "small": 64,
                "current_repository": len(source),
                "synthetic_10000": 10_000,
            },
        },
        "raw_samples": samples,
        "aggregates": aggregates,
        "guardrails": _guardrails(aggregates),
    }
    output.write_bytes(_canonical_bytes(document) + b"\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument(
        "--measured",
        choices=(
            "monolith_reference",
            "bucketed_chunks",
            "path_shards",
            "sqlite_wal",
        ),
    )
    parser.add_argument("--corpus", choices=CORPUS_NAMES)
    parser.add_argument("--scenario", choices=SCENARIO_NAMES)
    parser.add_argument("--sample-index", type=int)
    parser.add_argument("--workspace", type=Path)
    return parser


def _measured(value: str | None) -> MeasuredName:
    if value == "monolith_reference":
        return "monolith_reference"
    if value == "bucketed_chunks":
        return "bucketed_chunks"
    if value == "path_shards":
        return "path_shards"
    if value == "sqlite_wal":
        return "sqlite_wal"
    raise ValueError("--measured is required in worker mode")


def _corpus_name(value: str | None) -> CorpusName:
    if value == "small":
        return "small"
    if value == "current_repository":
        return "current_repository"
    if value == "synthetic_10000":
        return "synthetic_10000"
    raise ValueError("--corpus is required in worker mode")


def _scenario_name(value: str | None) -> ScenarioName:
    if value is None:
        raise ValueError("--scenario is required in worker mode")
    try:
        return _SCENARIO_BY_NAME[value]
    except KeyError as exc:
        raise ValueError("--scenario is required in worker mode") from exc


def _optional_string(value: object) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise CorruptStorage("worker discriminator must be a string")


def _recovery_status(value: object) -> RecoveryStatus:
    if value == "pass":
        return "pass"
    if value == "fail":
        return "fail"
    if value == "not_applicable":
        return "not_applicable"
    raise CorruptStorage("worker returned unknown recovery status")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.worker:
        if args.workspace is None or args.sample_index is None:
            raise ValueError("--workspace and --sample-index are required")
        sample = _worker(
            source_cache=args.source_cache,
            measured=_measured(args.measured),
            corpus_name=_corpus_name(args.corpus),
            scenario=_scenario_name(args.scenario),
            sample_index=args.sample_index,
            workspace=args.workspace,
        )
        sys.stdout.buffer.write(_canonical_bytes(sample) + b"\n")
        return 0
    if args.output is None or args.repository_root is None:
        raise ValueError("--output and --repository-root are required")
    run_bakeoff(
        repository_root=args.repository_root,
        source_cache=args.source_cache,
        output=args.output,
        repeats=args.repeats,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
