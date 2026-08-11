# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Typed, fail-safe Git snapshot collection shared by cache and R3 doors."""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Final

from ..models import (
    DigestObject,
    GitBlobIdentity,
    GitContentSnapshot,
    GitDirtyEntry,
    GitIndexEntry,
    GitIndexEntryInput,
    GitObjectFormat,
    GitStatusEntry,
    GitStatusEntryInput,
    GitTrackedContent,
    GitWorkspaceSnapshot,
)
from ..observability import record_counter, span


def _normalize_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.rstrip("/")
    if cleaned == ".":
        return ""
    if ".." in Path(cleaned).parts:
        raise ValueError(f"path traversal is not allowed: {path}")
    return cleaned


# Git subprocesses are the one analysis cost paid outside this process, and
# they were invisible: the two declared hygiene spans had no call site, so a
# slow `git status` on a large worktree looked like slow analysis.
_GIT_SUBPROCESS_SPANS: Final[Mapping[str, str]] = {
    "rev-parse": "hygiene.git.rev_parse",
    "status": "hygiene.git.status",
}


def _git_subprocess_span(args: Sequence[str]) -> AbstractContextManager[object]:
    name = _GIT_SUBPROCESS_SPANS.get(args[0]) if args else None
    return nullcontext() if name is None else span(name=name)


def _run_git_text(root: Path, args: Sequence[str], *, timeout: int) -> str | None:
    with _git_subprocess_span(args):
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        return completed.stdout


def _run_git_bytes(
    root: Path,
    args: Sequence[str],
    *,
    timeout: int,
    input_bytes: bytes | None = None,
) -> bytes | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            input=input_bytes,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    stdout = completed.stdout
    return stdout if isinstance(stdout, bytes) else None


def git_repository_available(root: Path) -> bool:
    output = _run_git_text(
        root,
        ["rev-parse", "--is-inside-work-tree"],
        timeout=10,
    )
    return output is not None and output.strip().lower() == "true"


def _status_entries(output: str) -> tuple[GitStatusEntry, ...] | None:
    entries: dict[str, GitStatusEntry] = {}
    try:
        for line in output.splitlines():
            if len(line) < 3:
                continue
            status_xy = line[:2]
            raw_path = line[3:].strip()
            if not raw_path:
                continue
            raw_paths = raw_path.split(" -> ", 1) if " -> " in raw_path else (raw_path,)
            for item in raw_paths:
                path = _normalize_path(item)
                parsed = GitStatusEntryInput.model_validate(
                    {"status_xy": status_xy, "path": path},
                )
                entries[path] = GitStatusEntry(
                    status_xy=parsed.status_xy,
                    path=parsed.path,
                )
    except ValueError:
        return None
    return tuple(entries[path] for path in sorted(entries))


def git_diff_bytes(root: Path, args: Sequence[str]) -> bytes | None:
    record_counter("git_diff_invocations")
    return _run_git_bytes(root, args, timeout=30)


def _untracked_file_digest(root: Path, path: str) -> tuple[str | None, str]:
    record_counter("untracked_file_reads")
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None, "unavailable"
    if not target.is_file():
        return None, "unavailable"
    digest = hashlib.sha256()
    digest.update(b"untracked\0")
    digest.update(path.encode("utf-8", "surrogateescape"))
    digest.update(b"\0")
    try:
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None, "unavailable"
    return digest.hexdigest(), "ok"


def dirty_entry_digest(
    root: Path,
    path: str,
    status_xy: str,
) -> tuple[str | None, str]:
    """Preserve the existing byte-exact workspace dirty digest contract."""

    if status_xy == "??":
        return _untracked_file_digest(root, path)
    index_status = status_xy[0]
    worktree_status = status_xy[1]
    cached = (
        git_diff_bytes(root, ["diff", "--cached", "--binary", "--", path])
        if index_status != " "
        else b""
    )
    worktree = (
        git_diff_bytes(root, ["diff", "--binary", "--", path])
        if worktree_status != " "
        else b""
    )
    if cached is None or worktree is None:
        return None, "unavailable"
    digest = hashlib.sha256()
    digest.update(status_xy.encode("utf-8", "surrogateescape"))
    digest.update(b"\0")
    digest.update(path.encode("utf-8", "surrogateescape"))
    digest.update(b"\0cached\0")
    digest.update(cached)
    digest.update(b"\0worktree\0")
    digest.update(worktree)
    return digest.hexdigest(), "ok"


