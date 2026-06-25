# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Digest-bound continuation cursors for memory retrieval lanes."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from typing import Final

import orjson

from ..exceptions import MemoryContractError

MEMORY_CONTINUATION_CURSOR_VERSION: Final = "1"
MEMORY_CONTINUATION_PROJECTION_KIND: Final = "memory_retrieval_lane_projection_v1"
MEMORY_CONTINUATION_ORDERING_VERSION: Final = "memory_retrieval_lane_order_v1"
DEFAULT_MEMORY_CONTINUATION_PAGE_SIZE: Final = 20
MAX_MEMORY_CONTINUATION_PAGE_SIZE: Final = 50
MEMORY_CONTINUATION_LANES: Final[frozenset[str]] = frozenset(
    {"records", "trajectories", "experiences"}
)


def memory_lane_item_ids(
    lane: str,
    items: Sequence[Mapping[str, object]],
) -> list[str]:
    """Return the stable item identities for a memory retrieval lane."""

    if lane == "records":
        key = "id"
    elif lane == "trajectories":
        key = "trajectory_id"
    elif lane == "experiences":
        key = "id"
    else:
        raise MemoryContractError(f"unknown memory continuation lane: {lane}")
    ids: list[str] = []
    for item in items:
        value = item.get(key)
        if not isinstance(value, str) or not value:
            raise MemoryContractError(f"memory continuation lane {lane} lacks {key}")
        ids.append(value)
    return ids


