# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig
from ..embedding import resolve_embedding_provider
from ..exceptions import MemoryContractError, MemorySemanticUnavailableError
from ..models import MemoryProject
from ..project import resolve_memory_db_path, resolve_project_identity
from ..sqlite_store import SqliteEngineeringMemoryStore
from .rebuild import rebuild_semantic_index
from .sources import (
    AuditIndexSource,
    IndexSource,
    MemoryIndexSource,
    TrajectoryIndexSource,
)


class RebuildSemanticIndexMeta(TypedDict):
    action: Literal["rebuild_semantic_index"]
    index_path: str
    embedding_provider: str


class RebuildSemanticIndexCounts(TypedDict):
    indexed: int
    deleted: int
    embedded: int
    skipped_unchanged: int
    by_source: dict[str, int]


class RebuildSemanticIndexOkPayload(
    RebuildSemanticIndexMeta, RebuildSemanticIndexCounts
):
    status: Literal["ok"]
    embedding_model: str


class RebuildSemanticIndexSkippedPayload(
    RebuildSemanticIndexMeta, RebuildSemanticIndexCounts
):
    status: Literal["skipped"]
    reason: str
    embedding_model: None


class RebuildSemanticIndexUnavailablePayload(
    RebuildSemanticIndexMeta, RebuildSemanticIndexCounts
):
    status: Literal["unavailable"]
    reason: str
    embedding_model: None


RebuildSemanticIndexPayload = (
    RebuildSemanticIndexOkPayload
    | RebuildSemanticIndexSkippedPayload
    | RebuildSemanticIndexUnavailablePayload
)


def build_semantic_index_sources(
    *,
    root_path: Path,
    config: MemoryConfig,
    store: SqliteEngineeringMemoryStore,
    project: MemoryProject,
) -> list[IndexSource]:
    audit_db_path = resolve_audit_path(
        root_path=root_path,
        value=DEFAULT_AUDIT_PATH,
    )
    return [
        MemoryIndexSource(store, project_id=project.id),
        AuditIndexSource(
            enabled=config.semantic.index_audit,
            db_path=audit_db_path,
        ),
        TrajectoryIndexSource(store, project_id=project.id),
    ]


def _rebuild_base_payload(config: MemoryConfig) -> RebuildSemanticIndexMeta:
    return {
        "action": "rebuild_semantic_index",
        "index_path": config.semantic.index_path,
        "embedding_provider": config.semantic.embedding_provider,
    }


def _rebuild_empty_counts() -> RebuildSemanticIndexCounts:
    return {
        "indexed": 0,
        "deleted": 0,
        "embedded": 0,
        "skipped_unchanged": 0,
        "by_source": {},
    }


def execute_semantic_index_rebuild(
    *,
    root_path: Path,
    config: MemoryConfig,
    store: SqliteEngineeringMemoryStore | None = None,
    project: MemoryProject | None = None,
) -> RebuildSemanticIndexPayload:
    """Rebuild the LanceDB semantic sidecar (MCP action + CLI rebuild).

    Returns a structured payload. Raises ``MemoryContractError`` when semantic
    is enabled but the engineering-memory SQLite database is missing.
    """
    base = _rebuild_base_payload(config)
    empty = _rebuild_empty_counts()
    if not config.semantic.enabled:
        return {
            **base,
            **empty,
            "status": "skipped",
            "reason": "disabled",
            "embedding_model": None,
        }
    try:
        provider = resolve_embedding_provider(config.semantic)
    except MemorySemanticUnavailableError as exc:
        return {
            **base,
            **empty,
            "status": "unavailable",
            "reason": str(exc),
            "embedding_model": None,
        }
    from . import close_semantic_index, resolve_semantic_index_writer

    writer = resolve_semantic_index_writer(config.semantic)
    if writer is None:
        return {
            **base,
            **empty,
            "status": "unavailable",
            "reason": "lancedb_not_installed",
            "embedding_model": None,
        }
    owns_store = store is None
    active_store = store
    try:
        resolved_project = project or resolve_project_identity(root_path)
        if active_store is None:
            db_path = resolve_memory_db_path(root_path, config)
            if not db_path.exists():
                raise MemoryContractError(
                    f"Engineering memory database not found: {db_path}. "
                    "Run memory init or "
                    "manage_engineering_memory(action='refresh_from_run')."
                )
            active_store = SqliteEngineeringMemoryStore(db_path)
        report = rebuild_semantic_index(
            writer=writer,
            provider=provider,
            sources=build_semantic_index_sources(
                root_path=root_path,
                config=config,
                store=active_store,
                project=resolved_project,
            ),
        )
    finally:
        close_semantic_index(writer)
        if owns_store and active_store is not None:
            active_store.close()
    return {
        **base,
        "status": "ok",
        "indexed": report.indexed,
        "deleted": report.deleted,
        "embedded": report.embedded,
        "skipped_unchanged": report.skipped_unchanged,
        "by_source": dict(sorted(report.by_source.items())),
        "embedding_model": provider.model_id,
    }


__all__ = [
    "RebuildSemanticIndexOkPayload",
    "RebuildSemanticIndexPayload",
    "RebuildSemanticIndexSkippedPayload",
    "RebuildSemanticIndexUnavailablePayload",
    "build_semantic_index_sources",
    "execute_semantic_index_rebuild",
]
