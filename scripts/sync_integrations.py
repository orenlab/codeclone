#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

SOURCE_REPOSITORY = "orenlab/codeclone"
MANIFEST_NAME = "SYNC_MANIFEST.json"


class SyncValidationError(Exception):
    """A pre-sync validation error that should exit with code 1."""


class SyncCopyError(Exception):
    """A copy/delete/write failure that should exit with code 2."""


@dataclass(frozen=True, slots=True)
class SyncTarget:
    name: str
    copies: tuple[tuple[str, str], ...]
    generated: tuple[str, ...]
    denylist: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SourceInfo:
    commit_short: str
    commit_full: str
    dirty: bool
    version: str


@dataclass(frozen=True, slots=True)
class SyncManifest:
    source_repository: str
    source_commit: str
    source_commit_full: str
    source_dirty: bool
    codeclone_version: str
    target: str
    synced_at_utc: str
    source_paths: tuple[str, ...]
    files_copied: int
    files_deleted: int


@dataclass(frozen=True, slots=True)
class SyncResult:
    target_name: str
    files_copied: int
    files_deleted: int
    manifest_path: Path
    dry_run: bool


SYNC_TARGETS: dict[str, SyncTarget] = {
    "codex": SyncTarget(
        name="codex",
        copies=(
            ("plugins/codeclone", "plugins/codeclone"),
            (".agents/plugins/marketplace.json", ".agents/plugins/marketplace.json"),
        ),
        generated=(MANIFEST_NAME,),
    ),
    "claude-desktop": SyncTarget(
        name="claude-desktop",
        copies=(("extensions/claude-desktop-codeclone", "."),),
        generated=(MANIFEST_NAME,),
    ),
    "vscode": SyncTarget(
        name="vscode",
        copies=(("extensions/vscode-codeclone", "."),),
        generated=(MANIFEST_NAME,),
        denylist=("node_modules/**", ".coverage"),
    ),
    "cursor": SyncTarget(
        name="cursor",
        copies=(
            ("plugins/cursor-codeclone", "."),
            (
                "plugins/codeclone/scripts/launch_mcp.py",
                "scripts/launch_mcp.py",
            ),
        ),
        generated=(MANIFEST_NAME,),
    ),
}

GLOBAL_DENYLIST: tuple[str, ...] = (
    ".git",
    ".git/**",
    "__pycache__/**",
    "*.pyc",
    ".DS_Store",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".coverage",
    ".coverage.*",
)


def resolve_target_path(target_name: str, base_dir: Path) -> Path:
    return base_dir / f"codeclone-{target_name}"


def validate_source(root: Path, allow_dirty: bool) -> SourceInfo:
    source_root = root.resolve()
    if not (source_root / ".git").exists():
        raise SyncValidationError(f"source {source_root} is not a git repository")

    commit_full = _run_git(source_root, ("rev-parse", "HEAD"))
    commit_short = _run_git(source_root, ("rev-parse", "--short", "HEAD"))
    dirty = bool(_run_git(source_root, ("status", "--porcelain")))
    if dirty and not allow_dirty:
        raise SyncValidationError(
            "source tree is dirty (use --allow-dirty to override)"
        )

    return SourceInfo(
        commit_short=commit_short,
        commit_full=commit_full,
        dirty=dirty,
        version=_read_version(source_root),
    )


def validate_target(path: Path, target_name: str) -> None:
    expected_name = f"codeclone-{target_name}"
    if path.name != expected_name:
        raise SyncValidationError(f"target {path} does not look like {expected_name}")
    if not path.exists() or not path.is_dir() or not (path / ".git").exists():
        raise SyncValidationError(f"target {path} does not exist or is not a git repo")


