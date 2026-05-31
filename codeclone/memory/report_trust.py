# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..utils.coerce import as_mapping, as_sequence


@dataclass(frozen=True, slots=True)
class CachedReportTrust:
    trusted: bool
    reason: str | None = None


def _git_repo(root_path: Path) -> bool:
    return (root_path / ".git").exists()


def cached_report_untrusted_reason(
    *,
    root_path: Path,
    report_path: Path,
    report_document: Mapping[str, object],
) -> str | None:
    """Return a human-readable reason when a cached report must not be reused."""
    meta = as_mapping(report_document.get("meta"))
    scan_root_raw = str(meta.get("scan_root", "")).strip()
    if not scan_root_raw:
        return "cached report missing meta.scan_root"
    try:
        scan_root = Path(scan_root_raw).expanduser().resolve()
    except OSError:
        return "cached report meta.scan_root is invalid"
    if scan_root != root_path.resolve():
        return "cached report scan_root does not match init root"

    inventory = as_mapping(report_document.get("inventory"))
    file_registry = as_mapping(inventory.get("file_registry"))
    items = {
        str(item).replace("\\", "/").strip("/")
        for item in as_sequence(file_registry.get("items"))
        if str(item).strip()
    }
    if not items:
        return "cached report inventory.file_registry is empty"

    if _git_repo(root_path):
        tracked = _git_tracked_py_paths(root_path)
        if tracked is not None:
            missing = tracked - items
            if missing:
                sample = ", ".join(sorted(missing)[:3])
                extra = len(missing) - 3
                suffix = f" (+{extra} more)" if extra > 0 else ""
                return (
                    "cached report missing "
                    f"{len(missing)} tracked Python files (e.g. {sample}{suffix})"
                )

        head = _git_head_commit(root_path)
        if head and report_path.is_file():
            commit_ts = _git_head_commit_unix(root_path)
            report_mtime = int(report_path.stat().st_mtime) + 1
            if commit_ts is not None and commit_ts > report_mtime:
                return "cached report is older than current git HEAD commit"

    return None


def _git_head_commit(root_path: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    text = completed.stdout.strip()
    return text or None


def assess_cached_report_trust(
    *,
    root_path: Path,
    report_path: Path,
    report_document: Mapping[str, object],
) -> CachedReportTrust:
    reason = cached_report_untrusted_reason(
        root_path=root_path,
        report_path=report_path,
        report_document=report_document,
    )
    if reason is None:
        return CachedReportTrust(trusted=True)
    return CachedReportTrust(trusted=False, reason=reason)


def _git_tracked_py_paths(root_path: Path) -> set[str] | None:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--", "*.py"],
            cwd=root_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return {
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip()
    }


def _git_head_commit_unix(root_path: Path) -> int | None:
    try:
        completed = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "HEAD"],
            cwd=root_path,
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    text = completed.stdout.strip()
    if not text:
        return None
    return int(text)


__all__ = [
    "CachedReportTrust",
    "assess_cached_report_trust",
    "cached_report_untrusted_reason",
]
