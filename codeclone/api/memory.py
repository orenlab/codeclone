# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""R3 door for memory-configuration reads that surfaces depend on."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..config.memory import resolve_memory_config
from ..config.memory_defaults import DEFAULT_MEMORY_MAX_BLAST_RADIUS_CACHE_ENTRIES
from ..memory.semantic.rebuild_workflow import execute_semantic_index_rebuild

SemanticIndexRebuildStatus = Literal["ok", "skipped", "unavailable"]


@dataclass(frozen=True, kw_only=True, slots=True)
class SemanticIndexRebuildDTO:
    """Immutable in-process projection of one semantic rebuild result."""

    action: Literal["rebuild_semantic_index"]
    status: SemanticIndexRebuildStatus
    index_path: str
    embedding_provider: str
    indexed: int
    deleted: int
    embedded: int
    skipped_unchanged: int
    by_source: tuple[tuple[str, int], ...]
    embedding_model: str | None
    reason: str | None = None

    def to_payload(self) -> dict[str, object]:
        """Project the DTO onto the existing CLI/MCP payload contract."""

        payload: dict[str, object] = {
            "action": self.action,
            "status": self.status,
            "index_path": self.index_path,
            "embedding_provider": self.embedding_provider,
            "indexed": self.indexed,
            "deleted": self.deleted,
            "embedded": self.embedded,
            "skipped_unchanged": self.skipped_unchanged,
            "by_source": dict(self.by_source),
            "embedding_model": self.embedding_model,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


def rebuild_semantic_index(*, root_path: Path) -> SemanticIndexRebuildDTO:
    """Delegate once to the canonical R2p semantic rebuild owner."""

    payload = execute_semantic_index_rebuild(
        root_path=root_path,
        config=resolve_memory_config(root_path),
    )
    status = payload["status"]
    reason_value = payload.get("reason")
    reason = reason_value if isinstance(reason_value, str) else None
    return SemanticIndexRebuildDTO(
        action=payload["action"],
        status=status,
        index_path=payload["index_path"],
        embedding_provider=payload["embedding_provider"],
        indexed=payload["indexed"],
        deleted=payload["deleted"],
        embedded=payload["embedded"],
        skipped_unchanged=payload["skipped_unchanged"],
        by_source=tuple(sorted(payload["by_source"].items())),
        embedding_model=payload["embedding_model"],
        reason=reason,
    )


def blast_radius_cache_limit(*, root_path: Path) -> int:
    """Bound on one root's cached blast-radius answers, from that root's config.

    The only reader of ``memory.max_blast_radius_cache_entries``, and the door
    the MCP session reaches it through: R4 surfaces may not import the R2
    configuration owner directly, so the enforcement path for this key runs
    ``config.memory`` -> here -> the session cache and nowhere else.

    The bound is per root because the cache key is per root. Applied to the
    session-wide dictionary it would mean that, with two checkouts in one
    session, whichever configuration was read last governs the other
    checkout's residency.

    It is therefore the partition quota and only that. The total a session may
    hold is a separate bound with a separate basis, held by the cache owner in
    ``_session_blast_radius_mixin`` and read from no configuration at all, so
    that this one key is never asked to mean both.

    A memory table that cannot be read at all yields the declared default.
    Blast radius carries ``start_controlled_change``,
    ``get_implementation_context`` and ``finish_controlled_change``; none of
    them should become unavailable because an unrelated memory key was
    mistyped.
    """

    try:
        return resolve_memory_config(root_path).max_blast_radius_cache_entries
    except ValueError:
        return DEFAULT_MEMORY_MAX_BLAST_RADIUS_CACHE_ENTRIES


__all__ = [
    "SemanticIndexRebuildDTO",
    "blast_radius_cache_limit",
    "rebuild_semantic_index",
]