def sync_target(
    *,
    source_root: Path,
    target_root: Path,
    target: SyncTarget,
    allow_dirty: bool,
    dry_run: bool,
) -> SyncResult:
    source_info = validate_source(source_root, allow_dirty=allow_dirty)
    validate_target(target_root, target.name)
    _validate_target_definition(target)

    source_root = source_root.resolve()
    target_root = target_root.resolve()
    denylist = GLOBAL_DENYLIST + target.denylist
    source_pairs = _resolve_source_pairs(
        source_root=source_root,
        target_root=target_root,
        target=target,
        denylist=denylist,
    )
    deletable_paths = _deletable_paths(
        source_root=source_root,
        target_root=target_root,
        target=target,
        denylist=denylist,
    )

    files_deleted = sum(_count_existing_files(path) for path in deletable_paths)
    files_copied = len(source_pairs)
    manifest_path = target_root / MANIFEST_NAME

    if not dry_run:
        try:
            for path in deletable_paths:
                _delete_path(path=path, target_root=target_root)
            for source_path, destination_path in source_pairs:
                _copy_file(
                    source_path=source_path,
                    destination_path=destination_path,
                    target_root=target_root,
                )
            manifest = _make_manifest(
                source_info=source_info,
                target=target,
                files_copied=files_copied,
                files_deleted=files_deleted,
            )
            write_manifest(target_root=target_root, manifest=manifest)
        except OSError as exc:
            raise SyncCopyError(str(exc)) from exc

    return SyncResult(
        target_name=target.name,
        files_copied=files_copied,
        files_deleted=files_deleted,
        manifest_path=manifest_path,
        dry_run=dry_run,
    )


def write_manifest(*, target_root: Path, manifest: SyncManifest) -> Path:
    manifest_path = target_root / MANIFEST_NAME
    payload = {
        "source_repository": manifest.source_repository,
        "source_commit": manifest.source_commit,
        "source_commit_full": manifest.source_commit_full,
        "source_dirty": manifest.source_dirty,
        "codeclone_version": manifest.codeclone_version,
        "target": manifest.target,
        "synced_at_utc": manifest.synced_at_utc,
        "source_paths": list(manifest.source_paths),
        "files_copied": manifest.files_copied,
        "files_deleted": manifest.files_deleted,
    }
    _write_json_atomically(manifest_path, payload)
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync CodeClone integration repos.")
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument(
        "--target",
        choices=tuple(SYNC_TARGETS),
        help="sync one target",
    )
    target_group.add_argument(
        "--all",
        action="store_true",
        help="sync all targets",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(".."),
        help="parent directory of distribution repos",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="allow sync from a dirty source tree",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned operation counts without writing",
    )
    args = parser.parse_args(argv)

    source_root = Path.cwd().resolve()
    base_dir = _resolve_base_dir(source_root=source_root, base_dir=args.base_dir)
    selected = tuple(SYNC_TARGETS) if args.all else (str(args.target),)

    try:
        for target_name in selected:
            target = SYNC_TARGETS[target_name]
            target_root = resolve_target_path(target_name, base_dir).resolve()
            result = sync_target(
                source_root=source_root,
                target_root=target_root,
                target=target,
                allow_dirty=bool(args.allow_dirty),
                dry_run=bool(args.dry_run),
            )
            _print_result(result=result, target_root=target_root)
    except SyncValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SyncCopyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return 0


