# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..baseline.trust import current_python_tag
from ..config.memory import MemoryConfig, resolve_memory_config
from ..report.meta import current_report_timestamp_utc
from ..utils.coerce import as_mapping
from .models import MemoryProject


@dataclass(frozen=True, slots=True)
class GitProvenance:
    remote: str | None
    branch: str | None
    head: str | None
    available: bool


def resolve_memory_db_path(root_path: Path, config: MemoryConfig | None = None) -> Path:
    resolved = config or resolve_memory_config(root_path)
    return resolved.db_path


def resolve_project_identity(root_path: Path) -> MemoryProject:
    resolved_root = root_path.resolve()
    git = read_git_provenance(resolved_root)
    now = current_report_timestamp_utc()
    project_id = compute_project_id(resolved_root)
    return MemoryProject(
        id=project_id,
        root=str(resolved_root),
        git_remote=git.remote,
        git_branch=git.branch,
        git_head=git.head,
        python_tag=current_python_tag(),
        created_at_utc=now,
        updated_at_utc=now,
    )


def compute_project_id(root_path: Path) -> str:
    digest = hashlib.sha256(str(root_path.resolve()).encode("utf-8")).hexdigest()
    return f"proj-{digest[:8]}"


def read_git_provenance(root_path: Path) -> GitProvenance:
    if not (root_path / ".git").exists():
        return GitProvenance(remote=None, branch=None, head=None, available=False)
    try:
        remote = _git_output(root_path, ["remote", "get-url", "origin"])
        branch = _git_output(root_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        head = _git_output(root_path, ["rev-parse", "HEAD"])
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return GitProvenance(remote=None, branch=None, head=None, available=False)
    return GitProvenance(
        remote=remote or None,
        branch=branch or None,
        head=head or None,
        available=True,
    )


def analysis_fingerprint_from_report(report_document: dict[str, object]) -> str:
    integrity = as_mapping(report_document.get("integrity"))
    digest = as_mapping(integrity.get("digest"))
    value = str(digest.get("value", "")).strip()
    if value:
        return value[:16]
    meta = as_mapping(report_document.get("meta"))
    generated = str(meta.get("report_generated_at_utc", "")).strip()
    if generated:
        return hashlib.sha256(generated.encode("utf-8")).hexdigest()[:16]
    return "unknown"


def report_digest_from_report(report_document: dict[str, object]) -> str | None:
    integrity = as_mapping(report_document.get("integrity"))
    digest = as_mapping(integrity.get("digest"))
    value = str(digest.get("value", "")).strip()
    return value or None


def _git_output(root_path: Path, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    return completed.stdout.strip()


__all__ = [
    "GitProvenance",
    "analysis_fingerprint_from_report",
    "compute_project_id",
    "read_git_provenance",
    "report_digest_from_report",
    "resolve_memory_db_path",
    "resolve_project_identity",
]
