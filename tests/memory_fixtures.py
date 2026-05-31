# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from codeclone.memory.identity import make_identity_key
from codeclone.memory.models import (
    MemoryProject,
    MemoryRecord,
    MemorySubject,
    generate_memory_id,
)
from codeclone.memory.project import resolve_project_identity
from codeclone.memory.sqlite_store import SqliteEngineeringMemoryStore
from codeclone.report.meta import current_report_timestamp_utc


def init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=root,
        check=True,
        capture_output=True,
    )


def git_repo_with_cached_report(
    tmp_path: Path,
    *,
    py_sources: Mapping[str, str],
    registry_items: list[str],
) -> tuple[Path, Path, dict[str, object]]:
    root = tmp_path / "repo"
    root.mkdir()
    init_git_repo(root)
    for rel_path, content in py_sources.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )

    report_path = root / ".cache" / "codeclone" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("{}", encoding="utf-8")
    report_document: dict[str, object] = {
        "meta": {"scan_root": str(root.resolve())},
        "inventory": {"file_registry": {"items": registry_items}},
    }
    return root, report_path, report_document


@contextmanager
def memory_store(
    tmp_path: Path,
) -> Iterator[tuple[Path, MemoryProject, SqliteEngineeringMemoryStore, Path]]:
    root = tmp_path / "repo"
    root.mkdir()
    project = resolve_project_identity(root)
    db_path = tmp_path / "memory.sqlite3"
    store = SqliteEngineeringMemoryStore(db_path)
    store.initialize(project)
    try:
        yield root, project, store, db_path
    finally:
        store.close()


def seed_module_role(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    file_path: str,
    statement: str = "module",
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    module_key = file_path.replace("/", ".").removesuffix(".py")
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="module_role",
            subject_kind="module",
            subject_key=module_key,
            discriminator="inventory_module",
        ),
        type="module_role",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="analysis",
        statement=statement,
        summary=None,
        payload={"module_path": module_key},
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )
    store.upsert_record(record)
    store.write_subject(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="module",
            subject_key=module_key,
            relation="about",
        )
    )
    return record


def seed_path_linked_module_role(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    file_path: str,
    statement: str = "module",
) -> MemoryRecord:
    record = seed_module_role(
        store,
        project_id=project_id,
        file_path=file_path,
        statement=statement,
    )
    store.write_subject(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key=file_path,
            relation="about",
        )
    )
    return record


def seed_path_subject_record(
    store: SqliteEngineeringMemoryStore,
    *,
    project_id: str,
    path: str,
    statement: str,
) -> MemoryRecord:
    now = current_report_timestamp_utc()
    module_key = path.replace("/", ".").removesuffix(".py")
    record = MemoryRecord(
        id=generate_memory_id(),
        project_id=project_id,
        identity_key=make_identity_key(
            type="module_role",
            subject_kind="module",
            subject_key=module_key,
            discriminator="inventory_module",
        ),
        type="module_role",
        status="active",
        confidence="supported",
        origin="system",
        ingest_source="analysis",
        statement=statement,
        summary=None,
        payload={"module_path": module_key},
        created_at_utc=now,
        updated_at_utc=now,
        last_verified_at_utc=now,
        expires_at_utc=None,
        created_by="test",
        verified_by=None,
        approved_by=None,
        approved_at_utc=None,
        report_digest=None,
        code_fingerprint=None,
        stale_reason=None,
        created_on_branch=None,
        created_at_commit=None,
        verified_on_branch=None,
        verified_at_commit=None,
    )
    store.upsert_record(record)
    store.write_subject(
        MemorySubject(
            id=generate_memory_id(prefix="subj"),
            memory_id=record.id,
            subject_kind="path",
            subject_key=path,
            relation="about",
        )
    )
    return record
