# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

from ...audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from ...config.memory import MemoryConfig, SemanticConfig
from ...observability import SpanHandle, is_observability_enabled, span
from ...observability.reason_kind import ReasonKind
from ..embedding import resolve_embedding_provider
from ..embedding.batching import EmbedBatchLimits
from ..embedding.length import (
    ProjectionTokenProber,
    resolve_planning_token_estimator,
)
from ..exceptions import MemoryContractError, MemorySemanticUnavailableError
from ..models import MemoryProject
from ..project import resolve_memory_db_path, resolve_project_identity
from ..sqlite_store import SqliteEngineeringMemoryStore
from .chunking import PassageChunker, resolve_passage_chunker
from .projection_probe import SemanticProjectionProbePayload, probe_semantic_projections
from .rebuild import RebuildReport, rebuild_semantic_index
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


def _rebuild_reason_kind(report: RebuildReport) -> ReasonKind:
    if report.indexed == 0:
        return "first_index"
    if report.embedded > 0 or report.deleted > 0:
        return "content_changed"
    if report.skipped_unchanged > 0:
        # Full reconcile with hash-skip only — operator or scheduler triggered
        # rebuild but the index was already current (no embed/prune work).
        return "manual_rebuild"
    return "manual_rebuild"


def _apply_rebuild_counters(
    rebuild_span: SpanHandle,
    report: RebuildReport,
    *,
    dimensions: int,
    batch_size: int,
    max_padded_tokens: int,
) -> None:
    if not is_observability_enabled():
        return
    rebuild_span.set_counter("indexed", report.indexed)
    rebuild_span.set_counter("embedded", report.embedded)
    rebuild_span.set_counter("skipped_unchanged", report.skipped_unchanged)
    rebuild_span.set_counter("deleted", report.deleted)
    rebuild_span.set_counter("embedding_dimensions", dimensions)
    rebuild_span.set_counter("embedding_batch_size", batch_size)
    rebuild_span.set_counter("embedding_max_padded_tokens", max_padded_tokens)
    for lane, count in sorted(report.by_source.items()):
        rebuild_span.set_counter(f"lane_{lane}", count)


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
    with span(name="memory.semantic.rebuild") as rebuild_span:
        if not config.semantic.enabled:
            return {
                **base,
                **empty,
                "status": "skipped",
                "reason": "disabled",
                "embedding_model": None,
            }
        with span(name="memory.semantic.bootstrap"):
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
        report: RebuildReport | None = None
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
                embed_batch_limits=EmbedBatchLimits(
                    max_documents=config.semantic.embed_max_documents_per_batch,
                    max_padded_tokens=config.semantic.embed_max_padded_tokens_per_batch,
                ),
            )
        except MemorySemanticUnavailableError as exc:
            # The embedding model loads lazily, so an unavailable model surfaces at
            # the first embed here rather than at resolve. Report it the same way an
            # unresolved provider does instead of letting the rebuild raise.
            return {
                **base,
                **empty,
                "status": "unavailable",
                "reason": str(exc),
                "embedding_model": None,
            }
        finally:
            close_semantic_index(writer)
            if owns_store and active_store is not None:
                active_store.close()
        assert report is not None
        rebuild_span.set_reason_kind(_rebuild_reason_kind(report))
        _apply_rebuild_counters(
            rebuild_span,
            report,
            dimensions=config.semantic.dimension,
            batch_size=config.semantic.embed_max_documents_per_batch,
            max_padded_tokens=config.semantic.embed_max_padded_tokens_per_batch,
        )
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


def execute_semantic_projection_probe(
    *,
    root_path: Path,
    config: MemoryConfig,
    store: SqliteEngineeringMemoryStore | None = None,
    project: MemoryProject | None = None,
    exact_tokens: bool = False,
) -> SemanticProjectionProbePayload | dict[str, object]:
    """Measure semantic projection length distribution per lane without embedding."""
    if not config.semantic.enabled:
        return {
            "action": "probe_semantic_projections",
            "status": "skipped",
            "reason": "disabled",
        }
    token_prober = _resolve_projection_token_prober(
        config.semantic,
        exact_tokens=exact_tokens,
    )
    passage_chunker = _resolve_projection_passage_chunker(
        config.semantic,
        exact_tokens=exact_tokens,
    )
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
        return probe_semantic_projections(
            sources=build_semantic_index_sources(
                root_path=root_path,
                config=config,
                store=active_store,
                project=resolved_project,
            ),
            token_prober=token_prober,
            passage_chunker=passage_chunker,
        )
    finally:
        if owns_store and active_store is not None:
            active_store.close()


def _resolve_projection_token_prober(
    config: SemanticConfig,
    *,
    exact_tokens: bool = False,
) -> ProjectionTokenProber:
    if exact_tokens and config.embedding_provider == "fastembed":
        provider = resolve_embedding_provider(config)
        if isinstance(provider, ProjectionTokenProber):
            return provider
    return resolve_planning_token_estimator(config)


def _resolve_projection_passage_chunker(
    config: SemanticConfig,
    *,
    exact_tokens: bool = False,
) -> PassageChunker | None:
    if not exact_tokens or config.embedding_provider != "fastembed":
        return None
    provider = resolve_embedding_provider(config)
    return resolve_passage_chunker(provider)


__all__ = [
    "RebuildSemanticIndexOkPayload",
    "RebuildSemanticIndexPayload",
    "RebuildSemanticIndexSkippedPayload",
    "RebuildSemanticIndexUnavailablePayload",
    "build_semantic_index_sources",
    "execute_semantic_index_rebuild",
    "execute_semantic_projection_probe",
]