def collect_git_workspace_snapshot(
    root: Path,
    *,
    include_digests: bool,
) -> GitWorkspaceSnapshot:
    if not git_repository_available(root):
        return GitWorkspaceSnapshot(git_available=False, entries=())
    output = _run_git_text(root, ["status", "--porcelain=v1"], timeout=30)
    parsed = _status_entries(output) if output is not None else None
    if parsed is None:
        return GitWorkspaceSnapshot(git_available=False, entries=())
    entries: list[GitDirtyEntry] = []
    for item in parsed:
        if include_digests:
            digest, digest_status = dirty_entry_digest(
                root,
                item.path,
                item.status_xy,
            )
        else:
            digest, digest_status = None, "not_requested"
        entries.append(
            GitDirtyEntry(
                path=item.path,
                status_xy=item.status_xy,
                digest=digest,
                digest_status=digest_status,
            )
        )
    return GitWorkspaceSnapshot(git_available=True, entries=tuple(entries))


def _object_format(root: Path) -> GitObjectFormat | None:
    output = _run_git_text(root, ["rev-parse", "--show-object-format"], timeout=10)
    value = output.strip() if output is not None else ""
    if value == "sha1":
        return "sha1"
    if value == "sha256":
        return "sha256"
    return None


def _index_mtime_ns(root: Path) -> int | None:
    output = _run_git_text(root, ["rev-parse", "--git-path", "index"], timeout=10)
    if output is None:
        return None
    raw_path = Path(output.strip())
    index_path = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        return os.stat(index_path).st_mtime_ns
    except OSError:
        return None


def _parse_index_batch(output: bytes) -> tuple[GitIndexEntry, ...] | None:
    entries: list[GitIndexEntry] = []
    cursor = 0
    try:
        while cursor < len(output):
            nul = output.find(b"\0", cursor)
            if nul < 0:
                return None
            header = output[cursor:nul].decode("utf-8", "surrogateescape")
            cursor = nul + 1
            debug_lines: list[str] = []
            for _line_number in range(5):
                newline = output.find(b"\n", cursor)
                if newline < 0:
                    return None
                debug_lines.append(
                    output[cursor:newline].decode("utf-8", "surrogateescape").strip()
                )
                cursor = newline + 1
            metadata, path = header.split("\t", 1)
            tag, mode, object_id, stage_text = metadata.split(" ", 3)
            mtime_value = debug_lines[1].removeprefix("mtime: ")
            mtime_seconds, mtime_nanoseconds = mtime_value.split(":", 1)
            size_text, flags_text = debug_lines[4].split("\t", 1)
            parsed = GitIndexEntryInput.model_validate(
                {
                    "tag": tag,
                    "mode": mode,
                    "object_id": object_id,
                    "stage": int(stage_text),
                    "path": _normalize_path(path),
                    "mtime_ns": int(mtime_seconds) * 1_000_000_000
                    + int(mtime_nanoseconds),
                    "size": int(size_text.removeprefix("size: ")),
                    "flags": int(flags_text.removeprefix("flags: ")),
                }
            )
            entries.append(
                GitIndexEntry(
                    tag=parsed.tag,
                    mode=parsed.mode,
                    object_id=parsed.object_id,
                    stage=parsed.stage,
                    path=parsed.path,
                    mtime_ns=parsed.mtime_ns,
                    size=parsed.size,
                    flags=parsed.flags,
                )
            )
    except ValueError:
        return None
    return tuple(sorted(entries, key=lambda item: item.path))


