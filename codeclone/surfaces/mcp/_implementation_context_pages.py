# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Session-local implementation-context facet page artifacts."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import orjson

IMPLEMENTATION_CONTEXT_PAGE_CONTRACT_VERSION: Final = "1"
IMPLEMENTATION_CONTEXT_PAGE_ORDERING_VERSION: Final = "context_facet_order_v1"
DEFAULT_IMPLEMENTATION_CONTEXT_PAGE_SIZE: Final = 20
MAX_IMPLEMENTATION_CONTEXT_PAGE_SIZE: Final = 50


@dataclass(frozen=True, slots=True)
class ContextFacetSnapshot:
    """Full evaluated item lane for one implementation-context facet key."""

    key: str
    items: tuple[dict[str, object], ...]
    identity_digest: str


@dataclass(frozen=True, slots=True)
class ContextProjectionArtifact:
    """Immutable in-session page source for one implementation-context response."""

    root: Path
    run_id: str
    context_artifact_digest: str
    context_projection_digest: str
    request_digest: str
    facets: Mapping[str, ContextFacetSnapshot]


def build_context_projection_artifact(
    *,
    root: Path,
    run_id: str,
    context_artifact_digest: str,
    context_projection_digest: str,
    request: Mapping[str, object],
    facets: Mapping[str, Sequence[Mapping[str, object]]],
) -> ContextProjectionArtifact:
    """Build a session-local immutable artifact for evaluated facet lanes."""

    snapshots = {
        key: _facet_snapshot(key, items)
        for key, items in facets.items()
        if _normalized_key(key)
    }
    return ContextProjectionArtifact(
        root=root.resolve(),
        run_id=run_id,
        context_artifact_digest=context_artifact_digest,
        context_projection_digest=context_projection_digest,
        request_digest=_digest({"request": dict(request)}),
        facets=dict(sorted(snapshots.items())),
    )


def context_page_inventory(
    artifact: ContextProjectionArtifact,
) -> dict[str, object]:
    """Return compact retrieval metadata for a saved context projection."""

    return {
        "retrieval_tool": "get_implementation_context_page",
        "route": (
            "get_implementation_context_page(root=..., "
            "context_projection_digest=..., facet=...)"
        ),
        "retention": "mcp_session_run_history",
        "contract_version": IMPLEMENTATION_CONTEXT_PAGE_CONTRACT_VERSION,
        "ordering_version": IMPLEMENTATION_CONTEXT_PAGE_ORDERING_VERSION,
        "available_facets": sorted(artifact.facets),
    }


def context_projection_page(
    *,
    artifact: ContextProjectionArtifact,
    facet: str,
    offset: int,
    page_size: int,
) -> dict[str, object]:
    """Return one exact page from a saved implementation-context facet lane."""

    normalized_facet = _normalized_key(facet)
    if normalized_facet not in artifact.facets:
        return {
            "status": "facet_not_found",
            "facet": normalized_facet,
            "available_facets": sorted(artifact.facets),
            "source": "mcp_session_context_projection",
            "retention": "mcp_session_run_history",
        }
    snapshot = artifact.facets[normalized_facet]
    bounded_offset = max(0, offset)
    bounded_page_size = bounded_context_page_size(page_size)
    items = snapshot.items[bounded_offset : bounded_offset + bounded_page_size]
    next_offset = bounded_offset + len(items)
    return {
        "status": "ok",
        "source": "mcp_session_context_projection",
        "exact": True,
        "retention": "mcp_session_run_history",
        "run_id": artifact.run_id,
        "context_artifact_digest": artifact.context_artifact_digest,
        "context_projection_digest": artifact.context_projection_digest,
        "request_digest": artifact.request_digest,
        "facet": normalized_facet,
        "facet_identity_digest": snapshot.identity_digest,
        "contract_version": IMPLEMENTATION_CONTEXT_PAGE_CONTRACT_VERSION,
        "ordering_version": IMPLEMENTATION_CONTEXT_PAGE_ORDERING_VERSION,
        "page": {
            "offset": bounded_offset,
            "page_size": bounded_page_size,
            "total": len(snapshot.items),
            "shown": len(items),
            "next_offset": next_offset if next_offset < len(snapshot.items) else None,
        },
        "items": [dict(item) for item in items],
    }


def bounded_context_page_size(value: int) -> int:
    """Clamp implementation-context page size to the documented bounds."""

    return min(MAX_IMPLEMENTATION_CONTEXT_PAGE_SIZE, max(1, int(value)))


def _facet_snapshot(
    key: str,
    items: Sequence[Mapping[str, object]],
) -> ContextFacetSnapshot:
    normalized_items = tuple(dict(item) for item in items)
    return ContextFacetSnapshot(
        key=_normalized_key(key),
        items=normalized_items,
        identity_digest=_digest(
            {
                "facet": _normalized_key(key),
                "ordering_version": IMPLEMENTATION_CONTEXT_PAGE_ORDERING_VERSION,
                "items": list(normalized_items),
            }
        ),
    )


def _normalized_key(value: str) -> str:
    return value.strip()


def _digest(payload: object) -> str:
    return hashlib.sha256(
        orjson.dumps(
            payload,
            option=orjson.OPT_SORT_KEYS | orjson.OPT_APPEND_NEWLINE,
        )
    ).hexdigest()


__all__ = [
    "DEFAULT_IMPLEMENTATION_CONTEXT_PAGE_SIZE",
    "IMPLEMENTATION_CONTEXT_PAGE_CONTRACT_VERSION",
    "IMPLEMENTATION_CONTEXT_PAGE_ORDERING_VERSION",
    "MAX_IMPLEMENTATION_CONTEXT_PAGE_SIZE",
    "ContextFacetSnapshot",
    "ContextProjectionArtifact",
    "bounded_context_page_size",
    "build_context_projection_artifact",
    "context_page_inventory",
    "context_projection_page",
]
