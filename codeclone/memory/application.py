# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config.memory import MemoryConfig, SemanticConfig, resolve_memory_config
from .embedding import EmbeddingProvider, resolve_embedding_provider
from .exceptions import MemorySemanticUnavailableError
from .models import MemoryProject
from .project import resolve_memory_db_path, resolve_project_identity
from .retrieval import query_engineering_memory
from .semantic import SemanticIndex, close_semantic_index, resolve_semantic_index
from .sqlite_store import SqliteEngineeringMemoryStore


@dataclass(frozen=True, slots=True)
class MemoryApplicationContext:
    """Resolved repository-local dependencies shared by memory transports."""

    config: MemoryConfig
    db_path: Path
    project: MemoryProject


def resolve_memory_application_context(
    root_path: Path,
    *,
    config_resolver: Callable[[Path], MemoryConfig] | None = None,
    db_path_resolver: Callable[[Path, MemoryConfig], Path] | None = None,
    project_resolver: Callable[[Path], MemoryProject] | None = None,
) -> MemoryApplicationContext:
    resolve_config = config_resolver or resolve_memory_config
    resolve_db_path = db_path_resolver or resolve_memory_db_path
    resolve_project = project_resolver or resolve_project_identity
    config = resolve_config(root_path)
    return MemoryApplicationContext(
        config=config,
        db_path=resolve_db_path(root_path, config),
        project=resolve_project(root_path),
    )


def execute_memory_query(
    store: SqliteEngineeringMemoryStore,
    *,
    context: MemoryApplicationContext,
    root_path: Path,
    mode: str,
    record_id: str | None = None,
    path: str | None = None,
    symbol: str | None = None,
    query: str | None = None,
    scope: Sequence[str] | None = None,
    filters: Mapping[str, object] | None = None,
    max_results: int = 20,
    include_stale: bool = False,
    include_drafts: bool = False,
    detail_level: str = "compact",
    semantic: bool = False,
    audit_db_path: Path | None = None,
    query_executor: Callable[..., dict[str, object]] | None = None,
    semantic_index_resolver: Callable[[SemanticConfig], SemanticIndex] | None = None,
    embedding_provider_resolver: Callable[[SemanticConfig], EmbeddingProvider]
    | None = None,
    semantic_index_closer: Callable[[object | None], None] | None = None,
) -> dict[str, object]:
    """Execute one memory query with a transport-neutral semantic lifecycle."""

    run_query = query_executor or query_engineering_memory
    resolve_index = semantic_index_resolver or resolve_semantic_index
    resolve_provider = embedding_provider_resolver or resolve_embedding_provider
    close_index = semantic_index_closer or close_semantic_index
    index = resolve_index(context.config.semantic) if semantic else None
    try:
        provider = None
        semantic_reason = None
        if semantic:
            try:
                provider = resolve_provider(context.config.semantic)
            except MemorySemanticUnavailableError as exc:
                semantic_reason = str(exc)
        return run_query(
            store,
            project_id=context.project.id,
            root_path=root_path,
            backend=context.config.backend,
            db_path=context.db_path,
            mode=mode,
            record_id=record_id,
            path=path,
            symbol=symbol,
            query=query,
            scope=scope,
            filters=filters,
            max_results=max_results,
            include_stale=include_stale,
            include_drafts=include_drafts,
            detail_level=detail_level,
            semantic=semantic,
            semantic_index=index,
            embedding_provider=provider,
            provider_label=context.config.semantic.embedding_provider,
            semantic_reason=semantic_reason,
            audit_db_path=audit_db_path,
        )
    finally:
        close_index(index)


__all__ = [
    "MemoryApplicationContext",
    "execute_memory_query",
    "resolve_memory_application_context",
]