def _blob_content_digests(
    root: Path,
    object_ids: Sequence[str],
) -> dict[str, DigestObject] | None:
    unique_ids = tuple(sorted(set(object_ids)))
    if not unique_ids:
        return {}
    output = _run_git_bytes(
        root,
        ["cat-file", "--batch"],
        timeout=30,
        input_bytes=("\n".join(unique_ids) + "\n").encode("ascii"),
    )
    if output is None:
        return None
    cursor = 0
    digests: dict[str, DigestObject] = {}
    try:
        for expected_id in unique_ids:
            newline = output.find(b"\n", cursor)
            if newline < 0:
                return None
            header = output[cursor:newline].decode("ascii")
            cursor = newline + 1
            object_id, object_type, size_text = header.split(" ", 2)
            size = int(size_text)
            if object_id != expected_id or object_type != "blob" or size < 0:
                return None
            end = cursor + size
            if end >= len(output) or output[end : end + 1] != b"\n":
                return None
            content = output[cursor:end]
            cursor = end + 1
            digests[object_id] = DigestObject(
                domain="codeclone.source-content.v1",
                algorithm="sha256",
                value=hashlib.sha256(content).hexdigest(),
            )
    except (UnicodeDecodeError, ValueError):
        return None
    return digests if cursor == len(output) else None


def _worktree_blob_ids(
    root: Path,
    paths: Sequence[str],
) -> dict[str, str] | None:
    ordered_paths = tuple(sorted(set(paths)))
    if not ordered_paths:
        return {}
    output = _run_git_bytes(
        root,
        ["hash-object", "--stdin-paths"],
        timeout=30,
        input_bytes=("\n".join(ordered_paths) + "\n").encode(
            "utf-8",
            "surrogateescape",
        ),
    )
    if output is None:
        return None
    try:
        object_ids = tuple(line.decode("ascii") for line in output.splitlines() if line)
    except UnicodeDecodeError:
        return None
    if len(object_ids) != len(ordered_paths):
        return None
    return dict(zip(ordered_paths, object_ids, strict=True))


def _unavailable_content_snapshot(root: Path) -> GitContentSnapshot:
    return GitContentSnapshot(
        root=str(root.resolve()),
        git_available=False,
        object_format=None,
        tracked=(),
        dirty_paths=frozenset(),
        untracked_paths=frozenset(),
        index_ambiguous_paths=frozenset(),
        racy_paths=frozenset(),
    )


def _normalized_repository_paths(
    root: Path,
    paths: Sequence[str],
) -> tuple[str, ...]:
    normalized: set[str] = set()
    for raw_path in paths:
        candidate = Path(raw_path)
        try:
            relative = (
                candidate.resolve().relative_to(root.resolve()).as_posix()
                if candidate.is_absolute()
                else _normalize_path(raw_path)
            )
        except (OSError, ValueError):
            continue
        normalized.add(relative)
    return tuple(sorted(normalized))


def _partition_index_entries(
    *,
    index_entries: Sequence[GitIndexEntry],
    status_entries: Sequence[GitStatusEntry],
    index_mtime_ns: int,
) -> tuple[set[str], frozenset[str], set[str], set[str], list[GitIndexEntry]]:
    status_by_path = {entry.path: entry.status_xy for entry in status_entries}
    dirty_paths = {
        path for path, status_xy in status_by_path.items() if status_xy != "??"
    }
    untracked_paths = frozenset(
        path for path, status_xy in status_by_path.items() if status_xy == "??"
    )
    index_ambiguous: set[str] = set()
    racy: set[str] = set()
    clean_candidates: list[GitIndexEntry] = []
    for entry in index_entries:
        special_index = entry.stage != 0 or entry.tag != "H" or entry.flags != 0
        if special_index:
            index_ambiguous.add(entry.path)
        elif entry.path in dirty_paths or entry.path in untracked_paths:
            continue
        elif entry.mtime_ns >= index_mtime_ns:
            racy.add(entry.path)
        else:
            clean_candidates.append(entry)
    return dirty_paths, untracked_paths, index_ambiguous, racy, clean_candidates


