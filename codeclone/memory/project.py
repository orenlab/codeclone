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
from ..paths.module_identity.projection import module_path_under_root
from ..report.meta import current_report_timestamp_utc
from ..utils.mapping_paths import section
from ..utils.repo_identity import resolve_repository_anchor_root
from ..utils.repo_paths import (
    PathOutsideRepoError,
    RepoPathError,
    RepoPathPolicy,
    resolve_under_repo_root,
)
from .models import MemoryEvidence, MemoryProject, MemorySubject, generate_memory_id
from .paths import normalize_repo_path


@dataclass(frozen=True, slots=True)
class GitProvenance:
    remote: str | None
    branch: str | None
    head: str | None
    available: bool


def resolve_memory_db_path(root_path: Path, config: MemoryConfig | None = None) -> Path:
    resolved = config or resolve_memory_config(root_path)
    return resolved.db_path


def repository_identity_root(root_path: Path) -> Path:
    """Root that owns durable repository state for *root_path*.

    Linked git worktrees anchor at the main checkout (resolved lexically
    from the git common directory), so every worktree of one repository
    shares one project identity and one memory store. All other layouts —
    main checkout, non-git directory, submodule, unresolvable git state —
    anchor at the resolved root itself.
    """

    return resolve_repository_anchor_root(root_path)


def resolve_project_identity(root_path: Path) -> MemoryProject:
    identity_root = repository_identity_root(root_path)
    git = read_git_provenance(identity_root)
    now = current_report_timestamp_utc()
    project_id = compute_project_id(identity_root)
    return MemoryProject(
        id=project_id,
        root=str(identity_root),
        git_remote=git.remote,
        git_branch=git.branch,
        git_head=git.head,
        python_tag=current_python_tag(),
        created_at_utc=now,
        updated_at_utc=now,
    )


def compute_project_id(root_path: Path) -> str:
    identity_root = repository_identity_root(root_path)
    digest = hashlib.sha256(str(identity_root).encode("utf-8")).hexdigest()
    return f"proj-{digest[:8]}"


def read_git_provenance(root_path: Path) -> GitProvenance:
    if not (root_path / ".git").exists():
        return GitProvenance(remote=None, branch=None, head=None, available=False)
    branch = _git_output_optional(root_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    head = _git_output_optional(root_path, ["rev-parse", "HEAD"])
    if not branch or not head:
        return GitProvenance(remote=None, branch=None, head=None, available=False)
    remote = _git_output_optional(root_path, ["remote", "get-url", "origin"])
    return GitProvenance(
        remote=remote or None,
        branch=branch or None,
        head=head or None,
        available=True,
    )


def git_head_evidence(
    *,
    memory_id: str,
    git: GitProvenance,
    created_at_utc: str,
) -> MemoryEvidence | None:
    if not git.available or not git.head:
        return None
    return MemoryEvidence(
        id=generate_memory_id(prefix="evid"),
        memory_id=memory_id,
        evidence_kind="git_commit",
        ref=git.head,
        locator=git.branch,
        quote=git.remote,
        digest=None,
        created_at_utc=created_at_utc,
    )


def analysis_fingerprint_from_report(report_document: dict[str, object]) -> str:
    """Identity of the analysis a memory record was derived from.

    Reads the report-v3 ``analysis_facts`` tier: the digest over the source
    observations, the report schema version and the analysis contract. That
    tier changes when — and only when — the analysed facts change, so two
    runs over one tree agree while a run after a real edit does not. The
    baseline-relative ``comparison`` tier answers a different question and
    stays with :func:`report_digest_from_report`; ``envelope`` covers the
    whole document including its timestamps and identifies a run, not code.

    An absent tier yields ``"unknown"``. Deriving a fingerprint from the clock
    would make every run look like a new state of the code, which is exactly
    the identity this value must not carry.
    """

    analysis_facts = section(report_document, "integrity.digests.analysis_facts")
    return str(analysis_facts.get("value", "")).strip() or "unknown"


def report_digest_from_report(report_document: dict[str, object]) -> str | None:
    comparison = section(report_document, "integrity.digests.comparison")
    return str(comparison.get("value", "")).strip() or None


def module_repo_path(module_key: str, root_path: Path) -> str | None:
    """Project a module subject onto its repository file, or None.

    Routed through the module-identity projection owner: ``<pkg>/__init__.py``
    when it exists, else ``<pkg>.py`` when it exists, else UNRESOLVED — a
    package module used to fingerprint a phantom ``<pkg>.py`` and silently
    lose its code fingerprint.
    """

    return module_path_under_root(module_key, root_path)


def subject_path_fingerprint(root_path: Path, rel_path: str) -> str | None:
    """SHA-1 of on-disk bytes for a repo-relative subject path at HEAD."""

    try:
        normalized = normalize_repo_path(rel_path)
    except ValueError:
        return None
    try:
        file_path = resolve_under_repo_root(
            root_path,
            normalized,
            policy=RepoPathPolicy(must_exist=True, must_be_file=True),
        )
    except (PathOutsideRepoError, RepoPathError):
        return None
    return hashlib.sha1(file_path.read_bytes()).hexdigest()


def subject_fingerprint_for_subject(
    root_path: Path,
    subject: MemorySubject,
) -> str | None:
    if subject.subject_kind in ("path", "test", "doc"):
        return subject_path_fingerprint(root_path, subject.subject_key)
    if subject.subject_kind == "module":
        module_path = module_repo_path(subject.subject_key, root_path)
        if module_path is None:
            return None
        return subject_path_fingerprint(root_path, module_path)
    return None


def code_fingerprint_for_memory_subject(
    root_path: Path,
    *,
    subject_path: str | None = None,
    module_key: str | None = None,
    analysis_fingerprint: str | None = None,
) -> str | None:
    if subject_path is not None:
        file_fingerprint = subject_path_fingerprint(root_path, subject_path)
        if file_fingerprint is not None:
            return file_fingerprint
    if module_key is not None:
        module_path = module_repo_path(module_key, root_path)
        if module_path is not None:
            file_fingerprint = subject_path_fingerprint(root_path, module_path)
            if file_fingerprint is not None:
                return file_fingerprint
    return analysis_fingerprint


def _git_output_optional(root_path: Path, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
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


__all__ = [
    "GitProvenance",
    "analysis_fingerprint_from_report",
    "code_fingerprint_for_memory_subject",
    "compute_project_id",
    "git_head_evidence",
    "module_repo_path",
    "read_git_provenance",
    "report_digest_from_report",
    "repository_identity_root",
    "resolve_memory_db_path",
    "resolve_project_identity",
    "subject_fingerprint_for_subject",
    "subject_path_fingerprint",
]
