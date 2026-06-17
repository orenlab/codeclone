# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .chunking import (
    SEMANTIC_CHUNK_STRATEGY_VERSION,
    collapse_trajectory_hits,
    expand_projection,
    resolve_passage_chunker,
    trajectory_chunk_row_id,
)
from .models import (
    SemanticHit,
    SemanticIndexStatus,
    SemanticProjection,
    SemanticRow,
    SemanticRowFingerprint,
    SemanticSource,
)
from .projection import (
    INDEXED_AUDIT_EVENTS,
    INDEXED_MEMORY_TYPES,
    is_indexed_audit_event,
    is_indexed_memory_type,
    project_audit_event,
    project_memory_record,
    project_trajectory,
    text_hash,
)
from .rebuild import RebuildReport, rebuild_semantic_index
from .rebuild_workflow import (
    build_semantic_index_sources,
    execute_semantic_index_rebuild,
)
from .sources import (
    AuditIndexSource,
    IndexSource,
    MemoryIndexSource,
    TrajectoryIndexSource,
)

if TYPE_CHECKING:
    from ...config.memory import SemanticConfig


class SemanticIndex(Protocol):
    """Read surface of the semantic index (search + status).

    The retrieval layer talks to this Protocol; the degraded Null/Unavailable
    indexes implement it. Keeping mutation off the read surface lets the
    degraded indexes stay small and cohesive. The concrete backend is loaded
    lazily by the factory, so the memory package never imports a vector DB at
    module level.
    """

    def search(
        self, vector: Sequence[float], *, k: int, source: SemanticSource | None = None
    ) -> list[SemanticHit]:
        """Top-k nearest hits. ``source`` restricts the search to one lane
        (memory/audit/trajectory) so each lane gets its own budget; None
        searches every lane in a single shared top-k."""
        ...

    def status(self) -> SemanticIndexStatus: ...


class SemanticIndexWriter(SemanticIndex, Protocol):
    """Read + write surface. Only a real backend implements this, and rebuild
    requires it. Confining upsert/delete here keeps the degraded read indexes
    at two methods (cohesive) and isolates mutation to the stateful backend.
    """

    def upsert(self, rows: Sequence[SemanticRow]) -> None: ...

    def delete(self, ids: Sequence[str]) -> None: ...

    def known_ids(self) -> set[str]: ...

    def row_fingerprints(self, ids: Sequence[str]) -> dict[str, SemanticRowFingerprint]:
        """Stored (text_hash, embedding_model) for the given ids, vectors not
        loaded. Missing ids are omitted; empty ``ids`` returns ``{}``."""
        ...


class NullSemanticIndex:
    """Disabled index: every read is empty."""

    def search(
        self, vector: Sequence[float], *, k: int, source: SemanticSource | None = None
    ) -> list[SemanticHit]:
        return []

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(available=False, reason="disabled")


class UnavailableSemanticIndex:
    """Enabled, but the backend could not be loaded.

    Reads degrade to empty (never raise); the recorded ``reason`` is surfaced
    by ``status()`` so callers and explicit commands can fail clear.
    """

    def __init__(self, *, reason: str) -> None:
        self._reason = reason

    def search(
        self, vector: Sequence[float], *, k: int, source: SemanticSource | None = None
    ) -> list[SemanticHit]:
        return []

    def status(self) -> SemanticIndexStatus:
        return SemanticIndexStatus(available=False, reason=self._reason)


def close_semantic_index(index: object | None) -> None:
    """Close a semantic backend if it exposes a close hook.

    The read/write Protocols deliberately do not require ``close()`` because
    degraded indexes are stateless and some optional backends do not expose a
    public close API. Call boundaries can still release resources by using this
    best-effort helper.
    """

    if index is None:
        return
    close = getattr(index, "close", None)
    if callable(close):
        close()


def resolve_semantic_index(config: SemanticConfig) -> SemanticIndex:
    """Resolve the semantic index for the given config.

    Null when disabled; otherwise the backend. The LanceDB backend is wired in
    Phase 20.2 via a lazy import inside this function (so absence never crashes
    the import of the memory package). Until then an enabled index degrades to
    Unavailable — read paths stay empty and explicit commands fail clear.
    """
    if not config.enabled:
        return NullSemanticIndex()
    if not Path(config.index_path).exists():
        return UnavailableSemanticIndex(reason="not_built")
    backend = _resolve_backend(config, create=False)
    if backend is None:
        return UnavailableSemanticIndex(reason="lancedb_not_installed")
    return backend


def resolve_semantic_index_writer(config: SemanticConfig) -> SemanticIndexWriter | None:
    """Resolve a writable semantic index (the real backend), or None.

    None means no writable backend is available (disabled, or the optional
    backend not installed) — rebuild must fail clear.
    """
    if not config.enabled:
        return None
    return _resolve_backend(config, create=True)


def _resolve_backend(
    config: SemanticConfig, *, create: bool
) -> SemanticIndexWriter | None:
    # Lazy, isolated import: the only place a vector DB is referenced. Absence
    # of the optional `semantic-lancedb` extra degrades to None (no backend).
    try:
        from .lancedb_backend import LanceDbSemanticIndex

        return LanceDbSemanticIndex(
            path=Path(config.index_path),
            dimension=config.dimension,
            create=create,
        )
    except ImportError:
        return None


__all__ = [
    "INDEXED_AUDIT_EVENTS",
    "INDEXED_MEMORY_TYPES",
    "SEMANTIC_CHUNK_STRATEGY_VERSION",
    "AuditIndexSource",
    "IndexSource",
    "MemoryIndexSource",
    "NullSemanticIndex",
    "RebuildReport",
    "SemanticHit",
    "SemanticIndex",
    "SemanticIndexStatus",
    "SemanticIndexWriter",
    "SemanticProjection",
    "SemanticRow",
    "SemanticRowFingerprint",
    "SemanticSource",
    "TrajectoryIndexSource",
    "UnavailableSemanticIndex",
    "build_semantic_index_sources",
    "close_semantic_index",
    "collapse_trajectory_hits",
    "execute_semantic_index_rebuild",
    "expand_projection",
    "is_indexed_audit_event",
    "is_indexed_memory_type",
    "project_audit_event",
    "project_memory_record",
    "project_trajectory",
    "rebuild_semantic_index",
    "resolve_passage_chunker",
    "resolve_semantic_index",
    "resolve_semantic_index_writer",
    "text_hash",
    "trajectory_chunk_row_id",
]
