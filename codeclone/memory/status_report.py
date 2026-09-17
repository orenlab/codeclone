# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..contracts import ENGINEERING_MEMORY_SCHEMA_VERSION
from .exceptions import MemorySchemaError
from .project import GitProvenance, read_git_provenance, resolve_project_identity
from .schema_meta import get_meta
from .sqlite_store import SqliteEngineeringMemoryStore

#: What this checkout can say about the engineering-memory store, as three
#: mutually exclusive facts rather than one boolean plus an exception.
#:
#: ``absent``       -- no store file at ``db_path``; nothing was ever created.
#: ``ready``        -- store present and readable at this checkout's schema.
#: ``incompatible`` -- store present, but its on-disk schema is not the one
#: this executable supports, and opening it here carries no authority to
#: migrate it (see ``codeclone.memory.schema.ensure_schema``).
#:
#: ``incompatible`` is deliberately NOT folded into ``absent``: a store that
#: exists and holds records, reported as "not created yet", sends the reader
#: to ``codeclone memory init`` when the real remediation is
#: ``codeclone memory migrate`` (or a checkout whose version matches). The
#: discriminator is this field, never a nullable value whose ``None`` would
#: have to mean several different things at once.
MemoryStoreState = Literal["absent", "ready", "incompatible"]


@dataclass(frozen=True, slots=True)
class MemoryStatusReport:
    """One store, one state, one set of facts about it.

    ``state`` is the single stored discriminator. ``db_exists`` is derived
    from it rather than stored beside it, so the two can never disagree: a
    report claiming a present-but-incompatible store that does not exist, or
    an absent store that does, is not constructible.

    ``schema_version`` is what is ON DISK (``None`` when there is no store,
    or when the store is present but its meta row cannot be read at all);
    ``supported_schema_version`` is what THIS executable implements. They are
    equal exactly when ``state`` is ``ready``, and reporting both is what
    turns "cannot open the store" into an actionable fact.
    """

    db_path: Path
    schema_version: str | None
    project_id: str | None
    project_root: str | None
    backend: str
    git_available: bool
    git_branch: str | None
    git_head: str | None
    last_analysis_fingerprint: str | None
    last_init_run_id: str | None
    record_count: int
    records_by_type: dict[str, int]
    records_by_status: dict[str, int]
    state: MemoryStoreState
    supported_schema_version: str = ENGINEERING_MEMORY_SCHEMA_VERSION

    @property
    def db_exists(self) -> bool:
        """Whether a store file is present, derived from ``state``.

        Kept under the historical name every consumer already reads. It
        answers "is there a store" and nothing more -- a caller that needs
        to know whether the store can be USED must look at ``state``,
        because an ``incompatible`` store exists and still cannot be read.
        """
        return self.state != "absent"


def _peek_schema_version(db_path: Path) -> str | None:
    """Read the on-disk ``schema_version`` with no chance of writing it.

    Opened through SQLite's ``mode=ro`` URI, so this cannot migrate, create
    or otherwise touch the store even by accident -- the whole point of the
    ``incompatible`` state is that a status read carries no migration
    authority. Returns ``None`` when the file cannot be opened or holds no
    readable meta row; the state is ``incompatible`` either way, because the
    store is present and this checkout cannot read it.
    """
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        return get_meta(conn, "schema_version")
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _unusable_store_report(
    *,
    state: MemoryStoreState,
    db_path: Path,
    schema_version: str | None,
    project_id: str | None,
    project_root: str,
    backend: str,
    git: GitProvenance,
) -> MemoryStatusReport:
    """A report for a store this checkout cannot read records out of.

    Shared by the two such states -- ``absent`` and ``incompatible`` -- so
    the only difference between them is the state each caller names, and the
    counts stay zero because nothing was counted, not because the store was
    measured and found empty.
    """
    return MemoryStatusReport(
        db_path=db_path,
        schema_version=schema_version,
        project_id=project_id,
        project_root=project_root,
        backend=backend,
        git_available=git.available,
        git_branch=git.branch,
        git_head=git.head,
        last_analysis_fingerprint=None,
        last_init_run_id=None,
        record_count=0,
        records_by_type={},
        records_by_status={},
        state=state,
    )


def build_memory_status_report(
    *,
    root_path: Path,
    db_path: Path,
    backend: str = "sqlite",
) -> MemoryStatusReport:
    """Describe the engineering-memory store for *root_path*.

    Never raises for a schema this checkout cannot open, and never migrates
    one: such a store comes back as ``state="incompatible"`` carrying both
    schema versions. Status is a read, and a read has no migration
    authority.
    """
    resolved_root = root_path.resolve()
    project = resolve_project_identity(resolved_root)
    git = read_git_provenance(resolved_root)
    if not db_path.exists():
        return _unusable_store_report(
            state="absent",
            db_path=db_path,
            schema_version=None,
            project_id=project.id,
            project_root=str(resolved_root),
            backend=backend,
            git=git,
        )

    try:
        store = SqliteEngineeringMemoryStore(db_path)
    except MemorySchemaError:
        # The store is present and this checkout may not read it. Calling it
        # absent would send the reader to `memory init` and silently deny
        # that any records exist; reporting the two schema versions names
        # the real remediation instead.
        return _unusable_store_report(
            state="incompatible",
            db_path=db_path,
            schema_version=_peek_schema_version(db_path),
            project_id=project.id,
            project_root=str(resolved_root),
            backend=backend,
            git=git,
        )

    try:
        schema_version = store.get_meta("schema_version")
        project_id = store.get_meta("project_id") or project.id
        project_root = store.get_meta("project_root") or str(resolved_root)
        last_analysis_fingerprint = store.get_meta("last_analysis_fingerprint")
        last_init_run_id = store.get_meta("last_init_run_id")
        record_count = store.count_records()
        records_by_type = store.count_records_grouped(column="type")
        records_by_status = store.count_records_grouped(column="status")
    finally:
        store.close()

    return MemoryStatusReport(
        db_path=db_path,
        schema_version=schema_version or ENGINEERING_MEMORY_SCHEMA_VERSION,
        project_id=project_id,
        project_root=project_root,
        backend=backend,
        git_available=git.available,
        git_branch=git.branch,
        git_head=git.head,
        last_analysis_fingerprint=last_analysis_fingerprint,
        last_init_run_id=last_init_run_id,
        record_count=record_count,
        records_by_type=records_by_type,
        records_by_status=records_by_status,
        state="ready",
    )


__all__ = ["MemoryStatusReport", "MemoryStoreState", "build_memory_status_report"]