def memory_lane_identity_digest(
    lane: str,
    items: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    """Digest the exact ordered identities of a memory retrieval lane."""

    return _digest(
        {
            "projection_kind": MEMORY_CONTINUATION_PROJECTION_KIND,
            "ordering_version": MEMORY_CONTINUATION_ORDERING_VERSION,
            "lane": lane,
            "ids": memory_lane_item_ids(lane, items),
        }
    )


def build_memory_continuation_cursor(
    *,
    project_id: str,
    lane: str,
    request: Mapping[str, object],
    items: Sequence[Mapping[str, object]],
    offset: int,
) -> dict[str, object]:
    """Build a deterministic cursor envelope for the next page of *lane*."""

    if lane not in MEMORY_CONTINUATION_LANES:
        raise MemoryContractError(f"unknown memory continuation lane: {lane}")
    total = len(items)
    if offset < 0 or offset > total:
        raise MemoryContractError("memory continuation offset is out of bounds")
    payload: dict[str, object] = {
        "cursor_version": MEMORY_CONTINUATION_CURSOR_VERSION,
        "projection_kind": MEMORY_CONTINUATION_PROJECTION_KIND,
        "ordering_version": MEMORY_CONTINUATION_ORDERING_VERSION,
        "project_id": project_id,
        "lane": lane,
        "offset": offset,
        "total": total,
        "request": dict(request),
        "lane_identity_digest": memory_lane_identity_digest(lane, items),
    }
    payload["cursor_digest"] = _digest(payload)
    return {
        "cursor": _encode_cursor(payload),
        "cursor_digest": payload["cursor_digest"],
        "projection_kind": MEMORY_CONTINUATION_PROJECTION_KIND,
        "ordering_version": MEMORY_CONTINUATION_ORDERING_VERSION,
        "offset": offset,
        "total": total,
    }


def rebase_memory_continuation_cursor(
    cursor: str,
    *,
    offset: int,
) -> dict[str, object]:
    """Return the same digest-bound cursor envelope at a smaller shown offset."""

    payload = decode_memory_continuation_cursor(cursor)
    total = payload.get("total")
    if not isinstance(total, int):
        raise MemoryContractError("memory continuation total is invalid")
    if offset < 0 or offset > total:
        raise MemoryContractError("memory continuation offset is out of bounds")
    payload = dict(payload)
    payload["offset"] = offset
    payload.pop("cursor_digest", None)
    payload["cursor_digest"] = _digest(payload)
    return {
        "cursor": _encode_cursor(payload),
        "cursor_digest": payload["cursor_digest"],
        "projection_kind": MEMORY_CONTINUATION_PROJECTION_KIND,
        "ordering_version": MEMORY_CONTINUATION_ORDERING_VERSION,
        "offset": offset,
        "total": total,
    }


def decode_memory_continuation_cursor(cursor: str) -> dict[str, object]:
    """Decode and validate a memory continuation cursor."""

    if not cursor.strip():
        raise MemoryContractError("memory continuation cursor is required")
    try:
        raw = base64.urlsafe_b64decode(_padded_base64(cursor.strip()))
        payload = orjson.loads(raw)
    except (ValueError, orjson.JSONDecodeError) as exc:
        raise MemoryContractError("memory continuation cursor is invalid") from exc
    if not isinstance(payload, dict):
        raise MemoryContractError("memory continuation cursor payload is invalid")
    expected_digest = payload.get("cursor_digest")
    if not isinstance(expected_digest, dict):
        raise MemoryContractError("memory continuation cursor digest is missing")
    without_digest = dict(payload)
    without_digest.pop("cursor_digest", None)
    if _digest(without_digest) != expected_digest:
        raise MemoryContractError("memory continuation cursor digest mismatch")
    if payload.get("cursor_version") != MEMORY_CONTINUATION_CURSOR_VERSION:
        raise MemoryContractError("memory continuation cursor version is unsupported")
    if payload.get("projection_kind") != MEMORY_CONTINUATION_PROJECTION_KIND:
        raise MemoryContractError("memory continuation projection kind is unsupported")
    if payload.get("ordering_version") != MEMORY_CONTINUATION_ORDERING_VERSION:
        raise MemoryContractError("memory continuation ordering version is unsupported")
    lane = payload.get("lane")
    if not isinstance(lane, str) or lane not in MEMORY_CONTINUATION_LANES:
        raise MemoryContractError("memory continuation lane is invalid")
    request = payload.get("request")
    if not isinstance(request, dict):
        raise MemoryContractError("memory continuation request is invalid")
    return payload


def memory_continuation_page(
    *,
    cursor_payload: Mapping[str, object],
    items: Sequence[Mapping[str, object]],
    page_size: int,
) -> dict[str, object]:
    """Return an exact continuation page or a fail-closed mismatch payload."""

    lane = str(cursor_payload["lane"])
    raw_offset = cursor_payload.get("offset")
    if not isinstance(raw_offset, int):
        raise MemoryContractError("memory continuation offset is invalid")
    offset = raw_offset
    expected = cursor_payload.get("lane_identity_digest")
    actual = memory_lane_identity_digest(lane, items)
    if actual != expected:
        return {
            "status": "snapshot_mismatch",
            "reason": "memory_projection_changed",
            "lane": lane,
            "expected_lane_identity_digest": expected,
            "actual_lane_identity_digest": actual,
        }
    bounded_size = bounded_memory_continuation_page_size(page_size)
    total = len(items)
    page_items = list(items[offset : offset + bounded_size])
    next_offset = offset + len(page_items)
    payload: dict[str, object] = {
        "status": "ok",
        "projection_kind": MEMORY_CONTINUATION_PROJECTION_KIND,
        "ordering_version": MEMORY_CONTINUATION_ORDERING_VERSION,
        "lane": lane,
        "offset": offset,
        "page_size": bounded_size,
        "returned": len(page_items),
        "total": total,
        "response_complete": next_offset >= total,
        "items": page_items,
        "lane_identity_digest": actual,
    }
    if next_offset < total:
        request = cursor_payload.get("request")
        if not isinstance(request, dict):
            raise MemoryContractError("memory continuation request is invalid")
        payload["next"] = build_memory_continuation_cursor(
            project_id=str(cursor_payload["project_id"]),
            lane=lane,
            request=request,
            items=items,
            offset=next_offset,
        )
    return payload


def bounded_memory_continuation_page_size(value: int) -> int:
    """Normalize continuation page size without allowing unbounded pages."""

    if value < 1:
        raise MemoryContractError("memory continuation page_size must be >= 1")
    return min(value, MAX_MEMORY_CONTINUATION_PAGE_SIZE)


def _encode_cursor(payload: Mapping[str, object]) -> str:
    raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _padded_base64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return f"{value}{padding}".encode("ascii")


def _digest(payload: object) -> dict[str, str]:
    raw = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    return {
        "kind": MEMORY_CONTINUATION_PROJECTION_KIND,
        "algorithm": "sha256",
        "digest_version": MEMORY_CONTINUATION_CURSOR_VERSION,
        "value": hashlib.sha256(raw).hexdigest(),
    }


__all__ = [
    "DEFAULT_MEMORY_CONTINUATION_PAGE_SIZE",
    "MAX_MEMORY_CONTINUATION_PAGE_SIZE",
    "MEMORY_CONTINUATION_CURSOR_VERSION",
    "MEMORY_CONTINUATION_LANES",
    "MEMORY_CONTINUATION_ORDERING_VERSION",
    "MEMORY_CONTINUATION_PROJECTION_KIND",
    "bounded_memory_continuation_page_size",
    "build_memory_continuation_cursor",
    "decode_memory_continuation_cursor",
    "memory_continuation_page",
    "memory_lane_identity_digest",
    "memory_lane_item_ids",
    "rebase_memory_continuation_cursor",
]