def _verify_worktree_blob_ids(
    *,
    clean_candidates: Sequence[GitIndexEntry],
    worktree_blob_ids: dict[str, str],
    dirty_paths: set[str],
) -> list[GitIndexEntry]:
    verified: list[GitIndexEntry] = []
    for entry in clean_candidates:
        if worktree_blob_ids.get(entry.path) != entry.object_id:
            dirty_paths.add(entry.path)
        else:
            verified.append(entry)
    return verified


def _tracked_content_from_verified_entries(
    *,
    verified_candidates: Sequence[GitIndexEntry],
    blob_digests: dict[str, DigestObject],
    object_format: GitObjectFormat,
    index_ambiguous: set[str],
) -> list[GitTrackedContent]:
    tracked: list[GitTrackedContent] = []
    for entry in verified_candidates:
        digest = blob_digests.get(entry.object_id)
        if digest is None:
            index_ambiguous.add(entry.path)
            continue
        try:
            blob = GitBlobIdentity(
                object_format=object_format,
                object_id=entry.object_id,
            )
        except ValueError:
            index_ambiguous.add(entry.path)
            continue
        tracked.append(
            GitTrackedContent(
                path=entry.path,
                blob=blob,
                source_content_digest=digest,
            )
        )
    return tracked


def collect_git_content_snapshot(
    root: Path,
    paths: Sequence[str],
) -> GitContentSnapshot:
    """Collect one repository-wide cache identity proof without per-file Git."""

    if not git_repository_available(root):
        return _unavailable_content_snapshot(root)
    object_format = _object_format(root)
    index_mtime_ns = _index_mtime_ns(root)
    status_output = _run_git_text(root, ["status", "--porcelain=v1"], timeout=30)
    status_entries = (
        _status_entries(status_output) if status_output is not None else None
    )
    normalized_paths = _normalized_repository_paths(root, paths)
    if object_format is None or index_mtime_ns is None or status_entries is None:
        return _unavailable_content_snapshot(root)
    index_output = _run_git_bytes(
        root,
        ["ls-files", "--stage", "--debug", "-v", "-z", "--", *normalized_paths],
        timeout=30,
    )
    index_entries = (
        _parse_index_batch(index_output) if index_output is not None else None
    )
    if index_entries is None:
        return _unavailable_content_snapshot(root)

    (
        dirty_paths,
        untracked_paths,
        index_ambiguous,
        racy,
        clean_candidates,
    ) = _partition_index_entries(
        index_entries=index_entries,
        status_entries=status_entries,
        index_mtime_ns=index_mtime_ns,
    )

    worktree_blob_ids = _worktree_blob_ids(
        root,
        [entry.path for entry in clean_candidates],
    )
    if worktree_blob_ids is None:
        return _unavailable_content_snapshot(root)
    verified_candidates = _verify_worktree_blob_ids(
        clean_candidates=clean_candidates,
        worktree_blob_ids=worktree_blob_ids,
        dirty_paths=dirty_paths,
    )

    blob_digests = _blob_content_digests(
        root,
        [entry.object_id for entry in verified_candidates],
    )
    if blob_digests is None:
        return _unavailable_content_snapshot(root)
    tracked = _tracked_content_from_verified_entries(
        verified_candidates=verified_candidates,
        blob_digests=blob_digests,
        object_format=object_format,
        index_ambiguous=index_ambiguous,
    )
    return GitContentSnapshot(
        root=str(root.resolve()),
        git_available=True,
        object_format=object_format,
        tracked=tuple(sorted(tracked, key=lambda item: item.path)),
        dirty_paths=frozenset(dirty_paths),
        untracked_paths=untracked_paths,
        index_ambiguous_paths=frozenset(index_ambiguous),
        racy_paths=frozenset(racy),
    )


__all__ = [
    "collect_git_content_snapshot",
    "collect_git_workspace_snapshot",
    "dirty_entry_digest",
    "git_diff_bytes",
    "git_repository_available",
]