def _run_git(root: Path, args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise SyncValidationError(message) from exc
    return result.stdout.strip()


def _read_version(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SyncValidationError("cannot read version from pyproject.toml")
    return match.group(1)


def _resolve_base_dir(*, source_root: Path, base_dir: Path) -> Path:
    if base_dir.is_absolute():
        return base_dir.resolve()
    return (source_root / base_dir).resolve()


def _validate_target_definition(target: SyncTarget) -> None:
    for source, destination in target.copies:
        _validate_relative_path(source, field="source", allow_dot=False)
        _validate_relative_path(destination, field="target", allow_dot=True)
    for generated in target.generated:
        _validate_relative_path(generated, field="generated", allow_dot=False)


def _validate_relative_path(path: str, *, field: str, allow_dot: bool) -> None:
    if not path:
        raise SyncValidationError(f"{field} path is empty")
    candidate = Path(path)
    if candidate.is_absolute():
        raise SyncValidationError(f"{field} path must be relative: {path}")
    if path == "." and allow_dot:
        return
    if path == ".":
        raise SyncValidationError(f"{field} path cannot be '.': {path}")
    if ".." in candidate.parts:
        raise SyncValidationError(f"path traversal in {field} path: {path}")


def _resolve_source_pairs(
    *,
    source_root: Path,
    target_root: Path,
    target: SyncTarget,
    denylist: tuple[str, ...],
) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for source_rel, destination_rel in target.copies:
        source_path = _resolve_inside(root=source_root, relative=source_rel)
        if not source_path.exists():
            raise SyncValidationError(f"source path does not exist: {source_rel}")
        destination_base = (
            target_root
            if destination_rel == "."
            else _resolve_inside(root=target_root, relative=destination_rel)
        )
        if source_path.is_dir():
            for file_path in _iter_source_files(source_path, denylist):
                relative_file = file_path.relative_to(source_path)
                pairs.append((file_path, destination_base / relative_file))
        elif source_path.is_file():
            relative_name = source_path.name if destination_rel == "." else ""
            destination_path = (
                destination_base / relative_name if relative_name else destination_base
            )
            if not _is_denied(source_path.name, denylist):
                pairs.append((source_path, destination_path))
        else:
            raise SyncValidationError(f"unsupported source path: {source_rel}")
    return sorted(pairs, key=lambda item: item[1].as_posix())


def _deletable_paths(
    *,
    source_root: Path,
    target_root: Path,
    target: SyncTarget,
    denylist: tuple[str, ...],
) -> list[Path]:
    paths: list[Path] = []
    for source_rel, destination_rel in target.copies:
        if destination_rel != ".":
            paths.append(_resolve_inside(root=target_root, relative=destination_rel))
            continue
        source_path = _resolve_inside(root=source_root, relative=source_rel)
        if source_path.is_dir():
            paths.extend(
                target_root / child.name
                for child in sorted(source_path.iterdir(), key=lambda path: path.name)
                if not _is_denied(child.name, denylist)
            )
        elif source_path.is_file() and not _is_denied(source_path.name, denylist):
            paths.append(target_root / source_path.name)

    paths.extend(
        _resolve_inside(root=target_root, relative=generated)
        for generated in target.generated
    )

    return sorted(set(paths), key=lambda path: path.as_posix())


def _resolve_inside(*, root: Path, relative: str) -> Path:
    _validate_relative_path(relative, field="path", allow_dot=True)
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not _is_relative_to(resolved, resolved_root):
        raise SyncValidationError(f"path escapes target root: {relative}")
    return resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _iter_source_files(source_path: Path, denylist: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(source_path):
        current = Path(current_root)
        relative_root = current.relative_to(source_path)
        dirnames[:] = [
            dirname
            for dirname in sorted(dirnames)
            if not _is_denied(_join_relative(relative_root, dirname), denylist)
        ]
        for filename in sorted(filenames):
            file_path = current / filename
            relative_file = _join_relative(relative_root, filename)
            if _is_denied(relative_file, denylist):
                continue
            if file_path.is_symlink():
                raise SyncValidationError(f"refusing to copy symlink: {file_path}")
            files.append(file_path)
    return files


def _join_relative(relative_root: Path, name: str) -> str:
    if str(relative_root) == ".":
        return name
    return (relative_root / name).as_posix()


def _is_denied(relative_path: str, denylist: tuple[str, ...]) -> bool:
    normalized = relative_path.replace("\\", "/")
    for pattern in denylist:
        if fnmatch(normalized, pattern):
            return True
        if pattern.endswith("/**"):
            prefix = pattern[:-3]
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return True
    return False


def _count_existing_files(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        return 1
    return sum(1 for child in path.rglob("*") if child.is_file() or child.is_symlink())


def _delete_path(*, path: Path, target_root: Path) -> None:
    if path == target_root:
        raise SyncCopyError("refusing to delete target root")
    if not _is_relative_to(path.resolve(), target_root.resolve()):
        raise SyncCopyError(f"refusing to delete outside target root: {path}")
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _copy_file(
    *,
    source_path: Path,
    destination_path: Path,
    target_root: Path,
) -> None:
    if not _is_relative_to(destination_path.resolve().parent, target_root.resolve()):
        raise SyncCopyError(f"refusing to copy outside target root: {destination_path}")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)


def _make_manifest(
    *,
    source_info: SourceInfo,
    target: SyncTarget,
    files_copied: int,
    files_deleted: int,
) -> SyncManifest:
    return SyncManifest(
        source_repository=SOURCE_REPOSITORY,
        source_commit=source_info.commit_short,
        source_commit_full=source_info.commit_full,
        source_dirty=source_info.dirty,
        codeclone_version=source_info.version,
        target=target.name,
        synced_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        source_paths=tuple(source for source, _ in target.copies),
        files_copied=files_copied,
        files_deleted=files_deleted,
    )


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _print_result(*, result: SyncResult, target_root: Path) -> None:
    prefix = "dry-run" if result.dry_run else "sync"
    copied = "to copy" if result.dry_run else "copied"
    deleted = "to delete" if result.dry_run else "deleted"
    print(f"{prefix}: {result.target_name} -> {target_root}")
    print(f"  manifest: {result.manifest_path}")
    print(
        f"  result:   {result.files_copied} {copied}, {result.files_deleted} {deleted}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
